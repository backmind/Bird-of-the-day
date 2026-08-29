"""GBIF distribution map lookups.

Two responsibilities:

1. **Taxon match** — given a scientific name, ask GBIF's species match
   endpoint for its ``usageKey`` (the taxon key GBIF uses to index
   occurrences). Returns ``None`` when the species is unknown to GBIF
   or the lookup fails.

2. **Map URL construction** — given a taxon key, build the URL of a
   single hex-binned PNG world tile from GBIF's occurrence density map
   service. The image is hot-linked from the site, never cached locally,
   per the deployment decision in v1.1.0.

The hex-bin parameter is what makes occurrences visible at world zoom:
without it, the raw points are too sparse to render at all. The PNG
served at this URL is a 1024×1024 mercator tile with translucent
hexagons coloured by occurrence count. Mercator drops the polar caps
(roughly above 85°N and below 85°S), which is acceptable because
virtually no bird species lives only in those bands.

GBIF docs: https://www.gbif.org/developer/maps
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

GBIF_MATCH_URL = "https://api.gbif.org/v1/species/match"
GBIF_MAP_TEMPLATE = (
    "https://api.gbif.org/v2/map/occurrence/density/0/0/0@2x.png"
    "?taxonKey={key}&bin=hex&hexPerTile=75&style=classic.poly"
)
GBIF_SPECIES_PAGE_TEMPLATE = "https://www.gbif.org/species/{key}"

# Match states persisted in the content cache. MATCH_NONE is an
# authoritative "GBIF does not know this name" (never retried);
# MATCH_ERROR is a transient failure (retried by the backfill step).
MATCH_OK = "matched"
MATCH_NONE = "none"
MATCH_ERROR = "error"


def gbif_taxon_match_ex(
    scientific_name: str, session: requests.Session | None = None
) -> tuple[int | None, str]:
    """Like :func:`gbif_taxon_match` but reports HOW the match failed."""
    if not scientific_name:
        return None, MATCH_NONE

    sess = session or requests.Session()
    try:
        resp = sess.get(
            GBIF_MATCH_URL,
            params={"name": scientific_name},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        match_type = data.get("matchType", "")
        confidence = int(data.get("confidence", 0))
        # Reject NONE matches and very low-confidence guesses; accept
        # EXACT, FUZZY, and HIGHERRANK as long as confidence is reasonable
        # and the match rank is checked below (HIGHERRANK can land above
        # species, e.g. on the genus, which is rejected separately).
        if match_type == "NONE" or confidence < 80:
            logger.info(
                "GBIF match for %r rejected: matchType=%s confidence=%d",
                scientific_name, match_type, confidence,
            )
            return None, MATCH_NONE

        rank = data.get("rank", "")
        if rank and rank != "SPECIES":
            logger.info(
                "GBIF match for %r rejected: rank=%s (a genus-level match "
                "would map the whole genus)", scientific_name, rank,
            )
            return None, MATCH_NONE

        # Prefer ``usageKey`` (which follows synonym redirects) over
        # ``speciesKey``. Both should usually agree for accepted names.
        key = data.get("usageKey") or data.get("speciesKey")
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        # A non-dict JSON body (list, scalar) or an unparseable field
        # reaches here too: treat it as transient, same as a network
        # error, rather than letting it escape as an unhandled exception.
        logger.debug(
            "GBIF taxon match errored for %s", scientific_name, exc_info=True
        )
        return None, MATCH_ERROR

    if not isinstance(key, int) or key <= 0:
        return None, MATCH_NONE

    logger.info(
        "GBIF taxon match: %r -> usageKey=%d (matchType=%s, confidence=%d)",
        scientific_name, key, match_type, confidence,
    )
    return key, MATCH_OK


def gbif_taxon_match(
    scientific_name: str, session: requests.Session | None = None
) -> int | None:
    """Look up a GBIF ``usageKey`` for a scientific name.

    Returns the integer ``usageKey`` on a successful EXACT or FUZZY
    match (status ``ACCEPTED`` or ``SYNONYM``), or ``None`` when the
    species is not found, the API errors out, or the match confidence
    is too low to trust.

    Back-compat wrapper over :func:`gbif_taxon_match_ex`.
    """
    return gbif_taxon_match_ex(scientific_name, session=session)[0]


def gbif_map_url(taxon_key: int) -> str:
    """Build a hot-linkable GBIF density map PNG URL for a taxon.

    The result is a 1024×1024 mercator world tile with hex-binned
    occurrence density. Hot-linked directly from GBIF's CDN — never
    cached or downloaded by this project per the v1.1.0 deployment
    decision.
    """
    return GBIF_MAP_TEMPLATE.format(key=taxon_key)


def gbif_species_page_url(taxon_key: int) -> str:
    """Return the canonical GBIF species page URL for a taxon."""
    return GBIF_SPECIES_PAGE_TEMPLATE.format(key=taxon_key)


BIRDLIFE_FACTSHEET_TEMPLATE = (
    "https://datazone.birdlife.org/species/factsheet/{taxon_id}"
)


def fetch_iucn_category(
    taxon_key: int, session: requests.Session | None = None
) -> tuple[str, str, str] | None:
    """Fetch the IUCN Red List category for a GBIF taxon key.

    Returns ``(code, category, birdlife_url)`` on success, or ``None``
    when the lookup fails or the species has no IUCN assessment.
    ``code`` is the short code (e.g. ``"LC"``), ``category`` the full
    English label (e.g. ``"LEAST_CONCERN"``).
    """
    sess = session or requests.Session()
    url = f"https://api.gbif.org/v1/species/{taxon_key}/iucnRedListCategory"
    try:
        resp = sess.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        logger.debug("IUCN lookup failed for taxon %d", taxon_key, exc_info=True)
        return None

    code = data.get("code", "")
    category = data.get("category", "")
    # GBIF sometimes returns versioned IDs like "22735687_1"; BirdLife
    # only accepts the base ID without the suffix. The field is not always
    # a string (unversioned IDs come back as ints), hence the str() coercion.
    iucn_taxon_id = str(data.get("iucnTaxonID", "") or "").split("_")[0]
    if not code:
        return None

    birdlife_url = ""
    if iucn_taxon_id:
        birdlife_url = BIRDLIFE_FACTSHEET_TEMPLATE.format(taxon_id=iucn_taxon_id)

    logger.info("IUCN for taxon %d: %s (%s)", taxon_key, code, category)
    return code, category, birdlife_url


def fetch_distribution(
    scientific_name: str, session: requests.Session | None = None
) -> tuple[int, str] | None:
    """Look up the GBIF taxon and return ``(taxon_key, map_url)``.

    Convenience helper for the scrape pipeline: combines
    :func:`gbif_taxon_match` and :func:`gbif_map_url` and returns
    ``None`` when the taxon match fails.
    """
    key = gbif_taxon_match(scientific_name, session=session)
    if key is None:
        return None
    return key, gbif_map_url(key)


def fetch_distribution_ex(
    scientific_name: str, session: requests.Session | None = None
) -> tuple[int | None, str, str]:
    """Return ``(taxon_key, map_url, match_state)``."""
    key, state = gbif_taxon_match_ex(scientific_name, session=session)
    if key is None:
        return None, "", state
    return key, gbif_map_url(key), state
