"""Site chrome, the plate/card renderers, and the home page.

No JavaScript, no build step. This module owns the page shell (header,
footer, theme toggle), the ``SiteEntry`` dataclass, the plate and card
renderers shared by every page, and ``build_index``: the most recent
bird is the hero on ``index.html``, with up to ``INDEX_GRID_SIZE``
previous birds in a grid below it.

Every other page (the archive front, one bucket per month, one
canonical page per species) is built in :mod:`scripts.archive_builder`,
which imports this module for its chrome and renderers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from scripts import esc_html as _esc, name_linker, urls

if TYPE_CHECKING:
    from scripts.i18n import Catalog

logger = logging.getLogger(__name__)

INDEX_GRID_SIZE = 12


@dataclass(frozen=True)
class RenderContext:
    """Per-render context bundle so helper signatures stay compact.

    Constructed once per page (in :func:`build_index` and the
    :mod:`scripts.archive_builder` page builders) and threaded through
    every ``_render_*`` helper. Holds the i18n catalog plus the small
    handful of page-level scalars the helpers need.

    ``feed_link`` is carried for absolute-URL generation (canonical links,
    Open Graph tags) and is deliberately not read by any renderer yet.

    ``full_feed`` says whether ``feed-full.xml`` is actually published.
    It only is when a cap applies (see :func:`feed_builder.write_feeds`),
    so the pages have to be told: advertising a file that was never
    written hands every reader a 404.
    """

    catalog: "Catalog"
    feed_link: str
    english_name_index: dict = field(default_factory=dict)
    code_to_localized: dict = field(default_factory=dict)
    published_anchors: dict = field(default_factory=dict)
    path_prefix: str = ""
    full_feed: bool = False

    def u(self, path: str) -> str:
        """Resolve a root-relative site path from this page's location."""
        return f"{self.path_prefix}{path}"


def for_subdirectory(ctx: RenderContext, prefix: str) -> RenderContext:
    """Context for a page that lives below the site root.

    The name-linker catalog holds root-relative targets, so it is
    rewritten with the same prefix: seen from ``birds/x.html``, the link
    to another species page is ``../birds/y.html``. Absolute targets (the
    feed passes those through the same catalog) are left untouched.
    """
    prefixed = {
        code: target
        if target.startswith(("http://", "https://", "/"))
        else f"{prefix}{target}"
        for code, target in ctx.published_anchors.items()
    }
    return replace(ctx, path_prefix=prefix, published_anchors=prefixed)


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
    iucn_code: str = ""                # IUCN Red List code (LC, VU, EN, etc.)
    iucn_birdlife_url: str = ""        # BirdLife factsheet URL
    enriched_prose: str = ""           # LLM-generated prose (enriched mode)
    enriched_identification: list[str] | None = None  # LLM ID bullets

    @property
    def anchor(self) -> str:
        return urls.entry_anchor(self.species_code, self.date)

    @property
    def archive_url(self) -> str:
        """Permalink of THIS publication: its month bucket plus anchor."""
        return urls.bucket_url(self.species_code, self.date)

    @property
    def species_url(self) -> str:
        """Canonical page for the species, independent of any date."""
        return urls.species_url(self.species_code)

    @property
    def date_dotted(self) -> str:
        """ISO date as `YYYY · MM · DD` — language-neutral, used in plate-date."""
        return self.date.replace("-", " · ")


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
      <h1><a href="{_esc(ctx.u(urls.INDEX_PAGE))}">{_esc(t("site.title"))}</a></h1>
    </div>
    <nav aria-label="{_esc(t("nav.principal_aria"))}">
      <a href="{_esc(ctx.u(urls.INDEX_PAGE))}"{home_class}>{_esc(t("nav.home"))}</a>
      <a href="{_esc(ctx.u(urls.ARCHIVE_FRONT))}"{archive_class}>{_esc(t("nav.archive"))}</a>
      <a href="{_esc(ctx.u(urls.FEED_FILE))}">{_esc(t("nav.rss"))}</a>
      {toggle}
    </nav>
  </div>
</header>
""".strip()


def render_subscribe(ctx: RenderContext) -> str:
    """Refined RSS footnote — not a marketing banner.

    The secondary link to the full history is offered only when that file
    is actually published. With ``full_feed`` off the subtitle keeps the
    exact markup it had before the full feed existed, so turning the
    feature off does not churn every page for an invisible reason.
    """
    t = ctx.catalog.t
    target = ctx.u(urls.FEED_FILE)
    sub = _esc(t("subscribe.subtitle"))
    if ctx.full_feed:
        full_target = ctx.u(urls.FEED_FULL_FILE)
        sub = (
            f'{sub} · <a href="{_esc(full_target)}">'
            f'{_esc(t("subscribe.full_feed"))}</a>'
        )
    return f"""
<aside class="subscribe" aria-label="{_esc(t("subscribe.aria_label"))}">
  <div class="icon" aria-hidden="true">
    <svg viewBox="0 0 24 24" fill="currentColor">
      <path d="M6.18 17.82a2.18 2.18 0 1 1-4.36 0 2.18 2.18 0 0 1 4.36 0zM2 6.44v3.1c7.03 0 12.73 5.7 12.73 12.73h3.1C17.83 13.39 10.61 6.17 2 6.44zM2 .5v3.1c10.04 0 18.18 8.14 18.18 18.18h3.1C23.28 9.97 13.45.5 2 .5z"/>
    </svg>
  </div>
  <div class="text">
    <p class="title">{_esc(t("subscribe.title"))}</p>
    <p class="sub">{sub}</p>
  </div>
  <a class="button" href="{_esc(target)}">{_esc(t("subscribe.button"))}</a>
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


def render_plate(
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
    # Enriched mode: LLM-generated prose and identification bullets. They
    # are asked for separately and can arrive separately, so each is
    # rendered on its own condition; nesting the bullets inside the prose
    # dropped both them and their heading whenever an enrichment came
    # back with one and not the other, and published the scraped
    # paragraph in their place. feed_builder.build_entry_html renders the
    # same two fields with the same three branches.
    desc_html = ""
    if entry.enriched_prose:
        # Split on double-newline so each paragraph gets its own <p>.
        paragraphs = [p.strip() for p in entry.enriched_prose.split("\n\n") if p.strip()]
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
    if not entry.enriched_prose and not entry.enriched_identification:
        if entry.description:
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

    # IUCN badge (compact circle with code, tooltip with localized name).
    iucn_html = ""
    if entry.iucn_code:
        iucn_label = ctx.catalog.t(f"iucn.{entry.iucn_code}")
        iucn_cls = f"iucn-{entry.iucn_code.lower()}"
        if entry.iucn_birdlife_url:
            iucn_html = (
                f' <a class="iucn-badge {iucn_cls}" '
                f'href="{_esc(entry.iucn_birdlife_url)}" '
                f'target="_blank" rel="noopener" '
                f'data-iucn="{_esc(iucn_label)}" '
                f'aria-label="{_esc(iucn_label)}">{_esc(entry.iucn_code)}</a>'
            )
        else:
            iucn_html = (
                f' <span class="iucn-badge {iucn_cls}" '
                f'data-iucn="{_esc(iucn_label)}" '
                f'aria-label="{_esc(iucn_label)}">{_esc(entry.iucn_code)}</span>'
            )

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
    <p class="plate-subtitle">{_esc(entry.scientific_name)}{iucn_html}</p>
    {desc_html}
    {atlas_block}
    <div class="plate-foot">
      {chr(10).join("      " + link for link in foot_links).strip()}
    </div>
  </div>
</{tag}>
""".strip()


def _render_atlas(entry: SiteEntry, ctx: RenderContext, *, hero: bool = False) -> str:
    """Render the GBIF distribution map as an atlas-styled section.

    Returns the empty string when ``entry.distribution_map_url`` is not
    set, so the renderer can drop the section silently for species
    without a GBIF match (recent splits, very obscure endemics).

    The atlas frame composites two layers: the published static basemap
    (the continents) and the GBIF density tile (the colored occurrence
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
    <img class="atlas-base" src="{_esc(ctx.u(urls.BASEMAP))}" alt="" loading="lazy" />
    <img class="atlas-data" src="{_esc(entry.distribution_map_url)}" alt="{_esc(alt)}" loading="lazy" />
    <span class="atlas-equator" aria-hidden="true"></span>
    <span class="atlas-meridian" aria-hidden="true"></span>
    <span class="atlas-legend" aria-hidden="true"><span>−</span><span class="atlas-legend-bar"></span><span>+</span></span>
    <span class="atlas-attribution">&copy; OpenStreetMap &middot; GBIF</span>
  </a>
  <footer class="atlas-scale" aria-hidden="true">
    <span>180°W</span>
    <span>0°</span>
    <span>180°E</span>
  </footer>
</section>
""".strip()


def render_card(entry: SiteEntry, ctx: RenderContext) -> str:
    """Render a grid card linking to the entry's canonical species page."""
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

    card_iucn = ""
    if entry.iucn_code:
        card_iucn = (
            f' <span class="iucn-badge iucn-badge-sm '
            f'iucn-{entry.iucn_code.lower()}">'
            f'{_esc(entry.iucn_code)}</span>'
        )

    return f"""
<article class="card">
  <a href="{_esc(ctx.u(entry.species_url))}">
    {thumb}
    <div class="card-meta">
      {number_html}
      <span>{_esc(entry.date_dotted)}</span>
    </div>
    <h3 class="card-name">{_esc(entry.common_name)}</h3>
    <p class="card-sci">{_esc(entry.scientific_name)}{card_iucn}</p>
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


def render_page(
    title: str, body: str, ctx: RenderContext, active: str, head_extra: str = ""
) -> str:
    """Render a full page.

    ``head_extra`` is raw markup appended to ``<head>``, for the rare
    thing that has to run before first paint rather than in document
    order; it is emitted right after the theme-boot script, which is
    there for the same reason. Empty by default, and it contributes no
    whitespace when empty so a page without it keeps its exact bytes.

    The second ``rel="alternate"`` is emitted only when the full-history
    feed is actually published, for the reason given on
    :attr:`RenderContext.full_feed`.
    """
    t = ctx.catalog.t
    stylesheet_href = _esc(ctx.u(urls.STYLESHEET))
    head_block = f"\n  {head_extra}" if head_extra else ""
    full_feed_link = ""
    if ctx.full_feed:
        full_feed_link = (
            '\n  <link rel="alternate" type="application/rss+xml" title="'
            f'{_esc(t("feed.full_title_template", title=t("site.title")))}" '
            f'href="{_esc(ctx.u(urls.FEED_FULL_FILE))}">'
        )
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
  <link rel="alternate" type="application/rss+xml" title="{_esc(t("site.title"))}" href="{_esc(ctx.u(urls.FEED_FILE))}">{full_feed_link}
  {_THEME_BOOT_SCRIPT}{head_block}
  <link rel="stylesheet" href="{stylesheet_href}">
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
        body = f'<p>{_esc(t("index.empty"))}</p>\n' + render_subscribe(ctx)
        return render_page(t("site.title"), body, ctx, active="home")

    hero = entries[0]
    grid_entries = entries[1 : 1 + INDEX_GRID_SIZE]
    grid_html = ""
    if grid_entries:
        cards = "\n".join(render_card(e, ctx) for e in grid_entries)
        grid_html = f"""
<div class="section-divider"><span class="label">{_esc(t("section.recent"))}</span></div>
<div class="grid">
{cards}
</div>
""".strip()

    body = "\n".join(
        [render_plate(hero, ctx, hero=True), render_subscribe(ctx), grid_html]
    )
    page_title = t(
        "page.home_hero_title_template", name=hero.common_name
    )
    return render_page(page_title, body, ctx, active="home")
