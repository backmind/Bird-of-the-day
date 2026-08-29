"""Tests for GBIF match state: authoritative misses vs transient errors."""

from unittest.mock import MagicMock

import requests

from scripts.distribution_map import (
    MATCH_ERROR,
    MATCH_NONE,
    MATCH_OK,
    fetch_distribution_ex,
    gbif_taxon_match_ex,
)


def _session_returning(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    sess = MagicMock()
    sess.get.return_value = resp
    return sess


class TestMatchEx:
    def test_exact_match(self):
        sess = _session_returning(
            {"matchType": "EXACT", "confidence": 99, "usageKey": 42}
        )
        key, state = gbif_taxon_match_ex("Parus major", session=sess)
        assert (key, state) == (42, MATCH_OK)

    def test_none_match_is_authoritative(self):
        sess = _session_returning({"matchType": "NONE", "confidence": 100})
        key, state = gbif_taxon_match_ex("Nonexistus birdus", session=sess)
        assert (key, state) == (None, MATCH_NONE)

    def test_low_confidence_is_authoritative(self):
        sess = _session_returning(
            {"matchType": "FUZZY", "confidence": 10, "usageKey": 42}
        )
        key, state = gbif_taxon_match_ex("Parus sp", session=sess)
        assert (key, state) == (None, MATCH_NONE)

    def test_network_error_is_transient(self):
        sess = MagicMock()
        sess.get.side_effect = requests.ConnectionError("boom")
        key, state = gbif_taxon_match_ex("Parus major", session=sess)
        assert (key, state) == (None, MATCH_ERROR)

    def test_empty_name_is_authoritative(self):
        key, state = gbif_taxon_match_ex("")
        assert (key, state) == (None, MATCH_NONE)

    def test_malformed_payload_is_transient(self):
        sess = _session_returning(["not", "a", "dict"])
        key, state = gbif_taxon_match_ex("Parus major", session=sess)
        assert (key, state) == (None, MATCH_ERROR)

    def test_genus_rank_rejected(self):
        sess = _session_returning(
            {
                "matchType": "HIGHERRANK",
                "confidence": 95,
                "usageKey": 2480909,
                "rank": "GENUS",
            }
        )
        key, state = gbif_taxon_match_ex("Botaurus lentiginosus", session=sess)
        assert (key, state) == (None, MATCH_NONE)


class TestFetchDistributionEx:
    def test_success_builds_map_url(self):
        sess = _session_returning(
            {"matchType": "EXACT", "confidence": 99, "usageKey": 42}
        )
        key, url, state = fetch_distribution_ex("Parus major", session=sess)
        assert key == 42
        assert "taxonKey=42" in url
        assert state == MATCH_OK

    def test_error_keeps_empty_url(self):
        sess = MagicMock()
        sess.get.side_effect = requests.ConnectionError("boom")
        key, url, state = fetch_distribution_ex("Parus major", session=sess)
        assert (key, url, state) == (None, "", MATCH_ERROR)


class TestContentCacheRoundTrip:
    def test_gbif_match_persisted(self, tmp_path):
        from scripts.content_scraper import (
            SpeciesContent,
            load_cached_content,
            save_cached_content,
        )
        content = SpeciesContent(
            description="x", description_source="ebird",
            bow_intro="", taxonomy={}, gbif_match=MATCH_ERROR,
        )
        save_cached_content("abc", content, str(tmp_path))
        loaded = load_cached_content("abc", str(tmp_path))
        assert loaded is not None
        assert loaded.gbif_match == MATCH_ERROR

    def test_legacy_cache_defaults_empty(self, tmp_path):
        from scripts.content_scraper import load_cached_content
        (tmp_path / "old.json").write_text(
            '{"description": "x", "description_source": "ebird"}',
            encoding="utf-8",
        )
        loaded = load_cached_content("old", str(tmp_path))
        assert loaded is not None
        assert loaded.gbif_match == ""
