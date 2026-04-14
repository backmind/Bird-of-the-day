"""Scrape species description from public sources, language-aware.

Source chain (first match in the configured language wins):

  1. eBird species page → ``og:description`` with the catalog's eBird
     locale. Carries the Merlin identification text, translated when
     available. ``og:description`` is the source — the page has no
     ``__NEXT_DATA__`` block.
  2. Wikipedia REST summary in the catalog's subdomain. Follows taxonomic
     redirects automatically (e.g. ``Meliphaga fordiana`` →
     ``Microptilotis fordianus``).
  3. Birds of the World introduction paragraph in the configured language.

A separate Wikipedia URL probe also runs in the configured language with
an English fallback, so the rendered ``plate-foot`` always has a Wikipedia
link even when the description came from eBird.

Language detection (rejecting eBird/BoW text in the wrong language) goes
through ``i18n.matches_language``, which uses ``langid`` constrained to
the languages with a catalog file.

The page also requires cookies because of eBird's CAS gateway, so callers
should pass a ``Session`` shared with ``image_fetcher``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import requests
from bs4 import BeautifulSoup

from scripts import distribution_map, i18n
from scripts.image_fetcher import new_session

if TYPE_CHECKING:
    from scripts.i18n import Catalog

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

# Hard cap on the description shown to the reader. Applied uniformly after
# the source chain picks a winner. BoW intros can run to 2000+ chars and
# would otherwise dominate the hero layout. 700 chars is ~5-6 lines at the
# default body font size.
MAX_DESCRIPTION_CHARS = 700


def _truncate_at_sentence_boundary(
    text: str, max_chars: int = MAX_DESCRIPTION_CHARS
) -> str:
    """Trim ``text`` to ``max_chars`` at the last sentence boundary.

    If a sentence-ending punctuation mark is found in the upper 60% of the
    cut, the trim happens there. Otherwise we hard-cut on the last word
    boundary and append a horizontal ellipsis. The result never exceeds
    ``max_chars`` characters.
    """
    if not text or len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    floor = int(max_chars * 0.6)
    best = -1
    for boundary in (". ", "! ", "? ", "… ", ".\n", "!\n", "?\n"):
        idx = cut.rfind(boundary)
        if idx > best:
            best = idx + len(boundary) - 1  # keep the punctuation, drop the space
    if best >= floor:
        return cut[: best + 1].strip()
    # No clean sentence boundary high enough — hard cut on last word.
    word_cut = cut.rsplit(" ", 1)[0].strip()
    return word_cut + "…"

@dataclass
class SpeciesContent:
    description: str              # text in the target language, or ""
    description_source: str       # "ebird" | "wikipedia" | ""
    bow_intro: str
    taxonomy: dict
    wikipedia_summary: str = ""   # Wikipedia REST summary (always captured
                                  # when available, independent of description)
    wikipedia_url: str = ""       # canonical URL of the Wikipedia article
    wikipedia_language: str = ""  # "es" | "en" | "" (the lang we resolved to)
    fallback_text: str = ""       # rejected foreign-language text (e.g. EN
                                  # Merlin) preserved for the foreign_fallback
                                  # description policy
    fallback_language: str = ""   # ISO code of the rejected text, or ""
    gbif_taxon_key: int | None = None  # GBIF usageKey for the species, or None
                                       # when the match failed or wasn't attempted
    distribution_map_url: str = ""     # hot-linkable GBIF density map PNG URL,
                                       # or "" when no GBIF match was found


def _fetch_ebird_og_description(
    species_code: str, session: requests.Session, locale: str = "es"
) -> str:
    """Return the Merlin ID text from eBird's og:description meta tag."""
    url = f"https://ebird.org/species/{species_code}"
    try:
        resp = session.get(url, params={"locale": locale}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        logger.warning(
            "Failed to fetch eBird species page for %s", species_code, exc_info=True
        )
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")
    og = soup.find("meta", property="og:description")
    if og and og.get("content"):
        return og["content"].strip()
    return ""


def _fetch_wikipedia(
    scientific_name: str, language: str, session: requests.Session
) -> dict | None:
    """Look up a Wikipedia REST summary in the given language.

    Returns a ``{"extract": str, "url": str}`` dict on success, or ``None``
    if the article doesn't exist (404), is a disambiguation page, or the
    request fails. The REST summary endpoint follows taxonomic redirects
    automatically (e.g. ``Meliphaga fordiana`` → ``Microptilotis fordianus``).
    """
    if not scientific_name:
        return None
    title = scientific_name.replace(" ", "_")
    url = f"https://{language}.wikipedia.org/api/rest_v1/page/summary/{title}"
    try:
        resp = session.get(
            url,
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        logger.debug(
            "Wikipedia %s lookup failed for %s", language, scientific_name, exc_info=True
        )
        return None

    if data.get("type") == "disambiguation":
        return None
    extract = (data.get("extract") or "").strip()
    canonical_url = (
        data.get("content_urls", {}).get("desktop", {}).get("page", "")
    )
    if not canonical_url:
        return None
    return {"extract": extract, "url": canonical_url}


# Phrases that mark BoW promo/login banners (we want the real intro instead).
_BOW_BANNER_PHRASES = (
    "subscriber",
    "suscriptor",
    "sign in",
    "inicie sesión",
    "iniciar sesión",
    "full content is available",
    "recurso científico de acceso",
    "global alliance of nature organizations",
)


def _fetch_bow_intro(
    species_code: str, session: requests.Session, target_language: str
) -> str:
    """Return the public introduction text from Birds of the World.

    The result is filtered through ``i18n.matches_language``: if BoW
    served the wrong language (e.g. English when we asked for Spanish via
    Accept-Language but no translation exists), we drop it.
    """
    url = f"https://birdsoftheworld.org/bow/species/{species_code}/cur/introduction"
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        logger.debug("Failed to fetch BoW page for %s", species_code, exc_info=True)
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")
    collected: list[str] = []
    for p in soup.find_all("p"):
        # Real intro paragraphs are unstyled. Banners and promo blocks all
        # carry CSS classes.
        if p.get("class"):
            continue
        text = p.get_text(separator=" ", strip=True)
        if len(text) < 100:
            continue
        lowered = text.lower()
        if any(phrase in lowered for phrase in _BOW_BANNER_PHRASES):
            continue
        collected.append(text)
        if len(collected) >= 2:
            break

    intro = " ".join(collected)
    if intro and not i18n.matches_language(intro, target_language):
        return ""
    return intro


def scrape_species_content(
    species_code: str,
    scientific_name: str = "",
    catalog: "Catalog | None" = None,
    session: requests.Session | None = None,
    max_description_chars: int = MAX_DESCRIPTION_CHARS,
) -> SpeciesContent:
    """Run the source chain and return the best content in the target language.

    Also resolves the canonical Wikipedia URL — preferring the configured
    language, falling back to English. The URL is captured even when the
    description ends up coming from eBird, so the rendered ``plate-foot``
    can always link to Wikipedia.

    The ``catalog`` argument carries both the language identity and the
    eBird/Wikipedia mappings. If omitted, defaults to a Spanish catalog
    so the function remains usable as a standalone helper.
    """
    if catalog is None:
        catalog = i18n.Catalog.load("es")
    target_language = catalog.language
    ebird_locale = catalog.ebird_locale
    wiki_subdomain = catalog.wikipedia_subdomain

    sess = session or new_session()

    description = ""
    description_source = ""

    ebird_text = _fetch_ebird_og_description(
        species_code, sess, locale=ebird_locale
    )

    # Probe Wikipedia in the configured language once. We may use both the
    # extract (if eBird gave us nothing) and the URL (always).
    wiki_target = _fetch_wikipedia(scientific_name, wiki_subdomain, sess)

    # If eBird returned text but it doesn't match the target language, we
    # capture it for later use by the foreign_fallback policy. The render
    # layer decides whether to actually show it.
    fallback_text = ""
    fallback_language = ""

    if ebird_text and i18n.matches_language(ebird_text, target_language):
        description = ebird_text
        description_source = "ebird"
        logger.debug("eBird text matched %s for %s", target_language, species_code)
    else:
        if ebird_text:
            logger.info(
                "eBird text not in target language %s for %s, trying Wikipedia",
                target_language, species_code,
            )
            # Capture the rejected text for the foreign_fallback policy.
            # eBird Merlin in untranslated form is almost always English.
            fallback_text = ebird_text
            detected = i18n.detect_language(ebird_text)
            fallback_language = detected[0] if detected else "en"
        if wiki_target and wiki_target["extract"]:
            description = wiki_target["extract"]
            description_source = "wikipedia"
            logger.info(
                "Using Wikipedia %s summary for %s", wiki_subdomain, species_code
            )
        else:
            logger.info(
                "No %s source available for %s; description will be empty",
                target_language, species_code,
            )

    # Resolve the Wikipedia URL: prefer target language, fall back to English.
    wikipedia_url = ""
    wikipedia_language = ""
    if wiki_target:
        wikipedia_url = wiki_target["url"]
        wikipedia_language = wiki_subdomain
    elif wiki_subdomain != "en":
        wiki_en = _fetch_wikipedia(scientific_name, "en", sess)
        if wiki_en:
            wikipedia_url = wiki_en["url"]
            wikipedia_language = "en"
            logger.info("Wikipedia URL fallback → en for %s", species_code)

    # Always capture the Wikipedia summary for LLM context, even when
    # eBird won the description slot.
    wikipedia_summary = ""
    if wiki_target and wiki_target.get("extract"):
        wikipedia_summary = wiki_target["extract"]

    bow_intro = _fetch_bow_intro(species_code, sess, target_language)

    # GBIF distribution map. Best-effort: a failed lookup leaves the
    # map fields empty and the renderer skips the atlas section.
    gbif_taxon_key: int | None = None
    distribution_map_url = ""
    gbif_result = distribution_map.fetch_distribution(scientific_name, session=sess)
    if gbif_result is not None:
        gbif_taxon_key, distribution_map_url = gbif_result

    # Apply the layout rail uniformly to every source (including the
    # fallback text — it might end up rendered if foreign_fallback is on).
    raw_desc_len = len(description)
    description = _truncate_at_sentence_boundary(description, max_description_chars)
    raw_bow_len = len(bow_intro)
    bow_intro = _truncate_at_sentence_boundary(bow_intro, max_description_chars)
    fallback_text = _truncate_at_sentence_boundary(fallback_text, max_description_chars)
    wikipedia_summary = _truncate_at_sentence_boundary(wikipedia_summary, max_description_chars)
    if description and raw_desc_len != len(description):
        logger.info(
            "description: source=%s truncated %d → %d chars",
            description_source, raw_desc_len, len(description),
        )
    if bow_intro and raw_bow_len != len(bow_intro):
        logger.info(
            "bow_intro: truncated %d → %d chars", raw_bow_len, len(bow_intro)
        )

    return SpeciesContent(
        description=description,
        description_source=description_source,
        bow_intro=bow_intro,
        taxonomy={},
        wikipedia_summary=wikipedia_summary,
        wikipedia_url=wikipedia_url,
        wikipedia_language=wikipedia_language,
        fallback_text=fallback_text,
        fallback_language=fallback_language,
        gbif_taxon_key=gbif_taxon_key,
        distribution_map_url=distribution_map_url,
    )


def _content_cache_path(species_code: str, cache_dir: str) -> Path:
    return Path(cache_dir) / f"{species_code}.json"


def load_cached_content(
    species_code: str, cache_dir: str = "cache"
) -> SpeciesContent | None:
    path = _content_cache_path(species_code, cache_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Invalid content cache for %s, ignoring", species_code)
        return None
    return SpeciesContent(
        description=data.get("description", data.get("ebird_description", "")),
        description_source=data.get("description_source", ""),
        bow_intro=data.get("bow_intro", ""),
        taxonomy=data.get("taxonomy", {}),
        wikipedia_summary=data.get("wikipedia_summary", ""),
        wikipedia_url=data.get("wikipedia_url", ""),
        wikipedia_language=data.get("wikipedia_language", ""),
        fallback_text=data.get("fallback_text", ""),
        fallback_language=data.get("fallback_language", ""),
        gbif_taxon_key=data.get("gbif_taxon_key"),
        distribution_map_url=data.get("distribution_map_url", ""),
    )


def save_cached_content(
    species_code: str, content: SpeciesContent, cache_dir: str = "cache"
) -> None:
    """Cache the scrape result. Saves whenever ANY content was found so the
    next run doesn't re-probe."""
    if (
        not content.description
        and not content.bow_intro
        and not content.wikipedia_url
        and not content.fallback_text
        and not content.distribution_map_url
    ):
        return
    path = _content_cache_path(species_code, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(content), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
