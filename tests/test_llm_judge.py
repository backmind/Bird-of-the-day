"""Tests for the optional adversarial judge pass."""

import json
from unittest.mock import MagicMock, patch

from scripts.content_scraper import SpeciesContent
from scripts.llm_enricher import enrich_species

_SENTENCE = (
    "Esta especie habita los bosques templados de Europa y se alimenta "
    "principalmente de insectos y semillas durante todo el invierno. "
)


def _paragraph(min_chars: int) -> str:
    text = ""
    while len(text) < min_chars:
        text += _SENTENCE
    return text.strip()


def _valid_body() -> dict:
    return {
        "prose": _paragraph(450) + "\n\n" + _paragraph(450),
        "identification": ["Pico corto", "Dorso pardo", "Canto agudo"],
    }


def _content() -> SpeciesContent:
    return SpeciesContent(
        description="A bird.", description_source="ebird",
        bow_intro="", taxonomy={},
    )


def _catalog() -> MagicMock:
    catalog = MagicMock()
    catalog.language = "es"
    return catalog


def _cfg(judge: bool) -> dict:
    return {"llm": {"endpoint": "http://fake", "models": ["m"],
                    "max_retries": 0, "judge": judge}}


class TestJudge:
    def test_disabled_makes_single_call(self):
        with patch("scripts.llm_enricher._call_llm",
                   return_value=_valid_body()) as call:
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                result = enrich_species(
                    "x", "Bird", "Aves avis", _content(), _cfg(False), _catalog()
                )
        assert result is not None
        assert call.call_count == 1

    def test_judge_pass_keeps_draft(self):
        draft = _valid_body()
        with patch("scripts.llm_enricher._call_llm",
                   side_effect=[draft, {"verdict": "pass"}]) as call:
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                result = enrich_species(
                    "x", "Bird", "Aves avis", _content(), _cfg(True), _catalog()
                )
        assert result is not None
        assert result.prose == draft["prose"]
        assert call.call_count == 2

    def test_judge_valid_revision_replaces_draft(self):
        revised = _valid_body()
        revised["prose"] = _paragraph(460) + "\n\n" + _paragraph(460)
        judge_reply = {"verdict": "revise", **revised}
        with patch("scripts.llm_enricher._call_llm",
                   side_effect=[_valid_body(), judge_reply]):
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                result = enrich_species(
                    "x", "Bird", "Aves avis", _content(), _cfg(True), _catalog()
                )
        assert result is not None
        assert result.prose == revised["prose"]

    def test_judge_invalid_revision_keeps_original(self):
        draft = _valid_body()
        bad_revision = {"verdict": "revise", "prose": "demasiado corto",
                        "identification": ["a", "b", "c"]}
        with patch("scripts.llm_enricher._call_llm",
                   side_effect=[draft, bad_revision]):
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                result = enrich_species(
                    "x", "Bird", "Aves avis", _content(), _cfg(True), _catalog()
                )
        assert result is not None
        assert result.prose == draft["prose"]
