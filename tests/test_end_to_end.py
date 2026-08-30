"""End-to-end tests of ``scripts.generate.main()``.

Drives the real orchestration -- the real selection window, the real page
builders, the real feed builders, the real write-if-changed policy and the
real self-healing backfill -- against fabricated days of history in a
throwaway state directory. Only the network boundary is stubbed:

- ``ebird_client.select_species`` / ``get_full_taxonomy`` /
  ``get_code_to_localized`` / ``get_english_name_index``
- ``image_fetcher.fetch_image`` / ``new_session``
- ``content_scraper.scrape_species_content``
- ``llm_enricher.is_configured`` (forced False, so the LLM branch is
  skipped the same honest way it is when nobody configured one)
- ``distribution_map.gbif_taxon_match_ex`` / ``fetch_iucn_category`` and
  ``map_composer.download_image``, stubbed to raise if ever called. The
  fake content below never sets ``distribution_map_url`` and always
  reports ``gbif_match=MATCH_NONE``, so nothing in a real run should ever
  reach GBIF or download a density tile; these three exist as a trip
  wire, not because the happy path needs them.

Everything else is real: page rendering, feed XML, the archive, the
sitemap, robots.txt, 404.html, atomic writes, and backfill's decision
about what needs healing.

Each test below is one property, named as a statement of what must be
true, so a failure says which property broke instead of aborting a long
narrative at its first assertion. The fixtures below form a small chain
(``state_dir`` -> ``after_first_day`` -> ``after_second_day``); a test
that needs a prior day's state depends on the fixture that produces it,
so every test gets a *fresh* run of whatever days it needs and none of
them depend on another test having run first.

What this file deliberately does not cover: the actual content of a
scrape or an LLM enrichment (both are stubbed away), real GBIF/IUCN
lookups or composed distribution maps (never engaged, see above), and
multi-day feed freeze/thaw (``max_feed_entries`` is set comfortably above
the entries any of these tests ever produce, so nothing is ever frozen).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import (
    content_scraper,
    distribution_map,
    ebird_client,
    generate,
    image_fetcher,
    llm_enricher,
    map_composer,
)
from scripts.generate import _ENV_OVERRIDES

# ---------------------------------------------------------------------------
# Fixed cast: one fabricated bird per day, none of them real eBird species.
# ---------------------------------------------------------------------------

FAKE_BIRDS: dict[str, dict[str, str]] = {
    "2026-01-01": {
        "speciesCode": "fakhaw1",
        "comName": "Fake Hawk",
        "sciName": "Falco fictus",
    },
    "2026-01-02": {
        "speciesCode": "fakwrn1",
        "comName": "Fake Wren",
        "sciName": "Troglodytes fictus",
    },
    "2026-01-03": {
        "speciesCode": "fakowl1",
        "comName": "Fake Owl",
        "sciName": "Strix ficta",
    },
}


def _fake_image(asset_id: str, species_code: str) -> image_fetcher.ImageResult:
    return image_fetcher.ImageResult(
        url=f"{image_fetcher.CDN_BASE}/{asset_id}/900",
        asset_id=asset_id,
        photographer="Test Photographer",
        attribution="Test Photographer / Macaulay Library",
        search_url=image_fetcher.ml_search_url(species_code),
    )


def _no_image(species_code: str) -> image_fetcher.ImageResult:
    """What every photograph strategy returns when none of them find one."""
    return image_fetcher.ImageResult(
        url=None,
        asset_id=None,
        photographer="",
        attribution="Macaulay Library / Cornell Lab of Ornithology",
        search_url=image_fetcher.ml_search_url(species_code),
    )


FAKE_IMAGES: dict[str, image_fetcher.ImageResult] = {
    "fakhaw1": _fake_image("100001", "fakhaw1"),
    "fakwrn1": _fake_image("100002", "fakwrn1"),
    # 2026-01-03's bird: the photograph-strategy-finds-nothing case.
    "fakowl1": _no_image("fakowl1"),
}

TEST_CONFIG: dict = {
    "language": "en",
    "ebird_locale": "en",
    "description_policy": "foreign_fallback",
    "max_skip_retries": 5,
    "pools": [{"id": "test", "type": "global_taxonomy", "weight": 1}],
    "dedup_window": 5,
    "rarity_bias": 0.5,
    "max_feed_entries": 10,
    "feed_rebuild_all": False,
    "back_days": 14,
    "backfill_limit": 3,
    "feed_link": "https://birds.example.test",
    "site_author": "Test Author",
    "site_author_url": "https://example.test/author",
}


def _fake_scrape_species_content(
    species_code,
    scientific_name: str = "",
    catalog=None,
    session=None,
    max_description_chars: int = 700,
) -> content_scraper.SpeciesContent:
    """Stand-in for the real scrape: real fields, fictional content.

    ``gbif_match=MATCH_NONE`` is what keeps backfill's GBIF healer from
    ever retrying this species (mirrors an authoritative "GBIF does not
    know this name"), and the empty ``distribution_map_url`` is what
    keeps ``map_composer.ensure_composed_maps`` from ever trying to
    download a density tile. Together they make the distribution_map /
    map_composer network surface unreachable by construction.
    """
    return content_scraper.SpeciesContent(
        description=(
            f"{species_code} is a fictional species invented for the "
            "end-to-end test suite."
        ),
        description_source="ebird",
        bow_intro="",
        taxonomy={},
        wikipedia_url=f"https://en.wikipedia.org/wiki/{species_code}",
        wikipedia_language="en",
        gbif_taxon_key=None,
        distribution_map_url="",
        gbif_match=distribution_map.MATCH_NONE,
        iucn_code="",
        iucn_birdlife_url="",
    )


def _boom(*args, **kwargs):
    """Trip wire for a network seam this test expects to be unreachable."""
    raise AssertionError(
        "unexpected outbound network call during the end-to-end test "
        f"(args={args!r}, kwargs={kwargs!r})"
    )


def _freeze(monkeypatch: pytest.MonkeyPatch, iso_date: str) -> None:
    """Pin ``generate.main()``'s clock to noon UTC on ``iso_date``.

    ``main()`` reads ``datetime.now(timezone.utc)`` exactly once, through
    the name ``datetime`` in its own module namespace (it does
    ``from datetime import datetime``). Swapping that name for a subclass
    whose ``now()`` ignores the wall clock is the least invasive way to
    control it: no production code changes, and it affects only this one
    module. Every other module keeps ticking on the real clock -- visible
    in the footer credit and the RSS channel's copyright year, both of
    which read ``datetime.now(timezone.utc).year`` themselves and which
    these tests do not assert on for that reason.
    """
    year, month, day = (int(part) for part in iso_date.split("-"))
    fixed = datetime(year, month, day, 12, tzinfo=timezone.utc)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(generate, "datetime", _FrozenDateTime)


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    """Every file under ``root``: its bytes and its mtime in nanoseconds."""
    return {
        p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


# ---------------------------------------------------------------------------
# Fixtures: environment wiring, then one fixture per day a test may need.
# Each depends on pytest's function-scoped tmp_path, so every test gets its
# own fresh state directory and re-runs whatever prior days it needs itself
# -- no test's pass/fail depends on another test having run first.
# ---------------------------------------------------------------------------


@pytest.fixture
def state_dir(tmp_path, monkeypatch) -> Path:
    """Redirect generate.py's state, wire the network boundary, isolate env.

    Paths: the four state-anchored constants are monkeypatched the way
    generate.py itself says to (they are computed once from
    BOTD_STATE_DIR at import time). CONFIG_PATH points at our own
    config.json rather than the repo's, and ENV_PATH at a file that does
    not exist so ``_load_dotenv`` is a no-op regardless of what the
    developer's own checkout has on disk.
    """
    root = tmp_path / "state"
    root.mkdir()
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(TEST_CONFIG), encoding="utf-8")

    monkeypatch.setattr(generate, "STATE_DIR", root)
    monkeypatch.setattr(generate, "CACHE_DIR", root / "cache")
    monkeypatch.setattr(generate, "MAPS_DIR", root / "maps")
    monkeypatch.setattr(generate, "HISTORY_PATH", root / "history.json")
    monkeypatch.setattr(generate, "CONFIG_PATH", config_path)
    monkeypatch.setattr(generate, "ENV_PATH", tmp_path / "unused.env")

    # The config above is the only source of truth for this run: nothing
    # the developer's own shell happens to export should leak in.
    leaky_vars = list(_ENV_OVERRIDES) + [
        "EBIRD_API_KEY", "EBIRD_API_KEY_FILE",
        "BOTD_LLM_API_KEY", "BOTD_LLM_API_KEY_FILE",
        "GITHUB_ACTIONS",
    ]
    for name in leaky_vars:
        monkeypatch.delenv(name, raising=False)

    # --- Network boundary -------------------------------------------------
    monkeypatch.setattr(
        ebird_client,
        "select_species",
        lambda config, published_codes, date_str, cache_dir=None,
        exclude=frozenset(), notes=None: dict(FAKE_BIRDS[date_str]),
    )
    monkeypatch.setattr(
        ebird_client, "get_full_taxonomy", lambda locale="en", cache_dir=None: []
    )
    monkeypatch.setattr(ebird_client, "get_code_to_localized", lambda: {})
    monkeypatch.setattr(
        ebird_client, "get_english_name_index", lambda cache_dir=None: {}
    )

    monkeypatch.setattr(
        image_fetcher, "new_session", lambda accept_language=None, **_: object()
    )
    monkeypatch.setattr(
        image_fetcher,
        "fetch_image",
        lambda species_code, session=None, locale="en", *, ordinal=0,
        seen_asset_ids=frozenset(): FAKE_IMAGES[species_code],
    )

    monkeypatch.setattr(
        content_scraper, "scrape_species_content", _fake_scrape_species_content
    )
    monkeypatch.setattr(llm_enricher, "is_configured", lambda config: False)

    # distribution_map / map_composer: stubbed at the actual egress points
    # (not at a module above them), as a trip wire -- see module docstring.
    monkeypatch.setattr(distribution_map, "gbif_taxon_match_ex", _boom)
    monkeypatch.setattr(distribution_map, "fetch_iucn_category", _boom)
    monkeypatch.setattr(map_composer, "download_image", _boom)

    return root


@pytest.fixture
def after_first_day(state_dir, monkeypatch) -> Path:
    """State after publishing 2026-01-01's bird: one history entry."""
    _freeze(monkeypatch, "2026-01-01")
    generate.main()
    return state_dir


@pytest.fixture
def after_second_day(after_first_day, monkeypatch) -> Path:
    """State after publishing 2026-01-02's bird on top of the first day."""
    _freeze(monkeypatch, "2026-01-02")
    generate.main()
    return after_first_day


@pytest.fixture
def after_no_photo_day(state_dir, monkeypatch) -> Path:
    """A single, otherwise-empty-state run whose photo strategy finds nothing.

    Deliberately independent of ``after_first_day`` / ``after_second_day``:
    this property has nothing to do with prior publications, so it doesn't
    borrow their state.
    """
    _freeze(monkeypatch, "2026-01-03")
    generate.main()
    return state_dir


# ---------------------------------------------------------------------------
# Tests: one property each.
# ---------------------------------------------------------------------------


def test_first_run_on_empty_state_publishes(after_first_day):
    state_dir = after_first_day
    bird_a = FAKE_BIRDS["2026-01-01"]

    history = json.loads((state_dir / "history.json").read_text(encoding="utf-8"))
    assert len(history["entries"]) == 1
    entry = history["entries"][0]
    assert entry["speciesCode"] == bird_a["speciesCode"]
    assert entry["comName"] == bird_a["comName"]
    assert entry["sciName"] == bird_a["sciName"]
    assert entry["date"] == "2026-01-01"
    assert entry["imageUrl"] == FAKE_IMAGES[bird_a["speciesCode"]].url
    assert entry["photographer"] == "Test Photographer"
    assert entry["attribution"] == "Test Photographer / Macaulay Library"

    promised_files = [
        "index.html",
        "archive.html",
        "archive-2026-01.html",
        f"birds/{bird_a['speciesCode']}.html",
        "feed.xml",
        "sitemap.xml",
        "robots.txt",
        "404.html",
    ]
    for relative in promised_files:
        path = state_dir / relative
        assert path.exists(), f"{relative} was not written"
        assert path.stat().st_size > 0, f"{relative} is empty"

    index_html = (state_dir / "index.html").read_text(encoding="utf-8")
    assert bird_a["comName"] in index_html
    feed_xml = (state_dir / "feed.xml").read_text(encoding="utf-8")
    assert bird_a["comName"] in feed_xml


def test_second_run_same_day_rewrites_nothing(after_first_day):
    state_dir = after_first_day

    before = _snapshot(state_dir)
    generate.main()  # clock is still frozen on 2026-01-01 by the fixture
    after = _snapshot(state_dir)

    assert after.keys() == before.keys(), "second run created or removed files"
    bytes_before = {k: v[0] for k, v in before.items()}
    bytes_after = {k: v[0] for k, v in after.items()}
    assert bytes_after == bytes_before, "second run rewrote content that did not change"

    # mtime, too -- with one documented exception. write_site copies the
    # committed basemap and the four webfont assets with shutil.copyfile
    # on every run (see archive_builder.write_site): they are static
    # source files, not behind write_text_if_changed, so their mtimes
    # bump on every call even though the bytes copied are, and stay,
    # identical (already proven above). Every page, both feeds, the
    # sitemap, robots.txt, 404.html and history.json go through
    # atomic_io.write_text_if_changed and must show the exact same mtime.
    always_copied = {
        p for p in after
        if p == "assets/basemap.png" or p.startswith("assets/fonts/")
    }
    assert always_copied, "expected the basemap and font assets on disk"
    governed = set(after) - always_copied
    for relative in governed:
        assert before[relative][1] == after[relative][1], (
            f"{relative} was rewritten even though its content did not change"
        )


def test_second_day_publishes_without_losing_the_first(after_second_day):
    state_dir = after_second_day
    bird_a = FAKE_BIRDS["2026-01-01"]
    bird_b = FAKE_BIRDS["2026-01-02"]

    history = json.loads((state_dir / "history.json").read_text(encoding="utf-8"))
    assert [e["speciesCode"] for e in history["entries"]] == [
        bird_a["speciesCode"], bird_b["speciesCode"],
    ]

    assert (state_dir / "birds" / f"{bird_a['speciesCode']}.html").exists()
    plate_b_path = state_dir / "birds" / f"{bird_b['speciesCode']}.html"
    assert plate_b_path.exists()
    assert bird_b["comName"] in plate_b_path.read_text(encoding="utf-8")

    archive_html = (state_dir / "archive.html").read_text(encoding="utf-8")
    assert bird_a["comName"] in archive_html
    assert bird_b["comName"] in archive_html


def test_no_photo_run_still_publishes_with_no_broken_url(after_no_photo_day):
    state_dir = after_no_photo_day
    bird_c = FAKE_BIRDS["2026-01-03"]

    history = json.loads((state_dir / "history.json").read_text(encoding="utf-8"))
    entry_c = history["entries"][-1]
    assert entry_c["speciesCode"] == bird_c["speciesCode"]
    assert entry_c["imageUrl"] is None

    plate_c_path = state_dir / "birds" / f"{bird_c['speciesCode']}.html"
    plate_c = plate_c_path.read_text(encoding="utf-8")
    assert bird_c["comName"] in plate_c
    assert 'class="no-image"' in plate_c
    assert f"taxonCode={bird_c['speciesCode']}" in plate_c  # the ML search link
    assert "<img" not in plate_c  # no hero photo, no atlas: nothing to draw

    # The exact production bug: a CDN URL published with an empty asset
    # id renders as ".../asset//900". Check every page and feed the run
    # wrote, not just this species' own plate.
    for path in state_dir.rglob("*"):
        if path.is_file() and path.suffix in (".html", ".xml"):
            text = path.read_text(encoding="utf-8")
            assert "/asset//" not in text, f"broken image URL (empty asset id) in {path}"


def test_sitemap_lists_exactly_the_html_on_disk(after_second_day):
    state_dir = after_second_day

    sitemap_root = ET.fromstring(
        (state_dir / "sitemap.xml").read_text(encoding="utf-8")
    )
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    base = TEST_CONFIG["feed_link"].rstrip("/") + "/"
    sitemap_paths = {
        el.text[len(base):] for el in sitemap_root.findall("sm:url/sm:loc", ns)
    }
    on_disk = {
        p.relative_to(state_dir).as_posix()
        for p in state_dir.rglob("*.html")
        if p.name != "404.html"  # never indexed, see build_sitemap's docstring
    }
    assert sitemap_paths == on_disk
