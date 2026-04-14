"""Tests for i18n.Catalog.t fallback chain."""

from scripts.i18n import Catalog


def test_t_returns_primary_string():
    cat = Catalog(
        language="es",
        fallback="en",
        _strings={"nav.home": "Hoy"},
        _fallback_strings={"nav.home": "Today"},
    )
    assert cat.t("nav.home") == "Hoy"


def test_t_falls_back_to_fallback():
    cat = Catalog(
        language="es",
        fallback="en",
        _strings={},
        _fallback_strings={"nav.home": "Today"},
    )
    assert cat.t("nav.home") == "Today"


def test_t_returns_key_when_missing_everywhere():
    cat = Catalog(
        language="es",
        fallback="en",
        _strings={},
        _fallback_strings={},
    )
    assert cat.t("missing.key") == "missing.key"


def test_t_format_kwargs():
    cat = Catalog(
        language="es",
        fallback="en",
        _strings={"footer": "By {author} {year}"},
        _fallback_strings={},
    )
    assert cat.t("footer", author="Yass", year=2026) == "By Yass 2026"


def test_t_format_error_returns_raw():
    cat = Catalog(
        language="es",
        fallback="en",
        _strings={"bad": "Hello {missing_var}"},
        _fallback_strings={},
    )
    # Format fails because 'missing_var' not in kwargs — returns raw string.
    result = cat.t("bad", other="value")
    assert result == "Hello {missing_var}"


def test_html_lang():
    cat = Catalog(language="fr", fallback="en", _strings={}, _fallback_strings={})
    assert cat.html_lang == "fr"
