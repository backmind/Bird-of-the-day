"""Tests for the shared esc_html utility."""

from scripts import esc_html


def test_basic_escaping():
    assert esc_html("<script>") == "&lt;script&gt;"


def test_ampersand():
    assert esc_html("A & B") == "A &amp; B"


def test_quotes_escaped():
    assert esc_html('say "hello"') == "say &quot;hello&quot;"


def test_single_quotes_escaped():
    assert esc_html("it's") == "it&#x27;s"


def test_none_returns_empty():
    assert esc_html(None) == ""


def test_empty_string():
    assert esc_html("") == ""


def test_plain_text_unchanged():
    assert esc_html("Hello world") == "Hello world"
