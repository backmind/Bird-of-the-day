"""Species pages live one directory down, so every internal link has to
be resolved from the page's own location."""

from scripts import site_builder
from scripts.i18n import Catalog


def _ctx(**kwargs):
    return site_builder.RenderContext(catalog=Catalog.load("en"), feed_link="", **kwargs)


def test_root_pages_use_bare_paths():
    assert _ctx().u("assets/site.css") == "assets/site.css"


def test_subdirectory_pages_climb_out():
    ctx = site_builder.for_subdirectory(_ctx(), "../")
    assert ctx.u("assets/site.css") == "../assets/site.css"
    assert ctx.path_prefix == "../"


def test_subdirectory_rewrites_the_linker_catalog():
    ctx = site_builder.for_subdirectory(
        _ctx(published_anchors={"eurbla": "birds/eurbla.html"}), "../"
    )
    assert ctx.published_anchors["eurbla"] == "../birds/eurbla.html"


def test_absolute_link_targets_are_left_alone():
    # The feed builder passes absolute targets through the same catalog.
    ctx = site_builder.for_subdirectory(
        _ctx(published_anchors={"eurbla": "https://x.es/birds/eurbla.html"}), "../"
    )
    assert ctx.published_anchors["eurbla"] == "https://x.es/birds/eurbla.html"


def test_index_cards_link_to_the_species_page():
    entry = site_builder.SiteEntry(
        species_code="eurbla",
        common_name="Mirlo",
        scientific_name="Turdus merula",
        date="2026-08-27",
        image_url=None,
        photographer="",
        attribution="",
        description="",
        description_source="",
        bow_intro="",
        taxonomy={},
        ml_search_url="https://example.invalid/ml",
        number=3,
    )
    html = site_builder.render_card(entry, _ctx())
    assert 'href="birds/eurbla.html"' in html


def test_header_links_are_prefixed_on_subdirectory_pages():
    html = site_builder._render_header(site_builder.for_subdirectory(_ctx(), "../"), "archive")
    assert 'href="../index.html"' in html
    assert 'href="../archive.html"' in html
