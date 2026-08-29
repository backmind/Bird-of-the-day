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
    def _page(self, prefix: str = "") -> str:
        ctx = site_builder.RenderContext(
            catalog=_catalog(), feed_link="", path_prefix=prefix
        )
        return site_builder.render_page("Title", "<p>body</p>", ctx, active="home")

    def test_both_feeds_are_announced(self):
        html = self._page()
        assert 'href="feed.xml"' in html
        assert 'href="feed-full.xml"' in html

    def test_species_pages_reach_the_feeds_from_their_subdirectory(self):
        html = self._page(prefix="../")
        assert 'href="../feed.xml"' in html
        assert 'href="../feed-full.xml"' in html

    def test_subscribe_card_offers_the_full_history(self):
        ctx = site_builder.RenderContext(catalog=_catalog(), feed_link="")
        html = site_builder.render_subscribe(ctx)
        assert 'href="feed-full.xml"' in html
