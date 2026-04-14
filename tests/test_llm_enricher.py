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
        assert "[Description]" in ctx
        assert "[Birds of the World]" in ctx

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
        msgs = _build_messages("Great Tit", "Parus major", content, "es")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert "Great Tit" in msgs[1]["content"]
        assert "Parus major" in msgs[1]["content"]

    def test_locale_in_system(self):
        content = _make_content()
        msgs = _build_messages("Mésange", "Parus major", content, "fr")
        assert "fr" in msgs[0]["content"]


class TestEnrichSpecies:
    def test_success(self):
        content = _make_content()
        config = {"llm": {"endpoint": "http://fake", "model": "test", "max_retries": 0}}
        catalog = MagicMock()
        catalog.language = "es"

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "prose": "Un pajarito interesante.",
                "identification": ["Pico corto", "Plumas azules"],
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
        assert result.prose == "Un pajarito interesante."
        assert len(result.identification) == 2

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
        config = {"llm": {"endpoint": "http://fake", "model": "test", "max_retries": 0}}
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
