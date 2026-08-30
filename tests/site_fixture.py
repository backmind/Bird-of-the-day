"""A whole site built by the real generator, with only the network stubbed.

Extracted from ``tests/test_end_to_end.py`` so that more than one suite
can drive ``scripts.generate.main()`` against the same fabricated days
without a second copy of the stubbing drifting away from the first. The
end-to-end tests use it one day at a time through their own fixtures;
``tests/test_browser.py`` uses :func:`build_site` to get a finished
directory it can serve over HTTP.

Only the network boundary is stubbed:

- ``ebird_client.select_species`` / ``get_full_taxonomy`` /
  ``get_code_to_localized`` / ``get_english_name_index``
- ``image_fetcher.fetch_image`` / ``new_session``
- ``content_scraper.scrape_species_content``
- ``llm_enricher.is_configured`` (forced False, so the LLM branch is
  skipped the same honest way it is when nobody configured one)
- ``map_composer.download_image``, which answers with a generated
  density tile instead of GBIF's, and raises for any URL other than the
  one the fixture's own mapped species asks for
- ``distribution_map.gbif_taxon_match_ex`` / ``fetch_iucn_category``,
  stubbed to raise if ever called. The fake content below answers with
  a settled ``gbif_match`` and, where there is a map, a taxon key
  already in hand, so neither backfill's GBIF healer nor the scraper
  should ever reach for them; they exist as a trip wire, not because
  the happy path needs them.

One species (:data:`MAPPED_SPECIES`) carries a GBIF distribution map and
the rest do not, so both plate layouts, the one with an atlas and the one
without, are produced by every suite that builds this site. That matters
most to the browser suite: the atlas frame is the widest thing the site
draws, and a fixture that never rendered one would leave the horizontal
overflow check blind to it.

Everything else is real: page rendering, feed XML, the archive, the
composed map PNG, the sitemap, robots.txt, 404.html, atomic writes, and
backfill's decision about what needs healing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

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

# The one species GBIF knows about. Deliberately the second day's bird,
# so that on a two-day site it is also the most recent one and therefore
# the hero on the home page, on the archive front and in its month
# bucket: four page classes rendering the atlas rather than one. Every
# other bird in the cast has no map, which is the other layout, and
# keeps ``fakowl1``'s "nothing at all to draw" case intact.
MAPPED_SPECIES = "fakwrn1"

# An arbitrary GBIF usageKey. Real only in shape: what matters is that
# the URL built from it is the genuine hot-linked density tile address,
# so the browser suite's allowed-origins check has something to allow
# rather than merely permitting api.gbif.org in the abstract.
FAKE_GBIF_KEY = 5229493
FAKE_MAP_URL = distribution_map.gbif_map_url(FAKE_GBIF_KEY)


def _fake_density_tile(url: str, session=None, timeout: int = 0) -> Image.Image:
    """Stand in for GBIF's occurrence density tile.

    Drawn rather than downloaded, and only for the one URL this fixture
    ever asks for: any other URL is a real outbound request that leaked
    past the boundary, and raises the way the other trip wires do.

    Transparent but for a couple of blobs in the density ramp's colours,
    which is what a real tile is: hexagons on nothing. ``compose_map``
    resizes it to the basemap and alpha-composites it, so the exact size
    here does not matter, only that it is square and has an alpha
    channel.
    """
    if url != FAKE_MAP_URL:
        _boom(url)
    tile = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    draw.ellipse((60, 120, 210, 260), fill=(255, 200, 0, 210))
    draw.ellipse((150, 200, 300, 330), fill=(220, 70, 0, 190))
    draw.ellipse((330, 260, 430, 360), fill=(139, 0, 0, 170))
    return tile

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

    Every species comes back with its GBIF question already settled, so
    backfill's healer never retries one and ``distribution_map`` is
    never reached: :data:`MAPPED_SPECIES` with ``MATCH_OK`` and a taxon
    key already in hand, everything else with ``MATCH_NONE``, which is
    an authoritative "GBIF does not know this name" rather than a
    failure worth another attempt.

    ``MAPPED_SPECIES`` is therefore the only one whose plate renders the
    atlas, and the only one ``map_composer.ensure_composed_maps`` ever
    composes a PNG for.
    """
    mapped = species_code == MAPPED_SPECIES
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
        gbif_taxon_key=FAKE_GBIF_KEY if mapped else None,
        distribution_map_url=FAKE_MAP_URL if mapped else "",
        gbif_match=distribution_map.MATCH_OK if mapped else distribution_map.MATCH_NONE,
        iucn_code="",
        iucn_birdlife_url="",
    )


def _boom(*args, **kwargs):
    """Trip wire for a network seam this test expects to be unreachable."""
    raise AssertionError(
        "unexpected outbound network call during the end-to-end test "
        f"(args={args!r}, kwargs={kwargs!r})"
    )


def freeze_clock(monkeypatch: pytest.MonkeyPatch, iso_date: str) -> None:
    """Pin ``generate.main()``'s clock to noon UTC on ``iso_date``.

    ``main()`` reads ``datetime.now(timezone.utc)`` exactly once, through
    the name ``datetime`` in its own module namespace (it does
    ``from datetime import datetime``). Swapping that name for a subclass
    whose ``now()`` ignores the wall clock is the least invasive way to
    control it: no production code changes, and it affects only this one
    module. Every other module keeps ticking on the real clock, visible
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


def install(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    feed_link: str | None = None,
) -> Path:
    """Redirect generate.py's state, wire the network boundary, isolate env.

    Paths: the four state-anchored constants are monkeypatched the way
    generate.py itself says to (they are computed once from
    BOTD_STATE_DIR at import time). CONFIG_PATH points at our own
    config.json rather than the repo's, and ENV_PATH at a file that does
    not exist so ``_load_dotenv`` is a no-op regardless of what the
    developer's own checkout has on disk.

    ``feed_link`` overrides the configured site root. The browser suite
    needs it to be the origin its own HTTP server answers on, because
    404.html is the one page rendered with absolute URLs (see
    ``archive_builder.build_not_found``) and would otherwise link its
    stylesheet off-site.

    Returns the state directory, which is also the site's output root.
    """
    root = tmp_path / "state"
    root.mkdir()
    config = dict(TEST_CONFIG)
    if feed_link is not None:
        config["feed_link"] = feed_link
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

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
    # (not at a module above them), see the module docstring. The first
    # two are pure trip wires. The third draws the density tile for the
    # one species that has a map, and is itself a trip wire for any
    # other URL.
    monkeypatch.setattr(distribution_map, "gbif_taxon_match_ex", _boom)
    monkeypatch.setattr(distribution_map, "fetch_iucn_category", _boom)
    monkeypatch.setattr(map_composer, "download_image", _fake_density_tile)

    return root


def publish(monkeypatch: pytest.MonkeyPatch, iso_date: str) -> None:
    """Run one whole day of the generator, as if the clock read ``iso_date``."""
    freeze_clock(monkeypatch, iso_date)
    generate.main()


def build_site(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dates: list[str],
    *,
    feed_link: str | None = None,
) -> Path:
    """Publish ``dates`` in order into a fresh state directory, and return it.

    The result is a finished site: index.html, archive.html, one month
    bucket, one page per species, both feeds, the sitemap, robots.txt,
    404.html and the copied stylesheet, basemap and webfonts.
    """
    root = install(monkeypatch, tmp_path, feed_link=feed_link)
    for iso_date in dates:
        publish(monkeypatch, iso_date)
    return root
