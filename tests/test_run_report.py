"""Tests for the run report: local logging and GitHub Actions surfaces."""

from unittest.mock import patch

from scripts.run_report import RunReport


class TestRunReport:
    def test_emit_outside_ci_prints_nothing(self, capsys, tmp_path):
        report = RunReport()
        report.info("Species: X")
        report.warn("LLM fallback")
        with patch.dict("os.environ", {}, clear=True):
            report.emit()
        assert "::warning::" not in capsys.readouterr().out

    def test_emit_in_ci_prints_warnings(self, capsys):
        report = RunReport()
        report.warn("LLM fallback for xyz")
        with patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}, clear=True):
            report.emit()
        assert "::warning::LLM fallback for xyz" in capsys.readouterr().out

    def test_emit_writes_step_summary(self, tmp_path):
        summary = tmp_path / "summary.md"
        report = RunReport()
        report.info("Species: Great Tit")
        report.warn("map composition failed")
        env = {"GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": str(summary)}
        with patch.dict("os.environ", env, clear=True):
            report.emit()
        text = summary.read_text(encoding="utf-8")
        assert "Species: Great Tit" in text
        assert "map composition failed" in text

    def test_degraded_flag(self):
        report = RunReport()
        assert report.degraded is False
        report.info("fine")
        assert report.degraded is False
        report.warn("bad")
        assert report.degraded is True
