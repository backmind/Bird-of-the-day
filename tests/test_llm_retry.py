"""Tests for the robust LLM call: backoff, Retry-After, model fallback."""

import json
from unittest.mock import MagicMock, patch

from scripts.llm_enricher import _call_llm

GOOD_BODY = {"prose": "Texto.", "identification": ["a", "b", "c"]}


def _ok_response(body=GOOD_BODY, content=None) -> MagicMock:
    """A 200 response. Pass *content* to control the raw completion text
    directly (e.g. malformed JSON or a markdown-fenced body), overriding
    the default of ``json.dumps(body)``.
    """
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [
            {"message": {"content": content if content is not None else json.dumps(body)}}
        ]
    }
    return resp


def _empty_choices_response() -> MagicMock:
    """A 200 response with no choices, as some OpenAI-compat shims return
    for a safety-blocked or filtered completion."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"choices": []}
    return resp


def _null_content_response() -> MagicMock:
    """A 200 whose message content is null, as OpenAI-compatible endpoints
    return for a content-filtered completion."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": None}}]}
    return resp


def _busy_response(status=503, retry_after=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"Retry-After": str(retry_after)} if retry_after else {}
    return resp


CFG = {"llm": {"endpoint": "http://fake", "models": ["m1"], "max_retries": 3}}


class TestCallLlm:
    def test_recovers_after_503(self):
        with patch("scripts.llm_enricher.requests.post",
                   side_effect=[_busy_response(), _busy_response(), _ok_response()]):
            with patch("scripts.llm_enricher.time.sleep") as sleep:
                with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                    result = _call_llm([], CFG)
        assert result == GOOD_BODY
        assert sleep.call_count == 2
        # First wait follows the schedule: 2s base plus at most 1s jitter.
        first_wait = sleep.call_args_list[0].args[0]
        assert 2 <= first_wait <= 3

    def test_honors_retry_after(self):
        with patch("scripts.llm_enricher.requests.post",
                   side_effect=[_busy_response(retry_after=45), _ok_response()]):
            with patch("scripts.llm_enricher.time.sleep") as sleep:
                with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                    result = _call_llm([], CFG)
        assert result == GOOD_BODY
        assert 45 <= sleep.call_args_list[0].args[0] <= 46

    def test_model_fallback_chain(self):
        cfg = {"llm": {"endpoint": "http://fake",
                       "models": ["m1", "m2"], "max_retries": 0}}
        calls = []

        def fake_post(url, headers=None, json=None, timeout=None):
            calls.append(json["model"])
            return _busy_response() if json["model"] == "m1" else _ok_response()

        with patch("scripts.llm_enricher.requests.post", side_effect=fake_post):
            with patch("scripts.llm_enricher.time.sleep"):
                with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                    result = _call_llm([], cfg)
        assert result == GOOD_BODY
        assert calls == ["m1", "m2"]

    def test_requests_json_mode(self):
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured.update(json)
            return _ok_response()

        with patch("scripts.llm_enricher.requests.post", side_effect=fake_post):
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                _call_llm([], CFG)
        assert captured["response_format"] == {"type": "json_object"}

    def test_all_models_exhausted_returns_none(self):
        cfg = {"llm": {"endpoint": "http://fake",
                       "models": ["m1"], "max_retries": 1}}
        with patch("scripts.llm_enricher.requests.post",
                   return_value=_busy_response()):
            with patch("scripts.llm_enricher.time.sleep"):
                with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                    assert _call_llm([], cfg) is None

    def test_empty_choices_retries_instead_of_crashing(self):
        # A 200 with no choices (safety-blocked/filtered completion) must
        # feed the retry loop, not escape as an uncaught IndexError.
        with patch("scripts.llm_enricher.requests.post",
                   side_effect=[_empty_choices_response(), _ok_response()]):
            with patch("scripts.llm_enricher.time.sleep") as sleep:
                with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                    result = _call_llm([], CFG)
        assert result == GOOD_BODY
        assert sleep.call_count == 1

    def test_null_content_retries_instead_of_crashing(self):
        # A 200 whose content is null (filtered completion) must feed the
        # retry loop, not escape as an uncaught AttributeError.
        with patch("scripts.llm_enricher.requests.post",
                   side_effect=[_null_content_response(), _ok_response()]):
            with patch("scripts.llm_enricher.time.sleep") as sleep:
                with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                    result = _call_llm([], CFG)
        assert result == GOOD_BODY
        assert sleep.call_count == 1

    def test_retry_after_capped_at_120(self):
        with patch("scripts.llm_enricher.requests.post",
                   side_effect=[_busy_response(retry_after=3600), _ok_response()]):
            with patch("scripts.llm_enricher.time.sleep") as sleep:
                with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                    result = _call_llm([], CFG)
        assert result == GOOD_BODY
        assert 120 <= sleep.call_args_list[0].args[0] <= 121

    def test_unparseable_completion_retries(self):
        with patch("scripts.llm_enricher.requests.post",
                   side_effect=[_ok_response(content="this is not json"),
                                _ok_response()]):
            with patch("scripts.llm_enricher.time.sleep") as sleep:
                with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                    result = _call_llm([], CFG)
        assert result == GOOD_BODY
        assert sleep.call_count == 1

    def test_fenced_json_parsed(self):
        fenced = "```json\n" + json.dumps(GOOD_BODY) + "\n```"
        with patch("scripts.llm_enricher.requests.post",
                   return_value=_ok_response(content=fenced)):
            with patch("scripts.llm_enricher.time.sleep") as sleep:
                with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                    result = _call_llm([], CFG)
        assert result == GOOD_BODY
        assert sleep.call_count == 0
