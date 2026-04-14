"""Tests for content_scraper._truncate_at_sentence_boundary."""

from scripts.content_scraper import _truncate_at_sentence_boundary


def test_short_text_unchanged():
    assert _truncate_at_sentence_boundary("Hello world.") == "Hello world."


def test_empty_string():
    assert _truncate_at_sentence_boundary("") == ""


def test_none_returns_none():
    assert _truncate_at_sentence_boundary(None) is None


def test_exact_limit_unchanged():
    text = "A" * 700
    assert _truncate_at_sentence_boundary(text, max_chars=700) == text


def test_truncates_at_sentence_boundary():
    # Build text that exceeds 100 chars with a sentence boundary in the upper 60%.
    text = "A" * 70 + ". " + "B" * 40
    result = _truncate_at_sentence_boundary(text, max_chars=100)
    assert result == "A" * 70 + "."
    assert len(result) <= 100


def test_hard_cut_when_no_sentence_boundary():
    # No sentence-ending punctuation at all — should hard cut on last word.
    text = " ".join(["word"] * 30)  # "word word word ..."
    result = _truncate_at_sentence_boundary(text, max_chars=50)
    assert result.endswith("\u2026")  # ellipsis
    assert len(result) <= 50


def test_sentence_boundary_too_low_triggers_hard_cut():
    # Sentence boundary exists but below the 60% floor.
    text = "Short. " + "A" * 200
    result = _truncate_at_sentence_boundary(text, max_chars=100)
    # "Short." ends at index 6 — floor is 60, so it's too low.
    assert result.endswith("\u2026")


def test_exclamation_boundary():
    # Boundary must be above the 60% floor (60 for max_chars=100).
    text = "A" * 65 + "! " + "B" * 40
    result = _truncate_at_sentence_boundary(text, max_chars=100)
    assert result == "A" * 65 + "!"
    assert len(result) <= 100


def test_question_boundary():
    text = "A" * 65 + "? " + "B" * 40
    result = _truncate_at_sentence_boundary(text, max_chars=100)
    assert result == "A" * 65 + "?"
    assert len(result) <= 100
