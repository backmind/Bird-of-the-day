"""Ventana escalada, clamp por oferta y válvula de reciclaje."""

import math

from scripts.ebird_client import (
    WINDOW_SUPPLY_FRACTION,
    _effective_window,
    _rarity_score,
    _recency_order,
    _recycle_pool,
    _select_from_observations,
    _weighted_pick,
    scaled_window,
)


def test_recency_order_is_distinct_and_newest_first():
    # Publicado: a, b, a, c. La última vez de "a" es la tercera entrada,
    # así que va por delante de "b".
    assert _recency_order(["a", "b", "a", "c"]) == ["c", "a", "b"]


def test_recency_order_drops_empty_codes():
    assert _recency_order(["a", "", None, "b"]) == ["b", "a"]


def test_scaled_window_uses_the_configured_floor():
    assert scaled_window({"dedup_window": 50}, 40) == 50


def test_scaled_window_grows_with_the_archive():
    assert scaled_window({"dedup_window": 50}, 141) == 70


def test_effective_window_is_clamped_by_supply():
    # 70 pedidos contra un pool de 60: no puede bloquear más de 45.
    assert _effective_window(70, 60) == 45
    assert _effective_window(70, 60) == int(60 * WINDOW_SUPPLY_FRACTION)


def test_effective_window_passes_through_when_supply_is_ample():
    assert _effective_window(70, 200) == 70


def test_effective_window_never_goes_negative():
    assert _effective_window(70, 0) == 0


def test_rarity_bias_is_softened():
    # 1/sqrt en vez de 1/n: cien ejemplares pesan un décimo, no un céntimo.
    assert _rarity_score(100) == 0.1
    assert _rarity_score(1) == 1.0
    assert _rarity_score(0) == 1.0


def test_weighted_pick_is_deterministic():
    candidates = [
        {"speciesCode": "a", "total_count": 1},
        {"speciesCode": "b", "total_count": 1},
    ]
    first = _weighted_pick(candidates, "2026-04-13", "pool")
    second = _weighted_pick(candidates, "2026-04-13", "pool")
    assert first["speciesCode"] == second["speciesCode"]


def test_recycle_pool_takes_the_oldest_quarter():
    candidates = [{"speciesCode": c, "total_count": 1} for c in "abcdefgh"]
    # Recencia: "h" es la más reciente, "a" la más antigua.
    recency = list("hgfedcba")
    picked = [c["speciesCode"] for c in _recycle_pool(candidates, recency)]
    assert picked == ["a", "b"]


def test_recycle_pool_puts_never_published_species_first():
    candidates = [{"speciesCode": c, "total_count": 1} for c in "abcd"]
    recency = ["a", "b"]  # "c" y "d" no se han publicado nunca
    picked = [c["speciesCode"] for c in _recycle_pool(candidates, recency)]
    assert picked == ["c"]


def _obs(code, count=1):
    return {
        "speciesCode": code,
        "comName": code.title(),
        "sciName": f"Genus {code}",
        "howMany": count,
    }


def test_observations_exclude_the_blocked_window():
    observations = [_obs("a"), _obs("b"), _obs("c"), _obs("d")]
    # Ventana 2 sobre oferta 4: el clamp la deja en 3, bloquea c, b, a.
    result = _select_from_observations(
        observations, ["c", "b", "a"], 2, "2026-04-13", "madrid"
    )
    assert result["speciesCode"] == "d"


def test_observations_recycle_instead_of_giving_up():
    observations = [_obs("a"), _obs("b"), _obs("c"), _obs("d")]
    notes = []
    result = _select_from_observations(
        observations, ["d", "c", "b", "a"], 99, "2026-04-13", "madrid",
        notes=notes,
    )
    assert result["speciesCode"] in {"a", "b", "c", "d"}
    assert any("recycl" in note for note in notes)


def test_observations_note_the_clamp():
    notes = []
    _select_from_observations(
        [_obs("a"), _obs("b")], [], 99, "2026-04-13", "madrid", notes=notes
    )
    assert any("clamp" in note for note in notes)


def test_exclude_wins_over_everything():
    observations = [_obs("a"), _obs("b")]
    result = _select_from_observations(
        observations, [], 0, "2026-04-13", "madrid", exclude=frozenset({"a"})
    )
    assert result["speciesCode"] == "b"


def test_recycling_is_not_a_carousel():
    """Veinte días de pool agotado no pueden dar la rotación estricta.

    Es el defecto que mata la válvula ingenua: publicar siempre la de
    última publicación más antigua convierte el sitio en un carrusel de
    orden fijo.
    """
    codes = list("abcdefgh")
    observations = [_obs(c) for c in codes]
    recency = list(reversed(codes))  # "h" reciente, "a" antigua
    published = []
    for day in range(1, 21):
        date_str = f"2026-05-{day:02d}"
        result = _select_from_observations(
            observations, recency, 99, date_str, "madrid"
        )
        code = result["speciesCode"]
        published.append(code)
        recency = [code] + [c for c in recency if c != code]

    strict_rotation = [codes[i % len(codes)] for i in range(20)]
    assert published != strict_rotation
    # Una vez publicada, una especie pasa a ser la más reciente y no puede
    # volver al cuartil antiguo hasta que roten las demás.
    assert len(set(published[:4])) == 4
