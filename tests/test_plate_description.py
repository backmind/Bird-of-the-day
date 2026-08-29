"""The plate's description block: prose, bullets, and the fallback.

``render_plate`` and ``feed_builder.build_entry_html`` read the same two
enrichment fields off the same cache file and must agree about what an
entry looks like. They both used to nest the identification bullets
inside the prose branch, so an enrichment with bullets and no prose lost
both the heading and the bullets on the web and in the feed alike, and
showed the scraped paragraph instead. The feed's twin of these cases is
``tests/test_feed_item_html.py::TestBulletsWithoutProse``.
"""

import pytest

from scripts import site_builder
from scripts.i18n import Catalog


@pytest.fixture
def ctx():
    return site_builder.RenderContext(catalog=Catalog.load("es"), feed_link="")


def _entry(**overrides) -> site_builder.SiteEntry:
    defaults = dict(
        species_code="eurbla",
        common_name="Mirlo común",
        scientific_name="Turdus merula",
        date="2026-08-27",
        image_url=None,
        photographer="",
        attribution="",
        description="Un pájaro negro.",
        description_source="ebird",
        bow_intro="Introducción.",
        taxonomy={},
        ml_search_url="https://example.invalid/ml",
        number=141,
        enriched_prose="Primero.\n\nSegundo.",
        enriched_identification=["Pico amarillo.", "Ojo con anillo."],
    )
    defaults.update(overrides)
    return site_builder.SiteEntry(**defaults)


class TestBulletsWithoutProse:
    def test_bullets_survive_an_empty_prose(self, ctx):
        html = site_builder.render_plate(_entry(enriched_prose=""), ctx)
        assert '<p class="plate-id-label">Identificación en campo</p>' in html
        assert "<li>Pico amarillo.</li>" in html
        assert "<li>Ojo con anillo.</li>" in html
        # The scraped text does not take their place.
        assert "Un pájaro negro." not in html
        assert "Introducción." not in html

    def test_prose_survives_empty_bullets(self, ctx):
        html = site_builder.render_plate(
            _entry(enriched_identification=None), ctx
        )
        assert "Primero." in html
        assert "Segundo." in html
        assert "plate-id-label" not in html
        assert "Un pájaro negro." not in html


class TestFallback:
    def test_the_scraped_text_is_used_when_nothing_is_enriched(self, ctx):
        html = site_builder.render_plate(
            _entry(enriched_prose="", enriched_identification=None), ctx
        )
        assert "Un pájaro negro." in html
        assert "Introducción." in html
        assert "plate-id-label" not in html

    def test_the_empty_marker_is_the_last_resort(self, ctx):
        html = site_builder.render_plate(
            _entry(
                enriched_prose="",
                enriched_identification=None,
                description="",
                bow_intro="",
            ),
            ctx,
        )
        assert 'class="plate-description empty"' in html
