"""Tests for name_linker.process_description."""

from scripts.name_linker import process_description


def test_empty_text():
    assert process_description("", {}, {}, {}) == ""


def test_no_index_escapes_html():
    assert process_description("<b>bold</b>", {}, {}, {}) == "&lt;b&gt;bold&lt;/b&gt;"


def test_substitutes_english_name():
    eni = {"Masked Booby": "masboo"}
    c2l = {"masboo": "Piquero Enmascarado"}
    result = process_description(
        "The Masked Booby is a seabird.", eni, c2l, {}
    )
    assert "Piquero Enmascarado" in result
    assert "Masked Booby" not in result
    # Unpublished species link to eBird with "(eBird)" hint.
    assert "ebird.org/species/masboo" in result
    assert "(eBird)" in result


def test_links_to_published_entry():
    eni = {"Masked Booby": "masboo"}
    c2l = {"masboo": "Piquero Enmascarado"}
    anchors = {"masboo": "archive.html#bird-masboo-2026-04-13"}
    result = process_description(
        "The Masked Booby is a seabird.", eni, c2l, anchors
    )
    assert '<a href="archive.html#bird-masboo-2026-04-13">' in result
    assert "Piquero Enmascarado" in result
    # Published species should NOT have the "(eBird)" hint.
    assert "(eBird)" not in result


def test_no_match_returns_escaped():
    eni = {"Masked Booby": "masboo"}
    result = process_description(
        "A plain description with no species.", eni, {}, {}
    )
    assert result == "A plain description with no species."


def test_html_in_description_escaped():
    eni = {"Masked Booby": "masboo"}
    c2l = {"masboo": "Piquero"}
    result = process_description(
        "The <em>Masked Booby</em> nests here.", eni, c2l, {}
    )
    # The <em> tags in the raw text should be escaped
    assert "&lt;em&gt;" in result
    # But the species replacement should still work
    assert "Piquero" in result
