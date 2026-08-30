# Roadmap

Features under consideration. Contributions welcome.

## Image carousel (frontend)

The hero photo is a single image from Macaulay Library. A lightweight carousel with left/right arrows would let the reader browse additional photos of the same species. Macaulay Library's search API supports multiple results per species.

Considerations:
- Blocked while Macaulay's search API stays gated (see [Open questions](#open-questions)): it is the only source of more than one photo for a species
- Fetch N images per publication instead of 1. The cache format already stores one photo per publication (`image_fetcher.py` suffixes the cache file by ordinal so a republished species gets a different photo), so this is a change to the fetch, not to the layout on disk
- Minimal vanilla JS carousel (scroll-snap + arrow buttons), consistent with the current no-framework approach
- Each photo keeps its own photographer attribution
- RSS stays with the single hero image (carousels don't work in feeds)

## Photo collage for RSS

The RSS feed currently shows one hero photo. A Pillow-composed collage (hero image + smaller thumbnails) could give feed readers a richer visual without requiring interactive elements. Similar to how the distribution map is already composed server-side.

Considerations:
- Compose at feed-build time, cache as `maps/{code}.collage.png`
- Layout: large hero left, 2-3 smaller photos stacked right (or grid)
- All photographer attributions in the caption
- Balance file size vs visual richness

## Seasonal distribution maps

The current GBIF density map shows year-round occurrence. Many species have distinct breeding and wintering ranges. GBIF's map API may support a `month` parameter (undocumented but possibly functional) that could enable seasonal overlays with different colours.

Considerations:
- Test whether GBIF `month` parameter actually filters results
- If it works: compose 2-3 seasonal layers with distinct colour ramps + legend
- If not: would require downloading raw occurrence data and rendering custom maps (significantly more complex)
- Hemisphere-dependent seasons complicate a global map at zoom 0

## Field guide illustrations

AI-generated or sourced illustrations for identification tips. The most complex feature on the roadmap due to copyright constraints on existing field guide art.

Considerations:
- No free API for field guide illustrations exists
- AI generation (Stable Diffusion, DALL-E) could produce stylised illustrations but quality and accuracy vary
- Could start with silhouette/outline SVGs generated from species photos

## Deferred on purpose

Two gaps that are known, not forgotten. Each was cut from the work that
would naturally have contained it, and each is written down here with the
reason, so the next person can weigh it rather than rediscover it.

**Offline fixtures and a browser suite in CI.** The test suite asserts on
rendered HTML as strings. Nothing opens a real browser, so nothing catches
a rule that only breaks at a given viewport, a focus ring that is invisible
against its background, or a layout that reflows on a narrow screen. A
Playwright job over frozen fixtures would. Cut because it means a second
toolchain, a browser download on every CI run, and a fixture corpus to keep
honest, which is a package of its own rather than a task inside one.

**Global search with a JSON index.** The archive is browsable by month and
by species, but there is no way to look for a bird by name across the whole
site. A small JSON index written at build time plus a few lines of vanilla
JS would do it. Cut because this project's rule is that a page renders
without JavaScript, and search is the first feature that genuinely needs
it: it deserves a design decision, not a drive-by.

## Open questions

**Macaulay's search API went behind an anti-bot gateway on 2026-08-30.**
The endpoint answers `200` with an HTML challenge instead of JSON, for
this project's own identifying user agent and for a real browser alike.
Nothing crashes: the JSON parse fails, the strategy returns nothing, and
the run keeps going. But that strategy is the only one that can find a
photograph eBird has not curated, and the only one that can find a
*different* photograph for a republication, so while the gateway stands
the different-photo-per-republication feature is inert. A repeat now
falls back to the curated eBird hero, which is the photograph the first
publication already used. The failed call is now logged as a warning
instead of being swallowed at debug level, so the outage is at least
visible in the run log while it lasts.

The consequence for a species eBird has not curated at all is that the
entry publishes with no photograph, and that state is deliberately not
retried (see below), so it stays that way: the plate degrades to its
honest gap with a link to search Macaulay by hand. The open part is what
to do if the gateway is permanent. There is no public, documented
Macaulay search endpoint to move to, so the choices are to find a
supported access path, to add a second photo source, or to accept that
every photograph comes from eBird's curation and retire the republication
feature.

**Absence and failure are still not the same answer.** Three production
bugs fixed on 2026-08-30 shared one root: the code read "the source has
nothing" as "the fetch failed". eBird emits an `og:image` tag even for a
species it has no hero for, leaving the asset id out, and that URL was
published as a broken image. GBIF answers `204 No Content` for a taxon it
has no occurrences to map, and the map composer asked again on every run
for the seventy days after the entry was published. The first photograph
healer retried entries with no photograph at all, so the newest one took
the single image slot every run and older, genuinely broken URLs were
never reached. All three are fixed the same way: record the authoritative
"there is nothing" and stop retrying it.

The convention is not universal yet. GBIF has explicit `MATCH_NONE` and
`MATCH_ERROR` states and the photograph healer encodes the distinction in
the URL it finds, but enrichment has no "gave up" marker at all: an entry
the LLM keeps refusing is retried on every run for ever, spending a slot
each time. It is bounded by `backfill_limit` and cheap, which is why it
was left alone, but anything that adds a fourth healable state should
settle the question rather than add a fourth answer to it.

## Known limits of the current selection

Not bugs, and not on anyone's list to fix. They are written down because
both will eventually show up in a running instance and are easier to read
about than to diagnose.

**The dedup clamp will start binding on a narrow, heavily weighted pool.**
The dedup window grows as half the publication history, and it is then
clamped so it never blocks more than 75% of what the pool offers that day.
Those two meet once the archive is roughly 1.5 times the number of species
the pool reports in `back_days` days: for a single province or state
queried over a fortnight, that is a few hundred entries in. From then on
the clamp is doing the work every day and the run report says so. When that
line starts appearing daily, the levers are: lower that pool's `weight`,
raise `back_days` so it offers more species, or accept that it repeats.
None is wrong; it is a taste call about how local the site should feel.

**The republication chip does not reach the frozen part of the full feed.**
A species published a second time gets a chip naming its previous
appearance. The web pages are re-rendered from history on every run, so
they always carry it. `feed-full.xml` does not: items outside the cap
window keep the body they were published with, so a republication that was
already frozen when the chip landed still shows no chip there. One run with
`feed_rebuild_all` (or `BOTD_FEED_REBUILD_ALL=1`) re-renders them all and
the file goes back to being append-only.
