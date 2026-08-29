"""Self-healing for past entries.

The daily pipeline degrades gracefully: a failed LLM call or GBIF lookup
publishes the entry anyway with reduced content. This module walks the
history on every run and retries what failed, newest first, capped per
run so a long outage can't turn one cron tick into an hour of API calls.

Healable states:

- Missing ``{code}.enriched.json`` while an LLM is configured.
- ``gbif_match == MATCH_ERROR`` (or a legacy cache with no taxon key and
  no recorded state): the taxon lookup failed transiently and was never
  retried. An authoritative ``MATCH_NONE`` is never retried.

There is no per-species retry budget: an entry that keeps failing is
retried again on every run, spending at most one of that run's slots.

The caller rebuilds feed and site when any action succeeded, so healed
content reaches readers the same day.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import requests

from scripts import content_scraper, distribution_map, llm_enricher

if TYPE_CHECKING:
    from scripts.i18n import Catalog

logger = logging.getLogger(__name__)


@dataclass
class BackfillAction:
    species_code: str
    kind: str  # "enrichment" | "gbif"
    ok: bool


def run_backfill(
    history: dict,
    config: dict,
    catalog: "Catalog",
    cache_dir: str,
    english_name_index: dict,
    code_to_localized: dict,
    limit: int,
    session: requests.Session | None = None,
) -> list[BackfillAction]:
    """Retry failed enrichments and GBIF lookups for past entries.

    Walks history newest first, deduplicated by species code. Every
    attempt (successful or not) counts against ``limit`` so a persistent
    outage doesn't hammer the endpoints on every run. ``session``, when
    given, is reused for GBIF requests so retry/backoff and connection
    pooling apply.
    """
    actions: list[BackfillAction] = []
    if limit <= 0:
        return actions

    llm_on = llm_enricher.is_configured(config)
    seen: set[str] = set()

    for entry in reversed(history.get("entries", [])):
        if len(actions) >= limit:
            break
        code = entry.get("speciesCode")
        if not code or code in seen:
            continue
        seen.add(code)

        content = content_scraper.load_cached_content(code, cache_dir)
        if content is None:
            continue

        # GBIF: retry transient failures (explicit error state, or a
        # legacy cache with no key and no recorded state). An empty
        # sciName can't be looked up; skip without touching state so it
        # doesn't get permanently marked as an error.
        sci_name = entry.get("sciName", "")
        needs_gbif = content.gbif_taxon_key is None and (
            content.gbif_match != distribution_map.MATCH_NONE
        )
        if needs_gbif and sci_name:
            key, state = distribution_map.gbif_taxon_match_ex(
                sci_name, session=session
            )
            content.gbif_match = state
            if key is not None:
                content.gbif_taxon_key = key
                content.distribution_map_url = distribution_map.gbif_map_url(key)
                iucn = distribution_map.fetch_iucn_category(key, session=session)
                if iucn is not None:
                    content.iucn_code, _, content.iucn_birdlife_url = iucn
            content_scraper.save_cached_content(code, content, cache_dir)
            actions.append(BackfillAction(code, "gbif", key is not None))
            logger.info(
                "backfill gbif for %s: %s", code,
                "healed" if key is not None else f"still {state}",
            )
            if len(actions) >= limit:
                break

        # Enrichment: retry entries that never got LLM content.
        if llm_on and llm_enricher.load_cached_enrichment(code, cache_dir) is None:
            enriched = llm_enricher.enrich_species(
                code,
                entry.get("comName", ""),
                entry.get("sciName", ""),
                content,
                config,
                catalog,
                english_name_index,
                code_to_localized,
            )
            ok = enriched is not None
            if ok:
                llm_enricher.save_cached_enrichment(code, enriched, cache_dir)
            actions.append(BackfillAction(code, "enrichment", ok))
            logger.info(
                "backfill enrichment for %s: %s", code,
                "healed" if ok else "failed",
            )

    return actions
