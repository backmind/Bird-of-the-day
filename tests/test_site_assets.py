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
