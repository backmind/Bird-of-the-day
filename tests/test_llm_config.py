"""Tests for LLM configuration resolution and the content_mode retirement."""

import json
from unittest.mock import patch

from scripts.llm_enricher import _resolve_models, is_configured


class TestResolveModels:
    def test_models_list(self):
        cfg = {"llm": {"models": ["model-a", "model-b"]}}
        assert _resolve_models(cfg) == ["model-a", "model-b"]

    def test_legacy_singular_model(self):
        cfg = {"llm": {"model": "model-a"}}
        assert _resolve_models(cfg) == ["model-a"]

    def test_models_wins_over_model(self):
        cfg = {"llm": {"models": ["new"], "model": "old"}}
        assert _resolve_models(cfg) == ["new"]

    def test_empty(self):
        assert _resolve_models({}) == []
        assert _resolve_models({"llm": {}}) == []


class TestIsConfigured:
    CFG = {"llm": {"endpoint": "http://fake", "models": ["m"]}}

    def test_true_with_key(self):
        with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
            assert is_configured(self.CFG) is True

    def test_false_without_key(self):
        with patch.dict("os.environ", {}, clear=True):
            assert is_configured(self.CFG) is False

    def test_false_without_endpoint(self):
        with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
            assert is_configured({"llm": {"models": ["m"]}}) is False

    def test_false_without_models(self):
        with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
            assert is_configured({"llm": {"endpoint": "http://fake"}}) is False


class TestContentModeDeprecation:
    def test_load_config_drops_content_mode(self, tmp_path, caplog):
        from scripts import generate
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({
            "language": "en",
            "content_mode": "enriched",
        }), encoding="utf-8")
        with patch.object(generate, "CONFIG_PATH", cfg_path):
            config = generate.load_config()
        assert "content_mode" not in config
        assert any("content_mode" in r.message for r in caplog.records)


class TestFeedRebuildFlag:
    def test_env_flag_parses_truthy_values(self, monkeypatch):
        from scripts.generate import _as_bool

        assert _as_bool("1") is True
        assert _as_bool("true") is True
        assert _as_bool("YES") is True
        assert _as_bool("0") is False
        assert _as_bool("false") is False
        assert _as_bool("") is False

    def test_a_hand_edited_string_is_not_read_as_truthy(self):
        # bool("false") is True, and this flag re-renders every item body
        # in the full feed, so the mistake costs a whole-file diff a day.
        from scripts.generate import _config_flag

        assert _config_flag({"feed_rebuild_all": "false"}, "feed_rebuild_all") is False
        assert _config_flag({"feed_rebuild_all": "0"}, "feed_rebuild_all") is False
        assert _config_flag({"feed_rebuild_all": "true"}, "feed_rebuild_all") is True

    def test_real_booleans_and_a_missing_key_are_unchanged(self):
        from scripts.generate import _config_flag

        assert _config_flag({"feed_rebuild_all": True}, "feed_rebuild_all") is True
        assert _config_flag({"feed_rebuild_all": False}, "feed_rebuild_all") is False
        assert _config_flag({}, "feed_rebuild_all") is False
