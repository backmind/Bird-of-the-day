"""The URL scheme is the site's contract with every link ever published."""

from scripts import urls


def test_month_key_is_the_iso_prefix():
    assert urls.month_key("2026-08-27") == "2026-08"


def test_entry_anchor_format_is_stable():
    assert urls.entry_anchor("eurbla", "2026-08-27") == "bird-eurbla-2026-08-27"


def test_bucket_filename_derives_from_the_date():
    assert urls.bucket_filename("2026-08-27") == "archive-2026-08.html"
    assert urls.bucket_filename_for_month("2026-01") == "archive-2026-01.html"


def test_bucket_url_joins_page_and_anchor():
    assert (
        urls.bucket_url("eurbla", "2026-08-27")
        == "archive-2026-08.html#bird-eurbla-2026-08-27"
    )


def test_species_paths():
    assert urls.species_filename("eurbla") == "birds/eurbla.html"
    assert urls.species_url("eurbla") == "birds/eurbla.html"


def test_prefix_applies_to_relative_targets():
    assert urls.species_url("eurbla", "../") == "../birds/eurbla.html"
    assert urls.bucket_url("eurbla", "2026-08-27", "../").startswith("../archive-")


def test_feed_guid_keeps_its_own_legacy_prefix():
    # Already delivered to readers: changing it would resurface every
    # past item as new.
    assert urls.feed_guid("eurbla", "2026-08-27") == "bird-of-the-day-eurbla-2026-08-27"


def test_absolute_joins_with_a_single_slash():
    assert urls.absolute("https://x.es/", "birds/a.html") == "https://x.es/birds/a.html"
    assert urls.absolute("https://x.es", "birds/a.html") == "https://x.es/birds/a.html"
    assert urls.absolute("", "birds/a.html") == "birds/a.html"


def test_feed_full_file_is_a_sibling_of_the_feed():
    assert urls.FEED_FULL_FILE.endswith(".xml")
    assert urls.FEED_FULL_FILE != urls.FEED_FILE


def test_discoverability_filenames():
    assert urls.SITEMAP == "sitemap.xml"
    assert urls.ROBOTS == "robots.txt"
    assert urls.NOT_FOUND == "404.html"
