"""Tests for generate._apply_description_policy."""

from scripts.content_scraper import SpeciesContent
from scripts.generate import _apply_description_policy


def _content(description="", source="", fallback_text="", fallback_language=""):
    return SpeciesContent(
        description=description,
        description_source=source,
        bow_intro="",
        taxonomy={},
        fallback_text=fallback_text,
        fallback_language=fallback_language,
    )


def test_has_description_strict():
    desc, src = _apply_description_policy(
        _content(description="Hola", source="ebird"), "strict"
    )
    assert desc == "Hola"
    assert src == "ebird"


def test_empty_description_strict():
    desc, src = _apply_description_policy(
        _content(fallback_text="English text"), "strict"
    )
    assert desc == ""
    assert src == ""


def test_foreign_fallback_substitutes():
    desc, src = _apply_description_policy(
        _content(fallback_text="English text", fallback_language="en"),
        "foreign_fallback",
    )
    assert desc == "English text"
    assert src == "ebird-foreign"


def test_foreign_fallback_no_fallback_text():
    desc, src = _apply_description_policy(
        _content(), "foreign_fallback"
    )
    assert desc == ""
    assert src == ""


def test_foreign_fallback_with_description_keeps_original():
    desc, src = _apply_description_policy(
        _content(description="Spanish text", source="ebird", fallback_text="English"),
        "foreign_fallback",
    )
    assert desc == "Spanish text"
    assert src == "ebird"


def test_skip_policy_empty():
    desc, src = _apply_description_policy(_content(), "skip")
    assert desc == ""
    assert src == ""
