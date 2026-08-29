"""Rendering is cheap; writing is not. Every page is rendered on every
run, but a page whose bytes did not change must not be rewritten: each
rewrite is a diff in the publishing repository."""

import pytest

from scripts import archive_builder
from scripts.i18n import Catalog
from tests.test_archive_buckets import _entry


@pytest.fixture
def catalog():
    return Catalog.load("en")


@pytest.fixture
def entries():
    return [
        _entry("c", "2026-08-02", 4),
        _entry("b", "2026-08-01", 3),
        _entry("a", "2026-07-31", 2),
    ]


def test_writes_the_full_page_set(tmp_path, catalog, entries):
    result = archive_builder.write_site(entries, tmp_path, catalog)
    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.html")}
    assert written == {
        "index.html",
        "archive.html",
        "archive-2026-08.html",
        "archive-2026-07.html",
        "birds/c.html",
        "birds/b.html",
        "birds/a.html",
    }
    assert result["written"] == result["pages"] == 7
    assert result["unchanged"] == 0


def test_second_identical_run_writes_nothing(tmp_path, catalog, entries):
    archive_builder.write_site(entries, tmp_path, catalog)
    stamps = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*.html")}
    result = archive_builder.write_site(entries, tmp_path, catalog)
    assert result["written"] == 0
    assert result["unchanged"] == 7
    assert {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*.html")} == stamps


def test_a_new_entry_touches_only_the_pages_that_changed(tmp_path, catalog, entries):
    archive_builder.write_site(entries, tmp_path, catalog)
    stamps = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*.html")}
    fresh = [_entry("d", "2026-08-03", 5)] + entries
    archive_builder.write_site(fresh, tmp_path, catalog)
    changed = {
        p.relative_to(tmp_path).as_posix()
        for p, stamp in stamps.items()
        if p.stat().st_mtime_ns != stamp
    }
    # birds/c.html changes because its "next plate" link now points at d:
    # the navigation is part of the page's content.
    assert changed == {
        "index.html",
        "archive.html",
        "archive-2026-08.html",
        "birds/c.html",
    }
    assert (tmp_path / "birds" / "d.html").exists()
    # The untouched month keeps its bytes: that is the churn guarantee.
    assert "archive-2026-07.html" not in changed
    assert "birds/a.html" not in changed


def test_no_entry_is_ever_dropped(tmp_path, catalog):
    many = [
        _entry(f"s{n}", f"2026-{(n % 12) + 1:02d}-0{(n % 9) + 1}", n)
        for n in range(200)
    ]
    archive_builder.write_site(many, tmp_path, catalog)
    for entry in many:
        assert (tmp_path / "birds" / f"{entry.species_code}.html").exists()


def test_assets_are_published(tmp_path, catalog, entries):
    archive_builder.write_site(entries, tmp_path, catalog)
    assert (tmp_path / "assets" / "site.css").exists()
    assert (tmp_path / "assets" / "basemap.png").exists()


def test_empty_history_still_produces_the_two_root_pages(tmp_path, catalog):
    result = archive_builder.write_site([], tmp_path, catalog)
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "archive.html").exists()
    assert result["pages"] == 2
