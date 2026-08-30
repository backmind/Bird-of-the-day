# Bird of the Day

[![Docker publish](https://github.com/backmind/Bird-of-the-day/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/backmind/Bird-of-the-day/actions/workflows/docker-publish.yml)
[![Release](https://img.shields.io/github/v/release/backmind/Bird-of-the-day?display_name=tag&sort=semver)](https://github.com/backmind/Bird-of-the-day/releases/latest)
[![Container](https://img.shields.io/badge/ghcr.io-bird--of--the--day-blue?logo=docker&logoColor=white)](https://github.com/backmind/Bird-of-the-day/pkgs/container/bird-of-the-day)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)

A daily bird species RSS feed and minimal static site, self-hostable as a
microservice. Each day a new species is selected from a configurable
weighted pool of regions, scraped from public Cornell Lab sources, and
published to a GitHub Pages site plus an RSS endpoint.

The example configuration ships with US-weighted pools. Copy
`data/config.example.json` to `data/config.json` and adjust the regions,
language and weights to your taste. English, Spanish, French and
Portuguese catalogs are included. Adding another language is one JSON
file under `data/i18n/`.

Optional LLM enrichment generates warm, narrative prose and field-ID
tips from the scraped sources whenever an OpenAI-compatible endpoint is
configured, trying an ordered chain of models until one succeeds. The
project runs fine without it, publishing the scraped description
directly. No tracking, no cookies.

## Endpoints

GitHub Pages serves the generated site as static routes from the
repository root:

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
any font CDN. The only requests that leave the site are the Macaulay
Library photo CDN and the GBIF occurrence-density tile.

### Archive and permalinks

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

## How it works

```
GitHub Actions (cron daily 07:00 UTC)
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
  └─ 8. git commit + git push → GitHub Pages republishes
```

The selection is **deterministic by date**: two runs on the same day pick
exactly the same species. If today's entry is already in `history.json`,
publication is skipped, but maintenance always runs first: up to
`backfill_limit` past entries with a missed LLM enrichment or a failed
GBIF map lookup are retried, and the feed and site are rebuilt when any
of them heal. This makes the daily cron and ad-hoc reruns self-healing
instead of duplicating work. See [Backfill and
self-healing](#backfill-and-self-healing) below.

### Selection, dedup and repeats

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

## Stack

- Python 3.12+, managed with [`uv`](https://github.com/astral-sh/uv)
- Four runtime dependencies: `requests`, `beautifulsoup4`, `langid`, `Pillow`
- One dev dependency: `pytest`
- No database. State lives in a few paths next to the code: `history.json`
  is the record of what was published, `cache/` holds the per-species
  scrapes and the taxonomy, `maps/` the composed map PNGs. Everything
  else (the pages, the feeds, `assets/`, `birds/`) is regenerated from
  those on every run

## Local installation

```bash
git clone https://github.com/backmind/Bird-of-the-day.git
cd Bird-of-the-day
uv sync
cp data/config.example.json data/config.json
# edit data/config.json — set your language, pools, feed_link
```

## Configuration

### Environment variables

| Variable | Required | Where to get it |
|---|---|---|
| `EBIRD_API_KEY` | yes | Free at <https://ebird.org/api/keygen> |
| `BOTD_LLM_API_KEY` | only if LLM enrichment is configured | Your LLM provider (e.g. [Google AI Studio](https://aistudio.google.com/apikey)) |

For local use copy `.env.example` to `.env` and fill the key:

```bash
cp .env.example .env
# edit .env
```

`.env` is gitignored and `generate.py` loads it automatically (no
`python-dotenv` required).

In GitHub Actions the key is injected from `Settings → Secrets and
variables → Actions → New repository secret` with the same name.

### `data/config.json`

Copy the bundled example and edit it:

```bash
cp data/config.example.json data/config.json
```

Every behavior knob lives here. This is what the bundled example ships,
with its `_*_help` keys elided for brevity (the file itself annotates
every one of them in place):

```json
{
  "language": "en",
  "ebird_locale": null,

  "description_policy": "foreign_fallback",
  "max_skip_retries": 50,

  "pools": [
    {"id": "local",   "region": "US-NY", "weight": 0.35, "type": "regional"},
    {"id": "country", "region": "US",    "weight": 0.27, "type": "regional"},
    {"id": "europe", "weight": 0.23, "type": "europe_random",
     "countries": ["PT", "FR", "IT", "DE", "GB", "GR", "SE", "NO", "PL"]},
    {"id": "global", "weight": 0.15, "type": "global_taxonomy"}
  ],
  "dedup_window": 50,
  "rarity_bias": 0.5,
  "max_feed_entries": 30,
  "feed_rebuild_all": false,
  "back_days": 14,
  "backfill_limit": 3,

  "feed_link": "",

  "site_author": "",
  "site_author_url": "",

  "llm": {
    "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai",
    "models": ["gemini-2.5-flash"],
    "temperature": 0.6,
    "judge": false
  }
}
```

Keys starting with `_` are documentation-only and ignored at load time.

Two of these are worth setting before your first run. `feed_link` is the
absolute base URL of your deployed site: without it there is no absolute
URL to build, so the feed items fall back to eBird, the Open Graph tags
are omitted entirely rather than emitted unresolvable, and no
`sitemap.xml` is written. `site_author` is your name; see
[Authorship](#authorship) below for what it does and what happens when
you leave it empty.

### Authorship

The footer carries two credits, and they are deliberately separate.

The **template credit** names whoever wrote this software and links its
repository. It is fixed, it comes from the i18n catalog, it appears on
every page, and there is no configuration knob that turns it off.

The **instance author** is you. Set `site_author` (and, optionally,
`site_author_url` to link it) and your name appears in its own footer
paragraph and in the RSS channel's `<copyright>`. Leave it empty and
neither the site nor the feed attributes the content to anyone. That is
the correct behavior for a fresh clone: a site that has published nothing
of its own yet should not claim an author, and it must never inherit the
name of whoever's instance you cloned from.

Upgrading an existing instance: these two keys are new, and
`data/config.json` is gitignored, so merging this version does not add
them to the copy your deployment already has. That matters more than a
missing knob usually would, because the footer's author line used to be
unconditional, with the name baked into the i18n catalog. It is now
conditional on `site_author`. Until you add the key by hand (or set
`BOTD_SITE_AUTHOR` on the container), your footer and your feed's
`<copyright>` carry only the template credit, and your name quietly stops
appearing on a site that used to show it. Two lines in
`data/config.json`, and it is back.

### LLM enrichment

| Key | Meaning |
|---|---|
| `llm.endpoint` | OpenAI-compatible chat completions base URL. Omit the whole `llm` block (or leave it unset) to disable enrichment. |
| `llm.models` | Ordered fallback chain, e.g. `["gemini-2.5-flash", "gemini-2.0-flash"]`. Models are tried in turn until one returns valid content. Pin concrete model names, not `-latest` aliases, so a provider-side swap can't silently change output mid-chain. |
| `llm.temperature` | Sampling temperature passed to the endpoint. |
| `llm.judge` | Enables an optional second-pass fact-check: a follow-up call reviews the draft against the scraped sources and can send it back for revision. Off by default; adds one extra request per entry. |
| `llm.max_retries` | Retries per model before moving to the next one in the chain (default `3`, so up to 4 attempts on a given model, with increasing backoff between them). |

Enrichment runs automatically whenever `llm.endpoint`, `llm.models` and
the `BOTD_LLM_API_KEY` env var are all set; there is no separate on/off
flag. A failed or invalid LLM response falls back to the scraped
programmatic description for that day rather than failing the run, and
the miss is picked up by the next run's backfill pass.

### Backfill and self-healing

Every run, before touching today's entry, the generator retries a
bounded number of past failures: entries published without an LLM
enrichment (the endpoint was down or misconfigured that day) or without
a GBIF distribution map (a transient lookup error). `backfill_limit`
caps how many such healing actions run per invocation, newest entry
first (default `3`; `0` disables self-healing). Override it with the
`BOTD_BACKFILL_LIMIT` environment variable. Healed entries trigger a
feed and site rebuild even on days when today's bird was already
published.

### Description policy

What happens when none of the sources (eBird Merlin, target-language
Wikipedia) returns text in your configured language:

| Policy | Behavior |
|---|---|
| `foreign_fallback` (default) | Show the original text with a disclaimer naming the source language (e.g. *"Description in English (no French translation available)"*). |
| `strict` | Show an em-dash placeholder. Never display foreign text. |
| `skip` | Re-roll species selection up to `max_skip_retries` times. On exhaustion, publishes the last species it tried, whose description is empty and therefore renders exactly as `strict` would. |

Even with `strict`, the footer always carries a Wikipedia link — falling
back to English Wikipedia (and labeled `Wikipedia (en)`) if the target
language has no article.

### Page metadata and social cards

Each of the four page classes writes its own `<meta name="description">`
from a catalog template: the home page names today's bird, the archive
front counts the birds published so far, a month bucket names its month,
a species page names its species. There is no shared site-wide tagline
for them to fall back on, on purpose: four different documents should
never describe themselves identically.

The same four classes emit Open Graph tags (`og:title`, `og:type`,
`og:url`, `og:description`, and `og:image` when the page has a photo),
which is what a link to the site unfurls into on a chat client or a
social network. The whole block is emitted only when `feed_link` is
configured, since a relative `og:url` is worse than none: no client
consuming the tag could resolve it.

The `feed.description` string in `data/i18n/*.json` is the RSS channel's
own description, and it is intentionally generic ("A new bird species
every day."): the regional flavor of the site is decided by `pools` in
`data/config.json`, not baked into the copy. If you want a
region-specific one, edit the catalog of the language you're shipping in.

## Running

### Locally

```bash
uv run python -m scripts.generate
```

This:

1. Loads `.env` if present, then any secret pointed at by a `*_FILE`
   variable.
2. Loads the config and the i18n catalog for the configured language.
3. Runs maintenance first, before anything else: up to `backfill_limit`
   past entries with a missed enrichment or a failed GBIF lookup are
   retried.
4. If today's entry is already in `history.json`, re-renders the whole
   site and both feeds and stops. Nothing on disk actually changes unless
   the backfill above healed something. This rebuild is skipped, with a
   warning, when maintenance or the taxonomy fetch failed: republishing
   every page with an empty cross-link catalog would overwrite good
   output with degraded output.
5. Otherwise selects the species and fetches image and content, writing
   to `cache/`.
6. Appends the entry to `history.json`.
7. Writes the site: `index.html`, `archive.html`, one page per month
   bucket, one page per species, `404.html`, `robots.txt`, `sitemap.xml`
   (only when `feed_link` is set), `assets/site.css`, `assets/fonts/`
   and `assets/basemap.png`.
8. Writes `feed.xml` and, when a cap is set, `feed-full.xml`.

Every one of those files goes through a content-addressed writer, so only
the ones whose bytes actually changed are rewritten. The two exceptions
are the fonts and the basemap, which are plain copies of committed
binaries: identical every run, so they never show up as a change either.
The site is written before the feeds on purpose: every feed item links a
species page, and publishing the feed first would open a window in which
the newest item points at a page that does not exist yet.

To force a regeneration of today's entry, empty the history:

```bash
echo '{"entries": []}' > history.json
uv run python -m scripts.generate
```

### Via GitHub Actions

Copy `.github/bird-of-the-day.yml.example` to
`.github/workflows/bird-of-the-day.yml` to enable the daily cron. It runs:

- Automatically every day at **07:00 UTC**.
- Manually from the **Actions → Bird of the Day → Run workflow** tab.

The workflow `git add -f`s `feed.xml`, `history.json`, `index.html`,
`archive.html`, `birds/`, `cache/`, `maps/` and `assets/` (which carries
the stylesheet, the fonts and the basemap) in one command. Everything
else goes through a loop that stages one path at a time, guarded by a
test that the path exists: `archive-*.html`, then `feed-full.xml`,
`sitemap.xml`, `robots.txt` and `404.html`.

That loop is not a stylistic choice and should not be "simplified" back
into the first command. `git add -f` on a literal path that does not
exist fails outright and leaves *nothing* staged, not even the paths it
had already accepted, and since Actions runs the step under `bash -e`
that failure kills the run before it reaches the commit.

The split is between paths that are always there and paths that are only
sometimes there. The first command's are the ones a repository that has
published even once always has: the feed, the history, the two fixed
pages, and the four directories, two of which (`cache/` and `maps/`) ship
a committed `.gitkeep` precisely so they exist before anything fills
them. Everything in the loop is conditional. `feed-full.xml` needs a feed
cap and `sitemap.xml` needs a configured `feed_link`, so neither exists
on an instance that has set neither. `archive-*.html` is subtler: the
buckets are written by the site build, and the site build is skipped on a
run where maintenance or the taxonomy fetch failed, so on a repository
that has not yet committed a bucket file the pattern can match nothing.
An unmatched glob is left literal by the shell, which is exactly what the
existence test is there to drop.

The rule for anyone extending this step: a new path goes in the loop
unless you can show it is present on every run that reaches it.

It then commits with a message of the form `🐦 Bird of the day:
2026-04-11`, rebases onto the remote and pushes. The rebase step names
`origin main` explicitly, so change it if your default branch is called
something else.

Every run writes a summary to the job log, whether or not anything is
degraded. In GitHub Actions specifically, each degraded step (a failed
backfill healing action, an LLM enrichment that fell back to the
programmatic description) is also surfaced as an `::warning::` build
annotation and appended to the job's step summary. The job itself still
succeeds (the site keeps publishing through outages); this reporting
just makes degradation visible instead of silently hiding it in the
scraped-fallback output.

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
commits from burning CI minutes every single day. No Python version is
pinned in the workflow; `uv` reads `.python-version` at the repository
root, so there is one source of truth for it.

There is **no linter and no type checker** configured in this repository,
and the workflow does not run one. If you want them, that is your call to
make in your own clone.

The other workflow, `.github/workflows/docker-publish.yml`, builds and
pushes the multi-arch image. It is guarded by a repository check
(`if: github.repository == '...'`) so a clone does not try to publish to
a package registry it has no business writing to. Point it at your own
repository if you want your clone to build its own image.

## Self-hosting

Two paths, pick whichever fits your taste. They are peer options, not
replacements: pick GitHub Pages if you want a free hosted site with zero
ops, or Docker if you run your own server.

| Path | Best for | Cost | Ops |
|---|---|---|---|
| GitHub Actions + Pages | "I just want a free site." | Free | None |
| Docker container | "I run my own server / VPS / Pi / fly.io." | A host with Docker | Standard container ops |

### Self-hosting with Docker

The image is published to `ghcr.io/backmind/bird-of-the-day` for
`linux/amd64` and `linux/arm64`. It runs nginx on port 8080 and a
built-in cron (supercronic) that regenerates the site daily at 07:00 UTC,
matching the GitHub Actions cadence. Total image size: ~340 MB.

nginx serves an explicit allow-list of routes (no directory listings, and
the `cache/` subtree is never exposed) and everything else returns 404.
The generated `404.html` is what those 404s render, with the site's own
chrome and the real status code preserved; it is the one route served
`no-store`, so an intermediary cannot cache a 404 for a species page that
becomes valid the day its bird is first published.

#### Quick start

```bash
docker run -d --name bird-of-the-day \
  -p 8080:8080 \
  -e EBIRD_API_KEY=YOUR_KEY \
  -v botd-data:/var/lib/botd \
  --restart unless-stopped \
  ghcr.io/backmind/bird-of-the-day:latest
```

Open <http://localhost:8080>. On a fresh container the first request may
take 30–60 seconds while the generator runs synchronously to populate
the volume.

#### Docker Compose

A ready-to-use `docker-compose.yml` lives at the repo root with sensible
defaults (named volume, healthcheck, `cap_drop: ALL`,
`no-new-privileges`). Set `EBIRD_API_KEY` in your shell or a sibling
`.env` file and run:

```bash
docker compose up -d
```

#### Configuration via environment variables

Scalar config knobs can be tweaked without rebuilding the image or
mounting a custom config file. Each maps to a key in `data/config.json`
and overrides it if set:

| Env var | Maps to | Example |
|---|---|---|
| `BOTD_LANGUAGE` | `language` | `en`, `fr`, `pt` |
| `BOTD_EBIRD_LOCALE` | `ebird_locale` | `pt_BR` |
| `BOTD_DESCRIPTION_POLICY` | `description_policy` | `strict`, `foreign_fallback`, `skip` |
| `BOTD_MAX_SKIP_RETRIES` | `max_skip_retries` | `50` |
| `BOTD_DEDUP_WINDOW` | `dedup_window` | `50` |
| `BOTD_RARITY_BIAS` | `rarity_bias` | `0` |
| `BOTD_MAX_FEED_ENTRIES` | `max_feed_entries` | `60` |
| `BOTD_FEED_REBUILD_ALL` | `feed_rebuild_all` | `1` |
| `BOTD_BACK_DAYS` | `back_days` | `14` |
| `BOTD_BACKFILL_LIMIT` | `backfill_limit` | `3` |
| `BOTD_FEED_LINK` | `feed_link` | `https://example.com/birds/` |
| `BOTD_SITE_AUTHOR` | `site_author` | `Jane Doe` |
| `BOTD_SITE_AUTHOR_URL` | `site_author_url` | `https://example.com` |

That table is the complete set: every scalar knob that can be overridden
from the environment is in it, and nothing else is. Nested structures
(`pools`, `llm`) are not overridable; mount a custom file instead.

`EBIRD_API_KEY` is required. LLM enrichment runs whenever
`llm.endpoint`, `llm.models` and the `BOTD_LLM_API_KEY` env var are
all set; otherwise the site renders the scraped descriptions
directly. The image ships no `.env` file and does not need one, since
env vars work everywhere; the loader is still there, so a `.env` mounted
at `/app/.env` would be read.

One more variable is not a config override: `BOTD_STATE_DIR` is where all
mutable state is written. The image sets it to `/var/lib/botd`, the
volume mount point. Unset (local runs, GitHub Actions) it defaults to the
repository root, which is the layout the rest of this README describes.

#### Secrets via files (Docker / Kubernetes secrets)

Standard Docker / k8s secrets convention: instead of passing the key as
an env var, mount a file containing the key and point at it with
`EBIRD_API_KEY_FILE`:

```bash
docker run ... \
  --secret source=ebird_api_key,target=/run/secrets/ebird_api_key \
  -e EBIRD_API_KEY_FILE=/run/secrets/ebird_api_key \
  ghcr.io/backmind/bird-of-the-day
```

In Kubernetes, mount a Secret as a volume and set
`EBIRD_API_KEY_FILE` to the mounted path. If both `EBIRD_API_KEY` and
`EBIRD_API_KEY_FILE` are set, the env var wins.

#### Mounting a custom `data/config.json`

The `pools` matrix is a nested structure not exposed via env vars
(stringifying it would be painful). To customise it without forking
the repo and rebuilding:

```bash
# 1. Copy the example and edit it
cp data/config.example.json my-config.json

# 2. Mount it into the container:
docker run -d ... \
  -v ./my-config.json:/app/data/config.json:ro \
  ghcr.io/backmind/bird-of-the-day
```

The mount is `:ro` (read-only) — the container only reads it.

#### Volume contents

The single volume at `/var/lib/botd` holds all mutable state:

```
/var/lib/botd/
├── cache/               # per-species + taxonomy caches
├── maps/                # composed distribution maps embedded in the RSS feed
├── assets/              # site.css + basemap.png + fonts/, written/copied at build time
├── birds/               # one canonical page per species ever published
├── feed.xml             # the RSS feed
├── feed-full.xml        # the same feed, whole history (only when a cap is set)
├── index.html           # the front page
├── archive.html         # the archive front (current month + month directory)
├── archive-YYYY-MM.html # one page per calendar month, every plate published in it
├── 404.html             # error page, served by nginx with a real 404 status
├── robots.txt           # always written; names the sitemap only when there is one
├── sitemap.xml          # only when feed_link is set
└── history.json         # the full publication history
```

Back this up and you can rebuild the running container without losing a
single day. The default schedule writes to it once per day at 07:00 UTC.

#### Health checks

The container's `HEALTHCHECK` verifies three things every 5 minutes:

1. `feed.xml` exists on the volume.
2. `feed.xml` was modified within the last 36 hours.
3. nginx is actually serving `/feed.xml` on port 8080.

If the daily cron silently stops working, the container goes
`unhealthy` within 36 hours — that's the **intended** behavior, and
your orchestrator (k8s / docker swarm / fly machines / etc.) will
surface it. The 36 h window gives the daily 07:00 UTC run a 12 h grace
period.

There's also a cheap liveness probe at `/healthz` that just returns
`200 ok` if nginx is up.

#### Hardened deployment

The container runs as a non-root user (`botd`, uid 1000) and needs no
Linux capabilities. Recommended hardening for security-conscious
deployments:

```bash
docker run -d \
  --read-only \
  --cap-drop=ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp \
  --tmpfs /var/log/nginx \
  --tmpfs /var/lib/nginx \
  --tmpfs /run/nginx \
  -p 8080:8080 \
  -e EBIRD_API_KEY=$KEY \
  -v botd-data:/var/lib/botd \
  ghcr.io/backmind/bird-of-the-day
```

The `--read-only` root filesystem requires writable `tmpfs` for
nginx's working directories. The container has been tested in this
mode end-to-end.

Resource hints: ~50–100 MB RAM at idle, ~150 MB during generation,
bursty CPU. A floor of `mem_limit: 256m` and `cpus: 0.5` is
comfortable.

#### Building locally

```bash
docker build -t bird-of-the-day .
# Multi-arch:
docker buildx build --platform linux/amd64,linux/arm64 -t bird-of-the-day .
```

#### Cron schedule and timezone

The container is UTC by default. The cron expression in
`docker/crontab` is `0 7 * * *` (07:00 UTC, matching the GitHub
Actions workflow). To change it, edit that file and rebuild — or
mount your own at `/etc/supercronic/crontab`.

### Self-hosting on GitHub Pages

1. Click **Use this template** on the repo page (or clone manually).
2. Copy and edit the config:
   ```bash
   cp data/config.example.json data/config.json
   ```
   Set `feed_link` to your `https://<user>.github.io/<repo>/` URL,
   pick a `language`, and adjust `pools` for your regions. Set
   `site_author` too if you want the site and the feed to credit you;
   left empty, they credit no one. `feed_link` is worth getting right
   before the first run: it is what turns on `sitemap.xml`, the
   `Sitemap:` line in `robots.txt` and the Open Graph tags.
3. Activate the daily workflow:
   ```bash
   cp .github/bird-of-the-day.yml.example .github/workflows/bird-of-the-day.yml
   ```
4. If you want a custom domain, copy `CNAME.example` to `CNAME` and
   write your domain in it. Configure your DNS to point to
   `<user>.github.io`.
5. **Settings → Secrets and variables → Actions** → add `EBIRD_API_KEY`.
   Optionally add `BOTD_LLM_API_KEY` and set `llm.endpoint` / `llm.models`
   in your config to enable LLM enrichment.
6. **Settings → Pages → Build and deployment** → source: `Deploy from a
   branch`, branch: `main`, folder: `/ (root)`. Save.
7. Either wait for the daily cron or trigger **Actions → Bird of the
   Day → Run workflow** manually for the first publication.

### Pool matrix examples

Some alternative presets you can paste into `data/config.json`:

**Western US flavor:**

```json
"pools": [
  {"id": "california", "region": "US-CA", "weight": 0.35, "type": "regional"},
  {"id": "us_west",    "region": "US",    "weight": 0.27, "type": "regional"},
  {"id": "americas",   "weight": 0.23, "type": "europe_random",
   "countries": ["MX", "CA", "CR", "BR", "AR", "CO", "EC", "PE", "CL"]},
  {"id": "global",     "weight": 0.15, "type": "global_taxonomy"}
]
```

**Pan-European balance (no national bias):**

```json
"pools": [
  {"id": "europe", "weight": 0.85, "type": "europe_random",
   "countries": ["ES", "PT", "FR", "IT", "DE", "GB", "GR", "SE", "NO", "PL", "NL", "BE", "AT", "CH", "DK", "FI"]},
  {"id": "global", "weight": 0.15, "type": "global_taxonomy"}
]
```

The `type` field accepts `regional` (single region code) or
`europe_random` (list of countries, one picked per day) or
`global_taxonomy` (any species in the eBird taxonomy).

### Adding a new language

1. Copy `data/i18n/en.json` to `data/i18n/{lang}.json` (use the ISO 639-1
   code, e.g. `de`, `it`, `ca`).
2. Translate every value. Missing keys fall back to English at render
   time, so partial translations are safe.
3. Add the language name in your file, plus the names of every other
   supported language as seen from your language. For example, in `de.json`:
   ```json
   "language_name.es": "Spanisch",
   "language_name.en": "Englisch",
   "language_name.fr": "Französisch",
   "language_name.pt": "Portugiesisch",
   "language_name.de": "Deutsch"
   ```
4. Set `language: "{lang}"` in your `data/config.json`.
5. **Clear `cache/*.json`** (but keep `cache/taxonomy.json`) so existing
   per-species caches don't render in the previous language.
6. Run `uv run python -m scripts.generate` and verify.
7. Open a PR.

`langid` (the language detector) supports 97 languages out of the box;
the only constraint on which target languages are valid is that there's a
`data/i18n/{lang}.json` file.

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

## Attribution and legal notes

- **eBird API**: non-commercial use is permitted under the
  [eBird API Terms of Use](https://ebird.org/api/keygen). A run that draws
  a `regional` or `europe_random` pool makes one observations query per
  selection attempt, which is one on every policy but `skip`. A run that
  draws the `global_taxonomy` pool makes none at all: it reads the taxonomy
  it already has on disk. The two taxonomy downloads, the localized one and
  the English one the cross-linker needs, each sit behind an on-disk cache
  with a 30-day TTL, so neither is fetched more than once a month.
- **Macaulay Library**: photographs are © their authors. The project
  hot-links the public Cornell CDN for non-commercial display with
  visible photographer attribution, mirroring the embed flow Cornell
  itself offers.
- **Merlin / eBird and Birds of the World text**: © Cornell Lab of
  Ornithology. The feed reproduces short fragments with clear
  attribution and links back to the source, with no commercial purpose.
- **Wikipedia**: REST summary content is CC BY-SA 3.0; we link to the
  canonical article and don't redistribute beyond the short summary.
- **GBIF distribution maps**: occurrence density tiles are served live
  from GBIF and attributed as such. The base map layer underneath them
  is a committed static tile (`data/assets/basemap@2x.png`, GBIF's own
  `gbif-light` OpenStreetMap style, downloaded once) rather than a live
  third-party basemap request. Both layers are credited in the map
  itself: "OpenStreetMap · GBIF".
- **Webfonts**: Fraunces and Source Serif 4, both under the
  [SIL Open Font License 1.1](https://openfontlicense.org/). The `.woff2`
  files are committed under `data/assets/fonts/` alongside an `OFL.txt`
  recording their provenance; no glyphs were added, removed or modified.
- **Generated data** (feed, site): MIT, free to reuse with attribution.
  The template's own footer credit is not part of that grant: it names
  who wrote the software, and it stays on every page a clone publishes.

## Privacy

This site stores your theme preference (light/dark) in `localStorage` so
it persists between visits. That's the only client-side state, it never
leaves the browser, and it falls under the "strictly necessary functional
preferences" exemption of the EU ePrivacy Directive — no consent banner
or cookie notice is required. There are no cookies, no analytics and no
trackers.

Exactly two third-party requests are made to render a page: the Macaulay
Library CDN, for the photo, and the GBIF tile server, for the live
occurrence-density overlay on a distribution map. Nothing else leaves the
site. The typefaces are served from the site's own `assets/fonts/`, not
from a font CDN, and the base map layer under the GBIF overlay is a
committed local asset. A page with no photo and no map (the empty site,
before the first bird) makes no external request at all.

## License

[MIT](LICENSE). Third-party content (photos, Cornell text excerpts,
Wikipedia summaries) keeps its respective licenses and attributions.
