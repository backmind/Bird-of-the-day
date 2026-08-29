"""Tests for llm_enricher — LLM-based content enrichment."""

import json
from unittest.mock import MagicMock, patch

from scripts.content_scraper import SpeciesContent
from scripts.llm_enricher import (
    EnrichedContent,
    _build_context,
    _build_messages,
    _truncate_context,
    enrich_species,
    load_cached_enrichment,
    save_cached_enrichment,
)

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


def _make_content(**kwargs):
    defaults = dict(
        description="A medium-sized bird found in forests.",
        description_source="ebird",
        bow_intro="This species inhabits temperate woodlands.",
        taxonomy={},
        fallback_text="",
        fallback_language="",
    )
    defaults.update(kwargs)
    return SpeciesContent(**defaults)


class TestTruncateContext:
    def test_short_text_unchanged(self):
        assert _truncate_context("Hello world.", 100) == "Hello world."

    def test_empty(self):
        assert _truncate_context("", 100) == ""

    def test_truncates_at_sentence(self):
        text = "First sentence. Second sentence. Third sentence."
        result = _truncate_context(text, 35)
        assert result.endswith(".")
        assert len(result) <= 35

    def test_hard_cut_with_ellipsis(self):
        text = "A very long word " * 20
        result = _truncate_context(text, 50)
        assert result.endswith("…")
        assert len(result) <= 50


class TestBuildContext:
    def test_combines_sources(self):
        content = _make_content()
        ctx = _build_context(content)
        assert "[eBird]" in ctx
        assert "[Birds of the World]" in ctx

    def test_wikipedia_source_label(self):
        content = _make_content(description_source="wikipedia")
        ctx = _build_context(content)
        assert "[Wikipedia]" in ctx
        assert "[eBird]" not in ctx

    def test_skips_empty(self):
        content = _make_content(bow_intro="")
        ctx = _build_context(content)
        assert "[Birds of the World]" not in ctx

    def test_respects_budget(self):
        content = _make_content(
            description="x" * 3000,
            bow_intro="y" * 3000,
        )
        ctx = _build_context(content)
        assert len(ctx) < 6000  # should be trimmed to ~5000


class TestBuildMessages:
    def test_structure(self):
        content = _make_content()
        msgs = _build_messages("Great Tit", "Parus major", content, "Spanish")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert "Great Tit" in msgs[1]["content"]
        assert "Parus major" in msgs[1]["content"]

    def test_language_in_user(self):
        content = _make_content()
        msgs = _build_messages("Mésange", "Parus major", content, "French")
        assert "French" in msgs[1]["content"]

    def test_name_pairs_in_user(self):
        content = _make_content()
        pairs = {"Great Tit": "Carbonero Común"}
        msgs = _build_messages("Herrerillo", "Parus major", content, "Spanish", pairs)
        assert "Great Tit" in msgs[1]["content"]
        assert "Carbonero Común" in msgs[1]["content"]


class TestEnrichSpecies:
    def test_success(self):
        content = _make_content()
        config = {"llm": {"endpoint": "http://fake", "models": ["test"], "max_retries": 0}}
        catalog = MagicMock()
        catalog.language = "es"

        valid_prose = _spanish_paragraph(450) + "\n\n" + _spanish_paragraph(450)
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "prose": valid_prose,
                "identification": ["Pico corto", "Plumas azules", "Canto agudo"],
            })}}],
        }
        fake_response.raise_for_status = MagicMock()

        with patch("scripts.llm_enricher.requests.post", return_value=fake_response):
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "test-key"}):
                result = enrich_species(
                    "partma1", "Great Tit", "Parus major",
                    content, config, catalog,
                )

        assert result is not None
        assert result.prose == valid_prose
        assert len(result.identification) == 3
        assert result.model == "test"

    def test_corrective_retry_recovers(self):
        content = _make_content()
        config = {"llm": {"endpoint": "http://fake", "models": ["test"], "max_retries": 0}}
        catalog = MagicMock()
        catalog.language = "es"

        # Single paragraph: fails the paragraph-count hard check.
        invalid_result = {
            "prose": _spanish_paragraph(900),
            "identification": ["Pico corto", "Plumas azules", "Canto agudo"],
        }
        valid_prose = _spanish_paragraph(450) + "\n\n" + _spanish_paragraph(450)
        valid_result = {
            "prose": valid_prose,
            "identification": ["Pico corto", "Plumas azules", "Canto agudo"],
        }

        with patch(
            "scripts.llm_enricher._call_llm",
            side_effect=[invalid_result, valid_result],
        ) as mock_call:
            result = enrich_species(
                "partma1", "Great Tit", "Parus major",
                content, config, catalog,
            )

        assert result is not None
        assert result.prose == valid_prose
        assert mock_call.call_count == 2

        second_call_messages = mock_call.call_args_list[1].args[0]
        assert second_call_messages[-2]["role"] == "assistant"
        assert json.loads(second_call_messages[-2]["content"]) == invalid_result
        assert second_call_messages[-1]["role"] == "user"
        assert "paragraph" in second_call_messages[-1]["content"]

    def test_corrective_retry_still_invalid_returns_none(self):
        content = _make_content()
        config = {"llm": {"endpoint": "http://fake", "models": ["test"], "max_retries": 0}}
        catalog = MagicMock()
        catalog.language = "es"

        invalid_result = {
            "prose": _spanish_paragraph(900),
            "identification": ["Pico corto", "Plumas azules", "Canto agudo"],
        }

        with patch(
            "scripts.llm_enricher._call_llm",
            side_effect=[invalid_result, invalid_result],
        ) as mock_call:
            result = enrich_species(
                "partma1", "Great Tit", "Parus major",
                content, config, catalog,
            )

        assert result is None
        assert mock_call.call_count == 2

    def test_no_api_key(self):
        content = _make_content()
        config = {"llm": {"endpoint": "http://fake", "model": "test"}}
        catalog = MagicMock()
        catalog.language = "es"

        with patch.dict("os.environ", {}, clear=True):
            result = enrich_species(
                "partma1", "Great Tit", "Parus major",
                content, config, catalog,
            )
        assert result is None

    def test_api_failure(self):
        content = _make_content()
        config = {"llm": {"endpoint": "http://fake", "models": ["test"], "max_retries": 0}}
        catalog = MagicMock()
        catalog.language = "es"

        import requests as req
        with patch("scripts.llm_enricher.requests.post", side_effect=req.ConnectionError("boom")):
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "key"}):
                result = enrich_species(
                    "partma1", "Great Tit", "Parus major",
                    content, config, catalog,
                )
        assert result is None


class TestCacheRoundTrip:
    def test_save_and_load(self, tmp_path):
        enriched = EnrichedContent(
            prose="Texto de prueba.",
            identification=["Rasgo 1", "Rasgo 2"],
            model="test-model",
            timestamp="2026-04-14T00:00:00Z",
        )
        save_cached_enrichment("abc", enriched, str(tmp_path))
        loaded = load_cached_enrichment("abc", str(tmp_path))

        assert loaded is not None
        assert loaded.prose == "Texto de prueba."
        assert loaded.identification == ["Rasgo 1", "Rasgo 2"]
        assert loaded.model == "test-model"

    def test_load_missing(self, tmp_path):
        assert load_cached_enrichment("nonexistent", str(tmp_path)) is None
