"""Month buckets are the site's permanent home for every plate."""

import pytest

from scripts import archive_builder, site_builder
from scripts.i18n import Catalog


def _entry(code, date, number):
    return site_builder.SiteEntry(
        species_code=code,
        common_name=f"Bird {code}",
        scientific_name="Genus species",
        date=date,
        image_url=None,
        photographer="",
        attribution="",
        description="A description.",
        description_source="ebird",
        bow_intro="",
        taxonomy={},
        ml_search_url="https://example.invalid/ml",
        number=number,
    )


@pytest.fixture
def ctx():
    return site_builder.RenderContext(catalog=Catalog.load("en"), feed_link="")


@pytest.fixture
def entries():
    # Newest first, exactly how generate.py hands them over.
    return [
        _entry("c", "2026-08-02", 4),
        _entry("b", "2026-08-01", 3),
        _entry("a", "2026-07-31", 2),
        _entry("z", "2026-06-30", 1),
    ]


def test_grouping_is_newest_month_first(entries):
    grouped = archive_builder.group_by_month(entries)
    assert [month for month, _ in grouped] == ["2026-08", "2026-07", "2026-06"]
    assert [e.species_code for e in grouped[0][1]] == ["c", "b"]


def test_grouping_keeps_every_entry(entries):
    grouped = archive_builder.group_by_month(entries)
    assert sum(len(month_entries) for _, month_entries in grouped) == len(entries)


def test_month_label_is_localized(ctx):
    assert archive_builder.month_label(ctx, "2026-08") == "August 2026"


def test_bucket_renders_every_plate_of_its_month(ctx, entries):
    html = archive_builder.build_month_bucket("2026-08", entries[:2], ctx)
    assert 'id="bird-c-2026-08-02"' in html
    assert 'id="bird-b-2026-08-01"' in html
    assert "bird-a-2026-07-31" not in html


def test_bucket_navigation_points_at_the_neighbouring_months(ctx, entries):
    html = archive_builder.build_month_bucket(
        "2026-07", entries[2:3], ctx, newer_month="2026-08", older_month="2026-06"
    )
    assert 'href="archive-2026-08.html"' in html
    assert 'href="archive-2026-06.html"' in html
    assert 'href="archive.html"' in html


def test_edge_months_omit_the_missing_direction(ctx, entries):
    html = archive_builder.build_month_bucket("2026-08", entries[:2], ctx, older_month="2026-07")
    assert 'href="archive-2026-07.html"' in html
    assert "archive-2026-09.html" not in html


def test_oldest_month_omits_the_older_link(ctx, entries):
    html = archive_builder.build_month_bucket("2026-06", entries[3:4], ctx, newer_month="2026-07")
    assert 'href="archive-2026-07.html"' in html
    assert "archive-2026-05.html" not in html
    assert "page-nav-older" not in html


def test_bucket_never_caps_a_months_entries(ctx):
    # The bug this plan removes: archive.html used to hard-cap at 90 and
    # silently drop the rest. A month bucket must render every plate it
    # is given, however many there are.
    big_month = [_entry(f"sp{i:03d}", "2026-08-15", i) for i in range(1, 121)]
    html = archive_builder.build_month_bucket("2026-08", big_month, ctx)
    for entry in big_month:
        assert f'id="{entry.anchor}"' in html


def test_bucket_is_a_full_page(ctx, entries):
    html = archive_builder.build_month_bucket("2026-08", entries[:2], ctx)
    assert html.startswith("<!DOCTYPE html>")
    assert "August 2026" in html
    assert 'href="assets/site.css"' in html
