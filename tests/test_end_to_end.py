"""End-to-end tests of ``scripts.generate.main()``.

Drives the real orchestration -- the real selection window, the real page
builders, the real feed builders, the real write-if-changed policy and the
real self-healing backfill -- against fabricated days of history in a
throwaway state directory. Only the network boundary is stubbed, and the
stubbing itself lives in :mod:`tests.site_fixture` because the browser
suite drives the same generator against the same fabricated cast; see
that module for what is faked and what is real.

Each test below is one property, named as a statement of what must be
true, so a failure says which property broke instead of aborting a long
narrative at its first assertion. The fixtures below form a small chain
(``state_dir`` -> ``after_first_day`` -> ``after_second_day``); a test
that needs a prior day's state depends on the fixture that produces it,
so every test gets a *fresh* run of whatever days it needs and none of
them depend on another test having run first.

What this file deliberately does not cover: the actual content of a
scrape or an LLM enrichment (both are stubbed away), real GBIF/IUCN
lookups or composed distribution maps (never engaged), and multi-day
feed freeze/thaw (``max_feed_entries`` is set comfortably above the
entries any of these tests ever produce, so nothing is ever frozen).
Anything only a real browser can answer lives in
``tests/test_browser.py``.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts import generate
from tests import site_fixture
from tests.site_fixture import FAKE_BIRDS, FAKE_IMAGES, TEST_CONFIG


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

    See :func:`tests.site_fixture.install` for what each of those means.
    """
    return site_fixture.install(monkeypatch, tmp_path)


@pytest.fixture
def after_first_day(state_dir, monkeypatch) -> Path:
    """State after publishing 2026-01-01's bird: one history entry."""
    site_fixture.publish(monkeypatch, "2026-01-01")
    return state_dir


@pytest.fixture
def after_second_day(after_first_day, monkeypatch) -> Path:
    """State after publishing 2026-01-02's bird on top of the first day."""
    site_fixture.publish(monkeypatch, "2026-01-02")
    return after_first_day


@pytest.fixture
def after_no_photo_day(state_dir, monkeypatch) -> Path:
    """A single, otherwise-empty-state run whose photo strategy finds nothing.

    Deliberately independent of ``after_first_day`` / ``after_second_day``:
    this property has nothing to do with prior publications, so it doesn't
    borrow their state.
    """
    site_fixture.publish(monkeypatch, "2026-01-03")
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
