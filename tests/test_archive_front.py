"""The archive front is a directory of months, not an endless scroll: its
weight has to stay flat as the history grows."""

import re

import pytest

from scripts import archive_builder, site_builder, urls
from scripts.i18n import Catalog
from tests.test_archive_buckets import _entry  # shared fixture helper


@pytest.fixture
def ctx():
    return site_builder.RenderContext(catalog=Catalog.load("en"), feed_link="")


@pytest.fixture
def entries():
    return [
        _entry("c", "2026-08-02", 4),
        _entry("b", "2026-08-01", 3),
        _entry("a", "2026-07-31", 2),
        _entry("z", "2025-12-30", 1),
    ]


def test_front_shows_the_current_month_as_cards(ctx, entries):
    html = archive_builder.build_archive_front(entries, ctx)
    assert 'href="birds/c.html"' in html
    assert 'href="birds/b.html"' in html
    # Cards, not plates: no full description, no anchor ids.
    assert 'id="bird-c-2026-08-02"' not in html


def test_front_lists_every_month_with_a_count(ctx, entries):
    html = archive_builder.build_archive_front(entries, ctx)
    assert 'href="archive-2026-08.html"' in html
    assert 'href="archive-2026-07.html"' in html
    assert 'href="archive-2025-12.html"' in html
    assert "August" in html and "December" in html
    assert "2025" in html and "2026" in html


def test_front_weight_does_not_grow_with_history(ctx, entries):
    small = archive_builder.build_archive_front(entries[:2], ctx)
    padded = entries[:2] + [
        _entry(f"x{n}", f"2025-{(n % 12) + 1:02d}-01", n) for n in range(200)
    ]
    large = archive_builder.build_archive_front(padded, ctx)
    # 200 extra entries in past months add month rows, never plates.
    assert len(large) < len(small) * 2


def test_legacy_anchor_shim_is_present_and_targets_the_bucket(ctx, entries):
    html = archive_builder.build_archive_front(entries, ctx)
    # Matched by its payload, not by "the script tag": the theme-boot
    # script in <head> has the same shape and comes first.
    assert "location.replace('archive-'" in html
    assert "/^#bird-" in html


def test_shim_pattern_matches_the_anchor_format_the_site_emits(ctx, entries):
    html = archive_builder.build_archive_front(entries, ctx)
    # Both halves of the contract, asserted together: the anchors the
    # site publishes, and the pattern the shim looks for.
    assert re.match(
        r"^bird-[a-z0-9]+-\d{4}-\d{2}-\d{2}$", urls.entry_anchor("eurbla", "2026-08-27")
    )
    assert r"/^#bird-[a-z0-9]+-(\d{4}-\d{2})-\d{2}$/" in html


def test_empty_history_renders_the_empty_notice(ctx):
    html = archive_builder.build_archive_front([], ctx)
    assert "archive is empty" in html.lower()
    assert html.startswith("<!DOCTYPE html>")
