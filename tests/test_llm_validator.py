"""Tests for the structural validator of LLM enrichment output."""

from scripts.llm_validator import validate_enrichment

# Realistic Spanish filler that langid classifies confidently.
_SENTENCE = (
    "Esta especie habita los bosques templados de Europa y se alimenta "
    "principalmente de insectos y semillas durante todo el invierno. "
)


def _spanish_paragraph(min_chars: int) -> str:
    text = ""
    while len(text) < min_chars:
        text += _SENTENCE
    return text.strip()


def _valid_result() -> dict:
    return {
        "prose": _spanish_paragraph(450) + "\n\n" + _spanish_paragraph(450),
        "identification": ["Pico corto y fuerte", "Dorso pardo", "Canto agudo"],
    }


class TestValidResult:
    def test_passes(self):
        hard, soft = validate_enrichment(_valid_result(), "es")
        assert hard == []
        assert soft == []


class TestHardFailures:
    def test_missing_prose(self):
        hard, _ = validate_enrichment({"identification": ["a", "b", "c"]}, "es")
        assert any("prose" in h for h in hard)

    def test_one_paragraph(self):
        r = _valid_result()
        r["prose"] = _spanish_paragraph(900)
        hard, _ = validate_enrichment(r, "es")
        assert any("paragraph" in h for h in hard)

    def test_too_few_bullets(self):
        r = _valid_result()
        r["identification"] = ["solo uno"]
        hard, _ = validate_enrichment(r, "es")
        assert any("identification" in h for h in hard)

    def test_empty_bullet(self):
        r = _valid_result()
        r["identification"] = ["a", "   ", "c"]
        hard, _ = validate_enrichment(r, "es")
        assert any("identification" in h for h in hard)

    def test_markdown_fences(self):
        r = _valid_result()
        r["prose"] = "```json\n" + r["prose"] + "\n```"
        hard, _ = validate_enrichment(r, "es")
        assert any("markdown" in h for h in hard)

    def test_wrong_language(self):
        english = (
            "This species inhabits the temperate woodlands of Europe and "
            "feeds mainly on insects and seeds through the long winter. "
        )
        prose = (english * 8).strip() + "\n\n" + (english * 8).strip()
        r = {"prose": prose, "identification": ["a", "b", "c"]}
        hard, _ = validate_enrichment(r, "es")
        assert any("language" in h for h in hard)

    def test_far_too_long(self):
        r = _valid_result()
        r["prose"] = _spanish_paragraph(1200) + "\n\n" + _spanish_paragraph(1200)
        hard, _ = validate_enrichment(r, "es")
        assert any("characters" in h for h in hard)


class TestSoftIssues:
    def test_slightly_long_is_soft(self):
        # Two 909-char paragraphs -> 1820 chars total: outside 800-1800
        # but inside the 10% hard tolerance (1980).
        r = _valid_result()
        r["prose"] = _spanish_paragraph(900) + "\n\n" + _spanish_paragraph(900)
        prose_len = len(r["prose"])
        assert 1800 < prose_len <= 1980
        hard, soft = validate_enrichment(r, "es")
        assert hard == []
        assert soft != []

    def test_long_wrong_language_bullets_is_soft(self):
        # Joined bullets >= 100 chars and genuinely classifiable as English:
        # a language mismatch here is a soft issue, not a hard rejection.
        r = _valid_result()
        r["identification"] = [
            "This bird has a short and sturdy beak used for cracking seeds",
            "Its back feathers show a warm brown tone across the whole body",
            "The call is loud, sharp and easy to recognize during flight",
        ]
        bullets_text = " ".join(r["identification"])
        assert len(bullets_text) >= 100
        hard, soft = validate_enrichment(r, "es")
        assert hard == []
        assert any("identification" in s for s in soft)


class TestShortBulletsSkipLanguageCheck:
    def test_short_bullets_no_language_violation(self):
        # Joined bullets below BULLETS_LANG_MIN_CHARS: langid is noise-prone
        # at this length (measured false positives against real Spanish),
        # so the language check is skipped entirely, not just softened.
        r = _valid_result()
        r["identification"] = ["Beak", "Wings", "Tail"]
        bullets_text = " ".join(r["identification"])
        assert len(bullets_text) < 100
        hard, soft = validate_enrichment(r, "es")
        assert hard == []
        assert soft == []
