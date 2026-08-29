"""The species page is the canonical URL for a bird: it is what the name
linker points at, so it must never depend on a publication date."""

import re

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


@pytest.fixture
def by_code(entries):
    """The grouping keyed by species code, for tests that want just one."""
    return dict(archive_builder.group_by_species(entries))


def test_grouping_collects_every_publication_of_a_species(entries):
    grouped = archive_builder.group_by_species(entries)
    assert [code for code, _ in grouped] == ["c", "b", "a"]
    assert [e.date for e in grouped[1][1]] == ["2026-08-01", "2026-01-05"]


def test_page_shows_the_latest_plate(ctx, by_code):
    publications = by_code["b"]
    # Same species, deliberately different names on the two publications:
    # a test that leaves them identical would still pass if the oldest
    # one were rendered by mistake.
    publications[0].common_name = "Bird b newest"
    publications[1].common_name = "Bird b oldest"
    html = archive_builder.build_species_page(publications, ctx)
    assert "Bird b newest" in html
    assert "Bird b oldest" not in html
    assert html.count("plate-title") == 1


def test_publication_history_links_every_date_to_its_bucket(ctx, by_code):
    html = archive_builder.build_species_page(by_code["b"], ctx)
    assert 'href="../archive-2026-08.html#bird-b-2026-08-01"' in html
    assert 'href="../archive-2026-01.html#bird-b-2026-01-05"' in html


def test_navigation_links_the_neighbouring_plates(ctx, entries, by_code):
    html = archive_builder.build_species_page(
        by_code["b"], ctx, older=entries[3], newer=entries[0]
    )
    assert 'href="../birds/a.html"' in html
    assert 'href="../birds/c.html"' in html


def test_navigation_omits_the_newer_link_when_there_is_none(ctx, entries, by_code):
    html = archive_builder.build_species_page(by_code["b"], ctx, older=entries[3])
    assert 'href="../birds/a.html"' in html
    assert "page-nav-newer" not in html


def test_navigation_omits_the_older_link_when_there_is_none(ctx, entries, by_code):
    html = archive_builder.build_species_page(by_code["b"], ctx, newer=entries[0])
    assert 'href="../birds/c.html"' in html
    assert "page-nav-older" not in html


def test_assets_are_reached_from_one_directory_down(ctx, by_code):
    html = archive_builder.build_species_page(by_code["a"], ctx)
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


# --- Navigation over the written site -------------------------------------
#
# Everything above renders one page with ``older``/``newer`` handed in, so
# it only exercises the rendering. These go through ``write_site`` and read
# the hrefs back off disk, which is the only way to catch a wrong choice of
# neighbour.

def _republished_entries():
    """Newest first, as generate.py hands them over.

    Species "b" is published twice, and sits in the middle of the species
    ordering rather than at either end.
    """
    return [
        _entry("e", "2026-08-06", 6),
        _entry("b", "2026-08-05", 5),
        _entry("b", "2026-08-04", 4),
        _entry("c", "2026-08-03", 3),
        _entry("d", "2026-01-05", 2),
        _entry("a", "2025-12-30", 1),
    ]


# Species ordered by their most recent publication.
_SPECIES_ORDER = ["e", "b", "c", "d", "a"]


def _nav_targets(page: "object") -> dict[str, str]:
    """``{"older": href, "newer": href}`` for one written species page."""
    html = page.read_text(encoding="utf-8")
    return dict(
        re.findall(r'class="page-nav-(older|newer)" href="([^"]+)"', html)
    )


def _code_of(href: str) -> str:
    return href.rsplit("/", 1)[-1].removesuffix(".html")


@pytest.fixture
def republished_nav(tmp_path):
    archive_builder.write_site(
        _republished_entries(), tmp_path, Catalog.load("en")
    )
    return {
        code: _nav_targets(tmp_path / "birds" / f"{code}.html")
        for code in _SPECIES_ORDER
    }


def test_no_species_page_links_to_itself(republished_nav):
    # The destination is a species page, so a species published twice used
    # to find itself as its own neighbouring publication.
    for code, links in republished_nav.items():
        assert code not in [_code_of(href) for href in links.values()], code


def test_the_older_walk_visits_every_species_exactly_once(republished_nav):
    walk = [_SPECIES_ORDER[0]]
    for _ in range(len(_SPECIES_ORDER)):
        older = republished_nav[walk[-1]].get("older")
        if older is None:
            break
        walk.append(_code_of(older))
    assert walk == _SPECIES_ORDER


def test_the_newer_walk_visits_every_species_exactly_once(republished_nav):
    walk = [_SPECIES_ORDER[-1]]
    for _ in range(len(_SPECIES_ORDER)):
        newer = republished_nav[walk[-1]].get("newer")
        if newer is None:
            break
        walk.append(_code_of(newer))
    assert walk == list(reversed(_SPECIES_ORDER))


def test_the_two_ends_omit_the_direction_that_does_not_exist(republished_nav):
    assert "newer" not in republished_nav[_SPECIES_ORDER[0]]
    assert "older" in republished_nav[_SPECIES_ORDER[0]]
    assert "older" not in republished_nav[_SPECIES_ORDER[-1]]
    assert "newer" in republished_nav[_SPECIES_ORDER[-1]]


def test_navigation_labels_name_the_neighbouring_species(tmp_path):
    archive_builder.write_site(
        _republished_entries(), tmp_path, Catalog.load("en")
    )
    html = (tmp_path / "birds" / "c.html").read_text(encoding="utf-8")
    assert ">Previous plate: Bird d</a>" in html
    assert ">Next plate: Bird b</a>" in html
