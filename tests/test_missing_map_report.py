"""Tests for the run-report warning about missing composed maps.

Map composition happens inside the feed rebuild and never fails the run.
``_report_missing_maps`` is what makes those silent failures visible: a
species that has a GBIF distribution map but no composed PNG must show up
in the run summary.
"""

import json

from scripts import generate
from scripts.run_report import RunReport


def _write_cache(cache_dir, code: str, map_url: str) -> None:
    (cache_dir / f"{code}.json").write_text(
        json.dumps(
            {
                "description": "texto",
                "description_source": "ebird",
                "bow_intro": "",
                "taxonomy": {},
                "distribution_map_url": map_url,
            }
        ),
        encoding="utf-8",
    )


class TestReportMissingMaps:
    def test_warns_only_for_composable_missing_maps(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        # composed: has a map URL and a composed PNG. No warning.
        _write_cache(cache_dir, "aaa", "https://gbif.example/aaa.png")
        # missing: has a map URL but no composed PNG. Must warn.
        _write_cache(cache_dir, "bbb", "https://gbif.example/bbb.png")
        # no GBIF map at all: nothing to compose, so no warning.
        _write_cache(cache_dir, "ccc", "")
        monkeypatch.setattr(generate, "CACHE_DIR", cache_dir)

        history = {
            "entries": [
                {"speciesCode": "aaa"},
                {"speciesCode": "bbb"},
                {"speciesCode": "ccc"},
            ]
        }
        report = RunReport()
        generate._report_missing_maps(history, {"aaa": "maps/aaa.png"}, report)

        assert report.warnings == ["map composition missing for bbb"]

    def test_uncached_species_does_not_warn(self, tmp_path, monkeypatch):
        # No cache file at all: the scrape never produced a map URL, so
        # there is nothing to report.
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        monkeypatch.setattr(generate, "CACHE_DIR", cache_dir)

        report = RunReport()
        generate._report_missing_maps(
            {"entries": [{"speciesCode": "zzz"}, {"date": "2026-01-01"}]},
            {},
            report,
        )

        assert report.warnings == []
