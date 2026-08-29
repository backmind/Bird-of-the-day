"""Tests for the generator's half of the feed: the wiring, not the XML.

``feed_builder`` is covered by its own files. What was untested is the
layer above it in ``generate.py``: which config keys reach it, in what
order history is handed over, where pubDates come from when two files
disagree, and what the run report says afterwards.

Every test that touches disk redirects ``STATE_DIR``'s three derived
directories at ``tmp_path``. ``_rebuild_feed`` takes ``state_dir`` as an
argument precisely so that redirection is complete: it used to read the
feeds through module constants while writing through the global, so a
test could point the writes at a temporary directory and still read the
repository's own published feed.
"""

import json
from datetime import datetime, timezone

from scripts import feed_builder, generate, run_report, urls
from scripts.backfill import BackfillAction
from scripts.i18n import Catalog

# Far from any real pubDate in the fixtures, so a date that leaked in
# from the run clock instead of from a stored feed is unmistakable.
NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)

FEED_LINK = "https://birds.example.org/"


def _config(**overrides) -> dict:
    config = {
        "language": "en",
        "feed_link": FEED_LINK,
        "max_feed_entries": 0,
    }
    config.update(overrides)
    return config


def _history(*rows: tuple[str, str]) -> dict:
    """History in the order generate.py keeps it: oldest first, appended."""
    return {
        "entries": [
            {
                "speciesCode": code,
                "comName": f"Bird {code}",
                "sciName": f"Genus {code}",
                "date": date,
                "imageUrl": None,
                "photographer": "",
                "attribution": "",
            }
            for code, date in rows
        ]
    }


def _isolate(monkeypatch, tmp_path) -> None:
    """Point every state-derived path at tmp_path.

    ``ensure_composed_maps`` creates its output directory eagerly, so an
    unpatched MAPS_DIR would leave a ``maps/`` behind in the repository
    even on a run that composes nothing.
    """
    monkeypatch.setattr(generate, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(generate, "MAPS_DIR", tmp_path / "maps")


def _rebuild(tmp_path, history: dict, config: dict) -> dict:
    _, feed_result = generate._rebuild_feed(
        history,
        config,
        Catalog.load("en"),
        "foreign_fallback",
        {},
        {},
        {},
        NOW,
        state_dir=tmp_path,
    )
    return feed_result


def _stored_feed(tmp_path, name: str = urls.FEED_FILE):
    return feed_builder.load_existing_feed(str(tmp_path / name))


def _minimal_feed(guid: str, pub_date: str, code: str = "aaa") -> str:
    """A feed with one item, hand-written so pubDate can be blank.

    ``build_feed`` cannot produce an empty ``<pubDate>``, and an empty one
    is exactly the shape the merge has to survive.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        "<title>Bird of the Day</title>"
        f"<generator>Bird of the Day (feed format {feed_builder.FEED_FORMAT})</generator>"
        "<item>"
        f"<title>Bird {code} (Genus {code})</title>"
        f"<link>{FEED_LINK}birds/{code}.html</link>"
        f'<guid isPermaLink="false">{guid}</guid>'
        f"<pubDate>{pub_date}</pubDate>"
        "</item>"
        "</channel></rss>"
    )


class TestEnvOverride:
    """The override table is data, so nothing type-checks the key names.

    A key renamed on one side of the table and not the other leaves the
    env var parsing correctly into a name no one reads.
    """

    def test_the_rebuild_flag_reaches_its_config_key(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"language": "en"}), encoding="utf-8")
        monkeypatch.setattr(generate, "CONFIG_PATH", cfg)
        monkeypatch.setenv("BOTD_FEED_REBUILD_ALL", "1")
        assert generate.load_config()["feed_rebuild_all"] is True

    def test_a_falsy_env_value_is_parsed_as_a_flag_not_as_a_string(
        self, tmp_path, monkeypatch
    ):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"language": "en"}), encoding="utf-8")
        monkeypatch.setattr(generate, "CONFIG_PATH", cfg)
        monkeypatch.setenv("BOTD_FEED_REBUILD_ALL", "0")
        assert generate.load_config()["feed_rebuild_all"] is False


class TestOrdering:
    """History is oldest first; the feed is newest first.

    The reversal happens once, in _rebuild_feed. Getting it wrong dates
    the channel to the oldest item and, under a cap, publishes the oldest
    entries as if they were today's.
    """

    HISTORY = _history(
        ("aaa", "2026-08-01"), ("bbb", "2026-08-02"), ("ccc", "2026-08-03")
    )

    def test_the_newest_entry_comes_first(self, tmp_path, monkeypatch):
        _isolate(monkeypatch, tmp_path)
        _rebuild(tmp_path, self.HISTORY, _config())
        assert [e.species_code for e in _stored_feed(tmp_path)] == [
            "ccc",
            "bbb",
            "aaa",
        ]

    def test_the_cap_keeps_the_newest_not_the_oldest(self, tmp_path, monkeypatch):
        _isolate(monkeypatch, tmp_path)
        result = _rebuild(tmp_path, self.HISTORY, _config(max_feed_entries=2))
        assert result["items"] == 2
        assert [e.species_code for e in _stored_feed(tmp_path)] == ["ccc", "bbb"]
        # The full feed still has everything, in the same order.
        assert [
            e.species_code for e in _stored_feed(tmp_path, urls.FEED_FULL_FILE)
        ] == ["ccc", "bbb", "aaa"]


class TestRepublicationContext:
    """A species published twice is the one history shape an inverted
    reverse-index mapping cannot fake: swapping which occurrence gets
    which context still produces one ordinal-0 and one ordinal-1 entry,
    just attached to the wrong publication, so only checking both sides
    together against a known-correct pairing can catch it.

    ``_rebuild_feed`` no longer computes the mapping itself, it consumes
    ``generate._entries_newest_first``; wrapping that shared helper with a
    recording spy observes the exact ``(ordinal, previous_date)`` pairs it
    handed to the loop for this call, since neither value is threaded into
    ``FeedEntry`` yet (that is Task 5's job).
    """

    HISTORY = _history(("aaa", "2026-08-01"), ("aaa", "2026-08-15"))

    def _history_with_distinct_photos(self) -> dict:
        # Two occurrences of the same species, each recorded with its own
        # photograph. Nothing is cached per ordinal, so `_image_for` falls
        # back to exactly what each history entry recorded: the two items
        # must not end up sharing one entry's photo (a raw-pairing bug
        # inside the loop, independent from the ordinal arithmetic that
        # the next test exercises).
        return {
            "entries": [
                {**raw, "imageUrl": f"https://cdn/asset/{i}/1200"}
                for i, raw in enumerate(self.HISTORY["entries"], start=1)
            ]
        }

    def test_the_newer_publication_gets_ordinal_one_and_the_older_date(
        self, tmp_path, monkeypatch
    ):
        _isolate(monkeypatch, tmp_path)
        seen: dict[str, tuple[int, str]] = {}
        real_entries_newest_first = generate._entries_newest_first

        def spy(raw_entries):
            for raw, number, ordinal, previous_date in real_entries_newest_first(
                raw_entries
            ):
                seen[raw["date"]] = (ordinal, previous_date)
                yield raw, number, ordinal, previous_date

        monkeypatch.setattr(generate, "_entries_newest_first", spy)

        _rebuild(tmp_path, self.HISTORY, _config())

        assert seen["2026-08-15"] == (1, "2026-08-01")
        assert seen["2026-08-01"] == (0, "")

    def test_each_publication_keeps_the_photograph_its_own_entry_recorded(
        self, tmp_path, monkeypatch
    ):
        # ``load_existing_feed`` never repopulates ``FeedEntry.image_url``
        # (round-tripping only needs the guid, pubDate and rendered body),
        # so the photo actually used has to be read from the rendered
        # HTML body itself, where ``build_entry_html`` embeds it as an
        # ``<img src=...>``.
        _isolate(monkeypatch, tmp_path)
        history = self._history_with_distinct_photos()
        _rebuild(tmp_path, history, _config())

        by_guid = {e.guid: e.description_html for e in _stored_feed(tmp_path)}
        assert "https://cdn/asset/1/1200" in by_guid[
            urls.feed_guid("aaa", "2026-08-01")
        ]
        assert "https://cdn/asset/2/1200" in by_guid[
            urls.feed_guid("aaa", "2026-08-15")
        ]
        assert "https://cdn/asset/2/1200" not in by_guid[
            urls.feed_guid("aaa", "2026-08-01")
        ]
        assert "https://cdn/asset/1/1200" not in by_guid[
            urls.feed_guid("aaa", "2026-08-15")
        ]

    def test_each_publication_gets_the_photograph_cached_for_its_own_ordinal(
        self, tmp_path, monkeypatch
    ):
        # Unlike the history-fallback test above, this one goes through
        # `_image_for`'s cache branch, which is keyed by ordinal: an
        # inverted mapping hands the debut's cache to the repeat and vice
        # versa, so this is the one photo-based assertion that only a
        # correct ordinal can produce.
        from scripts import image_fetcher

        _isolate(monkeypatch, tmp_path)
        cache_dir = str(generate.CACHE_DIR)
        image_fetcher.save_cached_image(
            "aaa",
            image_fetcher.ImageResult(
                url="https://cdn/asset/debut/1200", asset_id="debut",
                photographer="", attribution="Macaulay Library",
                search_url="s",
            ),
            cache_dir, ordinal=0,
        )
        image_fetcher.save_cached_image(
            "aaa",
            image_fetcher.ImageResult(
                url="https://cdn/asset/repeat/1200", asset_id="repeat",
                photographer="", attribution="Macaulay Library",
                search_url="s",
            ),
            cache_dir, ordinal=1,
        )

        _rebuild(tmp_path, self.HISTORY, _config())

        by_guid = {e.guid: e.description_html for e in _stored_feed(tmp_path)}
        assert "https://cdn/asset/debut/1200" in by_guid[
            urls.feed_guid("aaa", "2026-08-01")
        ]
        assert "https://cdn/asset/repeat/1200" in by_guid[
            urls.feed_guid("aaa", "2026-08-15")
        ]
        assert "https://cdn/asset/repeat/1200" not in by_guid[
            urls.feed_guid("aaa", "2026-08-01")
        ]
        assert "https://cdn/asset/debut/1200" not in by_guid[
            urls.feed_guid("aaa", "2026-08-15")
        ]


class TestPubDateMerge:
    """pubDates are read from both files, and either one can be blank.

    The full feed is consulted first and feed.xml second, so feed.xml is
    the one that can overwrite. A blank date there must not erase a good
    date from the full feed: doing so would republish the item with the
    run's own clock and resurface it as unread for every subscriber.
    """

    GOOD = "Sat, 01 Aug 2026 06:00:00 +0000"
    GUID = urls.feed_guid("aaa", "2026-08-01")

    def _stage(self, tmp_path) -> None:
        (tmp_path / urls.FEED_FULL_FILE).write_text(
            _minimal_feed(self.GUID, self.GOOD), encoding="utf-8"
        )
        (tmp_path / urls.FEED_FILE).write_text(
            _minimal_feed(self.GUID, ""), encoding="utf-8"
        )

    def test_a_blank_date_does_not_overwrite_a_good_one(self, tmp_path, monkeypatch):
        _isolate(monkeypatch, tmp_path)
        self._stage(tmp_path)
        _rebuild(tmp_path, _history(("aaa", "2026-08-01")), _config())
        assert [e.pub_date for e in _stored_feed(tmp_path)] == [self.GOOD]

    def test_an_entry_with_no_stored_date_anywhere_gets_the_run_clock(
        self, tmp_path, monkeypatch
    ):
        # The other half of the same branch: the fallback still applies
        # when neither file knows the guid.
        _isolate(monkeypatch, tmp_path)
        self._stage(tmp_path)
        _rebuild(
            tmp_path,
            _history(("aaa", "2026-08-01"), ("zzz", "2026-08-29")),
            _config(),
        )
        dates = {e.species_code: e.pub_date for e in _stored_feed(tmp_path)}
        assert dates["aaa"] == self.GOOD
        assert "29 Aug 2026 12:00:00" in dates["zzz"]


class TestHealedGuids:
    """What the backfill repaired, expressed as feed identities.

    A ``BackfillAction`` knows the species code and not the date, so the
    dates have to come from history. Get this wrong and the healed entry
    stays frozen in feed-full.xml with the body it was published with,
    which is the exact failure the thaw exists to prevent.
    """

    HISTORY = _history(
        ("aaa", "2026-06-01"), ("bbb", "2026-07-02"), ("aaa", "2026-08-03")
    )

    def test_the_date_comes_from_history(self):
        assert generate._healed_guids(
            [BackfillAction("bbb", "enrichment", True)], self.HISTORY
        ) == {urls.feed_guid("bbb", "2026-07-02")}

    def test_every_publication_of_a_healed_species_thaws(self):
        # One cache file feeds every publication of the species, so a
        # single heal changes both bodies. Thawing only the newest would
        # leave the file holding two versions of the same repair.
        assert generate._healed_guids(
            [BackfillAction("aaa", "gbif", True)], self.HISTORY
        ) == {
            urls.feed_guid("aaa", "2026-06-01"),
            urls.feed_guid("aaa", "2026-08-03"),
        }

    def test_nothing_healed_thaws_nothing(self):
        assert generate._healed_guids([], self.HISTORY) == set()

    def test_a_species_not_in_history_contributes_no_guid(self):
        assert generate._healed_guids(
            [BackfillAction("zzz", "gbif", True)], self.HISTORY
        ) == set()


class TestFeedReport:
    """What the run says about the two files afterwards."""

    BASE = {
        "items": 30,
        "feed_written": True,
        "full_items": 0,
        "full_written": False,
        "frozen": 0,
        "thawed": 0,
        "full_stale": False,
    }

    def _report(self, **overrides) -> run_report.RunReport:
        report = run_report.RunReport()
        generate._report_feed({**self.BASE, **overrides}, report)
        return report

    def test_the_capped_feed_is_always_named(self):
        assert self._report().lines == ["feed: 30 items, written"]

    def test_no_full_feed_line_when_there_is_no_full_feed(self):
        assert not any("feed-full" in line for line in self._report().lines)

    def test_the_full_feed_line_appears_when_there_is_one(self):
        lines = self._report(
            full_items=141, full_written=True, frozen=111
        ).lines
        assert lines[0] == "feed: 30 items, written"
        assert lines[1] == (
            "feed-full: 141 items, 111 reused from the published feed, written"
        )

    def test_an_unchanged_run_says_so_for_both_files(self):
        lines = self._report(
            feed_written=False, full_items=141, full_written=False, frozen=141
        ).lines
        assert lines[0].endswith("unchanged")
        assert lines[1].endswith("unchanged")

    def test_healed_entries_are_named_when_there_are_any(self):
        lines = self._report(
            full_items=141, full_written=True, frozen=109, thawed=2
        ).lines
        assert lines[1] == (
            "feed-full: 141 items, 109 reused from the published feed, "
            "2 re-rendered after healing, written"
        )

    def test_a_run_that_healed_nothing_old_says_nothing_about_healing(self):
        lines = self._report(full_items=141, full_written=True, frozen=111).lines
        assert "re-rendered" not in lines[1]

    def test_an_orphaned_full_feed_is_warned_about(self):
        report = self._report(full_stale=True)
        assert report.degraded
        assert any(urls.FEED_FULL_FILE in w for w in report.warnings)

    def test_no_warning_when_the_full_feed_is_maintained(self):
        assert not self._report(full_items=141, full_written=True).degraded
