"""eBird API v2 client and species selection logic."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from scripts.http_client import build_session

logger = logging.getLogger(__name__)

# Shared session for all eBird API calls: retries on 429/5xx with backoff.
_session = build_session()

BASE_URL = "https://api.ebird.org/v2"
REQUEST_TIMEOUT = 30
TAXONOMY_TTL_DAYS = 30

MAX_POOL_SPECIES = 1000
"""Species a pool may offer in a day.

The endpoint returns one record per species, so this is a species count,
not an observation count. It used to be 200, which is fewer species than
Spain reports in a fortnight: the dedup window was on course to outgrow
the supply and turn every regional day into a recycled one.
"""

# Module-level cache; populated lazily from disk or the network.
_taxonomy_cache: list[dict] | None = None
_taxonomy_index: dict[str, dict] | None = None

# Separate English-locale taxonomy used by the name linker to find
# English species names in description text and replace them with the
# configured-locale names. Cached independently.
_en_name_index: dict[str, str] | None = None  # English comName → speciesCode


def get_api_key() -> str:
    key = os.environ.get("EBIRD_API_KEY", "")
    if not key:
        logger.error("EBIRD_API_KEY environment variable is not set")
        sys.exit(1)
    return key


def _headers() -> dict[str, str]:
    return {"x-ebirdapitoken": get_api_key()}


def get_recent_observations(
    region: str, back: int = 14, locale: str = "es"
) -> list[dict]:
    """Recent species-level observations for a region. Empty list on error."""
    url = f"{BASE_URL}/data/obs/{region}/recent"
    params = {
        "back": back,
        "cat": "species",
        "hotspot": "false",
        "includeProvisional": "false",
        "maxResults": MAX_POOL_SPECIES,
        "locale": locale,
    }
    try:
        resp = _session.get(
            url, headers=_headers(), params=params, timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        logger.warning("HTTP %s from %s", e.response.status_code, url)
        return []
    except (requests.RequestException, ValueError) as e:
        logger.warning("Error fetching %s: %s", url, e)
        return []


def _taxonomy_cache_path(cache_dir: Path) -> Path:
    return cache_dir / "taxonomy.json"


def _load_taxonomy_from_disk(
    path: Path, locale: str
) -> list[dict] | None:
    """Load a taxonomy cache file, validating locale and TTL."""
    from scripts import load_json_cache
    data = load_json_cache(path, f"taxonomy cache at {path}")
    if data is None:
        return None

    if data.get("locale") != locale:
        logger.info("Taxonomy cache locale mismatch at %s, will refetch", path)
        return None

    fetched_at = data.get("fetched_at")
    if not fetched_at:
        return None
    try:
        ts = datetime.fromisoformat(fetched_at)
    except ValueError:
        return None
    age_days = (datetime.now(timezone.utc) - ts).days
    if age_days > TAXONOMY_TTL_DAYS:
        logger.info("Taxonomy cache expired (%d days old), will refetch", age_days)
        return None

    species = data.get("species") or []
    if not isinstance(species, list) or not species:
        return None
    logger.info("Loaded taxonomy from cache (%d species, %d days old)", len(species), age_days)
    return species


def _save_taxonomy_to_disk(
    species: list[dict], path: Path, locale: str
) -> None:
    """Write a taxonomy cache file with locale and timestamp metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "locale": locale,
        "species": species,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def get_full_taxonomy(
    locale: str = "es", cache_dir: Path | None = None
) -> list[dict]:
    """Return the full eBird taxonomy, using a disk cache with monthly TTL."""
    global _taxonomy_cache, _taxonomy_index
    if _taxonomy_cache is not None:
        return _taxonomy_cache

    if cache_dir is not None:
        path = _taxonomy_cache_path(cache_dir)
        disk = _load_taxonomy_from_disk(path, locale)
        if disk is not None:
            _taxonomy_cache = disk
            _taxonomy_index = {sp["speciesCode"]: sp for sp in disk if sp.get("speciesCode")}
            return _taxonomy_cache

    logger.info("Fetching full taxonomy from eBird API (locale=%s)", locale)
    url = f"{BASE_URL}/ref/taxonomy/ebird"
    params = {"fmt": "json", "locale": locale, "cat": "species"}
    resp = _session.get(url, headers=_headers(), params=params, timeout=120)
    resp.raise_for_status()
    species = resp.json()
    _taxonomy_cache = species
    _taxonomy_index = {
        sp["speciesCode"]: sp for sp in species if sp.get("speciesCode")
    }
    if cache_dir is not None:
        _save_taxonomy_to_disk(species, _taxonomy_cache_path(cache_dir), locale)
    return _taxonomy_cache


def _en_taxonomy_cache_path(cache_dir: Path) -> Path:
    return cache_dir / "taxonomy-en.json"


def get_english_name_index(cache_dir: Path | None = None) -> dict[str, str]:
    """Return an English comName → speciesCode mapping.

    Loads the English taxonomy from ``cache/taxonomy-en.json`` (fetching
    from the eBird API with ``locale=en`` if not cached or expired).
    Independent from the main taxonomy loaded by :func:`get_full_taxonomy`.
    """
    global _en_name_index
    if _en_name_index is not None:
        return _en_name_index

    if cache_dir is not None:
        species = _load_taxonomy_from_disk(
            _en_taxonomy_cache_path(cache_dir), locale="en"
        )
        if species is not None:
            _en_name_index = {
                sp["comName"]: sp["speciesCode"]
                for sp in species
                if sp.get("comName") and sp.get("speciesCode")
            }
            return _en_name_index

    logger.info("Fetching English taxonomy from eBird API")
    url = f"{BASE_URL}/ref/taxonomy/ebird"
    params = {"fmt": "json", "locale": "en", "cat": "species"}
    resp = _session.get(url, headers=_headers(), params=params, timeout=120)
    resp.raise_for_status()
    species = resp.json()
    _en_name_index = {
        sp["comName"]: sp["speciesCode"]
        for sp in species
        if sp.get("comName") and sp.get("speciesCode")
    }

    if cache_dir is not None:
        _save_taxonomy_to_disk(
            species, _en_taxonomy_cache_path(cache_dir), locale="en"
        )

    logger.info("English name index: %d entries", len(_en_name_index))
    return _en_name_index


def lookup_taxonomy(species_code: str) -> dict:
    """Return order/family/etc. for a species code, if taxonomy was loaded."""
    if _taxonomy_index is None:
        return {}
    sp = _taxonomy_index.get(species_code)
    if not sp:
        return {}
    return {
        k: sp[k]
        for k in (
            "order",
            "familyComName",
            "familySciName",
            "familyCode",
            "comName",
            "sciName",
        )
        if sp.get(k)
    }


def get_code_to_localized() -> dict[str, str]:
    """Return speciesCode → localized comName from the loaded taxonomy.

    Must be called after :func:`get_full_taxonomy` has populated the
    module-level index. Returns an empty dict if the taxonomy hasn't
    been loaded yet.
    """
    if not _taxonomy_index:
        return {}
    return {
        code: sp["comName"]
        for code, sp in _taxonomy_index.items()
        if sp.get("comName")
    }


def get_sciname_index() -> dict[str, str]:
    """Return lowercase sciName → canonical sciName from the loaded taxonomy.

    Used by the name linker to italicise binomial names in descriptions.
    Only includes binomial names (genus + epithet, i.e. names containing
    a space).
    """
    if not _taxonomy_index:
        return {}
    result: dict[str, str] = {}
    for sp in _taxonomy_index.values():
        sci = sp.get("sciName", "")
        if sci and " " in sci:
            result[sci.lower()] = sci
    return result


def _date_seed(date_str: str, salt: str = "") -> int:
    return int(hashlib.sha256((date_str + salt).encode()).hexdigest(), 16)


WINDOW_SUPPLY_FRACTION = 0.75


def _note(notes: list[str] | None, message: str) -> None:
    """Log a selection diagnostic and, when asked, hand it to the caller.

    The daily run turns these into report lines: the roadmap's rule is
    that degradation is visible, and a pool running out of unpublished
    species is exactly the kind of thing that used to happen in silence.
    """
    logger.info(message)
    if notes is not None:
        notes.append(message)


def _recency_order(published_codes: list[str]) -> list[str]:
    """Distinct species, most recently published first.

    ``published_codes`` arrives oldest first, repeats included, exactly as
    history stores it. Walking it backwards and keeping each code's first
    sighting gives the one ordering the dedup window and its clamp need.
    A species never published is absent from the result: it is infinitely
    old, so it is always eligible and always ahead of anything that has
    been published.
    """
    seen: set[str] = set()
    order: list[str] = []
    for code in reversed(published_codes):
        if code and code not in seen:
            seen.add(code)
            order.append(code)
    return order


def scaled_window(config: dict, history_len: int) -> int:
    """Dedup window that grows with the archive.

    Measured in entries rather than distinct species on purpose: counting
    distinct species would feed back on itself, because more repeats would
    slow the window's growth and cause more repeats.
    """
    floor = int(config.get("dedup_window", config.get("max_history", 50)))
    return max(floor, history_len // 2)


def _effective_window(window: int, supply: int) -> int:
    """The window a pool can actually afford today.

    The window scales with the archive, so on a long enough history it
    would name every species a pool is able to produce and leave the day
    with nothing to publish. Never blocking more than
    ``WINDOW_SUPPLY_FRACTION`` of today's supply keeps a quarter of the
    pool eligible no matter how long the archive gets.
    """
    return max(min(window, int(supply * WINDOW_SUPPLY_FRACTION)), 0)


DEFAULT_RARITY_BIAS = 0.5
"""Default strength of the rarity bias applied by :func:`_rarity_score`.

The value is the exponent in ``1 / count ** bias``, and it is a scale
rather than a fixed rule: 0 turns the draw uniform, with no rarity bias
at all, so every eligible species is equally likely. 0.5 is this
project's default: a soft bias that nudges the draw towards rarer
species without letting a single sighting dominate it. 1 is the strong
inverse-count bias the project used before 2026-08. A negative value
inverts the bias, favouring the most abundant species instead of the
rarest. How strong a bias reads as "right" is a matter of taste per
instance, hence the knob.
"""


def rarity_bias(config: dict) -> float:
    """Read the configured rarity bias, falling back to the default.

    ``config.json`` can hold a real JSON number, but a hand-edited file
    can hold anything: a string, ``null``, a typo. Anything that cannot
    be read as a float falls back to :data:`DEFAULT_RARITY_BIAS` with a
    warning rather than raising. The key's absence is handled
    separately from a present-but-invalid value: ``0`` is a legitimate,
    deliberate setting (a uniform draw), so this cannot use
    ``config.get("rarity_bias") or DEFAULT_RARITY_BIAS``, which would
    silently replace a configured ``0`` with the default.
    """
    if "rarity_bias" not in config:
        return DEFAULT_RARITY_BIAS
    value = config["rarity_bias"]
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning(
            "invalid rarity_bias=%r in config, using default %s",
            value, DEFAULT_RARITY_BIAS,
        )
        return DEFAULT_RARITY_BIAS


def _rarity_score(total_count: int, bias: float) -> float:
    """Selection weight for one candidate: ``1 / count ** bias``.

    ``bias`` is the knob documented at :data:`DEFAULT_RARITY_BIAS`: 0
    makes every candidate score 1.0 (a uniform draw), 1 is a plain
    inverse count, and the project's default of 0.5 is an inverse
    square root. The default is soft rather than a plain inverse
    because the candidate list runs to a thousand species, most of
    them reported once, and a linear inverse would let those single
    sightings swallow the draw against species with a hundred or more
    records.
    """
    return 1.0 / (max(total_count, 1) ** bias)


def _weighted_pick(
    candidates: list[dict], date_str: str, bias: float, salt: str
) -> dict:
    """The rarity-weighted, date-seeded draw shared by every path."""
    scores = [_rarity_score(c.get("total_count", 1), bias) for c in candidates]
    rng = random.Random(_date_seed(date_str, salt=salt))
    return rng.choices(candidates, weights=scores, k=1)[0]


def _clamp_and_pick(
    candidates: list[dict],
    recency: list[str],
    window: int,
    date_str: str,
    bias: float,
    salt: str,
    label: str,
    exclude: frozenset[str] = frozenset(),
    notes: list[str] | None = None,
) -> dict | None:
    """Clamp the dedup window to supply, then pick with rarity bias.

    Shared by every pool type so the clamp note, the exhaustion note, and
    the weighted draw exist in exactly one place. Two call sites drifted
    once already (the taxonomy path silently dropped the clamp note);
    this is the fix for that class of bug, not just this one instance.

    ``candidates`` must be non-empty; callers check that first, since an
    empty pool is a "no observations at all" case, not a clamp/valve one.
    ``label`` names the pool in the notes ("pool madrid", "the world
    list"); ``salt`` seeds the draw and is kept distinct per pool so
    today's picks do not change.

    ``exclude`` is a skip-policy re-roll's already-tried codes, not part
    of what the pool offers: it is applied only after the window has
    picked the eligible set, never folded into ``candidates`` or
    ``supply``. Folding it in earlier would shrink supply, and therefore
    the clamped window, on every retry for a reason that has nothing to
    do with today's dedup pressure. Returns ``None`` when ``exclude``
    empties what the window left standing, so the caller's rescue path
    can take over instead of failing here.
    """
    supply = len(candidates)
    effective = _effective_window(window, supply)
    # The clamp is only worth reporting when it actually blocked fewer
    # species than the raw window would have: when there are more
    # previously published species than the clamped window can hold. A
    # brand new instance with an empty history has nothing in `recency`
    # at all, so `effective < window` is true on its very first run while
    # the clamp costs nothing -- recency[:effective] and recency[:window]
    # are both empty either way. The note is meant to be the early
    # warning that the archive is catching up with the pool, not noise on
    # day one.
    if effective < window and len(recency) > effective:
        _note(
            notes,
            f"dedup window clamped from {window} to {effective}: "
            f"{label} offers {supply} species today",
        )

    # Blocking only the most recently published `effective` species, where
    # `effective <= WINDOW_SUPPLY_FRACTION * supply`, always leaves the
    # least recently published quarter (or more) standing, never-published
    # species among them first. That is the valve: there is no second path
    # to fall back to, because the clamp already is one.
    blocked = set(recency[:effective])
    eligible = [
        c for c in candidates
        if c["speciesCode"] not in blocked and c["speciesCode"] not in exclude
    ]

    # Exhaustion is a pure diagnostic here, not a branch: it flags the rare
    # case where the raw, unclamped window would have blocked every species
    # this pool offers today. It changes nothing about which candidates are
    # eligible, and it must not claim more than that: this fires inside one
    # attempt, and under the skip policy a later re-roll can still land on
    # a debut from a different pool. The run report's own republished:
    # line, read back from history, is what tells the true story.
    raw_blocked = set(recency[:window])
    if all(c["speciesCode"] in raw_blocked for c in candidates):
        _note(
            notes,
            f"{label} offers no species outside the dedup window",
        )

    if not eligible:
        return None
    return _weighted_pick(eligible, date_str, bias, salt)


def _pick_pool(pools: list[dict], date_str: str) -> dict:
    seed = _date_seed(date_str)
    rng = random.Random(seed)
    weights = [p["weight"] for p in pools]
    return rng.choices(pools, weights=weights, k=1)[0]


def _get_region_for_pool(pool: dict, date_str: str) -> str | None:
    pool_type = pool["type"]
    if pool_type == "regional":
        return pool["region"]
    if pool_type == "europe_random":
        seed = _date_seed(date_str, salt=pool["id"])
        rng = random.Random(seed)
        return rng.choice(pool["countries"])
    return None  # global_taxonomy


def _select_from_observations(
    observations: list[dict],
    recency: list[str],
    window: int,
    date_str: str,
    bias: float,
    pool_id: str,
    exclude: frozenset[str] = frozenset(),
    notes: list[str] | None = None,
) -> dict | None:
    """Aggregate observations by species and pick one with rarity bias.

    The window is applied here, not by the caller, because clamping it
    needs to know how many species this pool actually offers today, and
    that is only known once the region has answered.

    ``exclude`` never enters the aggregation: supply is what the pool
    offers today, full stop, and folding a skip-policy re-roll's
    already-tried codes into it here would shrink supply, and therefore
    the clamped window, on every retry. It is applied downstream, in
    ``_clamp_and_pick``, after the window has picked its eligible set.
    """
    species_map: dict[str, dict] = {}
    for obs in observations:
        code = obs.get("speciesCode")
        if not code:
            continue
        if code not in species_map:
            species_map[code] = {
                "speciesCode": code,
                "comName": obs.get("comName", code),
                "sciName": obs.get("sciName", ""),
                "total_count": 0,
            }
        species_map[code]["total_count"] += max(obs.get("howMany") or 1, 1)

    if not species_map:
        return None

    selected = _clamp_and_pick(
        list(species_map.values()), recency, window, date_str, bias,
        salt=pool_id, label=f"pool {pool_id}", exclude=exclude, notes=notes,
    )
    if selected is None:
        return None
    return {
        "speciesCode": selected["speciesCode"],
        "comName": selected["comName"],
        "sciName": selected["sciName"],
    }


def _select_from_taxonomy(
    taxonomy: list[dict],
    recency: list[str],
    window: int,
    date_str: str,
    bias: float,
    exclude: frozenset[str] = frozenset(),
    notes: list[str] | None = None,
) -> dict | None:
    """Pick from the world list under the same clamped window as a pool.

    Every species weighs the same here: the world list carries no counts,
    so there is no rarity to bias towards. With eleven thousand species
    the clamp never binds in practice, but it stays wired so this pool
    cannot quietly develop rules of its own.
    """
    candidates = [
        {
            "speciesCode": sp["speciesCode"],
            "comName": sp.get("comName", sp["speciesCode"]),
            "sciName": sp.get("sciName", ""),
            "total_count": 1,
        }
        for sp in taxonomy
        if sp.get("speciesCode")
    ]
    if not candidates:
        return None

    # `exclude` goes to the helper rather than being folded in above, for
    # the same reason it does on the observations path: it must not change
    # the measured supply, and therefore must not move the clamp.
    selected = _clamp_and_pick(
        candidates, recency, window, date_str, bias,
        salt="global", label="the world list", exclude=exclude, notes=notes,
    )
    if selected is None:
        return None
    return {
        "speciesCode": selected["speciesCode"],
        "comName": selected["comName"],
        "sciName": selected["sciName"],
    }


def _enrich_with_taxonomy(species: dict) -> dict:
    """Augment a selection with order/family info from the taxonomy index.

    ``comName`` and ``sciName`` are always overwritten from the
    taxonomy index, which was fetched with the configured locale. The
    observations endpoint does not reliably localise species names for
    regions outside the locale's language area (e.g. ``locale=es`` +
    region ``NO`` still returns English names), so the taxonomy is the
    only reliable source of the localised common name.
    """
    extra = lookup_taxonomy(species["speciesCode"])
    for key, value in extra.items():
        if key in ("comName", "sciName"):
            # Always overwrite — taxonomy is the locale-authoritative source.
            species[key] = value
        elif not species.get(key):
            species[key] = value
    return species


def _select_from_pool(
    pool: dict,
    recency: list[str],
    window: int,
    date_str: str,
    bias: float,
    back: int,
    locale: str,
    cache_dir: Path | None,
    exclude: frozenset[str] = frozenset(),
    notes: list[str] | None = None,
) -> dict | None:
    pool_type = pool["type"]
    if pool_type in ("regional", "europe_random"):
        region = _get_region_for_pool(pool, date_str)
        logger.info("Pool %s → region %s", pool["id"], region)
        observations = get_recent_observations(region, back=back, locale=locale)
        if not observations:
            logger.warning("No observations returned for region %s", region)
            return None
        return _select_from_observations(
            observations, recency, window, date_str, bias, pool["id"],
            exclude=exclude, notes=notes,
        )

    if pool_type == "global_taxonomy":
        logger.info("Pool %s → global taxonomy", pool["id"])
        try:
            taxonomy = get_full_taxonomy(locale=locale, cache_dir=cache_dir)
        except requests.RequestException:
            logger.exception("Failed to fetch global taxonomy")
            return None
        return _select_from_taxonomy(
            taxonomy, recency, window, date_str, bias,
            exclude=exclude, notes=notes,
        )

    logger.warning("Unknown pool type: %s", pool_type)
    return None


def select_species(
    config: dict,
    published_codes: list[str],
    date_str: str,
    cache_dir: Path | None = None,
    exclude: frozenset[str] = frozenset(),
    notes: list[str] | None = None,
) -> dict:
    """Select the bird of the day.

    ``published_codes`` is the whole publication history as species codes,
    oldest first, repeats included. Everything the selection needs is
    derived from it: which species the dedup window blocks, and how long
    each has been away when the pool runs out and one has to come back.

    ``exclude`` is rejected outright, before the window and the clamp. It
    carries the codes a skip-policy re-roll has already tried today.

    Picks one weighted pool by date hash and queries it. The clamp keeps
    the pool's own least recently published quarter eligible rather than
    let it come up empty, so the single global-taxonomy rescue below is
    left for the cases it was really meant for: a network error, or a
    region that answered with nothing at all.
    """
    pools = config["pools"]
    back = config.get("back_days", 14)
    locale = config.get("ebird_locale", "es")
    bias = rarity_bias(config)
    recency = _recency_order(published_codes)
    window = scaled_window(config, len(published_codes))

    # Load taxonomy upfront so we can enrich the final pick regardless of pool.
    try:
        get_full_taxonomy(locale=locale, cache_dir=cache_dir)
    except requests.RequestException:
        logger.warning("Could not preload taxonomy; family/order may be missing")

    chosen_pool = _pick_pool(pools, date_str)
    logger.info("Selected pool: %s (weight=%s)", chosen_pool["id"], chosen_pool["weight"])

    result = _select_from_pool(
        chosen_pool, recency, window, date_str, bias, back, locale, cache_dir,
        exclude=exclude, notes=notes,
    )
    if result:
        return _enrich_with_taxonomy(result)

    # Single rescue attempt: global taxonomy.
    logger.warning(
        "Pool %s yielded no candidate; falling back to global taxonomy",
        chosen_pool["id"],
    )
    rescue_pool = next(
        (p for p in pools if p["type"] == "global_taxonomy"), None
    )
    if rescue_pool is None:
        rescue_pool = {"id": "rescue", "type": "global_taxonomy"}

    result = _select_from_pool(
        rescue_pool, recency, window, date_str, bias, back, locale, cache_dir,
        exclude=exclude, notes=notes,
    )
    if result:
        return _enrich_with_taxonomy(result)

    raise RuntimeError(
        "Could not select a species from any pool. Check EBIRD_API_KEY and network."
    )
