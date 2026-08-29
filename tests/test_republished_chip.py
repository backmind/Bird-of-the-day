"""El chip que dice que esta ave ya salió."""

import json
from pathlib import Path

from scripts import archive_builder, feed_builder, i18n, site_builder, urls
from scripts.site_builder import RenderContext, SiteEntry


def _entry(previous_date=""):
    return SiteEntry(
        species_code="cometi1",
        common_name="Mirlo común",
        scientific_name="Turdus merula",
        date="2026-08-29",
        image_url="https://cdn/asset/1/1200",
        photographer="P",
        attribution="P / Macaulay Library",
        description="Texto.",
        description_source="ebird",
        bow_intro="",
        taxonomy={},
        ml_search_url="https://search.macaulaylibrary.org/catalog",
        number=42,
        previous_date=previous_date,
    )


def _ctx():
    return RenderContext(catalog=i18n.Catalog.load("es"), feed_link="")


def test_plate_shows_the_chip_linking_to_the_species_page():
    html = site_builder.render_plate(_entry("2026-06-12"), _ctx())
    assert "republished-chip" in html
    assert urls.species_url("cometi1") in html
    assert "2026 · 06 · 12" in html


def test_plate_without_a_previous_publication_has_no_chip():
    assert "republished-chip" not in site_builder.render_plate(_entry(), _ctx())


def test_card_chip_is_not_a_nested_link():
    """La tarjeta entera ya es un enlace: un <a> dentro sería inválido."""
    html = site_builder.render_card(_entry("2026-06-12"), _ctx())
    assert "republished-chip" in html
    assert html.count("<a ") == 1


def test_feed_item_chip_links_to_the_absolute_species_page():
    catalog = i18n.Catalog.load("es")
    html = feed_builder.build_entry_html(
        species_code="cometi1",
        common_name="Mirlo común",
        scientific_name="Turdus merula",
        image_url=None,
        image_attribution="",
        ml_search_url="",
        description="Texto.",
        description_source="ebird",
        bow_intro="",
        taxonomy={},
        catalog=catalog,
        number=42,
        date="2026-08-29",
        species_page_url="https://birds.example.com/birds/cometi1.html",
        previous_date="2026-06-12",
    )
    assert 'href="https://birds.example.com/birds/cometi1.html"' in html
    assert "2026 · 06 · 12" in html


def test_feed_item_without_a_previous_publication_is_unchanged():
    catalog = i18n.Catalog.load("es")
    html = feed_builder.build_entry_html(
        species_code="cometi1",
        common_name="Mirlo común",
        scientific_name="Turdus merula",
        image_url=None,
        image_attribution="",
        ml_search_url="",
        description="Texto.",
        description_source="ebird",
        bow_intro="",
        taxonomy={},
        catalog=catalog,
        number=42,
        date="2026-08-29",
    )
    assert catalog.t("republished.chip_template", date="x") not in html


def test_every_catalog_carries_the_chip_copy():
    for path in sorted(Path("data/i18n").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "republished.chip_template" in data, path.name
        assert "{date}" in data["republished.chip_template"], path.name


def test_species_page_omits_the_chip_but_its_month_bucket_still_shows_it(tmp_path):
    """The species page already lists every publication date under its own
    heading, so the brief rules the chip out there. A test that only
    checked the species page would still pass against a build that lost
    the chip everywhere, so the month bucket page is checked too, and it
    must still carry the chip for the same publication.
    """
    older = _entry()
    older.date = "2026-06-12"
    older.number = 1
    newer = _entry("2026-06-12")
    newer.date = "2026-08-29"
    newer.number = 2

    archive_builder.write_site([newer, older], tmp_path, i18n.Catalog.load("es"))

    species_html = (tmp_path / "birds" / "cometi1.html").read_text(encoding="utf-8")
    assert "republished-chip" not in species_html

    bucket_html = (
        tmp_path / urls.bucket_filename("2026-08-29")
    ).read_text(encoding="utf-8")
    assert "republished-chip" in bucket_html
