"""The rarity bias knob: a configurable exponent, not a fixed rule."""

import math

from scripts.ebird_client import (
    DEFAULT_RARITY_BIAS,
    _rarity_score,
    _select_from_observations,
    rarity_bias,
)


def test_rarity_score_at_bias_zero_is_uniform():
    assert _rarity_score(100, 0) == 1.0
    assert _rarity_score(1, 0) == 1.0


def test_rarity_score_at_bias_half_is_the_soft_default():
    assert _rarity_score(100, 0.5) == 0.1
    assert _rarity_score(1, 0.5) == 1.0


def test_rarity_score_at_bias_one_is_a_plain_inverse():
    assert _rarity_score(100, 1) == 0.01
    assert _rarity_score(1, 1) == 1.0


def test_rarity_bias_returns_the_default_when_absent():
    assert rarity_bias({}) == DEFAULT_RARITY_BIAS


def test_rarity_bias_returns_the_configured_value():
    assert rarity_bias({"rarity_bias": 1}) == 1.0
    assert rarity_bias({"rarity_bias": -0.3}) == -0.3


def test_rarity_bias_zero_survives_a_naive_or_fallback():
    # A naive `config.get("rarity_bias") or DEFAULT_RARITY_BIAS` would
    # treat 0 as falsy and silently replace it with the default. 0 is a
    # legitimate, deliberate setting (a uniform draw) and must survive.
    assert rarity_bias({"rarity_bias": 0}) == 0.0


def test_rarity_bias_falls_back_on_nonsense(caplog):
    result = rarity_bias({"rarity_bias": "not-a-number"})
    assert result == DEFAULT_RARITY_BIAS
    assert any("rarity_bias" in r.message for r in caplog.records)


def test_rarity_bias_falls_back_on_none(caplog):
    result = rarity_bias({"rarity_bias": None})
    assert result == DEFAULT_RARITY_BIAS
    assert any("rarity_bias" in r.message for r in caplog.records)


def test_default_bias_matches_the_pre_2026_08_formula():
    """An instance that does not set the key keeps today's behaviour.

    Today's behaviour, before this knob existed, was a hardcoded inverse
    square root. ``DEFAULT_RARITY_BIAS`` must reproduce it exactly, not
    just approximately, so a silent instance sees no change at all.
    """
    assert DEFAULT_RARITY_BIAS == 0.5
    for count in (1, 2, 3, 17, 100, 999, 1_234_567):
        assert _rarity_score(count, DEFAULT_RARITY_BIAS) == 1.0 / math.sqrt(count)


def _obs(code, count):
    return {
        "speciesCode": code,
        "comName": code.title(),
        "sciName": f"Genus {code}",
        "howMany": count,
    }


def test_bias_zero_is_really_uniform():
    """Bias 0 draws a species that the default bias would never reach.

    Two candidates whose counts differ by six orders of magnitude: under
    the default bias (0.5) "common" is so heavily discounted that it
    never wins the draw across this whole sweep of dates. Under bias 0
    every candidate scores 1.0 regardless of count, so both species come
    up. The sweep is deterministic: every draw goes through the same
    date-seeded RNG as production, no randomness is introduced by the
    test itself.
    """
    observations = [_obs("rare", 1), _obs("common", 1_000_000)]
    dates = [f"2026-{(i // 28) % 12 + 1:02d}-{(i % 28) + 1:02d}" for i in range(40)]

    seen_uniform = {
        _select_from_observations(observations, [], 0, date, 0, "pool")["speciesCode"]
        for date in dates
    }
    assert seen_uniform == {"rare", "common"}

    seen_default = {
        _select_from_observations(
            observations, [], 0, date, DEFAULT_RARITY_BIAS, "pool"
        )["speciesCode"]
        for date in dates
    }
    assert seen_default == {"rare"}
