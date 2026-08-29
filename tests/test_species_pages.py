"""The species page is the canonical URL for a bird: it is what the name
linker points at, so it must never depend on a publication date."""

import pytest

from scripts import archive_builder, site_builder
from scripts.i18n import Catalog
from tests.test_archive_buckets import _entry


@pytest.fixture
def ctx():
    root = site_builder.RenderContext(catalog=Catalog.load("en"), feed_link="")
    return site_builder.for_subdirectory(root, "../")


@pytest.fixture
def entries():
    return [
        _entry("c", "2026-08-02", 4),
        _entry("b", "2026-08-01", 3),
        _entry("b", "2026-01-05", 2),
        _entry("a", "2025-12-30", 1),
    ]


def test_grouping_collects_every_publication_of_a_species(entries):
    grouped = archive_builder.group_by_species(entries)
    assert list(grouped) == ["c", "b", "a"]
    assert [e.date for e in grouped["b"]] == ["2026-08-01", "2026-01-05"]


def test_page_shows_the_latest_plate(ctx, entries):
    grouped = archive_builder.group_by_species(entries)
    html = archive_builder.build_species_page(grouped["b"], ctx)
    assert "Bird b" in html
    assert html.count("plate-title") == 1


def test_publication_history_links_every_date_to_its_bucket(ctx, entries):
    grouped = archive_builder.group_by_species(entries)
    html = archive_builder.build_species_page(grouped["b"], ctx)
    assert 'href="../archive-2026-08.html#bird-b-2026-08-01"' in html
    assert 'href="../archive-2026-01.html#bird-b-2026-01-05"' in html


def test_navigation_links_the_neighbouring_plates(ctx, entries):
    grouped = archive_builder.group_by_species(entries)
    html = archive_builder.build_species_page(
        grouped["b"], ctx, older=entries[3], newer=entries[0]
    )
    assert 'href="../birds/a.html"' in html
    assert 'href="../birds/c.html"' in html


def test_assets_are_reached_from_one_directory_down(ctx, entries):
    grouped = archive_builder.group_by_species(entries)
    html = archive_builder.build_species_page(grouped["a"], ctx)
    assert 'href="../assets/site.css"' in html
    assert 'href="../index.html"' in html
    assert 'href="/' not in html


def test_the_map_basemap_is_reached_from_one_directory_down(ctx, entries):
    # The atlas is the only image the site serves itself, and it is the
    # one link a subdirectory page is most likely to get wrong.
    entry = entries[0]
    entry.distribution_map_url = (
        "https://api.gbif.org/v2/map/occurrence/density/0/0/0@2x.png"
    )
    entry.gbif_taxon_key = 1234
    html = archive_builder.build_species_page([entry], ctx)
    assert 'src="../assets/basemap.png"' in html
