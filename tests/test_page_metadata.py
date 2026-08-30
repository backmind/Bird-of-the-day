"""Every page class advertises itself, not the whole site.

Before this, the four page classes (home, archive front, month bucket,
species page) shared one ``<meta name="description">`` (the fixed
``site.tagline``) and emitted no Open Graph tags at all, so a link to a
species page unfurled identically to a link to the home page. These
tests build a small site into ``tmp_path`` with ``archive_builder.write_site``
and read the written files back, the same approach as
``tests/test_site_write_policy.py`` and ``tests/test_species_pages.py``.
"""

import re

import pytest

from scripts import archive_builder, site_builder, urls
from scripts.i18n import Catalog
from tests.test_archive_buckets import _entry

FEED_LINK = "https://example.invalid"
IMG_D = "https://macaulaylibrary.invalid/d.jpg"
IMG_C = "https://macaulaylibrary.invalid/c.jpg"
IMG_B = "https://macaulaylibrary.invalid/b.jpg"


@pytest.fixture
def catalog():
    return Catalog.load("en")


@pytest.fixture
def entries():
    # Newest first, as generate.py hands them over. "d" is the most
    # recent bird and carries a photo; "a" (an older month) has none, so
    # that species page exercises the no-photo branch.
    return [
        _entry("d", "2026-08-03", 5, image_url=IMG_D),
        _entry("c", "2026-08-02", 4, image_url=IMG_C),
        _entry("b", "2026-08-01", 3, image_url=IMG_B),
        _entry("a", "2026-07-31", 2, image_url=None),
    ]


def _pages(tmp_path) -> dict[str, str]:
    return {
        p.relative_to(tmp_path).as_posix(): p.read_text(encoding="utf-8")
        for p in tmp_path.rglob("*.html")
    }


def _meta_description(html: str) -> str | None:
    m = re.search(r'<meta name="description" content="([^"]*)">', html)
    return m.group(1) if m else None


def _og(html: str, prop: str) -> str | None:
    m = re.search(rf'<meta property="og:{prop}" content="([^"]*)">', html)
    return m.group(1) if m else None


def _canonical(html: str) -> str | None:
    m = re.search(r'<link rel="canonical" href="([^"]*)">', html)
    return m.group(1) if m else None


def _entry_with_name(code, date, number, common_name, *, image_url=None):
    """Like ``_entry``, but with a caller-chosen common name.

    Used to carry a name with characters that are dangerous inside an
    HTML attribute value (``"`` ends it early, ``&`` starts a malformed
    entity) through the same fields ``_entry`` fills in a boring way.
    """
    return site_builder.SiteEntry(
        species_code=code,
        common_name=common_name,
        scientific_name="Genus species",
        date=date,
        image_url=image_url,
        photographer="",
        attribution="",
        description="A description.",
        description_source="ebird",
        bow_intro="",
        taxonomy={},
        ml_search_url="https://example.invalid/ml",
        number=number,
    )


class TestPerPageDescriptions:
    def test_every_page_class_carries_its_own_description(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        pages = _pages(tmp_path)
        descriptions = {
            name: _meta_description(html)
            for name, html in pages.items()
            if name
            in {
                "index.html",
                "archive.html",
                "archive-2026-08.html",
                "birds/d.html",
            }
        }
        # All four classes have a non-empty description.
        assert all(descriptions.values()), descriptions
        # And they are not the same string repeated four times.
        assert len(set(descriptions.values())) == 4

    def test_species_page_description_names_the_species(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        html = _pages(tmp_path)["birds/d.html"]
        assert "Bird d" in _meta_description(html)

    def test_bucket_description_names_the_month(self, tmp_path, catalog, entries):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        html = _pages(tmp_path)["archive-2026-08.html"]
        assert "August 2026" in _meta_description(html)

    def test_archive_front_description_states_the_entry_count(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        html = _pages(tmp_path)["archive.html"]
        assert str(len(entries)) in _meta_description(html)

    def test_home_description_names_todays_bird(self, tmp_path, catalog, entries):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        html = _pages(tmp_path)["index.html"]
        # entries[0] ("d") is the hero on the home page.
        assert "Bird d" in _meta_description(html)

    def test_description_no_longer_defaults_to_the_shared_tagline(
        self, catalog
    ):
        # Direct render_page unit check: with no description passed, the
        # tag is omitted rather than falling back to a shared site-wide
        # copy (the old "site.tagline" key this once read no longer
        # exists at all), so an un-migrated caller cannot silently
        # resurrect it.
        ctx = site_builder.RenderContext(catalog=catalog, feed_link="")
        html = site_builder.render_page("Title", "<p>body</p>", ctx, active="home")
        assert 'name="description"' not in html


class TestOpenGraphWithFeedLink:
    def test_every_page_class_emits_the_core_og_tags(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        pages = _pages(tmp_path)
        for name in ("index.html", "archive.html", "archive-2026-08.html", "birds/d.html"):
            html = pages[name]
            assert _og(html, "title")
            assert _og(html, "type")
            url = _og(html, "url")
            assert url is not None
            assert url.startswith(FEED_LINK)
            assert _og(html, "description") == _meta_description(html)

    def test_og_url_is_absolute_and_ignores_page_depth(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        pages = _pages(tmp_path)
        assert _og(pages["index.html"], "url") == f"{FEED_LINK}/index.html"
        assert _og(pages["archive.html"], "url") == f"{FEED_LINK}/archive.html"
        assert (
            _og(pages["archive-2026-08.html"], "url")
            == f"{FEED_LINK}/archive-2026-08.html"
        )
        # Species pages live in birds/ and render with a "../" path
        # prefix for in-page navigation, but og:url must not carry it.
        assert _og(pages["birds/d.html"], "url") == f"{FEED_LINK}/birds/d.html"

    def test_species_og_image_is_its_own_photo(self, tmp_path, catalog, entries):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        html = _pages(tmp_path)["birds/d.html"]
        assert _og(html, "image") == IMG_D

    def test_home_and_archive_og_image_is_the_most_recent_bird(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        pages = _pages(tmp_path)
        # "d" is the most recent publication across the whole site.
        assert _og(pages["index.html"], "image") == IMG_D
        assert _og(pages["archive.html"], "image") == IMG_D

    def test_bucket_og_image_is_the_most_recent_bird_in_that_month(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        html = _pages(tmp_path)["archive-2026-08.html"]
        # All of d, c, b fall in 2026-08; d is the newest of the three.
        assert _og(html, "image") == IMG_D

    def test_page_without_a_photo_omits_og_image_rather_than_emit_it_empty(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        html = _pages(tmp_path)["birds/a.html"]
        assert 'property="og:image"' not in html

    def test_the_most_recent_bird_lacking_a_photo_still_omits_og_image(
        self, tmp_path, catalog
    ):
        # The newest entry has no photo even though an older one in the
        # same scope does; the rule is "the most recent", never "the
        # first one found with a photo".
        entries = [
            _entry("y", "2026-08-05", 6, image_url=None),
            _entry("x", "2026-08-04", 5, image_url=IMG_C),
        ]
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        pages = _pages(tmp_path)
        assert 'property="og:image"' not in pages["index.html"]
        assert 'property="og:image"' not in pages["archive.html"]
        assert 'property="og:image"' not in pages["archive-2026-08.html"]


class TestCanonicalWithFeedLink:
    """The home page is reachable at two URLs, the bare base and
    ``index.html``, and ``sitemap.xml`` and ``og:url`` both name the
    second. Without a canonical, nothing on the page says the two are
    the same document."""

    PAGE_CLASSES = ("index.html", "archive.html", "archive-2026-08.html", "birds/d.html")

    def test_every_page_class_declares_a_canonical(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        pages = _pages(tmp_path)
        for name in self.PAGE_CLASSES:
            canonical = _canonical(pages[name])
            assert canonical is not None, f"{name} has no canonical"
            assert canonical.startswith(FEED_LINK)

    def test_canonical_is_the_pages_own_absolute_url(
        self, tmp_path, catalog, entries
    ):
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        pages = _pages(tmp_path)
        for name in self.PAGE_CLASSES:
            assert _canonical(pages[name]) == f"{FEED_LINK}/{name}"

    def test_canonical_never_carries_the_page_depth_prefix(
        self, tmp_path, catalog, entries
    ):
        # Species pages render with a "../" prefix for in-page links. A
        # canonical that picked it up would name a URL outside the site.
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        assert ".." not in _canonical(_pages(tmp_path)["birds/d.html"])

    def test_canonical_agrees_with_og_url(self, tmp_path, catalog, entries):
        # Both come off OpenGraph.path precisely so they cannot disagree.
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        pages = _pages(tmp_path)
        for name in self.PAGE_CLASSES:
            assert _canonical(pages[name]) == _og(pages[name], "url")

    def test_the_404_declares_no_canonical(self, tmp_path, catalog, entries):
        # It is served for every URL that does not exist, so it has no
        # single URL to claim as its own. It carries noindex instead.
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        html = (tmp_path / urls.NOT_FOUND).read_text(encoding="utf-8")
        assert _canonical(html) is None


class TestNoOpenGraphWithoutFeedLink:
    """The rule this package cannot afford to get wrong: a relative
    og:url is worse than no og:url at all, because no client consuming
    the tag can resolve it."""

    def test_no_page_class_emits_any_og_tag(self, tmp_path, catalog, entries):
        archive_builder.write_site(entries, tmp_path, catalog)  # feed_link="" default
        pages = _pages(tmp_path)
        for name in ("index.html", "archive.html", "archive-2026-08.html", "birds/d.html"):
            html = pages[name]
            assert 'property="og:' not in html

    def test_descriptions_are_unaffected_by_the_missing_feed_link(
        self, tmp_path, catalog, entries
    ):
        # Losing Open Graph must not take the plain meta description
        # with it: the two are independent features.
        archive_builder.write_site(entries, tmp_path, catalog)
        html = _pages(tmp_path)["birds/d.html"]
        assert _meta_description(html)

    def test_render_page_with_og_data_but_no_feed_link_stays_quiet(self, catalog):
        ctx = site_builder.RenderContext(catalog=catalog, feed_link="")
        og = site_builder.OpenGraph(
            title="T", path="index.html", image="https://x.invalid/p.jpg"
        )
        html = site_builder.render_page(
            "Title", "<p>body</p>", ctx, active="home", og=og
        )
        assert 'property="og:' not in html

    def test_render_page_without_og_argument_stays_quiet_even_with_a_feed_link(
        self, catalog
    ):
        # og defaults to None: a feed_link alone must not resurrect tags
        # for a caller that never opted in.
        ctx = site_builder.RenderContext(catalog=catalog, feed_link=FEED_LINK)
        html = site_builder.render_page("Title", "<p>body</p>", ctx, active="home")
        assert 'property="og:' not in html

    def test_no_page_class_declares_a_canonical(self, tmp_path, catalog, entries):
        # Same rule as og:url, for the same reason: a relative canonical
        # cannot be resolved by the crawler that reads it, and a wrong
        # one is worse than none.
        archive_builder.write_site(entries, tmp_path, catalog)
        pages = _pages(tmp_path)
        for name in ("index.html", "archive.html", "archive-2026-08.html", "birds/d.html"):
            assert 'rel="canonical"' not in pages[name]

    def test_render_page_with_og_data_but_no_feed_link_emits_no_canonical(
        self, catalog
    ):
        ctx = site_builder.RenderContext(catalog=catalog, feed_link="")
        og = site_builder.OpenGraph(title="T", path="index.html")
        html = site_builder.render_page(
            "Title", "<p>body</p>", ctx, active="home", og=og
        )
        assert 'rel="canonical"' not in html


class TestEscaping:
    """A species name is user-supplied text (eBird's own common name),
    not a literal the codebase controls. It reaches three attribute
    values per page (meta description, og:title, og:description), and
    one unescaped ``"`` in any of them ends that attribute early; one
    unescaped ``&`` starts a malformed entity. Both characters together,
    in one name, is exactly the shape of input that reintroduces this
    class of bug."""

    TRICKY_NAME = 'Robin "Red" & Co'
    ESCAPED_NAME = "Robin &quot;Red&quot; &amp; Co"

    def test_quotes_and_ampersand_are_escaped_in_every_new_tag(
        self, tmp_path, catalog
    ):
        entries = [
            _entry_with_name("trky", "2026-08-03", 1, self.TRICKY_NAME),
        ]
        archive_builder.write_site(entries, tmp_path, catalog, feed_link=FEED_LINK)
        pages = _pages(tmp_path)

        for name in ("index.html", "birds/trky.html"):
            html = pages[name]
            # The raw name must never survive unescaped anywhere on the
            # page: that is the general guarantee. The three assertions
            # below pin down the specific tags this task adds.
            assert self.TRICKY_NAME not in html
            assert self.ESCAPED_NAME in _meta_description(html)
            assert self.ESCAPED_NAME in _og(html, "title")
            assert self.ESCAPED_NAME in _og(html, "description")
