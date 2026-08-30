# Deployment

Everything about running the generator somewhere other than your laptop:
the daily GitHub Actions workflow, the Docker image and its volume, a
GitHub Pages site, and the schedules both paths run on. The
[README](../README.md) covers installation and a local run, and
[CONFIGURATION.md](CONFIGURATION.md) covers every key you will be setting
along the way.

## Running via GitHub Actions

Copy `.github/bird-of-the-day.yml.example` to
`.github/workflows/bird-of-the-day.yml` to enable the daily cron. It runs:

- Automatically every day at **07:17 UTC**, best effort.
- Manually from the **Actions → Bird of the Day → Run workflow** tab.

The minute is odd on purpose, and the schedule is a hint rather than a
promise: GitHub queues scheduled runs and drops the ones it cannot
serve, and the top of the hour is where every cron in the world piles
up. On a real instance of this template a `':00'` schedule ran about an
hour late for eleven days, then drifted to between six and twelve hours
late over the next three. If the publication time matters to you, run
the Docker container instead, whose cron is your own machine's.

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
`linux/amd64` and `linux/arm64`. Tags: `latest` follows the default
branch, `sha-xxxxxxx` pins one commit, and a published release adds
`X.Y.Z`, `X.Y` and `X` (no `v`: the tag `v2.1.0` publishes as `2.1.0`),
so a compose file can pin a version instead of riding whatever landed
this morning. It runs nginx on port 8080 and a
built-in cron (supercronic) that regenerates the site daily at 07:00 UTC
(see [Cron schedule and timezone](#cron-schedule-and-timezone)). Total
image size: ~340 MB.

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
take 30 to 60 seconds while the generator runs synchronously to populate
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
(`pools`, `llm`) are not overridable; mount a custom file instead. What
each key means is in [CONFIGURATION.md](CONFIGURATION.md).

`EBIRD_API_KEY` is required, and `BOTD_LLM_API_KEY` is what completes a
configured `llm` block (see [LLM
enrichment](CONFIGURATION.md#llm-enrichment)). The image ships no `.env`
file and does not need one, since env vars work everywhere; the loader is
still there, so a `.env` mounted at `/app/.env` would be read.

One more variable is not a config override: `BOTD_STATE_DIR` is where all
mutable state is written. The image sets it to `/var/lib/botd`, the
volume mount point. Unset (local runs, GitHub Actions) it defaults to the
repository root, which is the layout the rest of this documentation
describes.

#### Secrets via files

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

To change `pools`, the `llm` block, or anything else the env-var table
above does not reach, mount your own config file instead of forking the
repo and rebuilding:

```bash
# 1. Copy the example and edit it
cp data/config.example.json my-config.json

# 2. Mount it into the container:
docker run -d ... \
  -v ./my-config.json:/app/data/config.json:ro \
  ghcr.io/backmind/bird-of-the-day
```

The mount is `:ro` (read-only): the container only reads it.

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
`unhealthy` within 36 hours, which is the **intended** behavior: your
orchestrator (k8s / docker swarm / fly machines / etc.) will surface it.
The 36 h window gives the daily 07:00 UTC run a 12 h grace period.

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

Resource hints: ~50 to 100 MB RAM at idle, ~150 MB during generation,
bursty CPU. A floor of `mem_limit: 256m` and `cpus: 0.5` is
comfortable.

#### Building locally

Build from a clone of this template. The published image is built from
this repository's `main`, so an instance repository's own changes under
`docker/` do not reach `ghcr.io`: if you have customised the crontab or
the entrypoint, build the image yourself rather than pulling it.

```bash
git clone https://github.com/backmind/Bird-of-the-day.git
cd Bird-of-the-day
docker build -t bird-of-the-day .
# Multi-arch:
docker buildx build --platform linux/amd64,linux/arm64 -t bird-of-the-day .
```

If you are on Windows and your clone predates 2026-08-30, the image will
build and then die on startup with:

```
env: 'bash\r': No such file or directory
```

That is a checkout with CRLF line endings: the carriage return becomes
part of the interpreter name in the entrypoint's shebang. `.gitattributes`
now pins LF on everything the image executes, so a fresh clone is fine.
An existing one is repaired with:

```bash
git rm --cached -r . && git reset --hard
```

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
   before the first run: see
   [`data/config.json`](CONFIGURATION.md#dataconfigjson) for what it
   turns on.
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

## Cron schedule and timezone

The two paths keep their own schedules, and they are deliberately a few
minutes apart:

- The workflow runs at **07:17 UTC**. The odd minute is explained under
  [Running via GitHub Actions](#running-via-github-actions) above. Change
  it by editing the `cron:` line in
  `.github/workflows/bird-of-the-day.yml`.
- The container runs at **07:00 UTC**. Its cron expression is
  `0 7 * * *` in `docker/crontab`. Change it by editing that file and
  rebuilding, or by mounting your own at `/etc/supercronic/crontab`.

Both are UTC: the image sets no timezone, and GitHub Actions schedules
are always interpreted as UTC. If you want a local publication time,
convert it yourself when you write the expression.
