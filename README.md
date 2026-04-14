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

An optional LLM enrichment mode can generate warm, narrative prose and
field-ID tips from the scraped sources (any OpenAI-compatible endpoint).
The project runs fine without it. No tracking, no cookies.

## Endpoints

GitHub Pages serves three static routes from the repository root:

| Route | What it is |
|---|---|
| `/` (`index.html`) | Hero of the day's bird + a grid of the most recent twelve |
| `/archive.html` | Every published bird in reverse chronological order, with permanent anchors (`#bird-{code}-{date}`) |
| `/feed.xml` | RSS 2.0 feed with rich `content:encoded` HTML |

Everything is server-rendered HTML — no JavaScript framework, no build
step. The single small piece of vanilla JS is an inline theme switcher
that persists light/dark preference in `localStorage`.

## How it works

```
GitHub Actions (cron daily 07:00 UTC)
  │
  ├─ 1. Pool weighted by date (e.g. 35% Madrid, 27% Spain,
  │     23% one random European country, 15% global taxonomy)
  ├─ 2. Species selection biased toward rarer observations,
  │     deduplicated against the last 50 publications
  ├─ 3. Photo + photographer from Macaulay Library Search API
  │     (with fallback to og:image on the eBird species page)
  ├─ 4. Description chain in the configured language:
  │     eBird Merlin → Wikipedia → policy-driven fallback
  ├─ 4b. (optional) LLM enrichment: sends scraped data to an
  │     OpenAI-compatible endpoint, receives narrative prose + ID tips
  ├─ 5. Wikipedia URL captured (target language → English fallback)
  │     so the footer link is always present
  ├─ 6. GBIF distribution map composed (basemap + density overlay)
  ├─ 7. feed.xml + index.html + archive.html written
  └─ 8. git commit + git push → GitHub Pages republishes
```

The selection is **deterministic by date**: two runs on the same day pick
exactly the same species. The script bails early if today's entry is
already in `history.json`, so the daily cron and ad-hoc reruns don't
duplicate work.

## Stack

- Python 3.12+, managed with [`uv`](https://github.com/astral-sh/uv)
- Four runtime dependencies: `requests`, `beautifulsoup4`, `langid`, `Pillow`
- No database. State lives in three files in the repo: `feed.xml`,
  `history.json`, `cache/`

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
| `BOTD_LLM_API_KEY` | only for `enriched` mode | Your LLM provider (e.g. [Google AI Studio](https://aistudio.google.com/apikey)) |

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

Every behavior knob lives here. Annotated example:

```json
{
  "language": "es",
  "_language_help": "One of es | en | fr | pt (or any other catalog you add).",

  "ebird_locale": null,
  "_ebird_locale_help": "Optional override for the eBird API locale (e.g. 'pt_BR'). If null, derived from `language`.",

  "description_policy": "foreign_fallback",
  "_description_policy_help": "How to render descriptions when no source produces text in the configured language. One of: strict | foreign_fallback | skip.",
  "max_skip_retries": 50,

  "pools": [
    {"id": "madrid", "region": "ES-MD", "weight": 0.35, "type": "regional"},
    {"id": "spain",  "region": "ES",    "weight": 0.27, "type": "regional"},
    {"id": "europe", "weight": 0.23, "type": "europe_random",
     "countries": ["PT", "FR", "IT", "DE", "GB", "GR", "SE", "NO", "PL"]},
    {"id": "global", "weight": 0.15, "type": "global_taxonomy"}
  ],
  "dedup_window": 50,
  "max_feed_entries": 60,
  "back_days": 14,

  "feed_link": "https://YOUR-USERNAME.github.io/Bird-of-the-day/",

  "content_mode": "programmatic",
  "llm": {
    "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai",
    "model": "gemini-flash-latest",
    "temperature": 0,
    "max_retries": 2
  }
}
```

Keys starting with `_` are documentation-only and ignored at load time.

### Description policy

What happens when none of the sources (eBird Merlin, target-language
Wikipedia) returns text in your configured language:

| Policy | Behavior |
|---|---|
| `foreign_fallback` (default) | Show the original text with a disclaimer naming the source language (e.g. *"Description in English (no French translation available)"*). |
| `strict` | Show an em-dash placeholder. Never display foreign text. |
| `skip` | Re-roll species selection up to `max_skip_retries` times. On exhaustion, falls back to `strict`. |

Even with `strict`, the footer always carries a Wikipedia link — falling
back to English Wikipedia (and labeled `Wikipedia (en)`) if the target
language has no article.

The `site.tagline` and `feed.description` strings in `data/i18n/*.json`
are intentionally generic ("A new bird species every day."): the regional
flavor of the site is decided by `pools` in `data/config.json`, not baked
into the copy. If you want a region-specific tagline, edit the catalog of
the language you're shipping in.

## Running

### Locally

```bash
uv run python -m scripts.generate
```

This:

1. Loads `.env` if present.
2. Loads the i18n catalog for the configured language.
3. Bails early if today's entry is already in `history.json`.
4. Selects the species, fetches image and content (writing to `cache/`).
5. Writes `feed.xml`, `index.html`, `archive.html`.
6. Updates `history.json`.

To force a regeneration of today's entry, empty the history:

```bash
echo '{"entries": []}' > history.json
uv run python -m scripts.generate
```

### Via GitHub Actions

`.github/workflows/bird-of-the-day.yml` runs:

- Automatically every day at **07:00 UTC** (09:00 CEST in Madrid).
- Manually from the **Actions → Bird of the Day → Run workflow** tab.

The workflow `git add`s `feed.xml`, `history.json`, `index.html`,
`archive.html` and `cache/`, then commits with a message of the form
`🐦 Bird of the day: 2026-04-11` and pushes to the default branch.

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
| `BOTD_MAX_FEED_ENTRIES` | `max_feed_entries` | `60` |
| `BOTD_BACK_DAYS` | `back_days` | `14` |
| `BOTD_FEED_LINK` | `feed_link` | `https://example.com/birds/` |
| `BOTD_CONTENT_MODE` | `content_mode` | `programmatic`, `enriched` |

`EBIRD_API_KEY` is required. `BOTD_LLM_API_KEY` is needed only when
`content_mode` is `enriched`. The container does **not** read `.env`
files (it doesn't need to — env vars work everywhere).

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
├── cache/         # per-species + taxonomy caches
├── feed.xml       # the RSS feed
├── index.html     # the front page
├── archive.html   # the chronological archive
└── history.json   # the full publication history
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
   pick a `language`, and adjust `pools` for your regions.
3. If you want a custom domain, copy `CNAME.example` to `CNAME` and
   write your domain in it. Configure your DNS to point to
   `<user>.github.io`.
4. **Settings → Secrets and variables → Actions** → add `EBIRD_API_KEY`.
   Optionally add `BOTD_LLM_API_KEY` if using enriched mode.
5. **Settings → Pages → Build and deployment** → source: `Deploy from a
   branch`, branch: `main`, folder: `/ (root)`. Save.
6. Either wait for the daily cron or trigger **Actions → Bird of the
   Day → Run workflow** manually for the first publication.

### Pool matrix examples

The default leans Iberian. Some alternative presets you can paste into
`data/config.json`:

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
├── .github/workflows/
│   ├── bird-of-the-day.yml     # daily cron + commit (GitHub Pages path)
│   └── docker-publish.yml      # build & push multi-arch image to ghcr.io
├── Dockerfile                  # multi-stage container build
├── .dockerignore
├── docker-compose.yml          # one-command self-host
├── docker/
│   ├── crontab                 # supercronic schedule (07:00 UTC)
│   ├── entrypoint.sh           # cold-start + supercronic + exec nginx
│   ├── healthcheck.sh          # smart freshness check (36h window)
│   ├── nginx.conf              # non-root nginx, port 8080
│   └── placeholder.html        # cold-start fallback page
├── scripts/
│   ├── generate.py        # orchestrator (entry point)
│   ├── ebird_client.py    # eBird API + species selection + taxonomy cache
│   ├── image_fetcher.py   # Macaulay Library API + og:image fallback
│   ├── content_scraper.py # eBird og:description + Wikipedia + BoW
│   ├── llm_enricher.py   # optional LLM content enrichment
│   ├── map_composer.py    # server-side map composition for RSS
│   ├── name_linker.py     # species name cross-linking
│   ├── feed_builder.py    # RSS 2.0 generation
│   ├── site_builder.py    # index.html + archive.html generation
│   ├── i18n.py            # Catalog loader + langid wrapper
│   └── seed_mock.py       # developer-only: populate the site for visual review
├── data/
│   ├── config.example.json     # copy to config.json and customize
│   └── i18n/{es,en,fr,pt}.json # translation catalogs
├── cache/                 # taxonomy + per-species caches (generated)
├── maps/                  # composed distribution maps (generated)
├── CNAME.example          # copy to CNAME for custom domain setup
├── .env.example           # environment variable template
├── pyproject.toml         # dependencies and uv metadata
├── uv.lock                # lock file
├── LICENSE                # MIT
└── README.md
```

## Attribution and legal notes

- **eBird API**: non-commercial use is permitted under the
  [eBird API Terms of Use](https://ebird.org/api/keygen). The project
  makes at most one selection call per day.
- **Macaulay Library**: photographs are © their authors. The project
  hot-links the public Cornell CDN for non-commercial display with
  visible photographer attribution, mirroring the embed flow Cornell
  itself offers.
- **Merlin / eBird and Birds of the World text**: © Cornell Lab of
  Ornithology. The feed reproduces short fragments with clear
  attribution and links back to the source, with no commercial purpose.
- **Wikipedia**: REST summary content is CC BY-SA 3.0; we link to the
  canonical article and don't redistribute beyond the short summary.
- **Generated data** (feed, site): MIT, free to reuse with attribution.

## Privacy

This site stores your theme preference (light/dark) in `localStorage` so
it persists between visits. That's the only client-side state, it never
leaves the browser, and it falls under the "strictly necessary functional
preferences" exemption of the EU ePrivacy Directive — no consent banner
or cookie notice is required. There are no cookies, no analytics, no
trackers, and no third-party requests beyond Google Fonts (for typography)
and the Macaulay Library CDN (for photos).

## License

[MIT](LICENSE). Third-party content (photos, Cornell text excerpts,
Wikipedia summaries) keeps its respective licenses and attributions.
