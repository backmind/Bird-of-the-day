"""Tests for the published basemap asset and atlas references."""

from unittest.mock import MagicMock

from scripts import archive_builder, site_builder, urls
from scripts.i18n import Catalog


def _catalog() -> Catalog:
    return Catalog.load("en")


class TestWriteSiteAssets:
    def test_basemap_copied_into_assets(self, tmp_path):
        archive_builder.write_site([], tmp_path, catalog=_catalog())
        asset = tmp_path / "assets" / "basemap.png"
        assert asset.exists()
        assert asset.stat().st_size > 0

    def test_fonts_copied_into_assets(self, tmp_path):
        archive_builder.write_site([], tmp_path, catalog=_catalog())
        fonts_dir = tmp_path / "assets" / "fonts"
        for filename in urls.FONT_FILES:
            asset = fonts_dir / filename
            assert asset.exists()
            assert asset.stat().st_size > 0

    def test_atlas_references_local_asset(self):
        entry = MagicMock()
        entry.distribution_map_url = "http://gbif/density.png"
        entry.gbif_taxon_key = 12345
        entry.scientific_name = "Parus major"
        ctx = site_builder.RenderContext(catalog=_catalog(), feed_link="")
        html = site_builder._render_atlas(entry, ctx)
        assert 'src="assets/basemap.png"' in html
        assert "cartocdn" not in html
        assert "OpenStreetMap" in html


class TestFeedDiscovery:
    """The pages may only advertise files the run actually publishes.

    ``feed-full.xml`` exists only when a cap applies, so every assertion
    here is paired: what the page says with the flag on, and what it must
    not say with it off.
    """

    def _ctx(self, prefix: str = "", full_feed: bool = True):
        return site_builder.RenderContext(
            catalog=_catalog(),
            feed_link="",
            path_prefix=prefix,
            full_feed=full_feed,
        )

    def _page(self, prefix: str = "", full_feed: bool = True) -> str:
        return site_builder.render_page(
            "Title", "<p>body</p>", self._ctx(prefix, full_feed), active="home"
        )

    def test_both_feeds_are_announced(self):
        html = self._page(full_feed=True)
        assert 'href="feed.xml"' in html
        assert 'href="feed-full.xml"' in html

    def test_species_pages_reach_the_feeds_from_their_subdirectory(self):
        html = self._page(prefix="../", full_feed=True)
        assert 'href="../feed.xml"' in html
        assert 'href="../feed-full.xml"' in html

    def test_subscribe_card_offers_the_full_history(self):
        html = site_builder.render_subscribe(self._ctx(full_feed=True))
        assert 'href="feed-full.xml"' in html

    def test_head_never_announces_an_unwritten_full_feed(self):
        html = self._page(full_feed=False)
        assert 'href="feed.xml"' in html
        assert "feed-full.xml" not in html

    def test_subscribe_card_stays_quiet_without_a_full_feed(self):
        html = site_builder.render_subscribe(self._ctx(full_feed=False))
        assert "feed-full.xml" not in html
        assert _catalog().t("subscribe.full_feed") not in html

    def test_species_page_context_keeps_the_flag(self):
        # for_subdirectory derives the species-page context. A dropped
        # field here would silently unlink the full feed on every one of
        # them while the root pages still advertised it.
        derived = site_builder.for_subdirectory(self._ctx(full_feed=True), "../")
        assert derived.full_feed is True
        html = site_builder.render_page(
            "Title", "<p>body</p>", derived, active="home"
        )
        assert 'href="../feed-full.xml"' in html


def test_no_third_party_font_request():
    """El sitio no puede pedirle nada a Google para renderizarse."""
    from scripts import site_css
    assert "fonts.googleapis" not in site_css.CSS
    assert "fonts.gstatic" not in site_css.CSS
    assert "@import" not in site_css.CSS


def test_font_faces_point_at_published_assets():
    from scripts import site_css, urls

    assert "@font-face" in site_css.CSS
    assert "font-display: swap" in site_css.CSS
    # The stylesheet and the fonts share the assets/ prefix, so a src
    # relative to the stylesheet drops it. Deriving the prefix here means
    # moving either constant breaks this test instead of the live site.
    stylesheet_dir = urls.STYLESHEET.rsplit("/", 1)[0]
    assert urls.FONTS_DIR.startswith(stylesheet_dir + "/")
    relative_dir = urls.FONTS_DIR[len(stylesheet_dir) + 1 :]
    for filename in urls.FONT_FILES:
        assert f"url('{relative_dir}/{filename}')" in site_css.CSS


class TestFontPreload:
    """The hero font must reach the browser before first paint, but the
    preload target still has to resolve from whatever depth the page
    lives at, exactly like the feed links above."""

    def _ctx(self, prefix: str = ""):
        return site_builder.RenderContext(
            catalog=_catalog(), feed_link="", path_prefix=prefix
        )

    def test_preload_links_the_plate_heading_font(self):
        html = site_builder.render_page(
            "Title", "<p>body</p>", self._ctx(), active="home"
        )
        assert 'rel="preload"' in html
        assert 'as="font"' in html
        assert 'type="font/woff2"' in html
        assert "crossorigin" in html
        assert f'href="{urls.FONT_PRELOAD}"' in html

    def test_preload_resolves_from_a_subdirectory(self):
        html = site_builder.render_page(
            "Title", "<p>body</p>", self._ctx(prefix="../"), active="home"
        )
        assert f'href="../{urls.FONT_PRELOAD}"' in html
