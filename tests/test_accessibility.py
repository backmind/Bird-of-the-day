"""Three accessibility defects, and the authorship split they surfaced.

``.card a { display: contents; }`` drops the whole card's link from the
accessibility tree in several browsers even though the anchor still
wraps every visible bit of the card; images render with no declared
proportion, so the page reflows as each one loads; and there was no
``prefers-reduced-motion`` escape hatch for the hover zooms and the
theme-toggle spin.

Fixing the footer meant noticing it hardcoded the original instance
owner's name in the same catalog keys a clone inherits verbatim, so a
clone publishes a site (and a feed) that claims to be someone else's.
This file also pins the fix for that: the template's own credit is
always visible and never configurable, the instance's author line is
opt-in via ``site_author``.
"""

import json
import re

from bs4 import BeautifulSoup

from scripts import archive_builder, feed_builder, site_builder, site_css
from scripts.i18n import CATALOG_DIR, Catalog, discover_languages
from tests.test_archive_buckets import _entry

FEED_LINK = "https://example.invalid"


def _ctx(**kwargs):
    return site_builder.RenderContext(catalog=Catalog.load("en"), feed_link="", **kwargs)


def _pages(tmp_path) -> dict[str, str]:
    return {
        p.relative_to(tmp_path).as_posix(): p.read_text(encoding="utf-8")
        for p in tmp_path.rglob("*.html")
    }


def _load_catalog(lang: str) -> dict:
    return json.loads((CATALOG_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def _css_classes_with_aspect_ratio() -> set[str]:
    """Every class named in a selector whose rule body sets aspect-ratio.

    The stylesheet has no rule that nests braces inside its own body (a
    flat property list per selector), so matching up to the first ``}``
    after a selector's ``{`` is exactly that rule, nested media queries
    included: their inner rules are simple selector/body pairs too.
    """
    classes: set[str] = set()
    for selector, body in re.findall(r"([.\w:,\s-]+)\{([^}]*)\}", site_css.CSS):
        if "aspect-ratio" not in body:
            continue
        classes.update(re.findall(r"\.([\w-]+)", selector))
    return classes


def _extract_block(css: str, marker: str) -> str:
    """Brace-matched contents of the first block starting at ``marker``."""
    start = css.index(marker)
    brace_start = css.index("{", start)
    depth = 0
    for i in range(brace_start, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[brace_start + 1 : i]
    raise AssertionError(f"unbalanced braces after {marker!r}")


class TestCardLinkIsARealAnchor:
    def test_display_contents_is_gone_from_the_card_link_rule(self):
        # Scoped to the rule itself, not a bare substring search: a
        # comment documenting the fix is allowed to name the property it
        # replaced without tripping this assertion.
        body = _extract_block(site_css.CSS, ".card a {")
        assert "contents" not in body

    def test_card_is_still_one_real_anchor_with_visible_text(self):
        html = site_builder.render_card(_entry("eurbla", "2026-08-27", 3), _ctx())
        assert html.count("<a ") == 1
        match = re.search(r'<a href="[^"]*">(.*)</a>', html, re.DOTALL)
        assert match is not None
        assert "Bird eurbla" in match.group(1)

    def test_no_anchor_nests_another_anchor_on_a_built_site(self, tmp_path):
        entries = [
            _entry("d", "2026-08-03", 5, image_url="https://x.invalid/d.jpg"),
            _entry("c", "2026-08-02", 4, image_url="https://x.invalid/c.jpg"),
        ]
        # A republished species: the chip is the other place a nested
        # anchor could creep back in (see test_republished_chip.py).
        entries[0].previous_date = "2026-01-01"
        archive_builder.write_site(
            entries, tmp_path, Catalog.load("en"), feed_link=FEED_LINK
        )
        for name, html in _pages(tmp_path).items():
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a"):
                assert a.find("a") is None, f"{name}: nested <a> inside {a}"


class TestImagesDeclareTheirProportion:
    def test_every_img_has_dimensions_or_a_ratio_declaring_ancestor(self, tmp_path):
        entries = [
            _entry("d", "2026-08-03", 5, image_url="https://x.invalid/d.jpg"),
            _entry("a", "2026-07-31", 2, image_url=None),
        ]
        entries[0].distribution_map_url = "https://x.invalid/map.png"
        archive_builder.write_site(
            entries, tmp_path, Catalog.load("en"), feed_link=FEED_LINK
        )
        ratio_classes = _css_classes_with_aspect_ratio()
        assert ratio_classes  # sanity: the stylesheet still declares some
        checked = 0
        for name, html in _pages(tmp_path).items():
            soup = BeautifulSoup(html, "html.parser")
            for img in soup.find_all("img"):
                checked += 1
                if img.get("width") and img.get("height"):
                    continue
                ancestor_classes = {
                    c for parent in img.parents for c in (parent.get("class") or [])
                }
                assert ancestor_classes & ratio_classes, (
                    f"{name}: <img> with no width/height and no "
                    f"ratio-declaring ancestor: {img}"
                )
        assert checked  # sanity: the fixture actually rendered <img> tags


class TestReducedMotion:
    def test_media_query_is_present(self):
        assert "@media (prefers-reduced-motion: reduce)" in site_css.CSS

    def test_it_neutralizes_transitions_and_animations(self):
        body = _extract_block(
            site_css.CSS, "@media (prefers-reduced-motion: reduce)"
        )
        assert "transition-duration" in body
        assert "animation-duration" in body

    def test_each_hover_transform_effect_is_individually_reset(self):
        # Checked one at a time on purpose: a single regex that matches
        # if any one selector survives would still pass after silently
        # deleting three of the four (e.g. keeping only
        # .theme-toggle:hover), which is exactly the regression this
        # test exists to catch.
        body = _extract_block(
            site_css.CSS, "@media (prefers-reduced-motion: reduce)"
        )
        for selector in (
            ".plate:hover .plate-image img",
            ".card a:hover .card-thumb img",
            ".theme-toggle:hover",
            ".iucn-badge:hover",
        ):
            assert selector in body, selector
            rule_body = _extract_block(body, selector)
            assert "transform: none" in rule_body, selector


class TestFooterWithoutSiteAuthor:
    def test_shows_the_template_credit_and_no_instance_author_line(self):
        html = site_builder._render_footer(_ctx())
        assert "github.com/backmind/Bird-of-the-day" in html
        assert "Non-commercial project by" not in html


class TestFooterWithSiteAuthor:
    def test_shows_both_the_instance_author_and_the_template_credit(self):
        html = site_builder._render_footer(_ctx(site_author="Jane Birder"))
        assert "Jane Birder" in html
        assert "Non-commercial project by" in html
        assert "github.com/backmind/Bird-of-the-day" in html

    def test_name_is_escaped_against_a_stray_ampersand(self):
        html = site_builder._render_footer(_ctx(site_author="Jane & Co"))
        assert "Jane & Co" not in html
        assert "Jane &amp; Co" in html

    def test_url_is_escaped_against_attribute_injection(self):
        tricky = 'https://jane.example/"><script>evil()</script>'
        html = site_builder._render_footer(
            _ctx(site_author="Jane", site_author_url=tricky)
        )
        assert "<script>evil()</script>" not in html
        assert "&quot;&gt;&lt;script&gt;" in html

    def test_name_is_linked_when_a_url_is_configured(self):
        html = site_builder._render_footer(
            _ctx(site_author="Jane", site_author_url="https://jane.example/")
        )
        assert '<a href="https://jane.example/"' in html
        assert ">Jane</a>" in html

    def test_name_is_plain_text_without_a_url(self):
        # The template credit's own anchor lives in the same footer,
        # so the check has to be anchored on the name itself rather than
        # on "no <a> anywhere near it".
        html = site_builder._render_footer(_ctx(site_author="Jane"))
        match = re.search(r"(<a[^>]*>)?Jane(</a>)?", html)
        assert match is not None
        assert match.group(1) is None
        assert match.group(2) is None

    def test_author_line_and_template_credit_are_separate_paragraphs(self):
        # Structural, not prose: the two authorships must not share one
        # <p>, since the template credit is the half that has to survive
        # any clone unchanged and a shared sentence only distinguishes
        # them by where the sentence break falls.
        html = site_builder._render_footer(_ctx(site_author="Jane Birder"))
        soup = BeautifulSoup(html, "html.parser")
        paragraphs = [str(p) for p in soup.find_all("p")]
        author_paragraphs = [p for p in paragraphs if "Jane Birder" in p]
        credit_paragraphs = [
            p for p in paragraphs if "backmind/Bird-of-the-day" in p
        ]
        assert len(author_paragraphs) == 1
        assert len(credit_paragraphs) == 1
        assert author_paragraphs[0] != credit_paragraphs[0]
        assert "Jane Birder" not in credit_paragraphs[0]
        assert "backmind/Bird-of-the-day" not in author_paragraphs[0]


class TestCloneNeverPublishesSomeoneElseAsAuthor:
    """The problem the authorship split fixes: a fresh clone with no
    ``site_author`` configured used to publish a site (and a feed) that
    named the original template author as if they owned the instance."""

    def test_default_site_never_links_the_original_owners_personal_site(
        self, tmp_path
    ):
        archive_builder.write_site(
            [_entry("d", "2026-08-03", 5)],
            tmp_path,
            Catalog.load("en"),
            feed_link=FEED_LINK,
        )
        for name, html in _pages(tmp_path).items():
            assert "yassfuentes.es" not in html, name

    def test_default_site_still_credits_the_template_everywhere(self, tmp_path):
        archive_builder.write_site(
            [_entry("d", "2026-08-03", 5)],
            tmp_path,
            Catalog.load("en"),
            feed_link=FEED_LINK,
        )
        for name, html in _pages(tmp_path).items():
            assert "github.com/backmind/Bird-of-the-day" in html, name

    def test_default_feed_copyright_names_no_one(self):
        xml = feed_builder.build_feed([], {"feed_link": FEED_LINK}, Catalog.load("en"))
        copyright_text = re.search(r"<copyright>(.*?)</copyright>", xml, re.DOTALL)
        assert copyright_text is not None
        assert "Yass Fuentes" not in copyright_text.group(1)

    def test_feed_copyright_names_the_configured_author(self):
        xml = feed_builder.build_feed(
            [],
            {"feed_link": FEED_LINK, "site_author": "Jane Birder"},
            Catalog.load("en"),
        )
        copyright_text = re.search(r"<copyright>(.*?)</copyright>", xml, re.DOTALL)
        assert copyright_text is not None
        assert "Jane Birder" in copyright_text.group(1)


class TestSiteAuthorReachesTheBuiltPagesThroughWriteSite:
    """The wiring, not just the renderer it ends up calling: a config
    value has to survive ``write_site`` building the ``RenderContext``
    and forwarding it to every page builder. Every other "with author"
    test in this file calls ``site_builder._render_footer`` directly,
    which would still pass if ``write_site`` silently dropped the
    ``site_author``/``site_author_url`` keyword arguments."""

    def test_site_author_configured_on_write_site_reaches_every_page(
        self, tmp_path
    ):
        archive_builder.write_site(
            [_entry("d", "2026-08-03", 5)],
            tmp_path,
            Catalog.load("en"),
            feed_link=FEED_LINK,
            site_author="Jane Birder",
            site_author_url="https://jane.example/",
        )
        for name, html in _pages(tmp_path).items():
            assert "Jane Birder" in html, name
            assert 'href="https://jane.example/"' in html, name


class TestTemplateCreditCatalogParity:
    def test_template_credit_key_exists_in_every_catalog(self):
        for lang in discover_languages():
            data = _load_catalog(lang)
            assert "footer.template_credit_html" in data, lang
            assert data["footer.template_credit_html"].strip(), lang
            assert "backmind/Bird-of-the-day" in data["footer.template_credit_html"]

    def test_the_old_code_link_key_is_gone_everywhere(self):
        for lang in discover_languages():
            data = _load_catalog(lang)
            assert "footer.code_link_html" not in data, lang

    def test_author_templates_take_a_name_placeholder_everywhere(self):
        for lang in discover_languages():
            data = _load_catalog(lang)
            assert "{name}" in data["footer.author_template"], lang
            assert "{name}" in data["feed.copyright_author_template"], lang
