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

    def test_index_and_archive_front_lastmod_is_the_most_recent_publication(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        locs = _sitemap_locs(tmp_path)
        # entries[0] ("c", 2026-08-02) is the newest publication on the
        # whole site; pinned to that exact date so dating these two
        # pages by the oldest entry instead (entries[-1], 2026-07-15)
        # cannot pass unnoticed.
        assert locs[urls.absolute(FEED_LINK, urls.INDEX_PAGE)] == "2026-08-02"
        assert locs[urls.absolute(FEED_LINK, urls.ARCHIVE_FRONT)] == "2026-08-02"

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

    def test_ends_with_a_newline_like_robots_does(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        sitemap = (tmp_path / urls.SITEMAP).read_text(encoding="utf-8")
        robots = (tmp_path / urls.ROBOTS).read_text(encoding="utf-8")
        assert sitemap.endswith("\n")
        assert robots.endswith("\n")


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

    def test_tells_crawlers_not_to_index_it(self, tmp_path, catalog, entries):
        # Requested by name it answers 200, on nginx and on GitHub Pages
        # alike: the 404 status is substituted for the URL that was
        # missing, not for this file. So being absent from sitemap.xml
        # is not enough; the page has to say so itself.
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        html = (tmp_path / urls.NOT_FOUND).read_text(encoding="utf-8")
        assert '<meta name="robots" content="noindex">' in html

    def test_says_so_even_without_a_feed_link(self, tmp_path, catalog, entries):
        # Unlike the canonical and the Open Graph block, this one does
        # not depend on a base URL: it is a directive, not a reference.
        archive_builder.write_site(entries, tmp_path, catalog, feed_link="")
        html = (tmp_path / urls.NOT_FOUND).read_text(encoding="utf-8")
        assert '<meta name="robots" content="noindex">' in html

    def test_no_other_page_is_marked_noindex(self, tmp_path, catalog, entries):
        # The whole site disappearing from search results is a plausible
        # outcome of copying this line to the wrong builder.
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        for page in tmp_path.rglob("*.html"):
            if page.name == urls.NOT_FOUND:
                continue
            assert 'name="robots"' not in page.read_text(encoding="utf-8"), page

    def test_shares_header_and_footer_with_every_other_page(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        html = (tmp_path / urls.NOT_FOUND).read_text(encoding="utf-8")
        assert html.startswith("<!DOCTYPE html>")
        assert '<header class="site">' in html
        assert '<footer class="site">' in html

    def test_copy_comes_from_the_catalog(self, tmp_path, entries):
        # A non-English catalog: notfound.title is also a substring of
        # <title> and notfound.message is also the page's
        # <meta name="description"> content, both in <head>, and both
        # of those already carry this same catalog's strings on every
        # page. Loading a language other than the fixture "en" catalog
        # every other test in this class uses is what stops a hardcoded
        # English literal in build_not_found from passing this test.
        catalog = Catalog.load("es")
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        html = (tmp_path / urls.NOT_FOUND).read_text(encoding="utf-8")
        # Scoped to <main>: without this, the assertions below would be
        # satisfied by <head> alone even if <main> were empty.
        main_html = html[html.index('<main id="main">') : html.index("</main>")]
        assert catalog.t("notfound.title") in main_html
        assert catalog.t("notfound.message") in main_html
        assert catalog.t("nav.back_to_archive") in main_html

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
