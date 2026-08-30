# Architecture

How a run turns an eBird query into a published site: the daily pipeline,
the rules that pick a species and keep it from repeating, every URL the
build writes, the repository layout and what the test suite covers. For
installation and a first local run see the [README](../README.md); for
the knobs that change any of this see
[CONFIGURATION.md](CONFIGURATION.md), and for hosting it see
[DEPLOYMENT.md](DEPLOYMENT.md).

## How it works

```
Daily run (GitHub Actions cron 07:17 UTC, or the container's own 07:00)
  │
  ├─ 1. Pool weighted by date (in the shipped example: 35% a state,
  │     27% a country, 23% one random country from a list,
  │     15% the global taxonomy)
  ├─ 2. Species selection biased toward rarer observations, minus a
  │     dedup window that grows with the archive and is clamped to
  │     what the pool can supply today
  ├─ 3. Photo + photographer: eBird's curated og:image hero first,
  │     Macaulay Library Search API as fallback. A republication
  │     skips the hero and walks the Macaulay list for an unused
  │     photo, falling back to the normal order if it finds none
  ├─ 4. Description chain in the configured language:
  │     eBird Merlin → Wikipedia → policy-driven fallback
  ├─ 4b. LLM enrichment (when an LLM endpoint is configured):
  │     narrative prose + ID tips, structurally validated, with
  │     automatic backfill of past failures
  ├─ 5. Wikipedia URL captured (target language → English fallback)
  │     so the footer link is always present
  ├─ 6. GBIF distribution map composed (committed basemap +
  │     density overlay) and the IUCN Red List category read off
  │     the same taxon match
  ├─ 7. Site written: index.html, archive.html, one page per month,
  │     one page per species, 404.html, robots.txt, sitemap.xml,
  │     assets/site.css, assets/fonts/, assets/basemap.png; then
  │     feed.xml and feed-full.xml. Everything but the two copied
  │     binary assets is only rewritten when its bytes change
  └─ 8. On GitHub Actions: git commit + git push → Pages republishes.
        In the container the files land on the volume nginx serves
```

The selection is **deterministic by date**: two runs on the same day pick
exactly the same species. If today's entry is already in `history.json`,
publication is skipped, but maintenance always runs first: up to
`backfill_limit` past entries with a broken photograph, a missed LLM
enrichment or a failed GBIF map lookup are retried, and the feed and site
are rebuilt when any of them heal. This makes the daily cron and ad-hoc
reruns self-healing instead of duplicating work. See [Backfill and
self-healing](CONFIGURATION.md#backfill-and-self-healing).

Every file the build writes goes through a content-addressed writer, so
only the ones whose bytes actually changed are rewritten. The two
exceptions are the fonts and the basemap, which are plain copies of
committed binaries: identical every run, so they never show up as a
change either. The site is written before the feeds on purpose: every
feed item links a species page, and publishing the feed first would open
a window in which the newest item points at a page that does not exist
yet.

## Selection, dedup and repeats

One pool is drawn per day, weighted by `weight` and seeded from the date.
A regional pool asks eBird for the species seen in its region over the
last `back_days` days, up to 1000 species; the `global_taxonomy` pool
uses the whole eBird world list instead.

Within the pool, each candidate is weighted by `1 / count ** rarity_bias`,
where `count` is the number of individuals eBird reports for it over that
window. A species seen once is therefore likelier than one seen a hundred
times. `rarity_bias` is a knob, not a rule: `0` makes the draw uniform,
`0.5` (the default) is a soft nudge, `1` is a plain inverse count, and a
negative value favours the most abundant species instead. The world list
carries no counts, so every species in it weighs the same.

Duplicates are held off by a dedup window that **grows with the archive**:
it is `dedup_window` entries at minimum and half the publication history
once that is larger. The window is then clamped so it can never block
more than three quarters of what the pool offers today, which keeps at
least a quarter of the pool eligible however long the archive gets. The
run report says so out loud when the clamp binds, so you see the pool
tightening before it starts repeating. If a pool answers with nothing at
all (a network error, a region with no recent observations), there is one
rescue attempt against the global taxonomy.

When a species does come back, it is normally not a carbon copy of the
first time. The rated Macaulay list is walked past every asset that
species has already been published with, so a repeat usually arrives with
a photo you have not seen. It is a preference, not a guarantee: when the
library offers nothing new, the ordinary lookup runs anyway and the photo
can repeat, on the principle that a familiar photograph beats no
photograph.

The entry also carries a chip naming its previous publication date. It
appears wherever that entry is rendered: the home hero, its month-bucket
plate, its grid card, and its RSS item. The species' own page is the one
place that leaves it out, since that page already lists every date the
species has been published.

## Endpoints

GitHub Pages serves the generated site as static routes from the
repository root, and the Docker image's nginx serves the same routes from
its volume:

| Route | What it is |
|---|---|
| `/` (`index.html`) | Hero of the day's bird + a grid of the twelve published before it |
| `/archive.html` | Archive front: the current month as cards, plus a directory of every month |
| `/archive-YYYY-MM.html` | Every plate published that month, with permanent anchors (`#bird-{code}-{date}`) |
| `/birds/{code}.html` | Canonical page for a species, with its publication history |
| `/feed.xml` | RSS 2.0 feed with rich `content:encoded` HTML |
| `/feed-full.xml` | The same feed with the complete history, when a cap is set |
| `/sitemap.xml` | The four HTML page classes above with a `lastmod` each. Written only when `feed_link` is set |
| `/robots.txt` | Allows everything, and names the sitemap when there is one |
| `/404.html` | Error page with the site's own chrome. GitHub Pages serves it natively |
| `/assets/` | `site.css`, the webfonts under `fonts/`, and `basemap.png` |

`feed.xml` carries the most recent `max_feed_entries` items and is
fully re-rendered every run; `feed-full.xml` carries everything and
reuses the bodies it already published, so it grows by one item a day
instead of being rewritten.

With `max_feed_entries` at `0` there is no cap, `feed.xml` already holds
the whole history, and `feed-full.xml` is not written: a second file
would be a byte-for-byte duplicate. The pages follow the same rule and
only link `feed-full.xml` when it is published, so no page ever
advertises a file that is not there.

`data/config.json` is gitignored, so a `git pull` never touches the copy
a running deployment made: changing the cap on a live instance is a hand
edit of that file (or a `BOTD_MAX_FEED_ENTRIES` on the container), not
something an upgrade does for you. The bundled example ships
`max_feed_entries: 30`, so a fresh clone publishes both files from its
first run.

Item bodies outside the cap window are reused exactly as published, so
`feed-full.xml` grows by one item a day. An entry the backfill repairs is
re-rendered automatically, but a purely retroactive edit is not: a
corrected common name, a new cross-link or a catalog change only reaches
the frozen part of the history when you ask for it with
`BOTD_FEED_REBUILD_ALL=1` (or `"feed_rebuild_all": true` in the config),
which re-renders every item once and then goes back to reusing them.

Everything is server-rendered HTML: no JavaScript framework, no build
step, no asset pipeline. Three small fragments of vanilla JS are inlined,
and there is no other script anywhere: a boot snippet in `<head>` that
applies the stored theme before first paint, the theme toggle's own
`onclick`, and, on `archive.html` only, a redirect for legacy anchors
(see [Archive and permalinks](#archive-and-permalinks) below). The first
two are one feature seen from two places: the light/dark preference,
persisted in `localStorage`.

The two webfonts (Fraunces and Source Serif 4, both OFL 1.1) are
committed to the repository under `data/assets/fonts/` and published to
`assets/fonts/` on every build, so rendering a page makes no request to
any font CDN. For the complete list of what does leave the reader's
browser, see [Privacy](../README.md#privacy).

## Archive and permalinks

The archive is paginated by calendar month instead of one growing page.
`archive.html` is the archive front: the current month rendered as
cards, plus a directory of every month grouped by year.
`archive-YYYY-MM.html` is a month bucket: every plate published in that
month, in full, oldest and newest linked to their neighboring buckets.

Three kinds of link make up the permalink contract:

- **Species page** (`/birds/{code}.html`) is the canonical URL for a
  bird. It never changes, always shows the most recent publication as
  the plate, and lists every date the species has been published.
- **Bucket anchor** (`archive-YYYY-MM.html#bird-{code}-{date}`) is the
  permalink for one publication: the month page it lives on, plus its
  anchor.
- **Legacy anchor**: before the archive was split into months, every
  publication's permalink was `archive.html#bird-{code}-{date}`, and
  that format was already delivered to RSS subscribers. A small inline
  script on `archive.html` reads the fragment, derives the month from
  the date it encodes, and redirects to the matching bucket page and
  anchor, so old links keep working.

The species-name cross-linker (`name_linker.py`) points at species
pages, never at a bucket anchor, so a link inserted in today's
description keeps resolving after the entry it points to moves into an
older month bucket.

## Repository layout

```
Bird-of-the-day/
├── .github/
│   ├── bird-of-the-day.yml.example  # copy to workflows/ to enable daily cron
│   └── workflows/
│       ├── docker-publish.yml       # build & push multi-arch image to ghcr.io
│       └── quality.yml              # run the test suite on PRs and code pushes
├── Dockerfile                  # multi-stage container build
├── .dockerignore
├── docker-compose.yml          # one-command self-host
├── docker/
│   ├── crontab                 # supercronic schedule (07:00 UTC)
│   ├── entrypoint.sh           # cold-start + supercronic + exec nginx
│   ├── healthcheck.sh          # smart freshness check (36h window)
│   ├── nginx.conf              # non-root nginx, port 8080, 404 page, allow-list
│   └── placeholder.html        # cold-start fallback page
├── scripts/
│   ├── __init__.py        # esc_html + load_json_cache, shared by every module
│   ├── generate.py        # orchestrator (entry point)
│   ├── http_client.py     # shared retry session + validated image download
│   ├── ebird_client.py    # eBird API + species selection + taxonomy cache
│   ├── image_fetcher.py   # eBird og:image hero, Macaulay Library API fallback
│   ├── content_scraper.py # eBird og:description + Wikipedia + BoW
│   ├── distribution_map.py # GBIF taxon match, density tile URL, IUCN category
│   ├── llm_enricher.py   # optional LLM content enrichment
│   ├── llm_validator.py   # structural checks on LLM output (hard/soft)
│   ├── map_composer.py    # server-side map composition for RSS
│   ├── name_linker.py     # species name cross-linking
│   ├── feed_builder.py    # RSS 2.0 generation, both feeds
│   ├── site_builder.py    # index page, plus the chrome/plate/card renderers shared by every page
│   ├── archive_builder.py # archive front, month buckets, species pages, sitemap/robots/404; owns write_site()
│   ├── site_css.py        # the stylesheet, as a Python string, written to assets/site.css
│   ├── urls.py            # canonical URL/anchor scheme shared by every page and the feed
│   ├── atomic_io.py       # content-addressed atomic writes (skip pages whose bytes didn't change)
│   ├── backfill.py        # self-healing retry of past degraded entries
│   ├── run_report.py      # run summary + GitHub Actions annotations
│   ├── i18n.py            # Catalog loader + langid wrapper
│   └── seed_mock.py       # developer-only: populate the site for visual review
├── tests/                 # pytest suite, one module per concern
├── data/
│   ├── config.example.json     # copy to config.json and customize
│   ├── assets/basemap@2x.png   # committed OSM/GBIF world tile (map base layer)
│   ├── assets/fonts/           # self-hosted woff2 webfonts, OFL 1.1 (+ OFL.txt)
│   └── i18n/{es,en,fr,pt}.json # translation catalogs
├── cache/                 # taxonomy + per-species caches (generated)
├── maps/                  # composed distribution maps for RSS (generated)
├── birds/                 # one canonical page per species ever published (generated)
├── assets/                # site.css + basemap.png + fonts/, written at build time (generated)
├── docs/
│   ├── ARCHITECTURE.md    # this file
│   ├── CONFIGURATION.md   # every knob, and how to add a language
│   └── DEPLOYMENT.md      # GitHub Actions, Docker, GitHub Pages
├── CNAME.example          # copy to CNAME for custom domain setup
├── .env.example           # environment variable template
├── .gitignore             # secrets, the venv, and the generated site output
├── .gitattributes         # forces LF on generated output, so Windows runs don't churn it
├── .python-version        # the interpreter uv installs; CI reads it too
├── pyproject.toml         # dependencies and uv metadata
├── uv.lock                # lock file
├── ROADMAP.md             # features under consideration
├── LICENSE                # MIT
└── README.md
```

## Tests and CI

Run the suite locally with:

```bash
uv run pytest
```

`.github/workflows/quality.yml` runs the same thing (`uv sync`, then
`uv run pytest -q`) on every pull request, and on a push that touches
`scripts/`, `tests/`, `data/`, `pyproject.toml`, `uv.lock`,
`.python-version` or the workflow itself. That path filter is the point:
a live instance's daily bot commits nothing but generated output, and
none of it changes what the suite verifies, so the filter keeps those
commits from burning CI minutes every single day. Documentation is
outside that list too, so a docs-only push does not run the suite, while
a pull request always does whatever it touches. No Python version is
pinned in the workflow; `uv` reads `.python-version` at the repository
root, so there is one source of truth for it.

### The browser tests

`tests/test_browser.py` is the one module that needs a real rendering
engine, and it holds only what Python structurally cannot answer: that
the webfonts actually painted rather than silently falling back, that no
request leaves the site beyond the two hot links it is allowed, that the
card link draws a focus ring and has an accessible name, that
`prefers-reduced-motion` really neutralises the transitions, that a URL
which does not exist answers with a 404 status, and that nothing
overflows sideways at 390 CSS pixels.

It serves the very site `tests/site_fixture.py` builds for the
end-to-end tests, over HTTP rather than `file://`, because relative
paths, the 404 status and font loading all behave differently on the
two. One species in that fixture carries a GBIF distribution map and
the rest do not, on purpose: the atlas frame is the widest thing a
plate draws, so a fixture with no mapped species would leave the
overflow check blind to the hardest case. `test_browser.py` asserts the
atlas is actually present on the three page classes that render a plate,
so that coverage cannot evaporate silently. Playwright is a dev dependency and must stay one; the module skips
itself when Playwright is missing and each test skips when its browser
is, so `uv run pytest` on a fresh clone is green plus skips, never an
error.

The `browser` job in `quality.yml` is what actually runs it: a second
job that installs Chromium and passes `-m browser`, kept separate so
that a browser download failing, or a rendering engine changing its mind
about a computed style, never takes the ordinary test signal with it.

There is **no linter and no type checker** configured in this repository,
and the workflow does not run one. If you want them, that is your call to
make in your own clone.

The other workflow, `.github/workflows/docker-publish.yml`, builds and
pushes the multi-arch image. It is guarded by a repository check
(`if: github.repository == '...'`) so a clone does not try to publish to
a package registry it has no business writing to. Point it at your own
repository if you want your clone to build its own image.
