"""Tests for the RSS channel, the item envelope and Media RSS."""

from scripts import urls
from scripts.feed_builder import (
    FEED_FORMAT,
    FeedEntry,
    build_feed,
    load_existing_feed,
    load_feed_format,
    write_feed,
)
from scripts.i18n import Catalog

CONFIG = {"feed_link": "https://birds.example.org/"}


def _entry(n: int = 1, **kwargs) -> FeedEntry:
    defaults = dict(
        species_code="eurbla",
        common_name="Mirlo común",
        scientific_name="Turdus merula",
        description_html="<p>cuerpo</p>",
        image_url="https://cdn.example.org/asset/1/900",
        image_attribution="Jane Doe / Macaulay Library",
        ml_search_url="https://search.macaulaylibrary.org/catalog",
        pub_date=f"Thu, 2{n} Aug 2026 06:00:00 +0000",
        guid=f"bird-of-the-day-eurbla-2026-08-2{n}",
        link="https://birds.example.org/birds/eurbla.html",
    )
    defaults.update(kwargs)
    return FeedEntry(**defaults)


class TestChannel:
    def test_self_link_points_at_the_file_being_written(self):
        xml = build_feed([_entry()], CONFIG, Catalog.load("es"))
        assert 'href="https://birds.example.org/feed.xml"' in xml

    def test_self_link_follows_the_full_feed(self):
        xml = build_feed(
            [_entry()], CONFIG, Catalog.load("es"),
            self_path=urls.FEED_FULL_FILE,
        )
        assert 'href="https://birds.example.org/feed-full.xml"' in xml

    def test_title_can_be_overridden(self):
        xml = build_feed([_entry()], CONFIG, Catalog.load("es"), title="Otro")
        assert "<title>Otro</title>" in xml

    def test_channel_pubdate_is_the_newest_item(self):
        xml = build_feed([_entry(9), _entry(1)], CONFIG, Catalog.load("es"))
        assert "<pubDate>Thu, 29 Aug 2026 06:00:00 +0000</pubDate>" in xml

    def test_generator_declares_the_format_version(self):
        xml = build_feed([_entry()], CONFIG, Catalog.load("es"))
        assert f"feed format {FEED_FORMAT}" in xml

    def test_empty_feed_has_no_pubdate(self):
        xml = build_feed([], CONFIG, Catalog.load("es"))
        assert "<pubDate>" not in xml


class TestItem:
    def test_link_points_at_the_species_page(self):
        xml = build_feed([_entry()], CONFIG, Catalog.load("es"))
        assert "<link>https://birds.example.org/birds/eurbla.html</link>" in xml

    def test_link_degrades_to_ebird(self):
        xml = build_feed([_entry(link="")], CONFIG, Catalog.load("es"))
        assert "<link>https://ebird.org/species/eurbla</link>" in xml

    def test_guid_format_is_untouched(self):
        xml = build_feed([_entry()], CONFIG, Catalog.load("es"))
        assert "<guid isPermaLink=\"false\">bird-of-the-day-eurbla-2026-08-21</guid>" in xml

    def test_media_content_carries_the_photo_and_its_credit(self):
        xml = build_feed([_entry()], CONFIG, Catalog.load("es"))
        assert 'url="https://cdn.example.org/asset/1/900"' in xml
        assert 'medium="image"' in xml
        assert "Jane Doe / Macaulay Library" in xml
        assert "media:thumbnail" in xml

    def test_no_media_without_a_photo(self):
        xml = build_feed([_entry(image_url=None)], CONFIG, Catalog.load("es"))
        assert "media:content" not in xml


class TestRoundTrip:
    def test_bodies_and_dates_survive_a_round_trip(self, tmp_path):
        target = tmp_path / "feed.xml"
        xml = build_feed([_entry()], CONFIG, Catalog.load("es"))
        write_feed(xml, str(target))
        loaded = load_existing_feed(str(target))
        assert len(loaded) == 1
        assert loaded[0].guid == "bird-of-the-day-eurbla-2026-08-21"
        assert loaded[0].description_html.strip() == "<p>cuerpo</p>"
        assert loaded[0].pub_date == "Thu, 21 Aug 2026 06:00:00 +0000"
        assert loaded[0].species_code == "eurbla"

    def test_format_version_is_readable_back(self, tmp_path):
        target = tmp_path / "feed.xml"
        write_feed(build_feed([_entry()], CONFIG, Catalog.load("es")), str(target))
        assert load_feed_format(str(target)) == FEED_FORMAT

    def test_missing_file_has_no_format(self, tmp_path):
        assert load_feed_format(str(tmp_path / "nope.xml")) is None
