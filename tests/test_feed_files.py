"""Tests for feed file writing: atomic, and only when bytes change."""

from scripts import urls
from scripts.feed_builder import write_feed


def test_feed_full_file_constant():
    assert urls.FEED_FULL_FILE == "feed-full.xml"


def test_write_feed_reports_first_write(tmp_path):
    target = tmp_path / "feed.xml"
    assert write_feed("<rss/>", str(target)) is True
    assert target.read_text(encoding="utf-8") == "<rss/>"


def test_write_feed_skips_identical_content(tmp_path):
    target = tmp_path / "feed.xml"
    write_feed("<rss/>", str(target))
    before = target.stat().st_mtime_ns
    assert write_feed("<rss/>", str(target)) is False
    assert target.stat().st_mtime_ns == before


def test_write_feed_rewrites_changed_content(tmp_path):
    target = tmp_path / "feed.xml"
    write_feed("<rss/>", str(target))
    assert write_feed("<rss></rss>", str(target)) is True
    assert target.read_text(encoding="utf-8") == "<rss></rss>"
