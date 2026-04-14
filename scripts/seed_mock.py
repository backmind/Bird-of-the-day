#!/usr/bin/env python3
"""Developer-only: seed cache + history + regenerate site with mock birds.

NOT FOR PRODUCTION. NOT COMMITTED. Run from the repo root with `uv run`:

    uv run python -m scripts.seed_mock

Picks 3 species from a candidate list with the goal of maximizing description
state coverage (long / short / empty). Writes cache files, history.json, then
regenerates feed.xml + index.html + archive.html via the existing builders.

The candidate list includes a mix of well-translated Iberian species (long
state), known Wikipedia-stub fallbacks (short state), and a few recently-split
or obscure species that may end up with no Spanish content at all (empty state).
The script probes each candidate, prints the resulting description length, and
picks the first one that fits each target slot.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

from scripts import (
    content_scraper,
    ebird_client,
    feed_builder,
    i18n,
    image_fetcher,
    site_builder,
)
from scripts.generate import (
    BASE_DIR,
    CACHE_DIR,
    CONFIG_PATH,
    ENV_PATH,
    FEED_PATH,
    HISTORY_PATH,
    STATE_DIR,
    _build_site_entries,
    _load_dotenv,
    _load_secret_files,
    load_config,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seed_mock")

# (species_code, sciName, comName) — sciName must match Wikipedia ES title or
# a sci synonym that REST follows. comName is the Spanish display name.
# Order matters: probe top-down, classify each by description length.
CANDIDATES = [
    # Known long: rich Merlin ES + BoW ES → will hit the truncation rail.
    ("spaeag1", "Aquila adalberti", "Águila Imperial Ibérica"),
    ("eutdov", "Streptopelia turtur", "Tórtola Europea"),
    ("hoopoe", "Upupa epops", "Abubilla Común"),
    # Known short: eBird returns English, Wikipedia ES has a stub.
    ("kimhon1", "Meliphaga fordiana", "Mielero de Kimberley"),
    # Probable empty: obscure recent splits or non-Iberian endemics.
    ("nicuso1", "Otus alius", "Autillo de Nicobar"),
    ("yebcuc1", "Coccyzus americanus", "Cuclillo Piquigualdo"),
    ("rufmot1", "Baryphthengus martii", "Momoto Rufo"),
    ("molsta1", "Aplonis mysolensis", "Estornino de Mysol"),
    ("ducfly", "Empidonax oberholseri", "Mosquero Oscuro"),
]


def _classify_state(description: str) -> str:
    """Bucket a scraped description by length so we can target slot coverage."""
    n = len(description)
    if n == 0:
        return "empty"
    if n < 350:
        return "short"
    return "long"


def _seed_one(
    code: str, sci: str, com: str, session, catalog
) -> dict | None:
    """Run scraper + image fetch for one species. Return summary dict."""
    logger.info("--- probing %s (%s) ---", code, com)

    # Image
    img = image_fetcher.load_cached_image(code, str(CACHE_DIR))
    if img is None:
        img = image_fetcher.fetch_image(
            code, session=session, locale=catalog.ebird_locale
        )
        if img.url:
            image_fetcher.save_cached_image(code, img, str(CACHE_DIR))

    # Content
    content = content_scraper.load_cached_content(code, str(CACHE_DIR))
    if content is None:
        content = content_scraper.scrape_species_content(
            code, scientific_name=sci, catalog=catalog, session=session
        )
        content_scraper.save_cached_content(code, content, str(CACHE_DIR))

    state = _classify_state(content.description)
    logger.info(
        "  state=%-5s desc=%dc source=%-9s bow=%dc image=%s",
        state,
        len(content.description),
        content.description_source or "—",
        len(content.bow_intro),
        "✓" if img.url else "✗",
    )
    return {
        "code": code,
        "sci": sci,
        "com": com,
        "state": state,
        "description": content.description,
        "description_source": content.description_source,
        "bow_intro": content.bow_intro,
        "image": img,
    }


def _deep_probe_for_empty(session, taxonomy: list[dict], catalog, max_tries: int = 60):
    """Sample random species from the eBird taxonomy until one returns no
    target-language content from any source. Returns ``(code, sci, com)`` or ``None``.

    Wikipedia has very broad bird coverage, so this can take many tries.
    The probe is deterministic (seeded) so reruns produce the same candidate.
    """
    import random

    target_lang = catalog.language
    wiki_subdomain = catalog.wikipedia_subdomain
    ebird_locale = catalog.ebird_locale

    rng = random.Random(20260411)
    pool = [
        sp for sp in taxonomy
        if sp.get("speciesCode") and sp.get("sciName") and " " in sp.get("sciName", "")
    ]
    sample = rng.sample(pool, min(len(pool), max_tries))
    logger.info("deep-probing %d random species for empty state...", len(sample))

    for sp in sample:
        code = sp["speciesCode"]
        sci = sp["sciName"]
        com = sp.get("comName", code)

        # Cheap test first: Wikipedia in target language (single GET, no auth)
        try:
            wiki = content_scraper._fetch_wikipedia(sci, wiki_subdomain, session)
        except Exception:
            wiki = None
        if wiki and wiki.get("extract"):
            continue  # has wiki content in target lang, not what we want

        # Now check eBird (more expensive: cookie dance + scraping)
        try:
            ebird_text = content_scraper._fetch_ebird_og_description(
                code, session, locale=ebird_locale
            )
        except Exception:
            ebird_text = ""
        if ebird_text and i18n.matches_language(ebird_text, target_lang):
            continue  # eBird returned target-language text, not what we want

        logger.info("FOUND empty candidate: %s (%s) — %s", code, sci, com)
        return (code, sci, com)

    logger.warning("deep-probe exhausted %d candidates without finding an empty", len(sample))
    return None


def main() -> None:
    _load_dotenv(ENV_PATH)
    _load_secret_files()
    if "EBIRD_API_KEY" not in __import__("os").environ:
        logger.error("EBIRD_API_KEY missing — set it in .env")
        sys.exit(1)

    config = load_config()
    catalog = i18n.Catalog.load(config["language"])
    ebird_locale = config.get("ebird_locale") or catalog.ebird_locale
    session = image_fetcher.new_session(
        accept_language=catalog.accept_language_header
    )

    # Preload taxonomy index for order/family enrichment.
    try:
        ebird_client.get_full_taxonomy(locale=ebird_locale, cache_dir=CACHE_DIR)
    except Exception:
        logger.warning("Could not preload taxonomy", exc_info=True)

    # Probe candidates and bucket them.
    by_state: dict[str, list[dict]] = {"long": [], "short": [], "empty": []}
    for code, sci, com in CANDIDATES:
        result = _seed_one(code, sci, com, session, catalog)
        if result:
            by_state[result["state"]].append(result)
        # Stop early if we have at least one of each state.
        if by_state["long"] and by_state["short"] and by_state["empty"]:
            logger.info("State coverage achieved — stopping probe early.")
            break

    # If no empty was found in the hardcoded list, deep-probe random species
    # from the taxonomy until we find one with no target-language content.
    if not by_state["empty"]:
        taxonomy = ebird_client.get_full_taxonomy(
            locale=ebird_locale, cache_dir=CACHE_DIR
        )
        empty_candidate = _deep_probe_for_empty(
            session, taxonomy, catalog, max_tries=80
        )
        if empty_candidate:
            code, sci, com = empty_candidate
            result = _seed_one(code, sci, com, session, catalog)
            if result:
                by_state[result["state"]].append(result)

    # Pick one per state in priority order.
    picks: list[dict] = []
    for state in ("long", "short", "empty"):
        if by_state[state]:
            picks.append(by_state[state][0])

    # Fill any missing slots from the longest available bucket.
    while len(picks) < 3:
        for state in ("long", "short", "empty"):
            extra = [r for r in by_state[state] if r not in picks]
            if extra:
                picks.append(extra[0])
                break
        else:
            break

    if len(picks) < 3:
        logger.error("Could not pick 3 mock birds. Got: %s", picks)
        sys.exit(1)

    logger.info(
        "Picked: %s",
        " | ".join(f"{p['code']}({p['state']}, {len(p['description'])}c)" for p in picks),
    )

    # Newest first; the script writes history with most recent at the END
    # (because that matches how generate.py appends), so reverse.
    today = datetime.now(timezone.utc).date()
    dates = [today - timedelta(days=i) for i in (2, 1, 0)]
    # picks[0] = long → oldest, picks[2] = empty → newest? Or the other way?
    # We want the most visually interesting one as the HERO (today). The hero
    # is the *most recent* entry. The state we want as hero is "long" because
    # it stresses the layout the most. So order: short oldest, empty middle,
    # long newest.
    sorted_picks = sorted(
        picks,
        key=lambda p: {"short": 0, "empty": 1, "long": 2}[p["state"]],
    )

    # Build history
    history_entries = []
    for date, p in zip(dates, sorted_picks):
        history_entries.append(
            {
                "speciesCode": p["code"],
                "comName": p["com"],
                "sciName": p["sci"],
                "date": date.isoformat(),
                "imageUrl": p["image"].url,
                "photographer": p["image"].photographer,
                "attribution": p["image"].attribution,
            }
        )
    history = {"entries": history_entries}
    HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("history.json written: %d entries", len(history_entries))

    # Build feed entries (most recent first, RSS convention)
    feed_entries = []
    for date, p in reversed(list(zip(dates, sorted_picks))):
        taxonomy = ebird_client.lookup_taxonomy(p["code"]) or {}
        # Read wikipedia + GBIF fields from the cached content if present
        cached = content_scraper.load_cached_content(p["code"], str(CACHE_DIR))
        wiki_url = cached.wikipedia_url if cached else ""
        wiki_lang = cached.wikipedia_language if cached else ""
        gbif_key = cached.gbif_taxon_key if cached else None
        map_url = cached.distribution_map_url if cached else ""
        entry_html = feed_builder.build_entry_html(
            species_code=p["code"],
            common_name=p["com"],
            scientific_name=p["sci"],
            image_url=p["image"].url,
            image_attribution=p["image"].attribution,
            ml_search_url=p["image"].search_url,
            description=p["description"],
            description_source=p["description_source"],
            bow_intro=p["bow_intro"],
            taxonomy=taxonomy,
            catalog=catalog,
            wikipedia_url=wiki_url,
            wikipedia_language=wiki_lang,
            distribution_map_url=map_url,
            gbif_taxon_key=gbif_key,
            english_name_index={},
            code_to_localized={},
            published_anchors={},
        )
        pub = datetime.combine(date, datetime.min.time(), tzinfo=timezone.utc).replace(
            hour=7
        )
        feed_entries.append(
            feed_builder.FeedEntry(
                species_code=p["code"],
                common_name=p["com"],
                scientific_name=p["sci"],
                description_html=entry_html,
                image_url=p["image"].url,
                image_attribution=p["image"].attribution,
                ml_search_url=p["image"].search_url,
                pub_date=format_datetime(pub),
                guid=f"bird-of-the-day-{p['code']}-{date.isoformat()}",
            )
        )

    feed_xml = feed_builder.build_feed(feed_entries, config, catalog)
    feed_builder.write_feed(feed_xml, str(FEED_PATH))

    # Build site
    site_entries = _build_site_entries(
        history, description_policy=config.get("description_policy", "foreign_fallback")
    )
    site_builder.write_site(
        site_entries,
        STATE_DIR,
        catalog=catalog,
        feed_link=config.get("feed_link", ""),
    )

    logger.info("DONE.")
    logger.info("Inspect: index.html, archive.html, feed.xml")
    for p in sorted_picks:
        logger.info(
            "  %s [%s] desc=%dc source=%s",
            p["com"],
            p["state"],
            len(p["description"]),
            p["description_source"] or "—",
        )


if __name__ == "__main__":
    main()
