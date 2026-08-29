"""The exact bytes of one item body, pinned.

READ THIS BEFORE YOU CHANGE ``build_entry_html``.

``feed-full.xml`` reuses the bodies it already published for every item
outside the cap window, and it decides they are reusable by reading the
format version ``FEED_FORMAT`` writes into ``<generator>``. That marker
is bumped by hand. Change the body and forget the bump, and the file
keeps the old shape for the whole history and the new one for today's
item, for good: nothing ever revisits a frozen body.

So a deliberate change to the body means two edits, not one:

1. update the golden string below to the new output, and
2. bump ``FEED_FORMAT`` in ``scripts/feed_builder.py``,

which makes the next run re-render the history in one piece instead of
leaving two formats mixed in one file.

The fixture is one representative item: head line, photo, credit, name,
taxonomy with an IUCN code, two prose paragraphs, identification
bullets, a composed map and a Wikipedia link. The em-dash in the ``<h2>``
is product copy and belongs there.
"""

from scripts.feed_builder import build_entry_html
from scripts.i18n import Catalog

GOLDEN = (
    '<p><small>№ 141 · 2026 · 08 · 27</small></p>\n'
    '<p><a href="https://birds.example.org/birds/eurbla.html">'
    '<img src="https://cdn.download.ams.birds.cornell.edu/api/v2/asset/1/900" '
    'alt="Mirlo común" style="max-width:100%;height:auto" /></a></p>\n'
    '<p><small><em>© Jane Doe / Macaulay Library</em></small></p>\n'
    '<h2>Mirlo común — <em>Turdus merula</em></h2>\n'
    '<p><small><em>Turdidae</em> · <em>Passeriformes</em> // '
    '<a href="https://datazone.birdlife.org/species/factsheet/22708775">LC</a>'
    ' · Preocupación Menor</small></p>\n'
    '<p>Primer parrafo.</p>\n'
    '<p>Segundo parrafo.</p>\n'
    '<h3>Identificación en campo</h3>\n'
    '<ul><li>Pico amarillo.</li><li>Anillo ocular.</li></ul>\n'
    '<figure style="margin:1.5rem 0;text-align:center">'
    '<a href="https://www.gbif.org/species/2490719">'
    '<img src="https://birds.example.org/maps/eurbla.png" '
    'alt="Distribución mundial de Turdus merula según GBIF" '
    'style="max-width:100%;height:auto" /></a>'
    '<figcaption><small>Distribución mundial</small></figcaption></figure>\n'
    '<p><small><a href="https://ebird.org/species/eurbla?siteLanguage=es">'
    'eBird</a> · '
    '<a href="https://es.wikipedia.org/wiki/Turdus_merula">Wikipedia</a> · '
    '<a href="https://birdsoftheworld.org/bow/species/eurbla/cur/introduction">'
    'Birds of the World</a> · '
    '<a href="https://search.macaulaylibrary.org/catalog?taxonCode=eurbla">'
    'Macaulay Library</a></small></p>'
)


def _render(*, previous_date: str = "") -> str:
    return build_entry_html(
        species_code="eurbla",
        common_name="Mirlo común",
        scientific_name="Turdus merula",
        image_url="https://cdn.download.ams.birds.cornell.edu/api/v2/asset/1/900",
        image_attribution="Jane Doe / Macaulay Library",
        ml_search_url="https://search.macaulaylibrary.org/catalog?taxonCode=eurbla",
        description="",
        description_source="",
        bow_intro="",
        taxonomy={"familySciName": "Turdidae", "order": "Passeriformes"},
        catalog=Catalog.load("es"),
        wikipedia_url="https://es.wikipedia.org/wiki/Turdus_merula",
        wikipedia_language="es",
        gbif_taxon_key=2490719,
        composed_map_url="https://birds.example.org/maps/eurbla.png",
        iucn_code="LC",
        iucn_birdlife_url="https://datazone.birdlife.org/species/factsheet/22708775",
        enriched_prose="Primer parrafo.\n\nSegundo parrafo.",
        enriched_identification=["Pico amarillo.", "Anillo ocular."],
        number=141,
        date="2026-08-27",
        species_page_url="https://birds.example.org/birds/eurbla.html",
        previous_date=previous_date,
    )


# Same fixture as GOLDEN, republished: only the head line changes, gaining
# the chip. This is the shape Task 5 added and the one the plain debut
# golden above cannot exercise, since it never passes ``previous_date``.
GOLDEN_REPUBLISHED = (
    '<p><small>№ 141 · 2026 · 08 · 27 · '
    '<a href="https://birds.example.org/birds/eurbla.html">'
    'Ya publicada: 2026 · 07 · 15</a></small></p>\n'
) + "\n".join(GOLDEN.split("\n")[1:])


def test_the_item_body_is_byte_for_byte_what_it_was():
    assert _render() == GOLDEN


def test_the_republished_item_body_is_byte_for_byte_what_it_was():
    assert _render(previous_date="2026-07-15") == GOLDEN_REPUBLISHED


def test_the_body_is_stable_across_calls():
    # Cheap, and it catches the one class of change the comparison above
    # cannot: a body that renders differently on the second call would
    # rewrite the whole feed every run while every assertion still passed.
    assert _render() == _render()
