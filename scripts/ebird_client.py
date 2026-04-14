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

logger = logging.getLogger(__name__)

BASE_URL = "https://api.ebird.org/v2"
REQUEST_TIMEOUT = 30
TAXONOMY_TTL_DAYS = 30

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
        "maxResults": 200,
        "locale": locale,
    }
    try:
        resp = requests.get(
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
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Invalid taxonomy cache at %s, ignoring", path)
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
    resp = requests.get(url, headers=_headers(), params=params, timeout=120)
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
    resp = requests.get(url, headers=_headers(), params=params, timeout=120)
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
    history_codes: set[str],
    date_str: str,
    pool_id: str,
) -> dict | None:
    """Aggregate observations by species and pick one with rarity bias."""
    species_map: dict[str, dict] = {}
    for obs in observations:
        code = obs.get("speciesCode")
        if not code or code in history_codes:
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

    candidates = list(species_map.values())
    # Inverse-howMany rarity bias: rarer species get higher weight.
    scores = [1.0 / c["total_count"] for c in candidates]
    seed = _date_seed(date_str, salt=pool_id)
    rng = random.Random(seed)
    selected = rng.choices(candidates, weights=scores, k=1)[0]
    return {
        "speciesCode": selected["speciesCode"],
        "comName": selected["comName"],
        "sciName": selected["sciName"],
    }


def _select_from_taxonomy(
    taxonomy: list[dict], history_codes: set[str], date_str: str
) -> dict | None:
    filtered = [
        sp for sp in taxonomy if sp.get("speciesCode") and sp["speciesCode"] not in history_codes
    ]
    if not filtered:
        filtered = taxonomy
    seed = _date_seed(date_str, salt="global")
    rng = random.Random(seed)
    sp = rng.choice(filtered)
    return {
        "speciesCode": sp["speciesCode"],
        "comName": sp.get("comName", sp["speciesCode"]),
        "sciName": sp.get("sciName", ""),
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
    history_codes: set[str],
    date_str: str,
    back: int,
    locale: str,
    cache_dir: Path | None,
) -> dict | None:
    pool_type = pool["type"]
    if pool_type in ("regional", "europe_random"):
        region = _get_region_for_pool(pool, date_str)
        logger.info("Pool %s → region %s", pool["id"], region)
        observations = get_recent_observations(region, back=back, locale=locale)
        if not observations:
            logger.warning("No observations returned for region %s", region)
            return None
        return _select_from_observations(observations, history_codes, date_str, pool["id"])

    if pool_type == "global_taxonomy":
        logger.info("Pool %s → global taxonomy", pool["id"])
        try:
            taxonomy = get_full_taxonomy(locale=locale, cache_dir=cache_dir)
        except requests.RequestException:
            logger.exception("Failed to fetch global taxonomy")
            return None
        return _select_from_taxonomy(taxonomy, history_codes, date_str)

    logger.warning("Unknown pool type: %s", pool_type)
    return None


def select_species(
    config: dict,
    history_codes: list[str],
    date_str: str,
    cache_dir: Path | None = None,
) -> dict:
    """Select the bird of the day.

    Picks one weighted pool by date hash, queries it, and dedupes against
    history. If that single attempt yields nothing (network error, empty
    region, or every candidate already used), falls back **once** to the
    global taxonomy pool — never an exhaustive cascade per plan §3.4.
    """
    pools = config["pools"]
    back = config.get("back_days", 14)
    locale = config.get("ebird_locale", "es")
    history_set = set(history_codes)

    # Load taxonomy upfront so we can enrich the final pick regardless of pool.
    try:
        get_full_taxonomy(locale=locale, cache_dir=cache_dir)
    except requests.RequestException:
        logger.warning("Could not preload taxonomy; family/order may be missing")

    chosen_pool = _pick_pool(pools, date_str)
    logger.info("Selected pool: %s (weight=%s)", chosen_pool["id"], chosen_pool["weight"])

    result = _select_from_pool(
        chosen_pool, history_set, date_str, back, locale, cache_dir
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
        rescue_pool, history_set, date_str, back, locale, cache_dir
    )
    if result:
        return _enrich_with_taxonomy(result)

    raise RuntimeError(
        "Could not select a species from any pool. Check EBIRD_API_KEY and network."
    )
