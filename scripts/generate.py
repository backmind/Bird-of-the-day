#!/usr/bin/env python3
"""Bird of the Day — Daily RSS Feed + Static Site generator.

Orchestrates species selection, image lookup, content scraping, RSS feed
construction, and the static index.html / archive.html pages. Idempotent
within a single UTC day: if today's bird is already in history, the script
exits without making changes.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

import requests

from scripts import (
    content_scraper,
    ebird_client,
    feed_builder,
    i18n,
    image_fetcher,
    llm_enricher,
    map_composer,
    site_builder,
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

# State-anchored (written at runtime, lives on the volume in Docker)
CACHE_DIR = STATE_DIR / "cache"
MAPS_DIR = STATE_DIR / "maps"
FEED_PATH = STATE_DIR / "feed.xml"
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


# Scalar config keys that may be overridden by environment variables. The
# table maps an env var name to (config key, caster). Env vars override the
# JSON file value when present, so users can ship the default
# ``data/config.json`` baked in the container and tweak individual knobs
# with ``-e BOTD_LANGUAGE=fr`` etc. Complex nested structures (like
# ``pools``) are intentionally not env-var-able — mount a custom file
# instead.
_ENV_OVERRIDES: dict[str, tuple[str, type]] = {
    "BOTD_LANGUAGE": ("language", str),
    "BOTD_EBIRD_LOCALE": ("ebird_locale", str),
    "BOTD_DESCRIPTION_POLICY": ("description_policy", str),
    "BOTD_MAX_SKIP_RETRIES": ("max_skip_retries", int),
    "BOTD_DEDUP_WINDOW": ("dedup_window", int),
    "BOTD_MAX_FEED_ENTRIES": ("max_feed_entries", int),
    "BOTD_BACK_DAYS": ("back_days", int),
    "BOTD_FEED_LINK": ("feed_link", str),
    "BOTD_CONTENT_MODE": ("content_mode", str),
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


def _build_site_entries(
    history: dict, description_policy: str = "foreign_fallback"
) -> list[site_builder.SiteEntry]:
    """Reconstruct rich SiteEntry objects from history + per-species caches.

    Iterates history in reverse so the most recent bird is first in the list.
    Missing caches degrade gracefully to empty fields. The
    ``description_policy`` argument controls how empty descriptions are
    handled: ``foreign_fallback`` substitutes the rejected foreign text,
    ``strict`` (and ``skip`` from this rendering perspective) leaves them
    empty so the layout shows the em-dash placeholder.
    """
    entries: list[site_builder.SiteEntry] = []
    cache_dir = str(CACHE_DIR)
    raw_entries = history.get("entries", [])
    total = len(raw_entries)
    for i, raw in enumerate(reversed(raw_entries)):
        code = raw.get("speciesCode")
        if not code:
            continue
        publication_number = total - i

        image = image_fetcher.load_cached_image(code, cache_dir)
        if image is None:
            image = image_fetcher.ImageResult(
                url=raw.get("imageUrl"),
                asset_id=None,
                photographer=raw.get("photographer", ""),
                attribution=raw.get("attribution", "Macaulay Library / Cornell Lab of Ornithology"),
                search_url=f"https://search.macaulaylibrary.org/catalog?taxonCode={code}&mediaType=photo&sort=rating_rank_desc",
            )

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
                enriched_prose=enriched.prose if enriched else "",
                enriched_identification=enriched.identification if enriched else None,
            )
        )
    return entries


def _build_indexes(
    history: dict, feed_link: str
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Build cross-reference indexes for the name linker.

    Returns ``(code_to_localized, published_anchors, published_anchors_abs)``.
    ``published_anchors`` uses relative archive URLs; ``published_anchors_abs``
    prepends the ``feed_link`` base so RSS readers can resolve them.
    """
    # Ensure the taxonomy is loaded (may not be if we're rebuilding
    # without going through the full selection pipeline).
    ebird_client.get_full_taxonomy(cache_dir=CACHE_DIR)
    code_to_localized = ebird_client.get_code_to_localized()

    published_anchors: dict[str, str] = {}
    published_anchors_abs: dict[str, str] = {}
    for h in history["entries"]:
        hc, hd = h["speciesCode"], h["date"]
        published_anchors[hc] = f"archive.html#bird-{hc}-{hd}"
        published_anchors_abs[hc] = (
            f"{feed_link.rstrip('/')}/archive.html#bird-{hc}-{hd}"
            if feed_link else published_anchors[hc]
        )

    return code_to_localized, published_anchors, published_anchors_abs


def _rebuild_feed(
    history: dict,
    config: dict,
    catalog: i18n.Catalog,
    description_policy: str,
    english_name_index: dict,
    code_to_localized: dict,
    published_anchors_abs: dict,
    now: datetime,
) -> None:
    """Full-rebuild the RSS feed from history.

    Every entry gets fresh name-linker output so cross-links to newly
    published species appear retroactively in older entries. pubDates are
    preserved from the existing feed via a pre-pass lookup.
    """
    existing_pub_by_guid = {
        e.guid: e.pub_date
        for e in feed_builder.load_existing_feed(str(FEED_PATH))
    }
    max_entries = config.get("max_feed_entries", 0) or None

    # Compose distribution maps for RSS (single image per species).
    feed_link = config.get("feed_link", "")
    composed_paths = map_composer.ensure_composed_maps(
        list(reversed(history["entries"])),
        str(CACHE_DIR),
        MAPS_DIR,
    )

    all_feed_entries: list[feed_builder.FeedEntry] = []
    for raw in reversed(history["entries"]):
        fc = raw["speciesCode"]
        fi = image_fetcher.load_cached_image(fc, str(CACHE_DIR))
        fco = content_scraper.load_cached_content(fc, str(CACHE_DIR))
        if fco is None:
            fco = content_scraper.SpeciesContent(
                description="", description_source="",
                bow_intro="", taxonomy={},
            )
        ft = ebird_client.lookup_taxonomy(fc) or fco.taxonomy or {}
        fd, fs = _apply_description_policy(fco, description_policy)

        # Build absolute URL for the pre-composed map (if available).
        composed_map_url = ""
        if fc in composed_paths and feed_link:
            composed_map_url = (
                f"{feed_link.rstrip('/')}/{composed_paths[fc]}"
            )

        fen = llm_enricher.load_cached_enrichment(fc, str(CACHE_DIR))

        fhtml = feed_builder.build_entry_html(
            species_code=fc,
            common_name=raw["comName"],
            scientific_name=raw["sciName"],
            image_url=fi.url if fi else None,
            image_attribution=fi.attribution if fi else "",
            ml_search_url=fi.search_url if fi else "",
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
            enriched_prose=fen.prose if fen else "",
            enriched_identification=fen.identification if fen else None,
            english_name_index=english_name_index,
            code_to_localized=code_to_localized,
            published_anchors=published_anchors_abs,
        )
        fguid = f"bird-of-the-day-{fc}-{raw['date']}"
        fpub = existing_pub_by_guid.get(fguid, format_datetime(now))
        all_feed_entries.append(
            feed_builder.FeedEntry(
                species_code=fc,
                common_name=raw["comName"],
                scientific_name=raw["sciName"],
                description_html=fhtml,
                image_url=fi.url if fi else None,
                image_attribution=fi.attribution if fi else "",
                ml_search_url=fi.search_url if fi else "",
                pub_date=fpub,
                guid=fguid,
            )
        )
    all_feed_entries = all_feed_entries[:max_entries]
    feed_xml = feed_builder.build_feed(all_feed_entries, config, catalog)
    feed_builder.write_feed(feed_xml, str(FEED_PATH))


def _select_and_fetch(
    config: dict,
    history_codes: list[str],
    date_str: str,
    catalog: i18n.Catalog,
    ebird_locale: str,
    description_policy: str,
) -> tuple[dict, image_fetcher.ImageResult, content_scraper.SpeciesContent]:
    """Run the species selection loop with image + content fetching.

    For ``strict`` / ``foreign_fallback`` the first pick wins. For ``skip``
    we re-roll up to ``max_skip_retries`` times until a species with text
    in the configured language is found.

    Returns ``(species_dict, image_result, content_result)``.
    """
    max_skip = int(config.get("max_skip_retries", 50))
    session = image_fetcher.new_session(
        accept_language=catalog.accept_language_header
    )

    tried_codes: list[str] = []
    last_attempt: tuple | None = None

    for attempt in range(max_skip + 1):
        logger.info("Selecting bird of the day for %s", date_str)
        species = ebird_client.select_species(
            config, history_codes + tried_codes, date_str, cache_dir=CACHE_DIR,
        )
        species_code = species["speciesCode"]
        logger.info(
            "Selected: %s (%s) [%s]",
            species["comName"], species["sciName"], species_code,
        )

        image = image_fetcher.load_cached_image(species_code, str(CACHE_DIR))
        if image is None:
            logger.info("Fetching image for %s", species_code)
            image = image_fetcher.fetch_image(
                species_code, session=session, locale=ebird_locale
            )
            image_fetcher.save_cached_image(species_code, image, str(CACHE_DIR))
        else:
            logger.info("Using cached image for %s", species_code)

        content = content_scraper.load_cached_content(species_code, str(CACHE_DIR))
        if content is None:
            logger.info("Scraping content for %s", species_code)
            # In enriched mode, cache full text (LLM applies its own
            # context budget). In programmatic mode, truncate for layout.
            enriched = config.get("content_mode") == "enriched"
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

    catalog = i18n.Catalog.load(config["language"])

    ebird_locale = config.get("ebird_locale") or catalog.ebird_locale
    config["ebird_locale"] = ebird_locale

    try:
        english_name_index = ebird_client.get_english_name_index(cache_dir=CACHE_DIR)
    except requests.RequestException:
        logger.warning("Could not load English taxonomy; name linker disabled")
        english_name_index = {}

    # Idempotency: skip if today's entry is already in history.
    last = history["entries"][-1] if history["entries"] else None
    if last and last.get("date") == date_str:
        logger.info("Already generated for %s, skipping", date_str)
        return

    description_policy = config.get("description_policy", "foreign_fallback")

    try:
        # 1. Select species, fetch image + content.
        dedup_window = config.get("dedup_window", config.get("max_history", 50))
        history_codes = [e["speciesCode"] for e in history["entries"][-dedup_window:]]

        species, image, content = _select_and_fetch(
            config, history_codes, date_str, catalog, ebird_locale,
            description_policy,
        )
        species_code = species["speciesCode"]
        common_name = species["comName"]
        scientific_name = species["sciName"]

        # 2. LLM enrichment (when content_mode is "enriched").
        content_mode = config.get("content_mode", "programmatic")
        if content_mode == "enriched":
            enriched = llm_enricher.load_cached_enrichment(
                species_code, str(CACHE_DIR)
            )
            if enriched is None:
                enriched = llm_enricher.enrich_species(
                    species_code, common_name, scientific_name,
                    content, config, catalog,
                )
                if enriched:
                    llm_enricher.save_cached_enrichment(
                        species_code, enriched, str(CACHE_DIR)
                    )
            if enriched:
                logger.info("Using enriched content for %s", species_code)
            else:
                logger.warning(
                    "LLM enrichment failed for %s, falling back to programmatic",
                    species_code,
                )

        # 3. Apply description policy.
        effective_description, effective_source = _apply_description_policy(
            content, description_policy
        )
        if effective_source == "ebird-foreign":
            logger.info(
                "foreign_fallback: using rejected %s text for %s",
                content.fallback_language, species_code,
            )

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

        # 4. Build cross-reference indexes for the name linker.
        feed_link = config.get("feed_link", "")
        code_to_localized, published_anchors, published_anchors_abs = (
            _build_indexes(history, feed_link)
        )

        # 5. Full-rebuild the RSS feed.
        _rebuild_feed(
            history, config, catalog, description_policy,
            english_name_index, code_to_localized, published_anchors_abs, now,
        )

        # 6. Generate the static site.
        site_entries = _build_site_entries(history, description_policy=description_policy)
        site_builder.write_site(
            site_entries,
            STATE_DIR,
            catalog=catalog,
            feed_link=feed_link,
            english_name_index=english_name_index,
            code_to_localized=code_to_localized,
            published_anchors=published_anchors,
        )

        logger.info("Done. Today's bird: %s (%s)", common_name, scientific_name)

    except Exception:
        logger.exception("Failed to generate bird of the day")
        sys.exit(1)


if __name__ == "__main__":
    main()
