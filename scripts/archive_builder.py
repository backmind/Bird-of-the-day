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
