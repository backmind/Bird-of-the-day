"""Tests for name_linker.process_description and extract_name_pairs."""

from scripts.name_linker import extract_name_pairs, process_description


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
    assert "ebird.org/species/masboo" in result


def test_links_to_published_entry():
    eni = {"Masked Booby": "masboo"}
    c2l = {"masboo": "Piquero Enmascarado"}
    anchors = {"masboo": "birds/masboo.html"}
    result = process_description(
        "The Masked Booby is a seabird.", eni, c2l, anchors
    )
    assert '<a href="birds/masboo.html">' in result
    assert "Piquero Enmascarado" in result
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
    assert "&lt;em&gt;" in result
    assert "Piquero" in result


def test_localized_name_linked():
    """Localized names in the text get linked even without English match."""
    c2l = {"masboo": "Piquero Enmascarado"}
    anchors = {"masboo": "birds/masboo.html"}
    result = process_description(
        "El Piquero Enmascarado anida en islas.", {}, c2l, anchors
    )
    assert '<a href="birds/masboo.html">' in result
    assert "Piquero Enmascarado" in result


def test_localized_name_ebird_fallback():
    """Unpublished localized names fall back to eBird."""
    c2l = {"mircab": "Mirlo Capiblanco"}
    result = process_description(
        "El Mirlo Capiblanco habita en montañas.", {}, c2l, {}, "es"
    )
    assert "ebird.org/species/mircab?siteLanguage=es" in result
    assert "Mirlo Capiblanco" in result


def test_no_double_link():
    """English match and locale match for the same species don't collide."""
    eni = {"Masked Booby": "masboo"}
    c2l = {"masboo": "Piquero Enmascarado"}
    result = process_description(
        "The Masked Booby, or Piquero Enmascarado, is large.",
        eni, c2l, {}
    )
    # Both should be linked, not duplicated
    assert result.count("ebird.org/species/masboo") == 2


def test_extract_name_pairs():
    eni = {"Masked Booby": "masboo", "Ring Ouzel": "rinouz1"}
    c2l = {"masboo": "Piquero Enmascarado", "rinouz1": "Mirlo Capiblanco"}
    pairs = extract_name_pairs(
        "The Masked Booby and Ring Ouzel share an island.", eni, c2l
    )
    assert pairs == {
        "Masked Booby": "Piquero Enmascarado",
        "Ring Ouzel": "Mirlo Capiblanco",
    }


def test_extract_name_pairs_empty():
    pairs = extract_name_pairs("No birds here.", {}, {})
    assert pairs == {}


def test_single_word_never_links():
    """One word of a confirmed name is not enough to link the species.

    The head word of a localized name is a group noun shared by dozens
    of species ("Paloma" heads 140), so on its own it identifies a
    genus at best, never a species.
    """
    eni = {"Atlantic Puffin": "atlpuf"}
    c2l = {"atlpuf": "Frailecillo Atlantico"}
    result = process_description(
        "El Atlantic Puffin anida aqui. Frailecillo vuela lejos.",
        eni, c2l, {}
    )
    assert result.count("ebird.org/species/atlpuf") == 1
    assert "Frailecillo vuela lejos" in result


def test_non_head_word_not_linked():
    """A non-head word of the confirmed name is not linked elsewhere."""
    eni = {"Salomon Pigeon": "salpig"}
    c2l = {"salpig": "Paloma Perdiz de las Salomon"}
    result = process_description(
        "The Salomon Pigeon lives there. "
        "En el archipielago de las Salomon hay muchas aves.",
        eni, c2l, {}
    )
    assert "archipielago de las Salomon hay" in result
    assert result.count("Paloma Perdiz de las Salomon") == 1


def test_genus_mention_not_linked():
    """A genus named as a genus is not a species reference.

    Production case: "perteneciente al genero Aratinga" linked the
    word to Aratinga Pechisulfurea, one of the 20-odd species that
    share the head.
    """
    c2l = {"subpar1": "Aratinga Pechisulfurea"}
    anchors = {"subpar1": "birds/subpar1.html"}
    result = process_description(
        "La Aratinga Pechisulfurea pertenece al genero Aratinga.",
        {}, c2l, anchors,
    )
    assert result.count("birds/subpar1.html") == 1
    assert "al genero Aratinga." in result


def test_another_species_head_word_not_linked():
    """A different species sharing the head keeps its own text.

    Production case: "la Aratinga del Sol" linked to Aratinga
    Pechisulfurea, which is not that bird.
    """
    c2l = {"subpar1": "Aratinga Pechisulfurea"}
    anchors = {"subpar1": "birds/subpar1.html"}
    result = process_description(
        "La Aratinga Pechisulfurea formaba parte de la Aratinga del Sol.",
        {}, c2l, anchors,
    )
    assert result.count("birds/subpar1.html") == 1
    assert "de la Aratinga del Sol" in result


def test_english_substitution_fixes_determiner():
    """Masculine 'El' before a feminine localized name becomes 'La'."""
    eni = {"Monk Parakeet": "monpar"}
    c2l = {"monpar": "Cotorra Argentina"}
    result = process_description(
        "El Monk Parakeet es ruidoso.", eni, c2l, {}
    )
    assert "La " in result
    assert "El Cotorra" not in result
    assert 'La <a' in result


def test_determiner_untouched_when_gender_agrees():
    """A determiner that already agrees with the localized gender is kept."""
    eni = {"Black Kite": "blakit1"}
    c2l = {"blakit1": "Milano Negro"}
    result = process_description(
        "el Black Kite vuela", eni, c2l, {}
    )
    assert "el " in result
    assert 'el <a' in result


def test_feminine_el_head_not_rewritten():
    """Feminine nouns using 'el' in the singular are left untouched."""
    eni = {"Golden Eagle": "goleag"}
    c2l = {"goleag": "Águila Real"}
    result = process_description(
        "el Golden Eagle planea alto", eni, c2l, {}
    )
    assert 'el <a href="https://ebird.org/species/goleag"' in result


def test_capitalized_determiner_preserved():
    """A capitalized determiner keeps its capitalization when rewritten."""
    eni = {"Monk Parakeet": "monpar"}
    c2l = {"monpar": "Cotorra Argentina"}
    result = process_description(
        "Del Monk Parakeet se dice mucho.", eni, c2l, {}
    )
    assert "De la " in result


def test_no_determiner_rewrite_without_substitution():
    """No real substitution happens when the code has no localized name.

    ``code_to_localized.get(code, matched)`` falls back to the English
    matched text itself (live production state when the taxonomy fetch
    degrades to ``{}``). The determiner must NOT be rewritten against
    the English head noun in that case.
    """
    eni = {"Barn Owl": "brnowl"}
    result = process_description(
        "la Barn Owl vuela de noche.", eni, {}, {}
    )
    assert 'la <a href="https://ebird.org/species/brnowl"' in result
    assert 'el <a' not in result


def test_whitespace_localized_name_does_not_crash():
    """A whitespace-only localized name must not raise IndexError."""
    eni = {"Barn Owl": "brnowl"}
    c2l = {"brnowl": "   "}
    result = process_description(
        "The Barn Owl flies at night.", eni, c2l, {}
    )
    assert "ebird.org/species/brnowl" in result


def _sciname(monkeypatch, index):
    """Point the scientific-name pass at a fixed taxonomy index."""
    from scripts import ebird_client

    monkeypatch.setattr(ebird_client, "get_sciname_index", lambda: index)


def test_binomial_italicised(monkeypatch):
    _sciname(monkeypatch, {"leiothrix lutea": "Leiothrix lutea"})
    c2l = {"reblei": "Leiotrix Piquirrojo"}
    result = process_description(
        "El Leiotrix Piquirrojo (Leiothrix lutea) canta al alba.",
        {}, c2l, {},
    )
    assert "<em>Leiothrix lutea</em>" in result


def test_binomial_italicised_when_genus_is_the_localized_head_word(monkeypatch):
    """A binomial keeps its italics when its genus heads the common name.

    Spanish bird names often reuse the genus as their head noun
    (Atlapetes, Curruca, Aratinga). Linking that head word inside the
    binomial split the name across an anchor and left the whole
    binomial un-italicised.
    """
    _sciname(monkeypatch, {"atlapetes melanopsis": "Atlapetes melanopsis"})
    c2l = {"bksbrf1": "Atlapetes de Anteojos"}
    anchors = {"bksbrf1": "birds/bksbrf1.html"}
    result = process_description(
        "El Atlapetes de Anteojos (Atlapetes melanopsis) vive en Peru.",
        {}, c2l, anchors,
    )
    assert "<em>Atlapetes melanopsis</em>" in result
    assert "melanopsis</a>" not in result
    assert '<a href="birds/bksbrf1.html">Atlapetes</a> melanopsis' not in result


def test_markdown_emphasis_stripped(monkeypatch):
    """Markdown emphasis from the model never reaches the page."""
    _sciname(monkeypatch, {"aegypius monachus": "Aegypius monachus"})
    c2l = {"cinvul1": "Buitre Negro"}
    result = process_description(
        "El Buitre Negro (*Aegypius monachus*) planea sobre la sierra.",
        {}, c2l, {},
    )
    assert "*" not in result
    assert "<em>Aegypius monachus</em>" in result


def test_markdown_emphasis_stripped_without_taxonomy():
    """Stripping does not depend on the taxonomy being loaded."""
    c2l = {"cinvul1": "Buitre Negro"}
    result = process_description(
        "El Buitre Negro (*Aegypius monachus*) planea.", {}, c2l, {}
    )
    assert "*" not in result
    assert "Aegypius monachus" in result


def test_lone_asterisk_kept():
    """A bare asterisk is not emphasis and is left alone."""
    result = process_description("Mide 5 * 3 metros.", {}, {}, {})
    assert result == "Mide 5 * 3 metros."
