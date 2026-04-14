"""Generate the static site (index.html + archive.html) from cached birds.

The site is two pages of plain HTML with embedded CSS — no JavaScript, no
build step. The most recent bird is the hero on ``index.html``; up to 12
previous birds appear as a grid below it. ``archive.html`` lists every
entry from history with full content and stable anchors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from scripts import esc_html as _esc, name_linker

if TYPE_CHECKING:
    from scripts.i18n import Catalog

logger = logging.getLogger(__name__)

INDEX_GRID_SIZE = 12
ARCHIVE_MAX_ENTRIES = 90  # ~1 season; full pagination in a future release


@dataclass(frozen=True)
class RenderContext:
    """Per-render context bundle so helper signatures stay compact.

    Constructed once per page (in :func:`build_index` / :func:`build_archive`)
    and threaded through every ``_render_*`` helper. Holds the i18n catalog
    plus the small handful of page-level scalars the helpers need.
    """

    catalog: "Catalog"
    feed_link: str
    english_name_index: dict = field(default_factory=dict)
    code_to_localized: dict = field(default_factory=dict)
    published_anchors: dict = field(default_factory=dict)


@dataclass
class SiteEntry:
    species_code: str
    common_name: str
    scientific_name: str
    date: str  # ISO YYYY-MM-DD
    image_url: str | None
    photographer: str
    attribution: str
    description: str
    description_source: str
    bow_intro: str
    taxonomy: dict
    ml_search_url: str
    number: int = 0  # 1-indexed publication number, populated by generate.py
    wikipedia_url: str = ""       # canonical Wikipedia article URL
    wikipedia_language: str = ""  # "es" | "en" | "" — what we resolved to
    fallback_language: str = ""   # ISO of the foreign source (when
                                  # description_source == "ebird-foreign")
    gbif_taxon_key: int | None = None  # GBIF usageKey for the species
    distribution_map_url: str = ""     # hot-linked GBIF density map PNG URL
    enriched_prose: str = ""           # LLM-generated prose (enriched mode)
    enriched_identification: list[str] | None = None  # LLM ID bullets

    @property
    def anchor(self) -> str:
        return f"bird-{self.species_code}-{self.date}"

    @property
    def archive_url(self) -> str:
        return f"archive.html#{self.anchor}"

    @property
    def date_dotted(self) -> str:
        """ISO date as `YYYY · MM · DD` — language-neutral, used in plate-date."""
        return self.date.replace("-", " · ")


_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght,SOFT@9..144,400;9..144,500;9..144,600;9..144,700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,500;8..60,600&display=swap');

/* ─── palette ──────────────────────────────────────────────────────
   Field Journal at Dawn — warm parchment + deep teal sky + brushed bronze
   Light mode reads as opening a leather-bound observation log on a desk.
   Dark mode reads as the same log lit by a single lantern at night.       */
:root {
  --paper: #F4EEE0;
  --paper-warm: #ECE2CC;
  --paper-deep: #E1D4B6;
  --ink: #1E2A2E;
  --ink-soft: #5C6A6E;
  --ink-faint: #8A8A7C;
  --accent: #0E5F66;
  --accent-warm: #B36B2F;
  --rule: #C8BEA4;
  --rule-strong: #A89B7D;
  --shadow: 0 1px 0 rgba(255,255,255,0.5), 0 10px 28px -12px rgba(30, 42, 46, 0.22), 0 2px 6px -2px rgba(30, 42, 46, 0.08);
  --max: 920px;
  --max-wide: 1080px;
}

/* Dark mode: applied automatically when the OS prefers dark, UNLESS the
   user has manually toggled to light. Manual override (data-theme="dark")
   wins regardless of the OS setting. */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper: #0F1518;
    --paper-warm: #161E22;
    --paper-deep: #1B252A;
    --ink: #E9E2D0;
    --ink-soft: #9AA4A4;
    --ink-faint: #5C6A6E;
    --accent: #5BB1B6;
    --accent-warm: #D9893A;
    --rule: #2A3338;
    --rule-strong: #3E4A50;
    --shadow: 0 0 0 1px rgba(255,255,255,0.04), 0 14px 36px -12px rgba(0,0,0,0.7), 0 2px 8px -2px rgba(0,0,0,0.5);
  }
}
:root[data-theme="dark"] {
  --paper: #0F1518;
  --paper-warm: #161E22;
  --paper-deep: #1B252A;
  --ink: #E9E2D0;
  --ink-soft: #9AA4A4;
  --ink-faint: #5C6A6E;
  --accent: #5BB1B6;
  --accent-warm: #D9893A;
  --rule: #2A3338;
  --rule-strong: #3E4A50;
  --shadow: 0 0 0 1px rgba(255,255,255,0.04), 0 14px 36px -12px rgba(0,0,0,0.7), 0 2px 8px -2px rgba(0,0,0,0.5);
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; -webkit-text-size-adjust: 100%; }

body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: 'Source Serif 4', 'Source Serif Pro', Georgia, serif;
  font-feature-settings: 'kern', 'liga', 'onum';
  font-variant-numeric: oldstyle-nums proportional-nums;
  font-optical-sizing: auto;
  font-size: 18px;
  line-height: 1.65;
  /* faint paper grain + a halo at the top of the page */
  background-image:
    radial-gradient(ellipse 1100px 520px at 50% -8%, rgba(179,107,47,0.05), transparent 60%),
    url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.06 0'/%3E%3C/filter%3E%3Crect width='200' height='200' filter='url(%23n)'/%3E%3C/svg%3E");
  background-attachment: fixed, fixed;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) body {
    background-image:
      radial-gradient(ellipse 1100px 520px at 50% -8%, rgba(91,177,182,0.07), transparent 60%),
      url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.04 0'/%3E%3C/filter%3E%3Crect width='200' height='200' filter='url(%23n)'/%3E%3C/svg%3E");
  }
}
:root[data-theme="dark"] body {
  background-image:
    radial-gradient(ellipse 1100px 520px at 50% -8%, rgba(91,177,182,0.07), transparent 60%),
    url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.04 0'/%3E%3C/filter%3E%3Crect width='200' height='200' filter='url(%23n)'/%3E%3C/svg%3E");
}

/* ─── links ────────────────────────────────────────────────────── */
a {
  color: var(--ink);
  text-decoration: underline;
  text-decoration-color: var(--rule-strong);
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
  transition: text-decoration-color .25s ease, color .25s ease;
}
a:hover { text-decoration-color: var(--accent-warm); color: var(--accent); }
a:focus-visible, button:focus-visible {
  outline: 2px solid var(--accent-warm);
  outline-offset: 3px;
  border-radius: 1px;
}

.skip-link {
  position: absolute; left: -1000px; top: 0;
  background: var(--ink); color: var(--paper);
  padding: .55rem 1.1rem;
  z-index: 100;
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .76rem;
  text-transform: uppercase;
  letter-spacing: .14em;
}
.skip-link:focus { left: 1rem; top: 1rem; }

/* ─── masthead ─────────────────────────────────────────────────── */
header.site {
  border-bottom: 1px solid var(--rule);
  background: linear-gradient(to bottom, transparent, var(--paper-warm));
}
header.site .inner {
  max-width: var(--max-wide);
  margin: 0 auto;
  padding: 1.6rem 2rem 1.25rem;
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: end;
  gap: 1rem;
}
header.site .brand { display: flex; flex-direction: column; gap: .15rem; }
header.site .eyebrow {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .68rem;
  text-transform: uppercase;
  letter-spacing: .22em;
  color: var(--ink-soft);
}
header.site h1 {
  margin: 0;
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'SOFT' 100, 'opsz' 48;
  font-weight: 600;
  font-size: 1.75rem;
  line-height: 1;
  letter-spacing: -0.012em;
}
header.site h1 a { color: var(--ink); text-decoration: none; }
header.site nav {
  display: flex;
  gap: 1.75rem;
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .72rem;
  text-transform: uppercase;
  letter-spacing: .18em;
  align-items: end;
}
header.site nav a {
  color: var(--ink-soft);
  text-decoration: none;
  padding-bottom: .12rem;
  border-bottom: 1px solid transparent;
  transition: color .25s ease, border-color .25s ease;
}
header.site nav a:hover,
header.site nav a[aria-current="page"] {
  color: var(--ink);
  border-bottom-color: var(--accent-warm);
}

.theme-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  margin-left: .25rem;
  padding: 0;
  background: transparent;
  border: 1px solid var(--rule);
  border-radius: 50%;
  color: var(--ink-soft);
  cursor: pointer;
  transition: color .25s ease, border-color .25s ease, transform .35s ease;
}
.theme-toggle:hover {
  color: var(--accent-warm);
  border-color: var(--accent-warm);
  transform: rotate(-12deg);
}
.theme-toggle svg { width: 16px; height: 16px; }
/* Show moon by default (light mode showing "switch to dark"), sun in dark mode */
.theme-toggle .icon-sun { display: none; }
.theme-toggle .icon-moon { display: block; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .theme-toggle .icon-sun { display: block; }
  :root:not([data-theme="light"]) .theme-toggle .icon-moon { display: none; }
}
:root[data-theme="dark"] .theme-toggle .icon-sun { display: block; }
:root[data-theme="dark"] .theme-toggle .icon-moon { display: none; }

/* ─── main column ──────────────────────────────────────────────── */
main {
  max-width: var(--max);
  margin: 0 auto;
  padding: 3rem 2rem 4rem;
}

/* ─── plate (used by hero AND archive entries) ─────────────────── */
.plate {
  position: relative;
  margin-bottom: 4.5rem;
}
.plate + .plate { margin-top: 4.5rem; }

.plate-head {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: baseline;
  gap: 1rem;
  font-family: 'Fraunces', Georgia, serif;
  font-feature-settings: 'lnum', 'tnum';
}
.plate-number {
  font-variation-settings: 'opsz' 14;
  font-size: 1rem;
  font-weight: 500;
  color: var(--ink-soft);
}
.plate-number .glyph {
  font-style: italic;
  font-weight: 400;
  color: var(--accent-warm);
  margin-right: .12rem;
}
.plate-date {
  font-variation-settings: 'opsz' 9;
  font-size: .72rem;
  text-transform: uppercase;
  letter-spacing: .16em;
  color: var(--ink-soft);
}

.plate-rule {
  display: flex;
  align-items: center;
  gap: .8rem;
  margin: .85rem 0 1.5rem;
  color: var(--ink-faint);
}
.plate-rule::before {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(to right, transparent, var(--rule-strong) 60%);
}
.plate-rule::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(to left, transparent, var(--rule-strong) 60%);
}
.plate-rule .ornament {
  font-family: 'Fraunces', serif;
  font-variation-settings: 'opsz' 14;
  font-size: 1.05rem;
  color: var(--accent-warm);
  line-height: 1;
}

.plate-image {
  position: relative;
  overflow: hidden;
  background: var(--paper-warm);
  aspect-ratio: 3 / 2;
  box-shadow: inset 0 0 0 1px var(--rule), var(--shadow);
}
.plate-image img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 1.4s cubic-bezier(.2,.6,.2,1), filter .6s ease;
}
.plate:hover .plate-image img { transform: scale(1.02); }
.plate-image .no-image {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--ink-soft);
  font-style: italic;
  font-size: .9rem;
  text-align: center;
  padding: 2rem;
  background: repeating-linear-gradient(135deg, transparent 0 9px, rgba(30,42,46,0.04) 9px 10px);
}
.plate-credit {
  margin: .75rem 0 0;
  font-size: .78rem;
  font-style: italic;
  color: var(--ink-soft);
  text-align: right;
}

.plate-body { margin-top: 2.4rem; }

.specimen-tag {
  display: inline-flex;
  align-items: center;
  gap: .55rem;
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .68rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .2em;
  color: var(--accent-warm);
  margin: 0 0 .9rem;
}
.specimen-tag::before {
  content: '';
  width: 1.6rem;
  height: 1px;
  background: var(--accent-warm);
}

.plate-title {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'SOFT' 30, 'opsz' 96;
  font-weight: 600;
  font-size: clamp(2.1rem, 4.6vw, 3.4rem);
  line-height: 1.02;
  letter-spacing: -0.018em;
  margin: 0 0 .35rem;
  color: var(--ink);
  text-wrap: balance;
}
.plate-subtitle {
  font-family: 'Source Serif 4', Georgia, serif;
  font-style: italic;
  font-weight: 400;
  font-size: 1.15rem;
  color: var(--ink-soft);
  margin: 0 0 1.75rem;
}

.plate-description {
  font-size: 1.04rem;
  line-height: 1.72;
  color: var(--ink);
  margin: 0 0 1rem;
  text-align: justify;
  text-wrap: pretty;
  hyphens: auto;
}
.plate-id-label {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .18em;
  color: var(--accent-warm);
  margin: 1.5rem 0 .6rem;
}
.plate-identification {
  font-size: .92rem;
  line-height: 1.65;
  color: var(--ink);
  margin: .4rem 0 1rem;
  padding-left: 0;
  list-style: none;
}
.plate-identification li {
  margin-bottom: .45rem;
  padding-left: 1.2rem;
  position: relative;
}
.plate-identification li::before {
  content: '\2014';
  position: absolute;
  left: 0;
  color: var(--accent-warm);
}
.plate-description-note {
  font-size: .82rem;
  color: var(--ink-soft);
  font-style: italic;
  margin: -0.6rem 0 1rem;
  padding-left: .9rem;
  border-left: 2px solid var(--accent-warm);
}
.plate-description.empty {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 14;
  font-size: 1.5rem;
  font-weight: 400;
  color: var(--ink-faint);
  text-align: center;
  margin: 1rem 0;
  letter-spacing: .3em;
}

.plate-foot {
  margin-top: 2rem;
  padding-top: 1.25rem;
  border-top: 1px solid var(--rule);
  display: flex;
  flex-wrap: wrap;
  gap: .25rem 1.6rem;
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .7rem;
  text-transform: uppercase;
  letter-spacing: .16em;
}
.plate-foot a {
  color: var(--ink-soft);
  text-decoration: none;
  padding-bottom: .15rem;
  border-bottom: 1px solid var(--rule);
  transition: color .25s ease, border-color .25s ease;
}
.plate-foot a:hover {
  color: var(--accent);
  border-bottom-color: var(--accent-warm);
}

/* ─── hero-only ornament: V-soaring bird watermark ─────────────── */
.plate.hero { isolation: isolate; }
.plate.hero::before {
  content: "";
  position: absolute;
  top: -1.5rem;
  right: -.25rem;
  width: 96px;
  height: 56px;
  pointer-events: none;
  opacity: .14;
  z-index: -1;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 60'%3E%3Cpath d='M8 38 Q 30 8, 50 32 Q 70 8, 92 38' fill='none' stroke='%231E2A2E' stroke-width='3.5' stroke-linecap='round'/%3E%3C/svg%3E");
  background-size: contain;
  background-repeat: no-repeat;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .plate.hero::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 60'%3E%3Cpath d='M8 38 Q 30 8, 50 32 Q 70 8, 92 38' fill='none' stroke='%23E9E2D0' stroke-width='3.5' stroke-linecap='round'/%3E%3C/svg%3E");
    opacity: .18;
  }
}
:root[data-theme="dark"] .plate.hero::before {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 60'%3E%3Cpath d='M8 38 Q 30 8, 50 32 Q 70 8, 92 38' fill='none' stroke='%23E9E2D0' stroke-width='3.5' stroke-linecap='round'/%3E%3C/svg%3E");
  opacity: .18;
}

/* ─── section divider ──────────────────────────────────────────── */
.section-divider {
  display: flex;
  align-items: baseline;
  gap: 1.25rem;
  margin: 4rem 0 2rem;
}
.section-divider .label {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .2em;
  color: var(--ink-soft);
  white-space: nowrap;
}
.section-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(to right, var(--rule-strong), transparent);
}

/* ─── recent-birds grid (specimen tags) ────────────────────────── */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 2.5rem 1.75rem;
}
.card a { display: contents; color: inherit; text-decoration: none; }
.card-thumb {
  /* 3:2 landscape, matching the hero plate-image. Most Macaulay photos
     are landscape DSLR shots so this fills cleanly. The few portrait
     ones get cropped on top/bottom — accepted trade-off vs the previous
     letterboxed 4:5 layout, which left visible bands above and below
     every photo (unsightly especially in dark mode). */
  aspect-ratio: 3 / 2;
  overflow: hidden;
  background: var(--paper-warm);
  position: relative;
  box-shadow: inset 0 0 0 1px var(--rule), 0 1px 0 rgba(255,255,255,0.4), 0 10px 24px -16px rgba(30,42,46,0.35);
}
.card-thumb img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  /* Bias the crop toward the top so that on portrait Macaulay shots
     (rare but real — tall birds, stylistic choices) the bird's head
     stays visible while feet/tail get cropped instead. Birds in
     wildlife photos are almost always composed above the vertical
     midline; this heuristic costs nothing on landscape sources. */
  object-position: center 30%;
  filter: saturate(.95);
  transition: transform .9s cubic-bezier(.2,.6,.2,1), filter .4s ease;
}
.card a:hover .card-thumb img { transform: scale(1.05); filter: saturate(1.05); }
.card-thumb .empty {
  width: 100%;
  height: 100%;
  background: repeating-linear-gradient(135deg, transparent 0 8px, rgba(30,42,46,0.04) 8px 9px);
}
.card-meta {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-top: .85rem;
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-feature-settings: 'lnum', 'tnum';
  font-size: .68rem;
  text-transform: uppercase;
  letter-spacing: .14em;
  color: var(--ink-faint);
}
.card-meta .glyph { font-style: italic; color: var(--accent-warm); margin-right: .12rem; }
.card-name {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'SOFT' 50, 'opsz' 32;
  font-weight: 600;
  font-size: 1.18rem;
  line-height: 1.2;
  margin: .35rem 0 .15rem;
  color: var(--ink);
  text-wrap: balance;
}
.card-sci {
  font-family: 'Source Serif 4', Georgia, serif;
  font-style: italic;
  font-size: .9rem;
  color: var(--ink-soft);
  margin: 0;
}
.card-tag {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .62rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .18em;
  color: var(--accent-warm);
  margin: .55rem 0 0;
}
.card a:hover .card-name { color: var(--accent); }

/* ─── subscribe (refined footnote, not a banner) ───────────────── */
.subscribe {
  margin: 4rem 0;
  padding: 1.5rem 1.75rem;
  border: 1px solid var(--rule);
  background: linear-gradient(180deg, var(--paper-warm), var(--paper));
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 1.25rem;
  position: relative;
}
.subscribe::before {
  content: '';
  position: absolute;
  top: -1px; left: -1px; bottom: -1px;
  width: 4px;
  background: linear-gradient(to bottom, var(--accent-warm), var(--accent));
}
.subscribe .icon {
  width: 36px; height: 36px;
  display: grid; place-items: center;
  color: var(--accent);
}
.subscribe .icon svg { width: 22px; height: 22px; }
.subscribe .text p { margin: 0; }
.subscribe .text .title {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'SOFT' 30, 'opsz' 24;
  font-weight: 600;
  font-size: 1.08rem;
  color: var(--ink);
}
.subscribe .text .sub {
  font-size: .86rem;
  color: var(--ink-soft);
  margin-top: .15rem;
  font-style: italic;
}
.subscribe .button {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .16em;
  color: var(--paper);
  background: var(--ink);
  padding: .75rem 1.2rem;
  text-decoration: none;
  white-space: nowrap;
  transition: background .25s ease;
}
.subscribe .button:hover { background: var(--accent); }
@media (max-width: 600px) {
  .subscribe { grid-template-columns: auto 1fr; gap: 1rem; }
  .subscribe .button { grid-column: 1 / -1; text-align: center; padding: .9rem; }
}

/* ─── archive intro ────────────────────────────────────────────── */
.archive-intro {
  margin: 1rem 0 4rem;
  text-align: center;
}
.archive-intro h1 {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'SOFT' 60, 'opsz' 96;
  font-weight: 600;
  font-size: clamp(2.5rem, 5vw, 3.8rem);
  margin: 0 0 .5rem;
  letter-spacing: -.02em;
  line-height: 1;
}
.archive-intro p { font-style: italic; color: var(--ink-soft); margin: 0; }

/* ─── footer ───────────────────────────────────────────────────── */
footer.site {
  margin-top: 5rem;
  padding: 2.5rem 2rem 3.5rem;
  border-top: 1px solid var(--rule);
  background: var(--paper-warm);
  text-align: center;
  font-size: .85rem;
  color: var(--ink-soft);
  font-style: italic;
}
footer.site p { margin: .4rem 0; }
footer.site a { color: var(--ink-soft); }

/* ─── atlas spread (GBIF distribution map) ─────────────────────── */
.atlas {
  position: relative;
  margin: 2.75rem 0 0;
  padding: 1.4rem 1.35rem 1rem;
  background: var(--paper-warm);
  border: 1px solid var(--rule-strong);
  box-shadow:
    0 1px 0 rgba(255,255,255,0.4),
    0 14px 32px -18px rgba(30,42,46,0.32),
    0 2px 6px -2px rgba(30,42,46,0.08);
}
/* a pair of ornament glyphs nicked into the top border like a ribbon */
.atlas::before,
.atlas::after {
  content: '❦';
  position: absolute;
  top: -.7rem;
  font-family: 'Fraunces', serif;
  font-variation-settings: 'opsz' 14;
  font-size: .92rem;
  color: var(--accent-warm);
  background: var(--paper-warm);
  padding: 0 .4rem;
  line-height: 1;
}
.atlas::before { left: 1.2rem; }
.atlas::after  { right: 1.2rem; }

.atlas-header {
  display: flex;
  justify-content: center;
  align-items: baseline;
  margin-bottom: .9rem;
}
.atlas-title {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .22em;
  color: var(--accent-warm);
}

.atlas-frame {
  position: relative;
  display: block;
  /* mercator z=0 is a square tile (the world minus polar caps); plate
     carrée 2:1 would need stitching two halves, not worth it */
  aspect-ratio: 1 / 1;
  background: var(--paper);
  border: 1px solid var(--rule);
  overflow: hidden;
  max-width: 480px;
  margin: 0 auto;
  text-decoration: none;
}
.atlas-base,
.atlas-data {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  /* harmonise both layers with the parchment palette */
  filter: sepia(.45) saturate(.7) contrast(.95);
  mix-blend-mode: multiply;
  transition: filter .6s ease;
}
.atlas-base { z-index: 0; }
.atlas-data { z-index: 1; }
.atlas-frame:hover .atlas-base,
.atlas-frame:hover .atlas-data {
  filter: sepia(.3) saturate(.9) contrast(1.02);
}
.atlas-attribution {
  position: absolute;
  bottom: .25rem;
  right: .35rem;
  z-index: 3;
  font-family: 'Source Serif 4', Georgia, serif;
  font-size: .56rem;
  font-style: italic;
  letter-spacing: .03em;
  color: var(--ink-faint);
  background: rgba(244, 238, 224, 0.72);
  padding: .1rem .35rem;
  pointer-events: none;
}
.atlas-legend {
  position: absolute;
  bottom: .25rem;
  left: .35rem;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: .2rem;
  background: rgba(244, 238, 224, 0.72);
  padding: .15rem .35rem;
  border-radius: 3px;
  pointer-events: none;
  font-family: 'Source Serif 4', Georgia, serif;
  font-size: .56rem;
  color: var(--ink-faint);
}
.atlas-legend-bar {
  width: 3rem;
  height: .4rem;
  border-radius: 2px;
  background: linear-gradient(to right, #ffff00, #ffc800, #ff8c00, #dc4600, #8b0000);
  filter: sepia(.45) saturate(.7) contrast(.95);
  transition: filter .6s ease;
}
.atlas-frame:hover .atlas-legend-bar {
  filter: sepia(.3) saturate(.9) contrast(1.02);
}
.atlas-equator,
.atlas-meridian {
  position: absolute;
  z-index: 2;
  pointer-events: none;
}
.atlas-equator {
  top: 50%;
  left: 0;
  right: 0;
  border-top: 1px dashed rgba(168, 155, 125, 0.45);
}
.atlas-meridian {
  left: 50%;
  top: 0;
  bottom: 0;
  border-left: 1px dashed rgba(168, 155, 125, 0.45);
}

.atlas-scale {
  display: flex;
  justify-content: space-between;
  margin: .55rem auto 0;
  padding: 0 .25rem;
  max-width: 480px;
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-feature-settings: 'lnum', 'tnum';
  font-size: .58rem;
  letter-spacing: .14em;
  color: var(--ink-faint);
}

/* dark mode: invert both map layers so the continents and dots stay
   legible on a dark background. The invert + hue-rotate trick keeps
   the colored hexagons roughly in their original hue while flipping
   the white base to dark. */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .atlas {
    background: var(--paper-warm);
    border-color: var(--rule);
  }
  :root:not([data-theme="light"]) .atlas-frame {
    background: var(--paper);
    border-color: rgba(154, 164, 164, 0.18);
  }
  :root:not([data-theme="light"]) .atlas-base,
  :root:not([data-theme="light"]) .atlas-data {
    filter: invert(1) hue-rotate(180deg) sepia(.25) saturate(.7) brightness(.95) contrast(.9);
    mix-blend-mode: screen;
  }
  :root:not([data-theme="light"]) .atlas-equator,
  :root:not([data-theme="light"]) .atlas-meridian {
    border-color: rgba(154, 164, 164, 0.25);
  }
  :root:not([data-theme="light"]) .atlas-attribution,
  :root:not([data-theme="light"]) .atlas-legend {
    background: rgba(15, 21, 24, 0.65);
    color: var(--ink-soft);
  }
  :root:not([data-theme="light"]) .atlas-legend-bar {
    filter: invert(1) hue-rotate(180deg) sepia(.25) saturate(.7) brightness(.95) contrast(.9);
  }
  :root:not([data-theme="light"]) .atlas::before,
  :root:not([data-theme="light"]) .atlas::after {
    background: var(--paper-warm);
  }
}
:root[data-theme="dark"] .atlas {
  background: var(--paper-warm);
  border-color: var(--rule);
}
:root[data-theme="dark"] .atlas-frame {
  background: var(--paper);
  border-color: rgba(154, 164, 164, 0.18);
}
:root[data-theme="dark"] .atlas-base,
:root[data-theme="dark"] .atlas-data {
  filter: invert(1) hue-rotate(180deg) sepia(.25) saturate(.7) brightness(.95) contrast(.9);
  mix-blend-mode: screen;
}
:root[data-theme="dark"] .atlas-equator,
:root[data-theme="dark"] .atlas-meridian {
  border-color: rgba(154, 164, 164, 0.25);
}
:root[data-theme="dark"] .atlas-attribution,
:root[data-theme="dark"] .atlas-legend {
  background: rgba(15, 21, 24, 0.65);
  color: var(--ink-soft);
}
:root[data-theme="dark"] .atlas-legend-bar {
  filter: invert(1) hue-rotate(180deg) sepia(.25) saturate(.7) brightness(.95) contrast(.9);
}
:root[data-theme="dark"] .atlas::before,
:root[data-theme="dark"] .atlas::after {
  background: var(--paper-warm);
}

/* ─── responsive tightening ────────────────────────────────────── */
@media (max-width: 720px) {
  main { padding: 2.25rem 1.25rem 3rem; }
  header.site .inner { padding: 1.25rem 1.25rem 1rem; grid-template-columns: 1fr; gap: .75rem; }
  header.site nav { gap: 1.25rem; }
  .plate-head { grid-template-columns: 1fr; gap: .25rem; }
  .plate.hero::before { width: 72px; height: 42px; top: -1rem; right: -.25rem; }
}
@media (max-width: 480px) {
  body { font-size: 17px; }
  .plate-title { font-size: clamp(1.8rem, 7vw, 2.6rem); }
  .grid { grid-template-columns: repeat(auto-fill, minmax(155px, 1fr)); gap: 2rem 1rem; }
  .card-name { font-size: 1.05rem; }
  .atlas { padding: 1.1rem .95rem .75rem; }
  .atlas::before { left: .8rem; }
  .atlas::after  { right: .8rem; }
  .atlas-title { font-size: .64rem; }
  .atlas-source { font-size: .72rem; }
  .atlas-scale { font-size: .52rem; }
}
""".strip()


_THEME_TOGGLE_BUTTON = """
<button class="theme-toggle" type="button" aria-label="{aria_label}" onclick="(function(b){{var h=document.documentElement;var c=h.dataset.theme;if(!c){{c=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}}var n=c==='dark'?'light':'dark';h.dataset.theme=n;try{{localStorage.setItem('bird-theme',n);}}catch(e){{}}}})(this);">
  <svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
  <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>
</button>
""".strip()


def _render_header(ctx: RenderContext, active: str) -> str:
    t = ctx.catalog.t
    archive_class = ' aria-current="page"' if active == "archive" else ""
    home_class = ' aria-current="page"' if active == "home" else ""
    toggle = _THEME_TOGGLE_BUTTON.format(aria_label=_esc(t("theme_toggle.aria_label")))
    return f"""
<a class="skip-link" href="#main">{_esc(t("site.skip_to_content"))}</a>
<header class="site">
  <div class="inner">
    <div class="brand">
      <span class="eyebrow">{_esc(t("site.eyebrow"))}</span>
      <h1><a href="index.html">{_esc(t("site.title"))}</a></h1>
    </div>
    <nav aria-label="{_esc(t("nav.principal_aria"))}">
      <a href="index.html"{home_class}>{_esc(t("nav.home"))}</a>
      <a href="archive.html"{archive_class}>{_esc(t("nav.archive"))}</a>
      <a href="feed.xml">{_esc(t("nav.rss"))}</a>
      {toggle}
    </nav>
  </div>
</header>
""".strip()


def _render_subscribe(ctx: RenderContext, feed_url: str = "feed.xml") -> str:
    """Refined RSS footnote — not a marketing banner."""
    t = ctx.catalog.t
    return f"""
<aside class="subscribe" aria-label="{_esc(t("subscribe.aria_label"))}">
  <div class="icon" aria-hidden="true">
    <svg viewBox="0 0 24 24" fill="currentColor">
      <path d="M6.18 17.82a2.18 2.18 0 1 1-4.36 0 2.18 2.18 0 0 1 4.36 0zM2 6.44v3.1c7.03 0 12.73 5.7 12.73 12.73h3.1C17.83 13.39 10.61 6.17 2 6.44zM2 .5v3.1c10.04 0 18.18 8.14 18.18 18.18h3.1C23.28 9.97 13.45.5 2 .5z"/>
    </svg>
  </div>
  <div class="text">
    <p class="title">{_esc(t("subscribe.title"))}</p>
    <p class="sub">{_esc(t("subscribe.subtitle"))}</p>
  </div>
  <a class="button" href="{_esc(feed_url)}">{_esc(t("subscribe.button"))}</a>
</aside>
""".strip()


def _render_footer(ctx: RenderContext) -> str:
    t = ctx.catalog.t
    year = datetime.now(timezone.utc).year
    # Author is hardcoded in the per-language template, which may contain
    # raw HTML for the embedded link — passed through verbatim.
    author_line = t("footer.author_template", year=year)
    code_link = t("footer.code_link_html")
    return f"""
<footer class="site">
  <p>{t("footer.data_credit_html")}</p>
  <p>{t("footer.photos_credit_html")}</p>
  <p>{author_line} {code_link}</p>
</footer>
""".strip()


def _specimen_tag(taxonomy: dict) -> str:
    """Inline 'family · order' tag rendered above the title.

    Both come from the eBird taxonomy and are scientific Latin names that
    don't need translation. The English ``familyComName`` is deliberately
    omitted (eBird doesn't translate it even with locale=es).
    """
    if not taxonomy:
        return ""
    parts = []
    if taxonomy.get("familySciName"):
        parts.append(_esc(taxonomy["familySciName"]))
    if taxonomy.get("order"):
        parts.append(_esc(taxonomy["order"]))
    if not parts:
        return ""
    return f'<p class="specimen-tag">{" · ".join(parts)}</p>'


def _render_plate(
    entry: SiteEntry, ctx: RenderContext, *, hero: bool = False
) -> str:
    """Render a bird as a numbered field-journal plate.

    Used both for the index hero and every archive entry. Hero variant gets
    the soaring-bird watermark via CSS (``.plate.hero::before``) and
    eager-loaded image; archive variant gets lazy loading and an anchor id.
    """
    target_lang = ctx.catalog.language

    tag = "section" if hero else "article"
    classes = "plate hero" if hero else "plate"
    title_id = ' id="hero-title"' if hero else ""
    aria = ' aria-labelledby="hero-title"' if hero else ""
    anchor_attr = "" if hero else f' id="{_esc(entry.anchor)}"'
    loading = "eager" if hero else "lazy"
    # Hero (index) navigates in the same tab; archive entries open a new
    # window so the reader doesn't lose their scroll position.
    _ext = "" if hero else ' target="_blank" rel="noopener"'

    # The species link reused below in plate-foot. Constructed once and
    # threaded into the image wrapper too so that clicking the photo lands
    # the reader on the eBird species page in their configured locale.
    ebird_url = (
        f"https://ebird.org/species/{_esc(entry.species_code)}"
        f"?siteLanguage={target_lang}"
    )

    if entry.image_url:
        image_block = (
            f'<div class="plate-image">'
            f'<a href="{ebird_url}"{_ext} '
            f'aria-label="{_esc(entry.common_name)} — eBird">'
            f'<img src="{_esc(entry.image_url)}" '
            f'alt="{_esc(entry.common_name)}" loading="{loading}" />'
            f'</a>'
            f'</div>'
            f'<p class="plate-credit">© {_esc(entry.attribution)}</p>'
        )
    else:
        image_block = (
            f'<div class="plate-image"><div class="no-image">'
            f'<a href="{_esc(entry.ml_search_url)}"{_ext}>Macaulay Library</a>'
            f'</div></div>'
        )

    _lang = ctx.catalog.language
    if entry.enriched_prose:
        # Enriched mode: LLM-generated prose + identification bullets.
        # Split on double-newline so each paragraph gets its own <p>.
        paragraphs = [p.strip() for p in entry.enriched_prose.split("\n\n") if p.strip()]
        desc_html = ""
        for para in paragraphs:
            processed = name_linker.process_description(
                para,
                ctx.english_name_index,
                ctx.code_to_localized,
                ctx.published_anchors,
                _lang,
            )
            desc_html += f'<p class="plate-description">{processed}</p>'
        if entry.enriched_identification:
            id_label = ctx.catalog.t("identification.label")
            bullets = "".join(
                f"<li>{_esc(b)}</li>" for b in entry.enriched_identification
            )
            desc_html += f'<p class="plate-id-label">{_esc(id_label)}</p>'
            desc_html += f'<ul class="plate-identification">{bullets}</ul>'
    elif entry.description:
        processed_desc = name_linker.process_description(
            entry.description,
            ctx.english_name_index,
            ctx.code_to_localized,
            ctx.published_anchors,
            _lang,
        )
        desc_html = f'<p class="plate-description">{processed_desc}</p>'
        if entry.description_source == "ebird-foreign":
            lang_name = ctx.catalog.t(
                f"language_name.{entry.fallback_language or 'en'}"
            )
            disclaimer = ctx.catalog.t(
                "description.foreign_disclaimer", source_language=lang_name
            )
            desc_html += (
                f'<p class="plate-description-note"><em>{_esc(disclaimer)}</em></p>'
            )
        if entry.bow_intro:
            processed_bow = name_linker.process_description(
                entry.bow_intro,
                ctx.english_name_index,
                ctx.code_to_localized,
                ctx.published_anchors,
                _lang,
            )
            desc_html += (
                f'<p class="plate-description">{processed_bow}</p>'
            )
    else:
        marker = ctx.catalog.t("description.empty_marker")
        desc_html = f'<p class="plate-description empty">{_esc(marker)}</p>'

    number_html = (
        f'<span class="plate-number"><span class="glyph">№</span>&nbsp;{entry.number}</span>'
        if entry.number
        else "<span></span>"
    )

    # plate-foot links: eBird → Wikipedia (if found) → BoW → Macaulay.
    # eBird is forced to the configured language via siteLanguage so the
    # link always lands in the reader's locale (no language hint needed).
    # Wikipedia is added even when the description came from eBird; if it
    # resolved to a non-target language, the label gets a "(<lang>)" hint.
    # ``ebird_url`` was already built above so the image wrapper and the
    # foot link share the exact same target.
    foot_links = [f'<a href="{ebird_url}"{_ext}>eBird</a>']

    if entry.wikipedia_url:
        wiki_label = "Wikipedia"
        if entry.wikipedia_language and entry.wikipedia_language != target_lang:
            wiki_label = f"Wikipedia ({entry.wikipedia_language})"
        foot_links.append(
            f'<a href="{_esc(entry.wikipedia_url)}"{_ext}>{wiki_label}</a>'
        )

    foot_links.append(
        f'<a href="https://birdsoftheworld.org/bow/species/{_esc(entry.species_code)}/cur/introduction"{_ext}>Birds of the World</a>'
    )
    foot_links.append(
        f'<a href="{_esc(entry.ml_search_url)}"{_ext}>Macaulay Library</a>'
    )

    atlas_block = _render_atlas(entry, ctx, hero=hero)

    return f"""
<{tag} class="{classes}"{anchor_attr}{aria}>
  <div class="plate-head">
    {number_html}
    <span class="plate-date">{_esc(entry.date_dotted)}</span>
  </div>
  <div class="plate-rule"><span class="ornament">❦</span></div>
  {image_block}
  <div class="plate-body">
    {_specimen_tag(entry.taxonomy)}
    <h2{title_id} class="plate-title">{_esc(entry.common_name)}</h2>
    <p class="plate-subtitle">{_esc(entry.scientific_name)}</p>
    {desc_html}
    {atlas_block}
    <div class="plate-foot">
      {chr(10).join("      " + link for link in foot_links).strip()}
    </div>
  </div>
</{tag}>
""".strip()


_ATLAS_BASEMAP_URL = (
    "https://basemaps.cartocdn.com/light_nolabels/0/0/0@2x.png"
)


def _render_atlas(entry: SiteEntry, ctx: RenderContext, *, hero: bool = False) -> str:
    """Render the GBIF distribution map as an atlas-styled section.

    Returns the empty string when ``entry.distribution_map_url`` is not
    set, so the renderer can drop the section silently for species
    without a GBIF match (recent splits, very obscure endemics).

    The atlas frame composites two layers: a Carto basemaps tile (the
    continents) and the GBIF density tile (the colored occurrence
    hexagons) stacked on top. Both share the same mercator z=0/0/0
    extent so they align pixel-perfectly. Without the basemap layer
    the GBIF tile is just dots floating on transparency — confusing.

    The frame itself is the link to the GBIF species page (single ``a``
    instead of nested anchors). Attribution for both upstream sources
    is overlaid in the bottom-right corner, the standard map convention.
    """
    if not entry.distribution_map_url:
        return ""
    t = ctx.catalog.t
    label = t("map.label")
    alt = t("map.alt_template", scientific_name=entry.scientific_name)
    species_page = (
        f"https://www.gbif.org/species/{entry.gbif_taxon_key}"
        if entry.gbif_taxon_key
        else entry.distribution_map_url
    )
    return f"""
<section class="atlas" aria-label="{_esc(label)}">
  <header class="atlas-header">
    <span class="atlas-title">{_esc(label)}</span>
  </header>
  <a class="atlas-frame" href="{_esc(species_page)}"{"" if hero else ' target="_blank" rel="noopener"'} aria-label="{_esc(entry.scientific_name)} — GBIF">
    <img class="atlas-base" src="{_ATLAS_BASEMAP_URL}" alt="" loading="lazy" />
    <img class="atlas-data" src="{_esc(entry.distribution_map_url)}" alt="{_esc(alt)}" loading="lazy" />
    <span class="atlas-equator" aria-hidden="true"></span>
    <span class="atlas-meridian" aria-hidden="true"></span>
    <span class="atlas-legend" aria-hidden="true"><span>−</span><span class="atlas-legend-bar"></span><span>+</span></span>
    <span class="atlas-attribution">© OSM · CARTO · GBIF</span>
  </a>
  <footer class="atlas-scale" aria-hidden="true">
    <span>180°W</span>
    <span>0°</span>
    <span>180°E</span>
  </footer>
</section>
""".strip()


def _render_card(entry: SiteEntry, ctx: RenderContext) -> str:
    """Render a grid card. The ``ctx`` parameter is unused for now (cards
    only contain proper-noun and metadata text) but kept for symmetry with
    other helpers and so the future addition of any UI string is local."""
    del ctx  # explicitly unused for now
    if entry.image_url:
        thumb = (
            f'<div class="card-thumb">'
            f'<img src="{_esc(entry.image_url)}" '
            f'alt="{_esc(entry.common_name)}" loading="lazy" />'
            f'</div>'
        )
    else:
        thumb = '<div class="card-thumb"><div class="empty"></div></div>'

    number_html = (
        f'<span><span class="glyph">№</span>&nbsp;{entry.number}</span>'
        if entry.number
        else "<span></span>"
    )

    family_tag = ""
    if entry.taxonomy.get("familySciName"):
        family_tag = f'<p class="card-tag">{_esc(entry.taxonomy["familySciName"])}</p>'

    return f"""
<article class="card">
  <a href="{_esc(entry.archive_url)}">
    {thumb}
    <div class="card-meta">
      {number_html}
      <span>{_esc(entry.date_dotted)}</span>
    </div>
    <h3 class="card-name">{_esc(entry.common_name)}</h3>
    <p class="card-sci">{_esc(entry.scientific_name)}</p>
    {family_tag}
  </a>
</article>
""".strip()


_FAVICON_SVG = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
    "%3Crect width='64' height='64' fill='%23F4EEE0'/%3E"
    "%3Cpath d='M6 38 Q 20 12, 32 32 Q 44 12, 58 38' fill='none' "
    "stroke='%230E5F66' stroke-width='4' stroke-linecap='round'/%3E"
    "%3C/svg%3E"
)


_THEME_BOOT_SCRIPT = (
    "<script>(function(){try{var s=localStorage.getItem('bird-theme');"
    "if(s==='light'||s==='dark')document.documentElement.dataset.theme=s;}"
    "catch(e){}})();</script>"
)


def _page(
    title: str, body: str, ctx: RenderContext, active: str
) -> str:
    t = ctx.catalog.t
    return f"""<!DOCTYPE html>
<html lang="{_esc(ctx.catalog.html_lang)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <meta name="description" content="{_esc(t("site.tagline"))}">
  <meta name="theme-color" content="#F4EEE0" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#0F1518" media="(prefers-color-scheme: dark)">
  <link rel="icon" type="image/svg+xml" href="{_FAVICON_SVG}">
  <link rel="alternate" type="application/rss+xml" title="{_esc(t("site.title"))}" href="feed.xml">
  {_THEME_BOOT_SCRIPT}
  <style>{_CSS}</style>
</head>
<body>
{_render_header(ctx, active)}
<main id="main">
{body}
</main>
{_render_footer(ctx)}
</body>
</html>
"""


def build_index(
    entries: list[SiteEntry], ctx: RenderContext
) -> str:
    t = ctx.catalog.t
    if not entries:
        body = f'<p>{_esc(t("index.empty"))}</p>\n' + _render_subscribe(ctx)
        return _page(t("site.title"), body, ctx, active="home")

    hero = entries[0]
    grid_entries = entries[1 : 1 + INDEX_GRID_SIZE]
    grid_html = ""
    if grid_entries:
        cards = "\n".join(_render_card(e, ctx) for e in grid_entries)
        grid_html = f"""
<div class="section-divider"><span class="label">{_esc(t("section.recent"))}</span></div>
<div class="grid">
{cards}
</div>
""".strip()

    body = "\n".join(
        [_render_plate(hero, ctx, hero=True), _render_subscribe(ctx), grid_html]
    )
    page_title = t(
        "page.home_hero_title_template", name=hero.common_name
    )
    return _page(page_title, body, ctx, active="home")


def build_archive(
    entries: list[SiteEntry], ctx: RenderContext
) -> str:
    t = ctx.catalog.t
    if not entries:
        body = f'<p>{_esc(t("archive.empty"))}</p>\n' + _render_subscribe(ctx)
        return _page(
            t("page.archive_title_template"), body, ctx, active="archive"
        )
    body_parts = [
        '<div class="archive-intro">',
        f'<h1>{_esc(t("section.archive_title"))}</h1>',
        f'<p>{_esc(t("section.archive_subtitle"))}</p>',
        "</div>",
        _render_subscribe(ctx),
    ]
    body_parts.extend(
        _render_plate(e, ctx, hero=False)
        for e in entries[:ARCHIVE_MAX_ENTRIES]
    )
    return _page(
        t("page.archive_title_template"),
        "\n".join(body_parts),
        ctx,
        active="archive",
    )


def write_site(
    entries: list[SiteEntry],
    output_dir: Path,
    catalog: "Catalog",
    feed_link: str = "",
    english_name_index: dict | None = None,
    code_to_localized: dict | None = None,
    published_anchors: dict | None = None,
) -> None:
    """Write index.html and archive.html to ``output_dir``.

    The ``catalog`` is required: every user-facing string is sourced from
    it. ``feed_link`` rounds out the per-page render context. The three
    ``*_index`` / ``*_anchors`` dicts power the name linker (English
    species name substitution + cross-linking to published entries).
    """
    ctx = RenderContext(
        catalog=catalog,
        feed_link=feed_link,
        english_name_index=english_name_index or {},
        code_to_localized=code_to_localized or {},
        published_anchors=published_anchors or {},
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    index_html = build_index(entries, ctx)
    archive_html = build_archive(entries, ctx)
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")
    (output_dir / "archive.html").write_text(archive_html, encoding="utf-8")
    logger.info("Site written: index.html, archive.html (%d entries)", len(entries))
