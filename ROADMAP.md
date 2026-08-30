# Roadmap

Features under consideration. Contributions welcome.

## Image carousel (frontend)

The hero photo is a single image from Macaulay Library. A lightweight carousel with left/right arrows would let the reader browse additional photos of the same species. Macaulay Library's search API supports multiple results per species.

Considerations:
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

Four gaps that are known, not forgotten. Each was cut from the work that
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

**Atomic writes for `history.json`.** Every generated page and both feeds
go through `atomic_io.write_text_if_changed`, which writes to a temporary
file and renames. `history.json` does not: `generate.save_history` calls
`Path.write_text` directly. A crash mid-write would truncate the one file
that cannot be regenerated from anything else. Cut because it is a
correctness fix to the pipeline, not a documentation or web-quality one,
and it should land with a test that actually simulates the interrupted
write.

**An end-to-end test of `generate.main()`.** Every stage is covered in
isolation and the wiring between several pairs of them is covered too, but
nothing exercises the orchestrator top to bottom against fakes. The
ordering guarantees it maintains (maintenance before publication, site
before feeds) are currently held up by comments and by review. Cut for
scope; it needs a fake for every outbound call the run makes.

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
