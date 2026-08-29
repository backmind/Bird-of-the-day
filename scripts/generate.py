#!/usr/bin/env python3
"""Bird of the Day — Daily RSS Feed + Static Site generator.

Orchestrates species selection, image lookup, content scraping, RSS feed
construction, and the static index.html / archive.html pages. Idempotent
within a single UTC day: if today's bird is already in history, no new
entry is published. Maintenance still runs on every invocation, so a
later tick can heal past entries and republish feed and site.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

import requests

from scripts import (
    archive_builder,
    backfill,
    content_scraper,
    ebird_client,
    feed_builder,
    i18n,
    image_fetcher,
    llm_enricher,
    map_composer,
    run_report,
    site_builder,
    urls,
)

BASE_DIR = Path(__file__).resolve().parent.parent

# Mutable state lives under STATE_DIR. When BOTD_STATE_DIR is unset (local
# development, GitHub Actions) it equals BASE_DIR and behavior is identical
# to the pre-Docker layout. When set (typically in the container, where it
# points at the mounted volume) the cache and generated files are written
# under that directory while CONFIG_PATH and ENV_PATH stay anchored to the
# code in /app.
STATE_DIR = Path(os.environ.get("BOTD_STATE_DIR", str(BASE_DIR)))

# Code-anchored (read-only, baked in container image)
CONFIG_PATH = BASE_DIR / "data" / "config.json"
CONFIG_EXAMPLE_PATH = BASE_DIR / "data" / "config.example.json"
ENV_PATH = BASE_DIR / ".env"

# State-anchored (written at runtime, lives on the volume in Docker).
# The two feed files deliberately have no constants here: both are
# derived from the ``state_dir`` handed to _rebuild_feed, so the paths
# it reads and the path it writes can never point at different places.
CACHE_DIR = STATE_DIR / "cache"
MAPS_DIR = STATE_DIR / "maps"
HISTORY_PATH = STATE_DIR / "history.json"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so local runs don't need an extra dependency.

    Existing environment variables always win, so CI (where the secret comes
    from the runner environment) is unaffected.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# Names that can be supplied via a *_FILE env var pointing at a file whose
# contents are the actual secret. Standard Docker / Kubernetes secrets
# convention (mirrors how postgres, mariadb, nginx and other "official"
# images handle secrets).
_SECRET_FILE_KEYS: tuple[str, ...] = ("EBIRD_API_KEY", "BOTD_LLM_API_KEY")


def _load_secret_files() -> None:
    """Inject secrets from `*_FILE` env vars into the matching env var.

    For each key in :data:`_SECRET_FILE_KEYS`, if ``{KEY}_FILE`` is set
    and ``KEY`` itself is not, read the file at the path and use its
    stripped contents as the value of ``KEY``. Existing env vars always
    win, so a user can still override with ``-e KEY=...`` directly.
    """
    for key in _SECRET_FILE_KEYS:
        file_var = f"{key}_FILE"
        path = os.environ.get(file_var)
        if path and key not in os.environ:
            try:
                os.environ[key] = Path(path).read_text(encoding="utf-8").strip()
            except OSError as e:
                logger.warning(
                    "%s set but couldn't read %s: %s", file_var, path, e
                )


def _as_bool(value: str) -> bool:
    """Parse an env var as a flag.

    ``bool("0")`` is True, so the plain type casters in the table below
    cannot be reused for flags.
    """
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _config_flag(config: dict, key: str) -> bool:
    """Read a boolean config value that may have been hand-edited.

    ``config.json`` can hold a real JSON boolean, but a hand-edited file
    often holds the string ``"false"``, and ``bool("false")`` is True.
    Strings go through the same parser the env overrides use; every other
    type keeps Python's own truthiness, so a real ``false`` is still
    false and a missing key is still false.
    """
    value = config.get(key, False)
    return _as_bool(value) if isinstance(value, str) else bool(value)


# Scalar config keys that may be overridden by environment variables. The
# table maps an env var name to (config key, caster). Env vars override the
# JSON file value when present, so users can ship the default
# ``data/config.json`` baked in the container and tweak individual knobs
# with ``-e BOTD_LANGUAGE=fr`` etc. Complex nested structures (like
# ``pools``) are intentionally not env-var-able — mount a custom file
# instead.
_ENV_OVERRIDES: dict[str, tuple[str, Callable[[str], object]]] = {
    "BOTD_LANGUAGE": ("language", str),
    "BOTD_EBIRD_LOCALE": ("ebird_locale", str),
    "BOTD_DESCRIPTION_POLICY": ("description_policy", str),
    "BOTD_MAX_SKIP_RETRIES": ("max_skip_retries", int),
    "BOTD_DEDUP_WINDOW": ("dedup_window", int),
    "BOTD_MAX_FEED_ENTRIES": ("max_feed_entries", int),
    "BOTD_BACK_DAYS": ("back_days", int),
    "BOTD_BACKFILL_LIMIT": ("backfill_limit", int),
    "BOTD_FEED_LINK": ("feed_link", str),
    "BOTD_FEED_REBUILD_ALL": ("feed_rebuild_all", _as_bool),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    """Load and normalize the project config.

    Migrations applied for back-compat with pre-i18n configs:

    - If ``language`` is missing, derive it from the legacy ``ebird_locale``
      field (or default to ``es``) and log a warning.
    - If the configured ``language`` doesn't have a catalog file, fall back
      to ``i18n.DEFAULT_FALLBACK`` (English) and warn.
    - Strip ``_*_help`` documentation keys so they don't pollute downstream.
    """
    path = CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_EXAMPLE_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))

    # Drop documentation-only keys (start with underscore by convention)
    config = {k: v for k, v in raw.items() if not k.startswith("_")}

    if "language" not in config:
        legacy = config.get("ebird_locale") or "es"
        derived = legacy.split("_")[0].split("-")[0] if isinstance(legacy, str) else "es"
        logger.warning(
            "config.json missing 'language'; derived %s from legacy ebird_locale=%s",
            derived, legacy,
        )
        config["language"] = derived

    # Apply BOTD_* env-var overrides for scalar config keys. This lets a
    # container user tweak individual knobs without mounting a custom
    # config.json. Complex nested structures (pools) are not overridable;
    # mount a custom file instead.
    for env_name, (key, caster) in _ENV_OVERRIDES.items():
        raw_value = os.environ.get(env_name)
        if raw_value is None or raw_value == "":
            continue
        try:
            config[key] = caster(raw_value)
            logger.info("config override from env: %s = %r", key, config[key])
        except (ValueError, TypeError) as e:
            logger.warning(
                "ignoring %s=%r (cast to %s failed: %s)",
                env_name, raw_value, caster.__name__, e,
            )

    if "content_mode" in config:
        logger.warning(
            "config key 'content_mode' is deprecated and ignored; the "
            "pipeline enriches via LLM whenever one is configured"
        )
        config.pop("content_mode")

    known = i18n.discover_languages()
    if known and config["language"] not in known:
        logger.warning(
            "config language %r has no catalog file; falling back to %s",
            config["language"], i18n.DEFAULT_FALLBACK,
        )
        config["language"] = i18n.DEFAULT_FALLBACK

    return config


def load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {"entries": []}
    return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))


def save_history(history: dict) -> None:
    HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _apply_description_policy(
    content: content_scraper.SpeciesContent,
    description_policy: str,
) -> tuple[str, str]:
    """Derive effective description and source after applying the policy.

    Returns ``(description, description_source)``. The ``foreign_fallback``
    policy substitutes the rejected foreign-language text when no
    target-language description is available.
    """
    desc = content.description
    source = content.description_source
    if not desc and description_policy == "foreign_fallback" and content.fallback_text:
        desc = content.fallback_text
        source = "ebird-foreign"
    return desc, source


def _publication_context(raw_entries: list[dict]) -> list[tuple[int, str]]:
    """Per history entry, ``(ordinal, previous publication date)``.

    The ordinal is how many times the species had already been published
    before this entry, so a debut is 0. The date is the previous
    publication's, or empty when there is none. Both are derived from
    history rather than stored in it: nothing to migrate, and nothing that
    can drift out of sync with the entries it describes.
    """
    context: list[tuple[int, str]] = []
    seen: dict[str, tuple[int, str]] = {}
    for raw in raw_entries:
        code = raw.get("speciesCode") or ""
        count, last_date = seen.get(code, (0, ""))
        context.append((count, last_date))
        if code:
            seen[code] = (count + 1, raw.get("date", ""))
    return context


def _republished_note(
    raw_entries: list[dict], species_code: str, common_name: str
) -> str:
    """Report line for a species that has been published before.

    Empty on a debut, which is the overwhelming majority of runs: a line
    that appears every day is a line nobody reads.
    """
    dates = [
        e.get("date", "")
        for e in raw_entries
        if e.get("speciesCode") == species_code and e.get("date")
    ]
    if not dates:
        return ""
    return f"republished: {common_name} last appeared on {dates[-1]}"


def _entries_newest_first(raw_entries: list[dict]):
    """History newest first, each entry with its publication facts.

    Yields ``(raw, publication_number, ordinal, previous_date)``. The
    context is aligned to history in publication order while both callers
    walk it backwards, so the index mapping lives here once rather than
    being re-derived at every call site.
    """
    context = _publication_context(raw_entries)
    total = len(raw_entries)
    for i, raw in enumerate(reversed(raw_entries)):
        number = total - i
        ordinal, previous_date = context[number - 1]
        yield raw, number, ordinal, previous_date


def _seen_asset_ids(raw_entries: list[dict], species_code: str) -> frozenset[str]:
    """Photographs this species has already been published with."""
    ids = (
        image_fetcher.asset_id_from_url(e.get("imageUrl"))
        for e in raw_entries
        if e.get("speciesCode") == species_code
    )
    return frozenset(i for i in ids if i)


def _image_for(raw: dict, code: str, ordinal: int) -> image_fetcher.ImageResult:
    """The photograph a history entry was published with.

    Prefers the per-publication cache, which carries the asset id and the
    search URL. Falls back to what history recorded, the only source for
    entries published before photographs were cached per publication.
    """
    cached = image_fetcher.load_cached_image(code, str(CACHE_DIR), ordinal=ordinal)
    if cached is not None:
        return cached
    return image_fetcher.ImageResult(
        url=raw.get("imageUrl"),
        asset_id=None,
        photographer=raw.get("photographer", ""),
        attribution=raw.get(
            "attribution", "Macaulay Library / Cornell Lab of Ornithology"
        ),
        search_url=image_fetcher.ml_search_url(code),
    )


def _build_site_entries(
    history: dict, description_policy: str = "foreign_fallback"
) -> list[site_builder.SiteEntry]:
    """Reconstruct rich SiteEntry objects from history + per-species caches.

    Iterates history in reverse so the most recent bird is first in the list.
    Missing caches degrade gracefully to empty fields. The
    ``description_policy`` argument controls how empty descriptions are
    handled: ``foreign_fallback`` substitutes the rejected foreign text,
    ``strict`` (and ``skip`` from this rendering perspective) leaves them
    empty so the layout shows the em-dash placeholder. Each entry's
    publication ordinal and previous publication date are derived from the
    whole history and threaded into ``SiteEntry.previous_date``.
    """
    entries: list[site_builder.SiteEntry] = []
    cache_dir = str(CACHE_DIR)
    raw_entries = history.get("entries", [])
    for raw, publication_number, ordinal, previous_date in _entries_newest_first(
        raw_entries
    ):
        code = raw.get("speciesCode")
        if not code:
            continue

        image = _image_for(raw, code, ordinal)

        content = content_scraper.load_cached_content(code, cache_dir)
        if content is None:
            content = content_scraper.SpeciesContent(
                description="", description_source="", bow_intro="", taxonomy={}
            )

        # Apply description policy at render time so a config change is
        # picked up on the next site build without re-scraping.
        effective_description, effective_source = _apply_description_policy(
            content, description_policy
        )

        # Taxonomy may live in either the cache or the global taxonomy index
        taxonomy = content.taxonomy or ebird_client.lookup_taxonomy(code) or {}

        enriched = llm_enricher.load_cached_enrichment(code, cache_dir)

        entries.append(
            site_builder.SiteEntry(
                species_code=code,
                common_name=raw.get("comName", code),
                scientific_name=raw.get("sciName", ""),
                date=raw.get("date", ""),
                image_url=image.url,
                photographer=image.photographer,
                attribution=image.attribution,
                description=effective_description,
                description_source=effective_source,
                bow_intro=content.bow_intro,
                taxonomy=taxonomy,
                ml_search_url=image.search_url,
                number=publication_number,
                wikipedia_url=content.wikipedia_url,
                wikipedia_language=content.wikipedia_language,
                fallback_language=content.fallback_language,
                gbif_taxon_key=content.gbif_taxon_key,
                distribution_map_url=content.distribution_map_url,
                iucn_code=content.iucn_code,
                iucn_birdlife_url=content.iucn_birdlife_url,
                enriched_prose=enriched.prose if enriched else "",
                enriched_identification=enriched.identification if enriched else None,
                previous_date=previous_date,
            )
        )
    return entries


def _build_indexes(
    history: dict, feed_link: str, ebird_locale: str
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Build cross-reference indexes for the name linker.

    Returns ``(code_to_localized, published_anchors, published_anchors_abs)``.
    ``published_anchors`` maps each species to its canonical page (never a
    dated archive anchor, so the link never rots as new plates are
    published); ``published_anchors_abs`` prepends the ``feed_link`` base
    so RSS readers can resolve them.

    ``ebird_locale`` must be the resolved locale for the run. This function
    can be the first taxonomy load of a run, and ``get_full_taxonomy``
    caches both in-process and on disk keyed by locale, so omitting it
    would populate those caches with the default Spanish taxonomy.
    """
    # Ensure the taxonomy is loaded (may not be if we're rebuilding
    # without going through the full selection pipeline).
    ebird_client.get_full_taxonomy(locale=ebird_locale, cache_dir=CACHE_DIR)
    code_to_localized = ebird_client.get_code_to_localized()

    published_anchors: dict[str, str] = {}
    published_anchors_abs: dict[str, str] = {}
    for h in history["entries"]:
        hc = h["speciesCode"]
        published_anchors[hc] = urls.species_url(hc)
        published_anchors_abs[hc] = urls.absolute(feed_link, urls.species_url(hc))

    return code_to_localized, published_anchors, published_anchors_abs


def _healed_guids(
    healed: list[backfill.BackfillAction], history: dict
) -> set[str]:
    """Feed guids of the publications a backfill actually repaired.

    A ``BackfillAction`` carries the species code and not the date, while
    the feed is keyed by both, so the dates come from history. Backfill
    walks history deduplicated by code and repairs the per-species cache
    every publication of that species reads, so a species published more
    than once yields one guid per publication: healing it once heals all
    of them, and freezing any of the others would leave the same file
    holding two versions of the same repair.
    """
    codes = {action.species_code for action in healed}
    return {
        urls.feed_guid(entry["speciesCode"], entry["date"])
        for entry in history.get("entries", [])
        if entry.get("speciesCode") in codes and entry.get("date")
    }


def _rebuild_feed(
    history: dict,
    config: dict,
    catalog: i18n.Catalog,
    description_policy: str,
    english_name_index: dict,
    code_to_localized: dict,
    published_anchors_abs: dict,
    now: datetime,
    *,
    state_dir: Path = STATE_DIR,
    thaw: set[str] | None = None,
) -> tuple[dict[str, str], dict]:
    """Full-rebuild the RSS feeds from history.

    Every entry gets fresh name-linker output so cross-links to newly
    published species appear retroactively in older entries. pubDates are
    preserved from the existing feed via a pre-pass lookup.

    ``state_dir`` is where both feeds are read back from and written to.
    It has a default so the public behaviour is unchanged, but both call
    sites pass it explicitly: reading through module constants while
    writing through the global made the two halves divergeable, and a
    test that redirected only one of them silently read the repository's
    own published feed.

    ``thaw`` is passed straight to the writer: guids whose bodies must be
    re-rendered even when the full feed would otherwise reuse what it
    published. See :func:`_healed_guids` for what goes in it.

    Returns ``(composed_paths, feed_result)``: ``composed_paths`` is the
    ``species_code`` to relative-path map of composed distribution maps,
    so callers can report the ones that are missing; ``feed_result`` is
    the dict returned by :func:`feed_builder.write_feeds`.
    """
    # pubDates come from whichever file still has them. The full feed is
    # the long memory; feed.xml is the authority for what is currently
    # published, and on the run that introduces the cap it is still the
    # only file that exists.
    existing_pub_by_guid: dict[str, str] = {}
    for source in (
        state_dir / urls.FEED_FULL_FILE,
        state_dir / urls.FEED_FILE,
    ):
        for e in feed_builder.load_existing_feed(str(source)):
            if e.pub_date:
                existing_pub_by_guid[e.guid] = e.pub_date

    # Compose distribution maps for RSS (single image per species).
    feed_link = config.get("feed_link", "")
    composed_paths = map_composer.ensure_composed_maps(
        list(reversed(history["entries"])),
        str(CACHE_DIR),
        MAPS_DIR,
    )

    all_feed_entries: list[feed_builder.FeedEntry] = []
    for raw, publication_number, ordinal, previous_date in _entries_newest_first(
        history["entries"]
    ):
        fc = raw["speciesCode"]
        # The item's own destination on our site. Without feed_link no
        # absolute URL can be formed, and both the item link and the
        # photo fall back to eBird.
        species_page_abs = (
            urls.absolute(feed_link, urls.species_url(fc)) if feed_link else ""
        )
        fi = _image_for(raw, fc, ordinal)
        fco = content_scraper.load_cached_content(fc, str(CACHE_DIR))
        if fco is None:
            fco = content_scraper.SpeciesContent(
                description="", description_source="",
                bow_intro="", taxonomy={},
            )
        ft = ebird_client.lookup_taxonomy(fc) or fco.taxonomy or {}
        fd, fs = _apply_description_policy(fco, description_policy)

        composed_map_url = (
            urls.absolute(feed_link, composed_paths[fc])
            if fc in composed_paths and feed_link
            else ""
        )

        fen = llm_enricher.load_cached_enrichment(fc, str(CACHE_DIR))

        fhtml = feed_builder.build_entry_html(
            species_code=fc,
            common_name=raw["comName"],
            scientific_name=raw["sciName"],
            image_url=fi.url,
            image_attribution=fi.attribution,
            ml_search_url=fi.search_url,
            description=fd,
            description_source=fs,
            bow_intro=fco.bow_intro,
            taxonomy=ft,
            catalog=catalog,
            wikipedia_url=fco.wikipedia_url,
            wikipedia_language=fco.wikipedia_language,
            fallback_language=fco.fallback_language,
            distribution_map_url=fco.distribution_map_url,
            gbif_taxon_key=fco.gbif_taxon_key,
            composed_map_url=composed_map_url,
            iucn_code=fco.iucn_code,
            iucn_birdlife_url=fco.iucn_birdlife_url,
            enriched_prose=fen.prose if fen else "",
            enriched_identification=fen.identification if fen else None,
            english_name_index=english_name_index,
            code_to_localized=code_to_localized,
            published_anchors=published_anchors_abs,
            number=publication_number,
            date=raw["date"],
            species_page_url=species_page_abs,
            previous_date=previous_date,
        )
        fguid = urls.feed_guid(fc, raw["date"])
        fpub = existing_pub_by_guid.get(fguid, format_datetime(now))
        all_feed_entries.append(
            feed_builder.FeedEntry(
                species_code=fc,
                common_name=raw["comName"],
                scientific_name=raw["sciName"],
                description_html=fhtml,
                image_url=fi.url,
                image_attribution=fi.attribution,
                ml_search_url=fi.search_url,
                pub_date=fpub,
                guid=fguid,
                link=species_page_abs,
            )
        )
    feed_result = feed_builder.write_feeds(
        all_feed_entries,
        config,
        catalog,
        state_dir,
        rebuild_all=_config_flag(config, "feed_rebuild_all"),
        thaw=thaw,
    )
    return composed_paths, feed_result


def _report_missing_maps(
    history: dict,
    composed_paths: dict[str, str],
    report: run_report.RunReport,
) -> None:
    """Warn about species whose distribution map failed to compose.

    Composition never fails the run, so without this the feed silently
    loses maps. Only species that actually have a GBIF map URL are
    reported: the rest have nothing to compose.
    """
    for entry in history["entries"]:
        code = entry.get("speciesCode")
        if not code or code in composed_paths:
            continue
        cached = content_scraper.load_cached_content(code, str(CACHE_DIR))
        if cached is not None and cached.distribution_map_url:
            report.warn(f"map composition missing for {code}")


def _report_feed(feed_result: dict, report: run_report.RunReport) -> None:
    """Say what happened to each feed file, the way the site does."""
    state = "written" if feed_result["feed_written"] else "unchanged"
    report.info(f"feed: {feed_result['items']} items, {state}")
    if feed_result["full_items"]:
        full_state = "written" if feed_result["full_written"] else "unchanged"
        bits = [
            f"feed-full: {feed_result['full_items']} items",
            f"{feed_result['frozen']} reused from the published feed",
        ]
        # Only when it happened: on the overwhelming majority of runs
        # backfill heals nothing old, and a permanent ", 0 re-rendered"
        # would train the reader to stop seeing the line.
        if feed_result.get("thawed"):
            bits.append(f"{feed_result['thawed']} re-rendered after healing")
        bits.append(full_state)
        report.info(", ".join(bits))
    if feed_result.get("full_stale"):
        report.warn(
            f"{urls.FEED_FULL_FILE} is published but no longer maintained: "
            "the feed cap is off, so nothing rewrites it and no page links "
            "it. Set max_feed_entries above 0 to resume maintaining it, or "
            "remove the file by hand."
        )


def _select_and_fetch(
    config: dict,
    history_entries: list[dict],
    date_str: str,
    catalog: i18n.Catalog,
    ebird_locale: str,
    description_policy: str,
    notes: list[str] | None = None,
) -> tuple[dict, image_fetcher.ImageResult, content_scraper.SpeciesContent]:
    """Run the species selection loop with image + content fetching.

    For ``strict`` / ``foreign_fallback`` the first pick wins. For ``skip``
    we re-roll up to ``max_skip_retries`` times until a species with text
    in the configured language is found.

    ``history_entries`` is the whole history, which the selection reads as
    a recency ordering and the image fetch reads to avoid repeating a
    photograph. ``notes`` collects the selection diagnostics the run
    report prints.

    Returns ``(species_dict, image_result, content_result)``.
    """
    max_skip = int(config.get("max_skip_retries", 50))
    published_codes = [
        e["speciesCode"] for e in history_entries if e.get("speciesCode")
    ]
    session = image_fetcher.new_session(
        accept_language=catalog.accept_language_header
    )

    tried_codes: list[str] = []
    last_attempt: tuple | None = None

    for attempt in range(max_skip + 1):
        logger.info("Selecting bird of the day for %s", date_str)
        species = ebird_client.select_species(
            config, published_codes, date_str, cache_dir=CACHE_DIR,
            exclude=frozenset(tried_codes), notes=notes,
        )
        species_code = species["speciesCode"]
        logger.info(
            "Selected: %s (%s) [%s]",
            species["comName"], species["sciName"], species_code,
        )

        ordinal = published_codes.count(species_code)
        image = image_fetcher.load_cached_image(
            species_code, str(CACHE_DIR), ordinal=ordinal
        )
        if image is None:
            logger.info("Fetching image for %s", species_code)
            image = image_fetcher.fetch_image(
                species_code, session=session, locale=ebird_locale,
                ordinal=ordinal,
                seen_asset_ids=_seen_asset_ids(history_entries, species_code),
            )
            image_fetcher.save_cached_image(
                species_code, image, str(CACHE_DIR), ordinal=ordinal
            )
        else:
            logger.info("Using cached image for %s", species_code)

        content = content_scraper.load_cached_content(species_code, str(CACHE_DIR))
        if content is None:
            logger.info("Scraping content for %s", species_code)
            # When an LLM is configured, cache full text (LLM applies its
            # own context budget). Otherwise, truncate for layout.
            enriched = llm_enricher.is_configured(config)
            max_chars = (llm_enricher.MAX_CONTEXT_CHARS if enriched
                         else content_scraper.MAX_DESCRIPTION_CHARS)
            content = content_scraper.scrape_species_content(
                species_code,
                scientific_name=species["sciName"],
                catalog=catalog,
                session=session,
                max_description_chars=max_chars,
            )
            content_scraper.save_cached_content(species_code, content, str(CACHE_DIR))
        else:
            logger.info("Using cached content for %s", species_code)

        last_attempt = (species, image, content)

        if description_policy != "skip":
            break
        if content.description:
            break
        logger.info(
            "skip retry #%d: %s has no %s description, rerolling",
            attempt + 1, species_code, catalog.language,
        )
        tried_codes.append(species_code)
    else:
        logger.warning(
            "skip exhausted %d retries; publishing last attempt with empty description",
            max_skip,
        )

    if last_attempt is None:
        raise RuntimeError("Selection loop produced no attempt")

    species, image, content = last_attempt
    if image.url:
        logger.info("Image: asset %s by %s", image.asset_id, image.photographer or "?")
    else:
        logger.info("No image available, will link to ML Search")

    return species, image, content


def main() -> None:
    _load_dotenv(ENV_PATH)
    _load_secret_files()
    config = load_config()
    history = load_history()
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    report = run_report.RunReport()

    catalog = i18n.Catalog.load(config["language"])

    ebird_locale = config.get("ebird_locale") or catalog.ebird_locale
    config["ebird_locale"] = ebird_locale

    # The English taxonomy is the name linker's first pass. Losing it
    # degrades every page it renders, so the outcome is carried in a flag
    # instead of only in the log: the already-published rebuild below
    # refuses to republish on it, and the run report has to say why.
    linker_ok = True
    try:
        english_name_index = ebird_client.get_english_name_index(cache_dir=CACHE_DIR)
    except requests.RequestException:
        logger.warning("Could not load English taxonomy; name linker disabled")
        report.warn("taxonomy unavailable: the name linker is disabled this run")
        english_name_index = {}
        linker_ok = False

    description_policy = config.get("description_policy", "foreign_fallback")
    feed_link = config.get("feed_link", "")
    # Whether feed-full.xml is published this run, derived from the one
    # expression write_feeds itself uses: without a cap the full feed
    # would duplicate feed.xml byte for byte, so it is not written, and
    # the pages must not link a file that does not exist.
    full_feed = feed_builder.feed_cap(config) > 0

    try:
        # Maintenance first: heal past entries (missed enrichments,
        # failed GBIF lookups). Runs even when today is already
        # published, so a second cron tick repairs the morning's outage.
        # Guarded on its own: building the indexes may need to fetch the
        # taxonomy, and an outage there must not turn an otherwise no-op
        # run on an already-published day into a failure.
        maintenance_ok = True
        try:
            code_to_localized, published_anchors, published_anchors_abs = (
                _build_indexes(history, feed_link, ebird_locale)
            )
            session = image_fetcher.new_session(
                accept_language=catalog.accept_language_header
            )
            actions = backfill.run_backfill(
                history, config, catalog, str(CACHE_DIR),
                english_name_index, code_to_localized,
                limit=int(config.get("backfill_limit", 3)),
                session=session,
            )
        except requests.RequestException:
            logger.warning(
                "maintenance skipped: taxonomy or network unavailable",
                exc_info=True,
            )
            report.warn("maintenance skipped: taxonomy or network unavailable")
            maintenance_ok = False
            code_to_localized = {}
            published_anchors = {}
            published_anchors_abs = {}
            actions = []

        healed = [a for a in actions if a.ok]
        for action in actions:
            if action.ok:
                report.info(f"backfill healed {action.kind} for {action.species_code}")
            else:
                report.warn(f"backfill {action.kind} for {action.species_code} failed")

        # Idempotency: today's entry is already published. Republish only
        # when backfill actually changed something.
        last = history["entries"][-1] if history["entries"] else None
        if last and last.get("date") == date_str:
            # The one expression that decides whether anything is
            # republished. The log line and the report's closing line
            # both read it, so a run that skipped the rebuild cannot
            # claim to have rebuilt: the two taxonomy caches have their
            # own files and their own TTLs, so linker_ok goes false on
            # its own often enough for that lie to reach a real report.
            rebuilding = maintenance_ok and linker_ok
            if healed and rebuilding:
                logger.info(
                    "Already generated for %s; backfill healed %d, rebuilding",
                    date_str, len(healed),
                )
            else:
                logger.info("Already generated for %s, skipping", date_str)

            # Rendering the whole page set and the feed is cheap and both
            # writers are content-addressed, so this runs on every tick
            # regardless of whether backfill healed anything: a run that
            # died part way through on a previous tick must not leave a
            # mixed set on disk until the next new-day publish. But only
            # when maintenance actually succeeded: on a failed taxonomy
            # fetch the cross-link indexes above are empty dicts, and
            # writing with those would rewrite every page and every item
            # with the name linker disabled, content-addressed straight
            # over the good version already on disk. The same argument
            # covers english_name_index, the linker's other input: an
            # outage there is just as silent and just as wide.
            if rebuilding:
                # Site first, feeds second, on both paths. The state
                # directory is served live, and every feed item links a
                # species page: writing the feed first opens a window
                # where the newest item points at a page that does not
                # exist yet, and a crash inside that window leaves the
                # link 404 until the next tick. write_site depends on
                # nothing _rebuild_feed produces (the plates hot-link
                # GBIF and the committed basemap, never the composed
                # PNGs), so the swap is free. Report order is unchanged.
                site_entries = _build_site_entries(
                    history, description_policy=description_policy
                )
                site_result = archive_builder.write_site(
                    site_entries,
                    STATE_DIR,
                    catalog=catalog,
                    feed_link=feed_link,
                    english_name_index=english_name_index,
                    code_to_localized=code_to_localized,
                    published_anchors=published_anchors,
                    full_feed=full_feed,
                )
                composed_paths, feed_result = _rebuild_feed(
                    history, config, catalog, description_policy,
                    english_name_index, code_to_localized,
                    published_anchors_abs, now,
                    state_dir=STATE_DIR,
                    thaw=_healed_guids(healed, history),
                )
                _report_missing_maps(history, composed_paths, report)
                _report_feed(feed_result, report)
                report.info(
                    f"site: {site_result['written']} of {site_result['pages']} pages "
                    f"written, {site_result['unchanged']} unchanged"
                )
            elif not maintenance_ok:
                report.warn(
                    "rebuild skipped: maintenance failed, "
                    "not republishing with an empty cross-link catalog"
                )
            else:
                report.warn(
                    "rebuild skipped: taxonomy unavailable, "
                    "not republishing with the name linker disabled"
                )
            report.info(
                f"already published for {date_str}"
                + (
                    ", outputs rebuilt after healing"
                    if healed and rebuilding
                    else ""
                )
            )
            report.emit()
            return

        # 1. Select species, fetch image + content.
        selection_notes: list[str] = []
        species, image, content = _select_and_fetch(
            config, history["entries"], date_str, catalog, ebird_locale,
            description_policy, notes=selection_notes,
        )
        species_code = species["speciesCode"]
        common_name = species["comName"]
        scientific_name = species["sciName"]
        report.info(f"species: {common_name} ({scientific_name}) [{species_code}]")
        # Deduplicated: under the skip policy every re-roll runs the whole
        # selection again, so the same clamp note would otherwise be
        # printed once per attempt.
        for note in dict.fromkeys(selection_notes):
            report.info(note)
        republished = _republished_note(
            history["entries"], species_code, common_name
        )
        if republished:
            report.info(republished)

        # 2. LLM enrichment: always attempted when an LLM is configured.
        if llm_enricher.is_configured(config):
            enriched = llm_enricher.load_cached_enrichment(
                species_code, str(CACHE_DIR)
            )
            if enriched is None:
                enriched = llm_enricher.enrich_species(
                    species_code, common_name, scientific_name,
                    content, config, catalog,
                    english_name_index, code_to_localized,
                )
                if enriched:
                    llm_enricher.save_cached_enrichment(
                        species_code, enriched, str(CACHE_DIR)
                    )
            if enriched:
                logger.info("Using enriched content for %s", species_code)
                report.info("content: enriched")
            else:
                logger.warning(
                    "LLM enrichment failed for %s, falling back to programmatic",
                    species_code,
                )
                report.warn(
                    f"LLM enrichment failed for {species_code}, "
                    "published programmatic fallback"
                )
        else:
            report.info("content: programmatic (no LLM configured)")

        # 3. Apply description policy.
        effective_description, effective_source = _apply_description_policy(
            content, description_policy
        )
        if effective_source == "ebird-foreign":
            logger.info(
                "foreign_fallback: using rejected %s text for %s",
                content.fallback_language, species_code,
            )
            report.warn(f"foreign-language description published for {species_code}")

        # 3. Update history.
        history["entries"].append(
            {
                "speciesCode": species_code,
                "comName": common_name,
                "sciName": scientific_name,
                "date": date_str,
                "imageUrl": image.url,
                "photographer": image.photographer,
                "attribution": image.attribution,
            }
        )
        save_history(history)

        # 4. Rebuild cross-reference indexes so anchors include today.
        code_to_localized, published_anchors, published_anchors_abs = (
            _build_indexes(history, feed_link, ebird_locale)
        )

        # 5. Generate the static site. It goes before the feeds for the
        # reason given on the other path: the newest item's link has to
        # resolve the moment the feed carrying it is published.
        site_entries = _build_site_entries(history, description_policy=description_policy)
        site_result = archive_builder.write_site(
            site_entries,
            STATE_DIR,
            catalog=catalog,
            feed_link=feed_link,
            english_name_index=english_name_index,
            code_to_localized=code_to_localized,
            published_anchors=published_anchors,
            full_feed=full_feed,
        )

        # 6. Rebuild the RSS feeds.
        composed_paths, feed_result = _rebuild_feed(
            history, config, catalog, description_policy,
            english_name_index, code_to_localized, published_anchors_abs, now,
            state_dir=STATE_DIR,
            thaw=_healed_guids(healed, history),
        )
        _report_missing_maps(history, composed_paths, report)
        _report_feed(feed_result, report)
        report.info(
            f"site: {site_result['written']} of {site_result['pages']} pages "
            f"written, {site_result['unchanged']} unchanged"
        )

        logger.info("Done. Today's bird: %s (%s)", common_name, scientific_name)
        report.emit()

    except Exception:
        logger.exception("Failed to generate bird of the day")
        report.emit()
        sys.exit(1)


if __name__ == "__main__":
    main()
