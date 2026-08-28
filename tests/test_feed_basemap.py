"""Tests for the RSS map fallback rendering without CARTO."""

from scripts.feed_builder import build_entry_html
from scripts.i18n import Catalog


def _entry_html(**kwargs) -> str:
    defaults = dict(
        species_code="parmaj",
        common_name="Great Tit",
        scientific_name="Parus major",
        image_url=None,
        image_attribution="",
        ml_search_url="http://ml/search",
        description="A bird.",
        description_source="ebird",
        bow_intro="",
        taxonomy={},
        catalog=Catalog.load("en"),
        distribution_map_url="http://gbif/density.png",
        gbif_taxon_key=12345,
    )
    defaults.update(kwargs)
    return build_entry_html(**defaults)


class TestFeedBasemap:
    def test_fallback_uses_given_basemap_url(self):
        html = _entry_html(basemap_url="https://example.org/assets/basemap.png")
        assert "https://example.org/assets/basemap.png" in html
        assert "cartocdn" not in html

    def test_fallback_without_basemap_renders_density_only(self):
        html = _entry_html()
        assert "http://gbif/density.png" in html
        assert "cartocdn" not in html

    def test_composed_map_ignores_basemap_url(self):
        html = _entry_html(
            composed_map_url="https://example.org/maps/parmaj.png",
            basemap_url="https://example.org/assets/basemap.png",
        )
        assert "maps/parmaj.png" in html
        assert "assets/basemap.png" not in html
