"""Tests for ebird_client deterministic selection helpers."""

from scripts.ebird_client import _date_seed, _pick_pool


def test_date_seed_deterministic():
    a = _date_seed("2026-04-13")
    b = _date_seed("2026-04-13")
    assert a == b


def test_date_seed_varies_by_date():
    a = _date_seed("2026-04-13")
    b = _date_seed("2026-04-14")
    assert a != b


def test_date_seed_varies_by_salt():
    a = _date_seed("2026-04-13", salt="pool1")
    b = _date_seed("2026-04-13", salt="pool2")
    assert a != b


def test_pick_pool_deterministic():
    pools = [
        {"id": "A", "weight": 1},
        {"id": "B", "weight": 1},
        {"id": "C", "weight": 1},
    ]
    result1 = _pick_pool(pools, "2026-04-13")
    result2 = _pick_pool(pools, "2026-04-13")
    assert result1["id"] == result2["id"]


def test_pick_pool_respects_weights():
    # Pool B has overwhelming weight — should (almost) always be picked.
    pools = [
        {"id": "A", "weight": 0},
        {"id": "B", "weight": 100},
    ]
    result = _pick_pool(pools, "2026-04-13")
    assert result["id"] == "B"
