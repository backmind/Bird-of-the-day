"""Server-side composition of GBIF distribution maps for RSS feeds.

RSS readers don't support CSS positioning, so the two-layer overlay used
by the frontend (Carto basemap + GBIF density tile) shows as two stacked
images. This module downloads both tiles, alpha-composites them into a
single PNG with approximate sepia/saturate/contrast filters matching the
site's CSS, and saves the result for embedding in the feed.
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFont

from scripts import content_scraper

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

BASEMAP_URL = "https://basemaps.cartocdn.com/light_nolabels/0/0/0@2x.png"


def _download_image(
    url: str, session: requests.Session | None = None
) -> Image.Image | None:
    """Download a PNG from *url* and return it as an RGBA PIL Image."""
    sess = session or requests.Session()
    try:
        resp = sess.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content))
        return img.convert("RGBA")
    except (requests.RequestException, OSError):
        logger.warning("Failed to download image from %s", url, exc_info=True)
        return None


def _apply_css_sepia(img: Image.Image, amount: float = 0.45) -> Image.Image:
    """Apply the W3C ``sepia()`` filter via its colour matrix.

    Unlike grayscale+colorize (which destroys hue information), the
    standard matrix preserves colour differentiation — matching what
    browsers actually render.
    """
    r, g, b, a = img.split()
    inv = 1.0 - amount

    def _mix(rc: float, gc: float, bc: float) -> Image.Image:
        cr = r.point(lambda x: x * rc)
        cg = g.point(lambda x: x * gc)
        cb = b.point(lambda x: x * bc)
        return ImageChops.add(ImageChops.add(cr, cg), cb)

    # W3C sepia matrix blended with identity at *amount*.
    nr = _mix(inv + 0.393 * amount, 0.769 * amount, 0.189 * amount)
    ng = _mix(0.349 * amount, inv + 0.686 * amount, 0.168 * amount)
    nb = _mix(0.272 * amount, inv + 0.534 * amount, 0.131 * amount)

    return Image.merge("RGBA", (nr, ng, nb, a))


def _apply_filters(img: Image.Image) -> Image.Image:
    """Approximate the site CSS ``filter: sepia(.45) saturate(.7) contrast(.95)``.

    Applied to the final composite (not per-layer) since the basemap is
    opaque and the density tile is mostly transparent hexagons — the
    visual result is nearly identical.
    """
    img = _apply_css_sepia(img, 0.45)

    # Saturate(0.7) and Contrast(0.95) operate on RGB only.
    alpha = img.split()[-1]
    rgb = img.convert("RGB")
    rgb = ImageEnhance.Color(rgb).enhance(0.7)
    rgb = ImageEnhance.Contrast(rgb).enhance(0.95)
    result = rgb.convert("RGBA")
    result.putalpha(alpha)
    return result


# GBIF classic.poly colour ramp (low → high density).
_DENSITY_RAMP = [
    (255, 255, 0),    # yellow  — sparse
    (255, 200, 0),    # gold
    (255, 140, 0),    # orange
    (220, 70, 0),     # red-orange
    (140, 0, 0),      # dark red — dense
]


def _draw_legend(img: Image.Image) -> None:
    """Draw a compact density legend in the bottom-right corner."""
    w, h = img.size
    # Scale legend proportionally to image size.
    bar_w = max(60, w // 8)
    bar_h = max(6, h // 80)
    pad = max(8, w // 60)
    font_size = max(10, h // 50)

    try:
        font = ImageFont.load_default(size=font_size)
    except TypeError:
        # Pillow < 10.1 doesn't accept size; fall back to default.
        font = ImageFont.load_default()

    label_minus = "−"
    label_plus = "+"

    draw = ImageDraw.Draw(img)

    # Measure text for layout.
    lm_bbox = draw.textbbox((0, 0), label_minus, font=font)
    lp_bbox = draw.textbbox((0, 0), label_plus, font=font)
    lm_w = lm_bbox[2] - lm_bbox[0]
    lp_w = lp_bbox[2] - lp_bbox[0]
    text_h = max(lm_bbox[3] - lm_bbox[1], lp_bbox[3] - lp_bbox[1])

    # Total legend box dimensions.
    inner_w = lm_w + 4 + bar_w + 4 + lp_w
    inner_h = max(bar_h, text_h)
    box_w = inner_w + pad * 2
    box_h = inner_h + pad * 2

    # Position: bottom-right with margin.
    margin = max(10, w // 40)
    bx = w - box_w - margin
    by = h - box_h - margin

    # Semi-transparent background.
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle(
        [bx, by, bx + box_w, by + box_h],
        radius=max(3, pad // 2),
        fill=(255, 255, 255, 180),
    )
    img.paste(Image.alpha_composite(img, overlay), (0, 0))

    # Redraw on the composited image.
    draw = ImageDraw.Draw(img)

    # Vertical centre of the legend content.
    cy = by + pad + inner_h // 2

    # "−" label.
    lx = bx + pad
    draw.text(
        (lx, cy - text_h // 2), label_minus,
        fill=(80, 80, 80, 255), font=font,
    )

    # Gradient bar.
    bar_x = lx + lm_w + 4
    bar_y = cy - bar_h // 2
    ramp = _DENSITY_RAMP
    for i in range(bar_w):
        t = i / max(1, bar_w - 1)
        seg = t * (len(ramp) - 1)
        idx = min(int(seg), len(ramp) - 2)
        frac = seg - idx
        c = tuple(
            int(ramp[idx][ch] * (1 - frac) + ramp[idx + 1][ch] * frac)
            for ch in range(3)
        )
        draw.line([(bar_x + i, bar_y), (bar_x + i, bar_y + bar_h)], fill=c)

    # "+" label.
    px = bar_x + bar_w + 4
    draw.text(
        (px, cy - text_h // 2), label_plus,
        fill=(80, 80, 80, 255), font=font,
    )


def compose_map(
    distribution_map_url: str,
    output_path: Path,
    session: requests.Session | None = None,
    basemap_image: Image.Image | None = None,
) -> bool:
    """Compose basemap + density tile into a single PNG.

    *basemap_image* allows reusing a pre-downloaded basemap across
    calls. When ``None``, the basemap is downloaded fresh.

    Returns ``True`` on success, ``False`` on failure.
    """
    if basemap_image is None:
        basemap_image = _download_image(BASEMAP_URL, session)
    if basemap_image is None:
        logger.warning("Cannot compose map: basemap download failed")
        return False

    density = _download_image(distribution_map_url, session)
    if density is None:
        logger.warning("Cannot compose map: density tile download failed")
        return False

    # Resize density to match basemap if dimensions differ.
    if density.size != basemap_image.size:
        density = density.resize(basemap_image.size, Image.LANCZOS)

    composed = Image.alpha_composite(basemap_image.copy(), density)
    _draw_legend(composed)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    composed.save(str(output_path), "PNG", optimize=True)
    logger.info("Composed map saved to %s", output_path)
    return True


def ensure_composed_maps(
    history_entries: list[dict],
    cache_dir: str,
    maps_dir: Path,
    session: requests.Session | None = None,
) -> dict[str, str]:
    """Compose maps for all history entries that need them.

    Skips entries that already have a composed map on disk or that
    lack a ``distribution_map_url`` in their cached content.

    Downloads the basemap once and reuses it for all compositions.

    Returns a dict mapping ``species_code`` to the relative path
    (e.g. ``"maps/norshr1.png"``).
    """
    maps_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, str] = {}
    basemap: Image.Image | None = None

    for entry in history_entries:
        code = entry.get("speciesCode")
        if not code:
            continue

        out = maps_dir / f"{code}.png"
        if out.exists():
            result[code] = f"maps/{code}.png"
            continue

        content = content_scraper.load_cached_content(code, cache_dir)
        if content is None or not content.distribution_map_url:
            continue

        # Lazy-download basemap on first actual composition.
        if basemap is None:
            basemap = _download_image(BASEMAP_URL, session)
            if basemap is None:
                logger.warning(
                    "Basemap download failed; skipping all map compositions"
                )
                return result

        if compose_map(content.distribution_map_url, out, session, basemap):
            result[code] = f"maps/{code}.png"

    return result
