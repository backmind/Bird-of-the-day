"""Archive pages: month buckets, the archive front page, species pages.

Layering: this module imports :mod:`scripts.site_builder` for the chrome
and the plate renderer and never the other way round. It owns every page
the site publishes except ``index.html``.

A publication's plate is rendered in exactly one bucket page, whose file
name derives from the publication date, so a bucket for a past month only
changes when its content genuinely changes.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from scripts import atomic_io, esc_html as _esc, site_builder, site_css, urls
from scripts.map_composer import BASEMAP_PATH as _BASEMAP_ASSET
from scripts.site_builder import RenderContext, SiteEntry

if TYPE_CHECKING:
    from scripts.i18n import Catalog

logger = logging.getLogger(__name__)


def group_by_month(entries: list[SiteEntry]) -> list[tuple[str, list[SiteEntry]]]:
    """Group entries into ``(month, entries)`` pairs, newest month first.

    ``entries`` arrives newest first, so insertion order already gives
    both the month order and the order inside each month.
    """
    grouped: dict[str, list[SiteEntry]] = {}
    for entry in entries:
        grouped.setdefault(urls.month_key(entry.date), []).append(entry)
    return list(grouped.items())


def month_label(ctx: RenderContext, month: str) -> str:
    """``"2026-08"`` to ``"August 2026"`` in the catalog's language."""
    year, _, number = month.partition("-")
    return f"{ctx.catalog.t(f'month.{int(number)}')} {year}"


def _page_nav(
    ctx: RenderContext,
    *,
    older: tuple[str, str] | None = None,
    newer: tuple[str, str] | None = None,
) -> str:
    """The pagination strip shared by month buckets and species pages.

    ``older`` and ``newer`` are ``(href, text)`` pairs already resolved by
    the caller, or None when that direction does not exist. The way back
    to the archive front is always offered.
    """
    t = ctx.catalog.t
    parts = []
    if older is not None:
        href, text = older
        parts.append(
            f'<a class="page-nav-older" href="{_esc(href)}">{_esc(text)}</a>'
        )
    parts.append(
        f'<a class="page-nav-up" href="{_esc(ctx.u(urls.ARCHIVE_FRONT))}">'
        f'{_esc(t("nav.back_to_archive"))}</a>'
    )
    if newer is not None:
        href, text = newer
        parts.append(
            f'<a class="page-nav-newer" href="{_esc(href)}">{_esc(text)}</a>'
        )
    return (
        f'<nav class="page-nav" aria-label="{_esc(t("nav.pagination_aria"))}">'
        f'{"".join(parts)}</nav>'
    )


def _month_nav(
    ctx: RenderContext, *, newer_month: str = "", older_month: str = ""
) -> str:
    t = ctx.catalog.t
    older = None
    if older_month:
        older = (
            ctx.u(urls.bucket_filename_for_month(older_month)),
            f'{t("nav.older_month")}: {month_label(ctx, older_month)}',
        )
    newer = None
    if newer_month:
        newer = (
            ctx.u(urls.bucket_filename_for_month(newer_month)),
            f'{t("nav.newer_month")}: {month_label(ctx, newer_month)}',
        )
    return _page_nav(ctx, older=older, newer=newer)


def _legacy_anchor_shim() -> str:
    """Redirect legacy ``archive.html#bird-{code}-{date}`` fragments.

    The month is inside the fragment, so no lookup table is needed. The
    two format literals are derived from :mod:`scripts.urls` rather than
    copied, so a change to the URL scheme cannot silently orphan links
    that readers already hold.

    Goes in ``<head>``: it only reads ``location.hash``, so it needs no
    DOM, and from the body it would let the reader watch the whole
    archive front paint before jumping away from it.
    """
    sentinel = "0000-00"
    head, _, tail = urls.bucket_filename_for_month(sentinel).partition(sentinel)
    anchor_head, _, _ = urls.entry_anchor("\x00", "\x01").partition("\x00")
    return (
        "<script>(function(){"
        f"var m=/^#{anchor_head}[a-z0-9]+-(\\d{{4}}-\\d{{2}})-\\d{{2}}$/"
        ".exec(location.hash);"
        f"if(m){{location.replace('{head}'+m[1]+'{tail}'+location.hash);}}"
        "})();</script>"
    )


def _month_index(months: list[tuple[str, list[SiteEntry]]], ctx: RenderContext) -> str:
    """The full directory of months, grouped by year, newest first."""
    t = ctx.catalog.t
    by_year: dict[str, list[tuple[str, int]]] = {}
    for month, month_entries in months:
        by_year.setdefault(month[:4], []).append((month, len(month_entries)))

    blocks = []
    for year, rows in by_year.items():
        items = "".join(
            f"<li>"
            f'<a href="{_esc(ctx.u(urls.bucket_filename_for_month(month)))}">'
            f"{_esc(month_label(ctx, month))}</a>"
            f'<span class="count">{count}</span>'
            f"</li>"
            for month, count in rows
        )
        blocks.append(
            f'<h3 class="month-year">{_esc(year)}</h3>'
            f'<ul class="month-list">{items}</ul>'
        )

    heading = _esc(t("archive.months_heading"))
    return (
        f'<section class="month-index" aria-labelledby="month-index-title">'
        f'<h2 id="month-index-title">{heading}</h2>'
        f'{"".join(blocks)}'
        f"</section>"
    )


def build_archive_front(entries: list[SiteEntry], ctx: RenderContext) -> str:
    """Render ``archive.html``: current month as cards, then every month."""
    t = ctx.catalog.t
    title = t("page.archive_title_template")
    if not entries:
        body = (
            f'<p>{_esc(t("archive.empty"))}</p>\n'
            + site_builder.render_subscribe(ctx)
        )
        return site_builder.render_page(
            title, body, ctx, active="archive",
            head_extra=_legacy_anchor_shim(),
        )

    months = group_by_month(entries)
    current_month, current_entries = months[0]
    cards = "\n".join(
        site_builder.render_card(entry, ctx) for entry in current_entries
    )
    body_parts = [
        '<div class="archive-intro">',
        f'<h1>{_esc(t("section.archive_title"))}</h1>',
        f'<p>{_esc(t("section.archive_subtitle"))}</p>',
        "</div>",
        site_builder.render_subscribe(ctx),
        f'<div class="section-divider"><span class="label">'
        f"{_esc(month_label(ctx, current_month))}</span></div>",
        f'<div class="grid">\n{cards}\n</div>',
        _month_index(months, ctx),
    ]
    return site_builder.render_page(
        title, "\n".join(body_parts), ctx, active="archive",
        head_extra=_legacy_anchor_shim(),
    )


def group_by_species(entries: list[SiteEntry]) -> list[tuple[str, list[SiteEntry]]]:
    """Group entries into ``(species_code, publications)`` pairs.

    Publications inside a species are newest first, and the species
    themselves are ordered by their most recent publication, because
    ``entries`` arrives newest first. Pairs rather than a dict for the
    same reason as :func:`group_by_month`: the callers walk the sequence
    by position.
    """
    grouped: dict[str, list[SiteEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.species_code, []).append(entry)
    return list(grouped.items())


def _plate_nav(
    ctx: RenderContext,
    *,
    older: SiteEntry | None = None,
    newer: SiteEntry | None = None,
) -> str:
    t = ctx.catalog.t
    older_pair = (
        (ctx.u(older.species_url), f'{t("nav.older_plate")}: {older.common_name}')
        if older is not None
        else None
    )
    newer_pair = (
        (ctx.u(newer.species_url), f'{t("nav.newer_plate")}: {newer.common_name}')
        if newer is not None
        else None
    )
    return _page_nav(ctx, older=older_pair, newer=newer_pair)


def _publication_history(publications: list[SiteEntry], ctx: RenderContext) -> str:
    t = ctx.catalog.t
    # ``archive_url`` is the entry's own permalink (its month bucket plus
    # anchor), so the history delegates to it instead of rebuilding the URL.
    rows = "".join(
        f"<li>"
        f'<a href="{_esc(ctx.u(p.archive_url))}">'
        f'<span class="glyph">№</span>&nbsp;{p.number} · '
        f"{_esc(p.date_dotted)}</a>"
        f"</li>"
        for p in publications
    )
    return (
        f'<section class="species-history" aria-labelledby="species-history-title">'
        f'<h2 id="species-history-title">{_esc(t("species.history_heading"))}</h2>'
        f"<ul>{rows}</ul>"
        f"</section>"
    )


def build_species_page(
    publications: list[SiteEntry],
    ctx: RenderContext,
    *,
    older: SiteEntry | None = None,
    newer: SiteEntry | None = None,
) -> str:
    """Render ``birds/{code}.html``: the canonical page for one species.

    ``publications`` is newest first; the most recent one supplies the
    plate, the rest become the publication history. ``ctx`` must already
    be a subdirectory context (see :func:`site_builder.for_subdirectory`).
    """
    latest = publications[0]
    body_parts = [
        site_builder.render_plate(latest, ctx, hero=True),
        _publication_history(publications, ctx),
        _plate_nav(ctx, older=older, newer=newer),
        site_builder.render_subscribe(ctx),
    ]
    title = ctx.catalog.t(
        "page.species_title_template", name=latest.common_name
    )
    return site_builder.render_page(
        title, "\n".join(body_parts), ctx, active="archive"
    )


def build_month_bucket(
    month: str,
    entries: list[SiteEntry],
    ctx: RenderContext,
    *,
    newer_month: str = "",
    older_month: str = "",
) -> str:
    """Render one month's page: every plate published that month."""
    t = ctx.catalog.t
    label = month_label(ctx, month)
    nav = _month_nav(ctx, newer_month=newer_month, older_month=older_month)
    body_parts = [
        '<div class="archive-intro">',
        f"<h1>{_esc(label)}</h1>",
        f'<p>{_esc(t("archive.month_subtitle_template", count=len(entries)))}</p>',
        "</div>",
        nav,
    ]
    body_parts.extend(site_builder.render_plate(e, ctx) for e in entries)
    body_parts.append(nav)
    return site_builder.render_page(
        t("page.bucket_title_template", month=label),
        "\n".join(body_parts),
        ctx,
        active="archive",
    )


def _neighbours(
    species: list[tuple[str, list[SiteEntry]]], position: int
) -> tuple[SiteEntry | None, SiteEntry | None]:
    """The species sitting either side of ``species[position]``.

    The walk is over species, not over publications, because that is what
    it links to: ordering by publication makes a species published twice
    its own neighbour, and makes the backward walk dead-end there. The
    sequence :func:`group_by_species` returns is already ordered by most
    recent publication, newest first, so the newer neighbour sits at the
    lower index. Returns ``(older, newer)``, each represented by the
    neighbour's latest publication, which carries the common name to
    label the link with and the species page to point it at.
    """
    older = species[position + 1][1][0] if position + 1 < len(species) else None
    newer = species[position - 1][1][0] if position > 0 else None
    return older, newer


def write_site(
    entries: list[SiteEntry],
    output_dir: Path,
    catalog: "Catalog",
    feed_link: str = "",
    english_name_index: dict | None = None,
    code_to_localized: dict | None = None,
    published_anchors: dict | None = None,
) -> dict[str, int]:
    """Render every page and write the ones whose content changed.

    Returns ``{"pages": total, "written": n, "unchanged": n}``. Rendering
    the whole site costs milliseconds, so there is no incremental mode to
    keep in sync: correctness comes from always rendering everything,
    small diffs come from only writing what differs.
    """
    ctx = RenderContext(
        catalog=catalog,
        feed_link=feed_link,
        english_name_index=english_name_index or {},
        code_to_localized=code_to_localized or {},
        published_anchors=published_anchors or {},
    )
    output_dir = Path(output_dir)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    # The atlas sections must never depend on a third-party tile server.
    # urls.BASEMAP is already the full root-relative path, so it joins
    # onto output_dir, not onto assets_dir.
    try:
        shutil.copyfile(_BASEMAP_ASSET, output_dir / urls.BASEMAP)
    except OSError:
        logger.warning("Could not publish basemap asset from %s", _BASEMAP_ASSET)
    atomic_io.write_text_if_changed(output_dir / urls.STYLESHEET, site_css.CSS)

    pages: dict[str, str] = {
        urls.INDEX_PAGE: site_builder.build_index(entries, ctx),
        urls.ARCHIVE_FRONT: build_archive_front(entries, ctx),
    }

    months = group_by_month(entries)
    for position, (month, month_entries) in enumerate(months):
        newer = months[position - 1][0] if position > 0 else ""
        older = months[position + 1][0] if position + 1 < len(months) else ""
        pages[urls.bucket_filename_for_month(month)] = build_month_bucket(
            month, month_entries, ctx, newer_month=newer, older_month=older
        )

    species_ctx = site_builder.for_subdirectory(ctx, "../")
    species = group_by_species(entries)
    for position, (code, publications) in enumerate(species):
        older_entry, newer_entry = _neighbours(species, position)
        pages[urls.species_filename(code)] = build_species_page(
            publications, species_ctx, older=older_entry, newer=newer_entry
        )

    written = 0
    for relative_path, html in pages.items():
        if atomic_io.write_text_if_changed(output_dir / relative_path, html):
            written += 1

    logger.info(
        "Site written: %d of %d pages changed (%d entries)",
        written, len(pages), len(entries),
    )
    return {
        "pages": len(pages),
        "written": written,
        "unchanged": len(pages) - written,
    }
