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


from scripts import ebird_client
from scripts.ebird_client import MAX_POOL_SPECIES, select_species


def _obs(code, count=1):
    return {
        "speciesCode": code,
        "comName": code.title(),
        "sciName": f"Genus {code}",
        "howMany": count,
    }


CONFIG = {
    "pools": [{"id": "madrid", "region": "ES-MD", "weight": 1, "type": "regional"}],
    "dedup_window": 2,
    "back_days": 14,
}


def _patch_region(monkeypatch, observations):
    monkeypatch.setattr(
        ebird_client, "get_recent_observations", lambda *a, **k: observations
    )
    monkeypatch.setattr(ebird_client, "get_full_taxonomy", lambda **k: [])
    monkeypatch.setattr(ebird_client, "lookup_taxonomy", lambda code: {})


def test_max_pool_species_is_what_we_ask_for(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return []

    def fake_get(url, headers=None, params=None, timeout=None):
        captured.update(params)
        return _Resp()

    monkeypatch.setattr(ebird_client._session, "get", fake_get)
    monkeypatch.setenv("EBIRD_API_KEY", "x")
    ebird_client.get_recent_observations("ES-MD")
    assert captured["maxResults"] == MAX_POOL_SPECIES
    assert MAX_POOL_SPECIES == 1000


def test_select_species_blocks_the_recent_window(monkeypatch):
    """Window 2 over a supply of 4 blocks "c" and "b", the two most
    recently published, and leaves "a" and "d" eligible.

    A single date's result cannot tell an off-by-one window apart from a
    correct one: for this fixture "d" happens to win the weighted draw
    on windows 1, 2 and 3 alike, so pinning one date and one species
    would pass even if the window boundary were wrong. Checking across
    many dates instead makes the boundary itself the assertion: no
    result may ever be one of the blocked species, and the other
    eligible species ("a") has to be reachable too, not just "d".
    """
    _patch_region(monkeypatch, [_obs("a"), _obs("b"), _obs("c"), _obs("d")])
    dates = [f"2026-04-{day:02d}" for day in range(1, 29)]
    results = {
        select_species(CONFIG, ["a", "b", "c"], date)["speciesCode"]
        for date in dates
    }
    assert results.isdisjoint({"b", "c"})
    assert results == {"a", "d"}


def test_select_species_honours_exclude(monkeypatch):
    _patch_region(monkeypatch, [_obs("a"), _obs("b")])
    result = select_species(CONFIG, [], "2026-04-13", exclude=frozenset({"a"}))
    assert result["speciesCode"] == "b"


def test_select_species_republishes_inside_the_pool(monkeypatch):
    """Un pool agotado devuelve una suya, no un ave global cualquiera."""
    _patch_region(monkeypatch, [_obs("a"), _obs("b")])
    monkeypatch.setattr(
        ebird_client, "get_full_taxonomy",
        lambda **k: [{"speciesCode": "zzz", "comName": "Z", "sciName": "Z z"}],
    )
    notes = []
    result = select_species(CONFIG, ["a", "b"] * 40, "2026-04-13", notes=notes)
    assert result["speciesCode"] in {"a", "b"}
    assert any("offers no species outside the dedup window" in note for note in notes)


def test_select_species_is_deterministic(monkeypatch):
    _patch_region(monkeypatch, [_obs(c) for c in "abcdefgh"])
    first = select_species(CONFIG, [], "2026-04-13")
    second = select_species(CONFIG, [], "2026-04-13")
    assert first["speciesCode"] == second["speciesCode"]
