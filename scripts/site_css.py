"""The site stylesheet.

Kept as a Python constant so the generator stays a single-file-per-page
static build with no asset pipeline, but written to disk once as
``assets/site.css`` and linked from every page: the site now has one page
per month and one per species, and inlining would duplicate this file
across all of them.
"""

from __future__ import annotations

CSS = """
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
.iucn-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.35rem;
  height: 1.35rem;
  margin-left: .4em;
  border-radius: 50%;
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .6rem;
  font-weight: 700;
  font-style: normal;
  letter-spacing: .04em;
  line-height: 1;
  color: #fff;
  text-decoration: none;
  vertical-align: .15em;
  position: relative;
  transition: transform .2s ease, box-shadow .2s ease;
  box-shadow: 0 1px 2px rgba(30, 42, 46, 0.15);
}
.iucn-badge:hover {
  transform: scale(1.15);
  box-shadow: 0 2px 6px rgba(30, 42, 46, 0.25);
}
.iucn-badge::after {
  content: attr(data-iucn);
  position: absolute;
  bottom: calc(100% + .45em);
  left: 50%;
  transform: translateX(-50%);
  white-space: nowrap;
  max-width: 90vw;
  font-family: 'Source Serif 4', Georgia, serif;
  font-size: .82rem;
  font-weight: 400;
  font-style: italic;
  letter-spacing: .02em;
  color: var(--ink);
  background: var(--paper);
  border: 1px solid var(--rule);
  padding: .25em .55em;
  border-radius: 3px;
  box-shadow: 0 3px 8px rgba(30, 42, 46, 0.12);
  opacity: 0;
  pointer-events: none;
  transition: opacity .15s ease;
}
.iucn-badge:hover::after { opacity: 1; }
.iucn-lc { background: #5a8a5e; }
.iucn-nt { background: #8a7a3e; }
.iucn-vu { background: #b5893a; }
.iucn-en { background: #b35a3a; }
.iucn-cr { background: #8b2e2e; }
.iucn-ew { background: #4a3a5a; }
.iucn-ex { background: #2e2e2e; }
.iucn-dd { background: var(--ink-faint); }
.iucn-ne { background: var(--rule-strong); }
.iucn-badge-sm {
  width: 1.1rem;
  height: 1.1rem;
  font-size: .5rem;
  vertical-align: .1em;
  margin-left: .3em;
  cursor: inherit;
}
.iucn-badge-sm:hover { transform: none; box-shadow: 0 1px 2px rgba(30,42,46,.15); }
.iucn-badge-sm::after { display: none; }

.plate-meta {
  display: inline-flex;
  align-items: baseline;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: .6rem;
}
.republished-chip {
  display: inline-block;
  font-family: 'Source Serif 4', Georgia, serif;
  font-size: .74rem;
  font-style: italic;
  font-weight: 400;
  letter-spacing: .02em;
  line-height: 1;
  color: var(--ink-soft);
  border: 1px solid var(--rule);
  border-radius: 999px;
  padding: .32em .7em;
  text-decoration: none;
  white-space: nowrap;
  transition: color .2s ease, border-color .2s ease;
}
a.republished-chip:hover {
  color: var(--ink);
  border-color: var(--rule-strong);
}
.card .republished-chip {
  font-size: .66rem;
  padding: .26em .6em;
  margin-top: .5rem;
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
  font-size: .82rem;
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
  content: '\u2014';
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

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .iucn-badge {
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
  }
}
:root[data-theme="dark"] .iucn-badge {
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
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

/* ─── pagination ───────────────────────────────────────────────────
   Month buckets and species pages are separate documents, so every one
   of them offers a way out.                                              */
.page-nav {
  max-width: var(--max);
  margin: 2.25rem auto;
  padding: 0 1.25rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem 1.5rem;
  justify-content: space-between;
  align-items: baseline;
  font-size: 0.92rem;
}
.page-nav a {
  color: var(--accent);
  text-decoration: none;
  border-bottom: 1px solid var(--rule);
  padding-bottom: 2px;
}
.page-nav a:hover { border-bottom-color: var(--accent); }
.page-nav .page-nav-up { color: var(--ink-soft); }

/* ─── month index ──────────────────────────────────────────────────
   The archive front is a directory: one line per month, forever.        */
.month-index { max-width: var(--max); margin: 3rem auto 1rem; padding: 0 1.25rem; }
.month-index h2 { font-size: 1.1rem; margin: 0 0 0.5rem; }
.month-year {
  font-size: 0.9rem;
  color: var(--ink-faint);
  letter-spacing: 0.14em;
  margin: 1.75rem 0 0.5rem;
}
.month-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 0 1.5rem;
}
.month-list li {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.4rem 0;
  border-bottom: 1px dotted var(--rule);
}
.month-list a { color: var(--ink); text-decoration: none; }
.month-list a:hover { color: var(--accent); }
.month-list .count { color: var(--ink-faint); }

/* ─── species page ─────────────────────────────────────────────────
   One canonical page per bird; the list of dates is its provenance.     */
.species-history { max-width: var(--max); margin: 2rem auto; padding: 0 1.25rem; }
.species-history h2 { font-size: 1.05rem; margin: 0 0 0.5rem; }
.species-history ul { list-style: none; margin: 0; padding: 0; }
.species-history li { padding: 0.35rem 0; border-bottom: 1px dotted var(--rule); }
.species-history a { color: var(--ink); text-decoration: none; }
.species-history a:hover { color: var(--accent); }
.species-history .glyph { color: var(--ink-faint); }
""".strip()
