"""Self-healing for past entries.

The daily pipeline degrades gracefully: a failed LLM call or GBIF lookup
publishes the entry anyway with reduced content. This module walks the
history on every run and retries what failed, newest first, capped per
run so a long outage can't turn one cron tick into an hour of API calls.

Healable states:

- An entry whose photograph URL carries no asset id, and so renders broken.
- A recent entry published with no photograph at all (see
  :func:`_absent_and_recent`).
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

import datetime
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import requests

from scripts import content_scraper, distribution_map, image_fetcher, llm_enricher

if TYPE_CHECKING:
    from scripts.i18n import Catalog

logger = logging.getLogger(__name__)


@dataclass
class BackfillAction:
    species_code: str
    kind: str  # "enrichment" | "gbif" | "image"
    ok: bool


def _needs_image(image_url: str | None) -> bool:
    """Whether an entry's photograph is *broken*, as opposed to absent.

    Healable means a Macaulay CDN URL with no asset id in it, which older
    revisions published when eBird served a hero tag for a species it had
    no hero for. That is a defect: the reader gets a broken image.

    An absent photograph is handled apart, by :func:`_absent_and_recent`.
    """
    if not image_url:
        return False
    return (
        image_url.startswith(image_fetcher.CDN_BASE)
        and image_fetcher.asset_id_from_url(image_url) is None
    )


# How long an entry published without a photograph keeps being retried.
ABSENT_RETRY_DAYS = 7


def _absent_and_recent(entry: dict, newest_date: str) -> bool:
    """Whether an entry has no photograph and is young enough to retry.

    An empty ``imageUrl`` used to be final, on the argument that it meant
    every strategy had been asked and none had answered. That stopped
    being true when Cornell put its species pages and its search API
    behind bot gateways (2026-08-30, 2026-09-22): from then on "none
    answered" mostly meant "the runner was turned away this morning", and
    three of four consecutive entries went out with an empty frame that
    nothing would ever fill.

    The window keeps the reason the rule existed: with one image slot per
    run the newest photoless entry always wins, so retrying them for ever
    would starve everything older. Broken URLs are healed before any of
    these, and a photoless entry stops being retried a week after it was
    published. ``newest_date`` is the newest entry's date, not the clock,
    so a test or a late run reads the same window.
    """
    if entry.get("imageUrl"):
        return False
    date = entry.get("date") or ""
    if not date or not newest_date:
        return False
    try:
        age = (
            datetime.date.fromisoformat(newest_date)
            - datetime.date.fromisoformat(date)
        ).days
    except ValueError:
        return False
    return 0 <= age < ABSENT_RETRY_DAYS


def _heal_images(
    history: dict,
    cache_dir: str,
    locale: str,
    session: requests.Session | None,
    limit: int,
) -> list[BackfillAction]:
    """Re-fetch photographs for entries whose URL is broken.

    Walks entries newest first, and per entry rather than per species:
    the same bird can be published more than once, each publication with
    its own photograph, so only the broken publication is repaired.

    Both the history entry and the per-publication cache are rewritten,
    including when the retry fails. They have to move together, because
    the site renders from the cache when there is one and only falls back
    to the history. Rewriting on failure is what clears a broken URL, so
    a photograph that cannot be found degrades to the plate's honest
    "no photo, here is where to look" state instead of a broken image.
    """
    entries = history.get("entries", [])
    actions: list[BackfillAction] = []
    newest_date = entries[-1].get("date", "") if entries else ""

    # Broken first, then absent: a broken URL is a hole the reader sees
    # as an error, an absent one is an honest gap with a search link.
    newest_first = range(len(entries) - 1, -1, -1)
    queue = [i for i in newest_first if _needs_image(entries[i].get("imageUrl"))]
    queue += [i for i in newest_first if _absent_and_recent(entries[i], newest_date)]

    for index in queue:
        if len(actions) >= limit:
            break
        entry = entries[index]
        code = entry.get("speciesCode")
        if not code:
            continue

        ordinal = sum(1 for e in entries[:index] if e.get("speciesCode") == code)
        seen = frozenset(
            asset
            for e in entries
            if e.get("speciesCode") == code
            for asset in [image_fetcher.asset_id_from_url(e.get("imageUrl"))]
            if asset
        )
        image = image_fetcher.fetch_image(
            code,
            session=session,
            locale=locale,
            ordinal=ordinal,
            seen_asset_ids=seen,
            scientific_name=entry.get("sciName", ""),
        )
        entry["imageUrl"] = image.url
        entry["photographer"] = image.photographer
        entry["attribution"] = image.attribution

        ok = bool(image.url)
        if ok:
            image_fetcher.save_cached_image(code, image, cache_dir, ordinal=ordinal)
        else:
            # save_cached_image declines to store a failure, by design, so
            # the stale cache would survive and the site would keep
            # rendering the broken URL we just cleared from the history.
            # Delete it instead: the two have to agree, and the renderer
            # falls back to the history when there is no cache.
            image_fetcher.image_cache_path(code, cache_dir, ordinal).unlink(
                missing_ok=True
            )
        actions.append(BackfillAction(code, "image", ok))
        logger.info(
            "backfill image for %s: %s",
            code,
            "healed" if ok else "still no photograph",
        )

    return actions


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
    """Retry failed photographs, enrichments and GBIF lookups.

    Photographs are healed per entry (see :func:`_heal_images`), which
    **mutates** ``history``, so the caller has to persist it. The other
    two are healed per species, walking history newest first and
    deduplicated by code, because their caches are per species rather
    than per publication.

    Every attempt (successful or not) counts against ``limit`` so a
    persistent outage doesn't hammer the endpoints on every run.
    ``session``, when given, is reused so retry/backoff and connection
    pooling apply.
    """
    actions: list[BackfillAction] = []
    if limit <= 0:
        return actions

    # Photographs go first, because a broken one is the most visible thing
    # an entry can have: the plate is the page. They get half the run's
    # budget and never less than one slot, so a backlog of broken URLs
    # cannot disable the other two healers while it works through. Each
    # one is attempted once and then resolved either way, so the backlog
    # drains rather than repeating.
    #
    # ``ebird_locale`` is the resolved locale the caller has already
    # written back into the config, the same one the daily fetch uses.
    actions.extend(
        _heal_images(
            history,
            cache_dir,
            config.get("ebird_locale") or "en",
            session,
            max(1, limit // 2),
        )
    )
    if len(actions) >= limit:
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
