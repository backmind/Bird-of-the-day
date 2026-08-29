"""Tests for the published basemap asset and atlas references."""

from unittest.mock import MagicMock

from scripts import archive_builder, site_builder
from scripts.i18n import Catalog


def _catalog() -> Catalog:
    return Catalog.load("en")


class TestWriteSiteAssets:
    def test_basemap_copied_into_assets(self, tmp_path):
        archive_builder.write_site([], tmp_path, catalog=_catalog())
        asset = tmp_path / "assets" / "basemap.png"
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
