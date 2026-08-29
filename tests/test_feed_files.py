"""Tests for feed file writing: atomic, and only when bytes change."""

from pathlib import Path

from scripts import urls
from scripts.feed_builder import (
    FEED_FORMAT,
    FeedEntry,
    load_existing_feed,
    load_feed_format,
    write_feed,
    write_feeds,
)
from scripts.i18n import Catalog


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


def _entries(n: int) -> list[FeedEntry]:
    """n entries, newest first, bodies tagged so freezing is visible."""
    return [
        FeedEntry(
            species_code=f"sp{i:03d}",
            common_name=f"Bird {i}",
            scientific_name=f"Genus specimen{i}",
            description_html=f"<p>fresh {i}</p>",
            image_url=None,
            image_attribution="",
            ml_search_url="",
            pub_date="Thu, 27 Aug 2026 06:00:00 +0000",
            guid=f"bird-of-the-day-sp{i:03d}-2026-08-27",
            link=f"https://birds.example.org/birds/sp{i:03d}.html",
        )
        for i in range(n)
    ]


def _config(cap: int) -> dict:
    return {"feed_link": "https://birds.example.org/", "max_feed_entries": cap}


class TestFeedFiles:
    def test_cap_keeps_the_newest_entries(self, tmp_path):
        result = write_feeds(_entries(10), _config(3), Catalog.load("es"), tmp_path)
        assert result["items"] == 3
        loaded = load_existing_feed(str(tmp_path / urls.FEED_FILE))
        assert [e.species_code for e in loaded] == ["sp000", "sp001", "sp002"]

    def test_full_feed_keeps_everything(self, tmp_path):
        result = write_feeds(_entries(10), _config(3), Catalog.load("es"), tmp_path)
        assert result["full_items"] == 10
        assert (tmp_path / urls.FEED_FULL_FILE).exists()

    def test_no_full_feed_without_a_cap(self, tmp_path):
        result = write_feeds(_entries(10), _config(0), Catalog.load("es"), tmp_path)
        assert result["items"] == 10
        assert result["full_written"] is False
        assert not (tmp_path / urls.FEED_FULL_FILE).exists()


class TestStaleFullFeed:
    """Turning the cap off orphans a feed-full.xml that already exists.

    Nothing rewrites it and, since the fix to the page links, nothing
    mentions it either. Deleting a published file is out of scope, so the
    run has to say it is there.
    """

    def test_an_orphaned_full_feed_is_flagged(self, tmp_path):
        write_feeds(_entries(10), _config(3), Catalog.load("es"), tmp_path)
        assert (tmp_path / urls.FEED_FULL_FILE).exists()
        result = write_feeds(_entries(10), _config(0), Catalog.load("es"), tmp_path)
        assert result["full_stale"] is True
        # Reported, never removed.
        assert (tmp_path / urls.FEED_FULL_FILE).exists()

    def test_nothing_is_flagged_when_no_full_feed_was_ever_written(self, tmp_path):
        result = write_feeds(_entries(10), _config(0), Catalog.load("es"), tmp_path)
        assert result["full_stale"] is False

    def test_a_maintained_full_feed_is_not_stale(self, tmp_path):
        write_feeds(_entries(10), _config(3), Catalog.load("es"), tmp_path)
        result = write_feeds(_entries(10), _config(3), Catalog.load("es"), tmp_path)
        assert result["full_stale"] is False


class TestFreezing:
    def _first_run(self, tmp_path) -> None:
        write_feeds(_entries(5), _config(2), Catalog.load("es"), tmp_path)

    def _second_run(self, tmp_path, **kwargs) -> dict:
        changed = _entries(5)
        for entry in changed:
            entry.description_html = entry.description_html.replace("fresh", "redone")
        return write_feeds(
            changed, _config(2), Catalog.load("es"), tmp_path, **kwargs
        )

    def test_old_bodies_are_reused_and_recent_ones_are_not(self, tmp_path):
        self._first_run(tmp_path)
        result = self._second_run(tmp_path)
        assert result["frozen"] == 3
        bodies = {
            e.species_code: e.description_html
            for e in load_existing_feed(str(tmp_path / urls.FEED_FULL_FILE))
        }
        assert "redone 0" in bodies["sp000"]
        assert "redone 1" in bodies["sp001"]
        assert "fresh 4" in bodies["sp004"]

    def test_rebuild_all_thaws_everything(self, tmp_path):
        self._first_run(tmp_path)
        result = self._second_run(tmp_path, rebuild_all=True)
        assert result["frozen"] == 0
        bodies = [
            e.description_html
            for e in load_existing_feed(str(tmp_path / urls.FEED_FULL_FILE))
        ]
        assert all("redone" in b for b in bodies)

    def _restamp(self, tmp_path, replacement: str) -> None:
        """Rewrite the stored full feed's format marker in place."""
        target = tmp_path / urls.FEED_FULL_FILE
        target.write_text(
            target.read_text(encoding="utf-8").replace(
                f"feed format {FEED_FORMAT}", replacement
            ),
            encoding="utf-8",
        )

    def test_a_foreign_format_version_is_not_reused(self, tmp_path):
        # A real, readable version that is not ours. The marker is still
        # there, so this exercises the version comparison itself and not
        # the missing-marker branch below: an implementation that only
        # asked whether a marker exists would reuse these bodies and mix
        # two item formats in one file forever.
        self._first_run(tmp_path)
        self._restamp(tmp_path, "feed format 1")
        assert load_feed_format(str(tmp_path / urls.FEED_FULL_FILE)) == 1
        assert self._second_run(tmp_path)["frozen"] == 0

    def test_a_missing_format_marker_is_not_reused(self, tmp_path):
        # A feed written before the marker existed: nothing to compare,
        # so nothing may be trusted.
        self._first_run(tmp_path)
        self._restamp(tmp_path, "feed shape 2")
        assert load_feed_format(str(tmp_path / urls.FEED_FULL_FILE)) is None
        assert self._second_run(tmp_path)["frozen"] == 0

    def test_writing_twice_changes_nothing(self, tmp_path):
        self._first_run(tmp_path)
        result = write_feeds(_entries(5), _config(2), Catalog.load("es"), tmp_path)
        assert result["feed_written"] is False
        assert result["full_written"] is False
