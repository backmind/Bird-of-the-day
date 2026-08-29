"""Tests for the semantic RSS item body."""

import re

from scripts.feed_builder import build_entry_html
from scripts.i18n import Catalog


def _html(**kwargs) -> str:
    defaults = dict(
        species_code="eurbla",
        common_name="Eurasian Blackbird",
        scientific_name="Turdus merula",
        image_url="https://cdn.example.org/asset/1/900",
        image_attribution="Jane Doe / Macaulay Library",
        ml_search_url="https://search.macaulaylibrary.org/catalog",
        description="",
        description_source="",
        bow_intro="",
        taxonomy={"familySciName": "Turdidae", "order": "Passeriformes"},
        catalog=Catalog.load("es"),
        number=141,
        date="2026-08-27",
        species_page_url="https://birds.example.org/birds/eurbla.html",
        enriched_prose="Primero.\n\nSegundo.",
        enriched_identification=["Pico amarillo.", "Ojo con anillo."],
    )
    defaults.update(kwargs)
    return build_entry_html(**defaults)


class TestItemStructure:
    def test_identification_gets_a_semantic_heading(self):
        html = _html()
        assert "<h3>Identificación en campo</h3>" in html
        assert html.index("<h3>") < html.index("<ul>")

    def test_no_heading_without_bullets(self):
        html = _html(enriched_identification=None)
        assert "<h3>" not in html
        assert "<ul>" not in html

    def test_head_line_carries_number_and_dotted_date(self):
        assert "№ 141 · 2026 · 08 · 27" in _html()

    def test_head_line_is_omitted_when_unknown(self):
        html = _html(number=0, date="")
        assert "№" not in html

    def test_photo_links_to_the_species_page(self):
        html = _html()
        assert 'href="https://birds.example.org/birds/eurbla.html"' in html
        assert 'alt="Eurasian Blackbird"' in html

    def test_photo_falls_back_to_ebird_without_a_species_page(self):
        html = _html(species_page_url="")
        assert "ebird.org/species/eurbla" in html

    def test_credit_is_its_own_italic_line(self):
        assert "<em>© Jane Doe / Macaulay Library</em>" in _html()

    def test_name_line_keeps_the_scientific_name_in_italics(self):
        assert "<em>Turdus merula</em></h2>" in _html()


class TestTaxonomyAndIucn:
    def test_separator_levels_are_preserved(self):
        html = _html(iucn_code="LC")
        assert (
            "<em>Turdidae</em> · <em>Passeriformes</em> // "
            "LC · Preocupación Menor" in html
        )

    def test_the_link_sits_on_the_code(self):
        html = _html(iucn_code="LC", iucn_birdlife_url="https://birdlife.example/x")
        assert '<a href="https://birdlife.example/x">LC</a> · Preocupación Menor' in html

    def test_taxonomy_alone_when_no_iucn(self):
        # The bare-slash form would also match the "//" inside the
        # fixture's own https:// links (required verbatim by the photo
        # and eBird link tests above), so this checks for the actual
        # separator token the taxonomy/IUCN line emits: " // ".
        html = _html()
        assert " // " not in html


class TestReaderSafety:
    FORBIDDEN = ("color:", "background", "border", "font-family", "font-size")

    def test_no_absolute_styling_survives(self):
        html = _html(
            iucn_code="LC",
            iucn_birdlife_url="https://birdlife.example/x",
            composed_map_url="https://birds.example.org/maps/eurbla.png",
            gbif_taxon_key=42,
            wikipedia_url="https://es.wikipedia.org/wiki/Turdus_merula",
        )
        for style in re.findall(r'style="([^"]*)"', html):
            for bad in self.FORBIDDEN:
                assert bad not in style, f"{bad} found in {style!r}"

    def test_no_absolute_positioning(self):
        html = _html(distribution_map_url="https://gbif.example/density.png")
        assert "position:absolute" not in html


class TestMap:
    def test_composed_map_in_a_figure_with_a_caption(self):
        html = _html(
            composed_map_url="https://birds.example.org/maps/eurbla.png",
            gbif_taxon_key=42,
        )
        assert "<figure" in html
        assert 'href="https://www.gbif.org/species/42"' in html
        assert "<figcaption><small>Distribución mundial</small></figcaption>" in html

    def test_density_only_map_uses_the_same_figure(self):
        html = _html(distribution_map_url="https://gbif.example/density.png")
        assert html.count("<figure") == 1
        assert "https://gbif.example/density.png" in html

    def test_no_figure_without_a_map(self):
        assert "<figure" not in _html()


class TestFallbackDescription:
    def test_scraped_description_renders_without_a_heading(self):
        html = _html(
            enriched_prose="",
            enriched_identification=None,
            description="Un pájaro negro.",
            description_source="ebird",
            bow_intro="Introducción.",
        )
        assert "Un pájaro negro." in html
        assert "Introducción." in html
        assert "<h3>" not in html

    def test_foreign_disclaimer_is_kept(self):
        html = _html(
            enriched_prose="",
            enriched_identification=None,
            description="A black bird.",
            description_source="ebird-foreign",
            fallback_language="en",
        )
        assert "inglés" in html
