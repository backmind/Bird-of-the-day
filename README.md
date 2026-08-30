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

## Documentation

This file is the short version: what the site looks like when it is
running, and how to get it running on your own machine. Everything else
lives in three documents.

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**: how a run works, how
  a species is picked and kept from repeating, every URL the build
  writes, the repository layout and what CI checks.
- **[docs/CONFIGURATION.md](docs/CONFIGURATION.md)**: the environment
  variables, every key in `data/config.json`, alternative pool matrices
  and how to add a language.
- **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**: the daily GitHub Actions
  workflow, the Docker image and its volume, GitHub Pages, and the cron
  schedules.

[ROADMAP.md](ROADMAP.md) records what is under consideration, what was
deferred on purpose and the known limits of the current selection.

## What it produces

A complete static site and its RSS feeds, written to the repository root
(or, in the container, to the volume nginx serves):

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

Everything is server-rendered HTML: no JavaScript framework, no build
step, no asset pipeline. The archive is paginated by calendar month
instead of one growing page; every publication keeps a permanent anchor,
and every species has a canonical page whose URL never changes.

For the shape of each of those files, how the two feeds differ and which
one gets rewritten, and the full permalink contract, see
[Endpoints](docs/ARCHITECTURE.md#endpoints) and [Archive and
permalinks](docs/ARCHITECTURE.md#archive-and-permalinks).

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
# edit data/config.json: set your language, pools, feed_link
cp .env.example .env
# edit .env: EBIRD_API_KEY is free at https://ebird.org/api/keygen
```

`data/config.json` and `.env` are both gitignored, so neither is ever
overwritten by a `git pull`. What goes in them is documented in
[CONFIGURATION.md](docs/CONFIGURATION.md).

## Running locally

```bash
uv run python -m scripts.generate
```

This:

1. Loads `.env` if present, then any secret pointed at by a `*_FILE`
   variable.
2. Loads the config and the i18n catalog for the configured language.
3. Runs maintenance first, before anything else: up to `backfill_limit`
   past entries with a broken photograph, a missed enrichment or a failed
   GBIF lookup are retried.
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

Only the files whose bytes actually changed are rewritten, and the site
is written before the feeds on purpose. Both rules, and the reasons for
them, are in [How it works](docs/ARCHITECTURE.md#how-it-works).

To force a regeneration of today's entry, empty the history:

```bash
echo '{"entries": []}' > history.json
uv run python -m scripts.generate
```

Run the test suite with `uv run pytest`. See [Tests and
CI](docs/ARCHITECTURE.md#tests-and-ci) for what CI runs and when.

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
preferences" exemption of the EU ePrivacy Directive: no consent banner
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
