# Configuration

Every knob the generator reads: the two secrets it takes from the
environment, each key in `data/config.json` and what happens when you
leave it unset, and the two recipes people reach for most (a different
pool matrix, a new language). Start at the [README](../README.md) for
installation and a local run. What the knobs actually do to a run is
described in [ARCHITECTURE.md](ARCHITECTURE.md); how to deploy the result
is in [DEPLOYMENT.md](DEPLOYMENT.md), which also lists the `BOTD_*`
environment overrides a container accepts for the scalar keys below.

## Environment variables

| Variable | Required | Where to get it |
|---|---|---|
| `EBIRD_API_KEY` | yes | Free at <https://ebird.org/api/keygen> |
| `BOTD_LLM_API_KEY` | only if LLM enrichment is configured | Your LLM provider (e.g. [Google AI Studio](https://aistudio.google.com/apikey)) |

Locally they go in a `.env` file, copied from `.env.example` as part of
[installation](../README.md#local-installation). `.env` is gitignored and
`generate.py` loads it automatically (no `python-dotenv` required).
Either key can also be passed as a file instead, which is how Docker and
Kubernetes secrets work; see [Secrets via
files](DEPLOYMENT.md#secrets-via-files).

In GitHub Actions the key is injected from `Settings → Secrets and
variables → Actions → New repository secret` with the same name.

## `data/config.json`

Every behavior knob lives in `data/config.json`, which you create by
copying `data/config.example.json` during
[installation](../README.md#local-installation). This is what the
bundled example ships, with its `_*_help` keys elided for brevity (the
file itself annotates every one of them in place):

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

The knobs that shape the daily draw (`pools`, `dedup_window`,
`rarity_bias`, `back_days`) are explained in [Selection, dedup and
repeats](ARCHITECTURE.md#selection-dedup-and-repeats), and the two feed
keys (`max_feed_entries`, `feed_rebuild_all`) in
[Endpoints](ARCHITECTURE.md#endpoints).

## Authorship

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

## LLM enrichment

| Key | Meaning |
|---|---|
| `llm.endpoint` | OpenAI-compatible chat completions base URL. Omit the whole `llm` block (or leave it unset) to disable enrichment. |
| `llm.models` | Ordered fallback chain, e.g. `["gemini-2.5-flash", "gemini-2.0-flash"]`. Models are tried in turn until one returns valid content. Pin concrete model names, not `-latest` aliases, so a provider-side swap can't silently change output mid-chain. |
| `llm.temperature` | Sampling temperature passed to the endpoint. |
| `llm.judge` | Enables an optional second-pass fact-check: a follow-up call reviews the draft against the scraped sources and can send it back for revision. Off by default; adds one extra request per entry. |
| `llm.max_retries` | Retries per model before moving to the next one in the chain (default `3`, so up to 4 attempts on a given model, with increasing backoff between them). |

Enrichment runs automatically whenever `llm.endpoint`, `llm.models` and
the `BOTD_LLM_API_KEY` env var are all set; there is no separate on/off
flag. Without all three the site publishes the scraped description
directly. A failed or invalid LLM response falls back to that same
scraped description for the day rather than failing the run, and the miss
is picked up by the next run's backfill pass.

## Backfill and self-healing

Every run, before touching today's entry, the generator retries a bounded
number of past failures. Three states are healable:

- a photograph whose URL carries no Macaulay asset id, which renders as a
  broken image;
- an entry published without an LLM enrichment, because the endpoint was
  down or misconfigured that day;
- an entry without a GBIF distribution map, after a transient lookup
  error.

`backfill_limit` caps how many healing actions run per invocation, newest
entry first (default `3`; `0` disables self-healing). Override it with the
`BOTD_BACKFILL_LIMIT` environment variable. Photographs are attempted
first and take at most half the budget, never less than one slot, so a
backlog of broken images cannot starve the other two healers while it
drains. Healed entries trigger a feed and site rebuild even on days when
today's bird was already published.

What is *not* retried matters as much. An entry with no photograph at
all, and a taxon GBIF answers with an authoritative "no such record", are
answers rather than outages: every strategy was asked and none had
anything. Retrying them would spend a slot on every run for ever and
never resolve, so each is left alone and the page degrades honestly (a
plate with a search link in place of the photo, a plate with no map).

## Description policy

What happens when none of the sources (eBird Merlin, target-language
Wikipedia) returns text in your configured language:

| Policy | Behavior |
|---|---|
| `foreign_fallback` (default) | Show the original text with a disclaimer naming the source language (e.g. *"Description in English (no French translation available)"*). |
| `strict` | Show an em-dash placeholder. Never display foreign text. |
| `skip` | Re-roll species selection up to `max_skip_retries` times. On exhaustion, publishes the last species it tried, whose description is empty and therefore renders exactly as `strict` would. |

Even with `strict`, the footer always carries a Wikipedia link, falling
back to English Wikipedia (and labeled `Wikipedia (en)`) if the target
language has no article.

## Page metadata and social cards

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

## Pool matrix examples

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

## Adding a new language

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
