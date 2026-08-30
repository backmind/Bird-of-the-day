"""sitemap.xml, robots.txt and 404.html: the three files a crawler or a
lost reader needs that ``write_site`` did not produce before this."""

import xml.etree.ElementTree as ET

import pytest

from scripts import archive_builder, site_builder, urls
from scripts.i18n import Catalog
from tests.test_archive_buckets import _entry

FEED_LINK = "https://example.invalid"
SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


@pytest.fixture
def catalog():
    return Catalog.load("en")


@pytest.fixture
def entries():
    # Newest first, as generate.py hands them over: two species across
    # two months, "c" published twice so its lastmod must be the later
    # of its two dates, not the earlier one.
    return [
        _entry("c", "2026-08-02", 4),
        _entry("b", "2026-08-01", 3),
        _entry("a", "2026-07-31", 2),
        _entry("c", "2026-07-15", 1),
    ]


def _written_html_pages(tmp_path) -> set[str]:
    """Every HTML file the build actually wrote, except 404.html.

    404.html is a real file on disk but is not one of the four page
    classes and has nothing to index, so it does not belong in the
    sitemap; excluding it here is what lets the comparison below stay
    "the pages the build produced", not "every file on disk".
    """
    return {
        p.relative_to(tmp_path).as_posix()
        for p in tmp_path.rglob("*.html")
        if p.name != "404.html"
    }


def _sitemap_locs(tmp_path) -> dict[str, str | None]:
    root = ET.fromstring((tmp_path / urls.SITEMAP).read_text(encoding="utf-8"))
    result = {}
    for url_el in root.findall("s:url", SITEMAP_NS):
        loc = url_el.find("s:loc", SITEMAP_NS).text
        lastmod_el = url_el.find("s:lastmod", SITEMAP_NS)
        result[loc] = lastmod_el.text if lastmod_el is not None else None
    return result


class TestSitemap:
    def test_lists_exactly_the_pages_the_build_wrote(self, tmp_path, catalog, entries):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        expected = {
            urls.absolute(FEED_LINK, page) for page in _written_html_pages(tmp_path)
        }
        assert set(_sitemap_locs(tmp_path)) == expected

    def test_every_entry_carries_a_lastmod(self, tmp_path, catalog, entries):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        locs = _sitemap_locs(tmp_path)
        assert locs  # sanity: the site is not empty in this fixture
        for loc, lastmod in locs.items():
            assert lastmod, f"{loc} has no lastmod"

    def test_species_page_lastmod_is_its_latest_publication(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        locs = _sitemap_locs(tmp_path)
        # "c" was published on both 2026-07-15 and 2026-08-02; the
        # canonical species page's lastmod must be the later date.
        assert locs[urls.absolute(FEED_LINK, "birds/c.html")] == "2026-08-02"
        assert locs[urls.absolute(FEED_LINK, "birds/a.html")] == "2026-07-31"

    def test_bucket_lastmod_is_the_newest_entry_in_that_month(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        locs = _sitemap_locs(tmp_path)
        assert locs[urls.absolute(FEED_LINK, "archive-2026-08.html")] == "2026-08-02"
        assert locs[urls.absolute(FEED_LINK, "archive-2026-07.html")] == "2026-07-31"

    def test_not_written_without_a_feed_link(self, tmp_path, catalog, entries):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link="")
        assert not (tmp_path / urls.SITEMAP).exists()

    def test_second_identical_build_does_not_rewrite_it(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        path = tmp_path / urls.SITEMAP
        stamp = path.stat().st_mtime_ns
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        assert path.stat().st_mtime_ns == stamp


class TestRobots:
    def test_allows_everything(self, tmp_path, catalog, entries):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        robots = (tmp_path / urls.ROBOTS).read_text(encoding="utf-8")
        assert "Disallow" not in robots
        assert "Allow: /" in robots

    def test_points_at_the_sitemap_when_one_is_published(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        robots = (tmp_path / urls.ROBOTS).read_text(encoding="utf-8")
        assert f"Sitemap: {FEED_LINK}/{urls.SITEMAP}" in robots

    def test_omits_the_sitemap_line_without_a_feed_link(
        self, tmp_path, catalog, entries
    ):
        # There is no sitemap.xml in this case (see TestSitemap above),
        # so referencing one would point crawlers at a 404.
        archive_builder.write_site(entries, tmp_path, catalog, feed_link="")
        robots = (tmp_path / urls.ROBOTS).read_text(encoding="utf-8")
        assert "Sitemap" not in robots

    def test_is_written_even_without_a_feed_link(self, tmp_path, catalog, entries):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link="")
        assert (tmp_path / urls.ROBOTS).exists()

    def test_second_identical_build_does_not_rewrite_it(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        path = tmp_path / urls.ROBOTS
        stamp = path.stat().st_mtime_ns
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        assert path.stat().st_mtime_ns == stamp


class TestNotFound:
    def test_is_written(self, tmp_path, catalog, entries):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        assert (tmp_path / urls.NOT_FOUND).exists()

    def test_shares_header_and_footer_with_every_other_page(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        html = (tmp_path / urls.NOT_FOUND).read_text(encoding="utf-8")
        assert html.startswith("<!DOCTYPE html>")
        assert '<header class="site">' in html
        assert '<footer class="site">' in html

    def test_copy_comes_from_the_catalog(self, tmp_path, catalog, entries):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        html = (tmp_path / urls.NOT_FOUND).read_text(encoding="utf-8")
        assert catalog.t("notfound.title") in html
        assert catalog.t("notfound.message") in html
        assert catalog.t("nav.back_to_archive") in html

    def test_paths_are_absolute_when_a_feed_link_is_configured(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        html = (tmp_path / urls.NOT_FOUND).read_text(encoding="utf-8")
        assert f'href="{FEED_LINK}/{urls.STYLESHEET}"' in html
        assert f'href="{FEED_LINK}/{urls.ARCHIVE_FRONT}"' in html
        assert f'href="{FEED_LINK}/{urls.INDEX_PAGE}"' in html
        assert f'href="{FEED_LINK}/{urls.FEED_FILE}"' in html

    def test_falls_back_to_root_relative_paths_without_a_feed_link(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link="")
        html = (tmp_path / urls.NOT_FOUND).read_text(encoding="utf-8")
        assert f'href="/{urls.STYLESHEET}"' in html
        assert f'href="/{urls.ARCHIVE_FRONT}"' in html
        assert f'href="/{urls.INDEX_PAGE}"' in html
        # Never a bare relative path: that is the bug this task fixes.
        assert f'href="{urls.STYLESHEET}"' not in html

    def test_second_identical_build_does_not_rewrite_it(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        path = tmp_path / urls.NOT_FOUND
        stamp = path.stat().st_mtime_ns
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        assert path.stat().st_mtime_ns == stamp


class TestForAbsoluteRoot:
    """Unit coverage of the helper build_not_found relies on."""

    def test_prefixes_with_the_feed_link(self, catalog):
        ctx = site_builder.RenderContext(catalog=catalog, feed_link=FEED_LINK)
        absolute_ctx = site_builder.for_absolute_root(ctx)
        assert absolute_ctx.path_prefix == f"{FEED_LINK}/"
        assert absolute_ctx.u(urls.STYLESHEET) == f"{FEED_LINK}/{urls.STYLESHEET}"

    def test_falls_back_to_a_leading_slash_without_a_feed_link(self, catalog):
        ctx = site_builder.RenderContext(catalog=catalog, feed_link="")
        absolute_ctx = site_builder.for_absolute_root(ctx)
        assert absolute_ctx.path_prefix == "/"
        assert absolute_ctx.u(urls.STYLESHEET) == f"/{urls.STYLESHEET}"
