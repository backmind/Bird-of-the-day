"""Tests for the RSS map rendering: no CARTO, no overlay tricks."""

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


class TestFeedMap:
    def test_fallback_renders_the_density_layer_alone(self):
        html = _entry_html()
        assert "http://gbif/density.png" in html
        assert "cartocdn" not in html
        assert "position:absolute" not in html

    def test_composed_map_wins_over_the_density_layer(self):
        html = _entry_html(composed_map_url="https://example.org/maps/parmaj.png")
        assert "maps/parmaj.png" in html
        assert "gbif/density.png" not in html

    def test_map_links_to_the_gbif_species_page(self):
        html = _entry_html(composed_map_url="https://example.org/maps/parmaj.png")
        assert 'href="https://www.gbif.org/species/12345"' in html
