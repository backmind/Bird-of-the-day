"""Ventana escalada y clamp por oferta: el clamp es la válvula."""

from scripts.ebird_client import (
    WINDOW_SUPPLY_FRACTION,
    _effective_window,
    _rarity_score,
    _recency_order,
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
    assert _rarity_score(100, 0.5) == 0.1
    assert _rarity_score(1, 0.5) == 1.0
    assert _rarity_score(0, 0.5) == 1.0


def test_weighted_pick_is_deterministic():
    candidates = [
        {"speciesCode": "a", "total_count": 1},
        {"speciesCode": "b", "total_count": 1},
    ]
    first = _weighted_pick(candidates, "2026-04-13", 0.5, "pool")
    second = _weighted_pick(candidates, "2026-04-13", 0.5, "pool")
    assert first["speciesCode"] == second["speciesCode"]


def _obs(code, count=1):
    return {
        "speciesCode": code,
        "comName": code.title(),
        "sciName": f"Genus {code}",
        "howMany": count,
    }


def test_select_from_observations_never_empties_for_any_supply():
    """The clamp is the valve, so this property must never regress.

    Pinned through the real selection function, not by re-deriving
    ``_effective_window``'s arithmetic (that arithmetic already has its
    own unit tests above): for every supply size, with a recency list
    that covers every candidate and a window far larger than the supply,
    a species always comes back, and it always belongs to the pool.
    """
    for supply in (1, 3, 4, 8, 60, 200):
        codes = [f"sp{i}" for i in range(supply)]
        observations = [_obs(c) for c in codes]
        recency = list(reversed(codes))  # covers every candidate
        result = _select_from_observations(
            observations, recency, supply * 100, "2026-04-13", 0.5, "madrid"
        )
        assert result is not None
        assert result["speciesCode"] in set(codes)


def test_select_from_observations_returns_none_when_exclude_empties_the_survivors():
    """Exclude is applied after the window, on the pool's real supply.

    The window here leaves only "sp0" and "sp1" standing; excluding both
    of them (a skip-policy re-roll that already tried them) legitimately
    empties the eligible set. The function must not paper over that by
    shrinking supply to make room -- it returns ``None`` so the caller's
    global-taxonomy rescue takes over.
    """
    codes = [f"sp{i}" for i in range(8)]
    observations = [_obs(c) for c in codes]
    recency = list(reversed(codes))
    exclude = frozenset(codes[:-1])  # only the last species is left
    result = _select_from_observations(
        observations, recency, 800, "2026-04-13", 0.5, "madrid", exclude=exclude
    )
    assert result is None


def test_supply_is_measured_before_exclude_not_after():
    """Supply is what the pool offers today, not what survives exclude.

    A skip-policy re-roll's exclude must not shrink supply -- and with it
    the clamped window -- on every retry: that is exactly the
    contamination the dedup window was built to remove. The clamp note
    (and the effective window it reports) must be identical whether or
    not species have already been excluded.
    """
    codes = [f"sp{i}" for i in range(8)]
    observations = [_obs(c) for c in codes]
    recency = list(reversed(codes))  # every candidate has been published
    notes_bare: list[str] = []
    notes_excluded: list[str] = []
    _select_from_observations(
        observations, recency, 800, "2026-04-13", 0.5, "madrid", notes=notes_bare
    )
    _select_from_observations(
        observations, recency, 800, "2026-04-13", 0.5, "madrid",
        exclude=frozenset(codes[:5]), notes=notes_excluded,
    )
    clamp_bare = next(n for n in notes_bare if "clamped" in n)
    clamp_excluded = next(n for n in notes_excluded if "clamped" in n)
    assert clamp_bare == clamp_excluded
    assert "offers 8 species today" in clamp_bare


def test_observations_window_two_leaves_only_a_and_d_eligible():
    observations = [_obs("a"), _obs("b"), _obs("c"), _obs("d")]
    # Ventana 2 sobre oferta 4: effective = min(2, int(4 * 0.75) = 3) = 2,
    # sin clamp. Bloqueados los dos mas recientes, c y b; elegibles a y d.
    dates = [f"2026-04-{day:02d}" for day in range(1, 15)]
    results = {
        _select_from_observations(
            observations, ["c", "b", "a"], 2, date, 0.5, "madrid"
        )["speciesCode"]
        for date in dates
    }
    assert results == {"a", "d"}


def test_observations_window_three_forces_d_with_no_draw():
    observations = [_obs("a"), _obs("b"), _obs("c"), _obs("d")]
    # Ventana 3 sobre oferta 4: effective = min(3, int(4 * 0.75) = 3) = 3,
    # bloquea c, b y a; solo queda d, sin necesidad de sorteo.
    result = _select_from_observations(
        observations, ["c", "b", "a"], 3, "2026-04-13", 0.5, "madrid"
    )
    assert result["speciesCode"] == "d"


def test_observations_note_the_republication_instead_of_giving_up():
    observations = [_obs("a"), _obs("b"), _obs("c"), _obs("d")]
    notes = []
    result = _select_from_observations(
        observations, ["d", "c", "b", "a"], 99, "2026-04-13", 0.5, "madrid",
        notes=notes,
    )
    # Never a rescue: the pick still comes from this pool's own species.
    assert result["speciesCode"] in {"a", "b", "c", "d"}
    assert any("offers no species outside the dedup window" in note for note in notes)


def test_observations_no_clamp_note_on_an_empty_history():
    """A brand new instance must not print a misleading clamp note.

    Supply 2 against window 99 clamps effective to 1 whether or not
    anything has ever been published, but with an empty history nothing
    is actually blocked either way: recency[:1] and recency[:99] are
    both empty. The note is an early warning that the archive is
    catching up with the pool, and on day one it has not.
    """
    notes = []
    _select_from_observations(
        [_obs("a"), _obs("b")], [], 99, "2026-04-13", 0.5, "madrid", notes=notes
    )
    assert not any("clamp" in note for note in notes)


def test_observations_note_the_clamp_when_it_genuinely_bites():
    """The clamp note fires once there is more history than it can hold."""
    notes = []
    _select_from_observations(
        [_obs("a"), _obs("b")], ["a", "b"], 99, "2026-04-13", 0.5, "madrid",
        notes=notes,
    )
    assert any("clamp" in note for note in notes)


def test_exclude_wins_over_everything():
    observations = [_obs("a"), _obs("b")]
    result = _select_from_observations(
        observations, [], 0, "2026-04-13", 0.5, "madrid", exclude=frozenset({"a"})
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
            observations, recency, 99, date_str, 0.5, "madrid"
        )
        code = result["speciesCode"]
        published.append(code)
        recency = [code] + [c for c in recency if c != code]

    strict_rotation = [codes[i % len(codes)] for i in range(20)]
    assert published != strict_rotation
    # Una vez publicada, una especie pasa a ser la más reciente y no puede
    # volver al cuartil antiguo hasta que roten las demás.
    assert len(set(published[:4])) == 4
