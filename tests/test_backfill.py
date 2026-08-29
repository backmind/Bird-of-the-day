"""Tests for the self-healing backfill step."""

import json
from unittest.mock import MagicMock, patch

from scripts.backfill import run_backfill
from scripts.distribution_map import MATCH_ERROR, MATCH_NONE, MATCH_OK
from scripts.llm_enricher import EnrichedContent


def _history(*codes_dates):
    return {"entries": [
        {"speciesCode": c, "comName": c.upper(), "sciName": f"Genus {c}",
         "date": d}
        for c, d in codes_dates
    ]}


def _write_content(tmp_path, code, **overrides):
    data = {
        "description": "texto", "description_source": "ebird",
        "bow_intro": "", "taxonomy": {}, "gbif_taxon_key": 1,
        "distribution_map_url": "http://gbif/x.png", "gbif_match": MATCH_OK,
    }
    data.update(overrides)
    (tmp_path / f"{code}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _write_enrichment(tmp_path, code):
    (tmp_path / f"{code}.enriched.json").write_text(json.dumps({
        "prose": "p", "identification": ["a"], "model": "m", "timestamp": "t",
    }), encoding="utf-8")


CFG = {"llm": {"endpoint": "http://fake", "models": ["m"]}}
ENRICHED = EnrichedContent(
    prose="nuevo", identification=["a", "b", "c"], model="m", timestamp="t"
)


def _run(history, tmp_path, limit=3, cfg=CFG):
    return run_backfill(
        history, cfg, MagicMock(language="es"), str(tmp_path), {}, {}, limit
    )


class TestEnrichmentBackfill:
    def test_heals_missing_enrichment(self, tmp_path):
        _write_content(tmp_path, "aaa")
        with patch("scripts.backfill.llm_enricher.enrich_species",
                   return_value=ENRICHED) as enrich:
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                actions = _run(_history(("aaa", "2026-01-01")), tmp_path)
        assert enrich.call_count == 1
        assert [(a.kind, a.ok) for a in actions] == [("enrichment", True)]
        assert (tmp_path / "aaa.enriched.json").exists()

    def test_newest_first_and_limit(self, tmp_path):
        for code in ("old", "mid", "new"):
            _write_content(tmp_path, code)
        history = _history(
            ("old", "2026-01-01"), ("mid", "2026-01-02"), ("new", "2026-01-03")
        )
        with patch("scripts.backfill.llm_enricher.enrich_species",
                   return_value=ENRICHED) as enrich:
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                actions = _run(history, tmp_path, limit=2)
        called = [c.args[0] for c in enrich.call_args_list]
        assert called == ["new", "mid"]
        assert len(actions) == 2

    def test_skips_already_enriched(self, tmp_path):
        _write_content(tmp_path, "aaa")
        _write_enrichment(tmp_path, "aaa")
        with patch("scripts.backfill.llm_enricher.enrich_species") as enrich:
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                actions = _run(_history(("aaa", "2026-01-01")), tmp_path)
        assert enrich.call_count == 0
        assert actions == []

    def test_no_llm_configured_skips_enrichment(self, tmp_path):
        _write_content(tmp_path, "aaa")
        with patch.dict("os.environ", {}, clear=True):
            actions = _run(_history(("aaa", "2026-01-01")), tmp_path)
        assert actions == []

    def test_failed_attempt_counts_against_limit(self, tmp_path):
        for code in ("aaa", "bbb"):
            _write_content(tmp_path, code)
        history = _history(("aaa", "2026-01-01"), ("bbb", "2026-01-02"))
        with patch("scripts.backfill.llm_enricher.enrich_species",
                   return_value=None):
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                actions = _run(history, tmp_path, limit=1)
        assert len(actions) == 1
        assert actions[0].ok is False


class TestGbifBackfill:
    def test_retries_transient_error(self, tmp_path):
        _write_content(
            tmp_path, "aaa", gbif_taxon_key=None,
            distribution_map_url="", gbif_match=MATCH_ERROR,
        )
        _write_enrichment(tmp_path, "aaa")
        with patch("scripts.backfill.distribution_map.gbif_taxon_match_ex",
                   return_value=(42, MATCH_OK)):
            with patch("scripts.backfill.distribution_map.fetch_iucn_category",
                       return_value=("LC", "LEAST_CONCERN", "http://bl")):
                with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                    actions = _run(_history(("aaa", "2026-01-01")), tmp_path)
        assert [(a.kind, a.ok) for a in actions] == [("gbif", True)]
        data = json.loads((tmp_path / "aaa.json").read_text(encoding="utf-8"))
        assert data["gbif_taxon_key"] == 42
        assert "taxonKey=42" in data["distribution_map_url"]
        assert data["iucn_code"] == "LC"

    def test_authoritative_none_not_retried(self, tmp_path):
        _write_content(
            tmp_path, "aaa", gbif_taxon_key=None,
            distribution_map_url="", gbif_match=MATCH_NONE,
        )
        _write_enrichment(tmp_path, "aaa")
        with patch("scripts.backfill.distribution_map.gbif_taxon_match_ex") as m:
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                actions = _run(_history(("aaa", "2026-01-01")), tmp_path)
        assert m.call_count == 0
        assert actions == []

    def test_zero_limit_disables(self, tmp_path):
        _write_content(tmp_path, "aaa")
        with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
            actions = _run(_history(("aaa", "2026-01-01")), tmp_path, limit=0)
        assert actions == []

    def test_gbif_consumes_last_slot_before_enrichment(self, tmp_path):
        _write_content(
            tmp_path, "aaa", gbif_taxon_key=None,
            distribution_map_url="", gbif_match=MATCH_ERROR,
        )
        with patch("scripts.backfill.distribution_map.gbif_taxon_match_ex",
                   return_value=(42, MATCH_OK)):
            with patch("scripts.backfill.distribution_map.fetch_iucn_category",
                       return_value=("LC", "LEAST_CONCERN", "http://bl")):
                with patch("scripts.backfill.llm_enricher.enrich_species") as enrich:
                    with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                        actions = _run(
                            _history(("aaa", "2026-01-01")), tmp_path, limit=1
                        )
        assert [(a.kind, a.ok) for a in actions] == [("gbif", True)]
        assert enrich.call_count == 0

    def test_gbif_failure_persists_state(self, tmp_path):
        _write_content(
            tmp_path, "aaa", gbif_taxon_key=None,
            distribution_map_url="", gbif_match=MATCH_ERROR,
        )
        _write_enrichment(tmp_path, "aaa")
        with patch("scripts.backfill.distribution_map.gbif_taxon_match_ex",
                   return_value=(None, MATCH_ERROR)):
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                actions = _run(_history(("aaa", "2026-01-01")), tmp_path)
        assert [(a.kind, a.ok) for a in actions] == [("gbif", False)]
        data = json.loads((tmp_path / "aaa.json").read_text(encoding="utf-8"))
        assert data["gbif_match"] == "error"
        assert data["gbif_taxon_key"] is None

    def test_legacy_empty_state_retries(self, tmp_path):
        _write_content(
            tmp_path, "aaa", gbif_taxon_key=None,
            distribution_map_url="", gbif_match="",
        )
        _write_enrichment(tmp_path, "aaa")
        with patch("scripts.backfill.distribution_map.gbif_taxon_match_ex",
                   return_value=(42, MATCH_OK)) as m:
            with patch("scripts.backfill.distribution_map.fetch_iucn_category",
                       return_value=("LC", "LEAST_CONCERN", "http://bl")):
                with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                    _run(_history(("aaa", "2026-01-01")), tmp_path)
        assert m.call_count == 1

    def test_empty_sciname_skips_gbif(self, tmp_path):
        _write_content(
            tmp_path, "aaa", gbif_taxon_key=None, gbif_match=MATCH_ERROR,
        )
        _write_enrichment(tmp_path, "aaa")
        history = {"entries": [
            {"speciesCode": "aaa", "comName": "AAA", "sciName": "",
             "date": "2026-01-01"},
        ]}
        with patch("scripts.backfill.distribution_map.gbif_taxon_match_ex") as m:
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                actions = _run(history, tmp_path)
        assert actions == []
        assert m.call_count == 0
