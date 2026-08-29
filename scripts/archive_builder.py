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

from scripts import esc_html as _esc, site_builder, urls
from scripts.site_builder import RenderContext, SiteEntry

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


def _month_nav(
    ctx: RenderContext, *, newer_month: str = "", older_month: str = ""
) -> str:
    t = ctx.catalog.t
    parts = []
    if older_month:
        parts.append(
            f'<a class="page-nav-older" '
            f'href="{_esc(ctx.u(urls.bucket_filename_for_month(older_month)))}">'
            f'{_esc(t("nav.older_month"))}: {_esc(month_label(ctx, older_month))}</a>'
        )
    parts.append(
        f'<a class="page-nav-up" href="{_esc(ctx.u(urls.ARCHIVE_FRONT))}">'
        f'{_esc(t("nav.back_to_archive"))}</a>'
    )
    if newer_month:
        parts.append(
            f'<a class="page-nav-newer" '
            f'href="{_esc(ctx.u(urls.bucket_filename_for_month(newer_month)))}">'
            f'{_esc(t("nav.newer_month"))}: {_esc(month_label(ctx, newer_month))}</a>'
        )
    return (
        f'<nav class="page-nav" aria-label="{_esc(t("nav.pagination_aria"))}">'
        f'{"".join(parts)}</nav>'
    )


# Links already delivered to RSS readers point at
# ``archive.html#bird-{code}-{date}``. The month is inside the fragment,
# so the redirect needs no lookup table. Without JavaScript the reader
# lands on the archive front page: degraded, not broken.
_LEGACY_ANCHOR_SHIM = (
    "<script>(function(){"
    "var m=/^#bird-[a-z0-9]+-(\\d{4}-\\d{2})-\\d{2}$/.exec(location.hash);"
    "if(m){location.replace('archive-'+m[1]+'.html'+location.hash);}"
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
        body = f'<p>{_esc(t("archive.empty"))}</p>\n' + site_builder.render_subscribe(ctx)
        return site_builder.render_page(title, body, ctx, active="archive")

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
        _LEGACY_ANCHOR_SHIM,
    ]
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
