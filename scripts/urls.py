"""Canonical URL and anchor scheme for the generated site.

Every page path, entry anchor and cross-link is built here. The format
used to be reimplemented in three places (``SiteEntry``, the anchor
catalog in ``generate.py``, the feed guid) and drifted; now each caller
delegates to this module.

Paths are root-relative (``archive-2026-08.html``, ``birds/eurbla.html``).
A page that lives in a subdirectory passes its own ``prefix`` (``"../"``)
so one catalog of targets works from any depth. Root-absolute paths are
deliberately never produced: they break ``file://`` preview and
deployments under a sub-path.
"""

from __future__ import annotations

INDEX_PAGE = "index.html"
ARCHIVE_FRONT = "archive.html"
FEED_FILE = "feed.xml"
FEED_FULL_FILE = "feed-full.xml"
STYLESHEET = "assets/site.css"
BASEMAP = "assets/basemap.png"
SPECIES_DIR = "birds"


def month_key(date: str) -> str:
    """``"2026-08-27"`` to ``"2026-08"``. The bucket a date belongs to."""
    return date[:7]


def entry_anchor(species_code: str, date: str) -> str:
    """Anchor of one publication inside its month bucket page."""
    return f"bird-{species_code}-{date}"


def bucket_filename_for_month(month: str) -> str:
    return f"archive-{month}.html"


def bucket_filename(date: str) -> str:
    return bucket_filename_for_month(month_key(date))


def bucket_url(species_code: str, date: str, prefix: str = "") -> str:
    """Permalink of one publication: the bucket page plus its anchor."""
    return (
        f"{prefix}{bucket_filename(date)}"
        f"#{entry_anchor(species_code, date)}"
    )


def species_filename(species_code: str) -> str:
    return f"{SPECIES_DIR}/{species_code}.html"


def species_url(species_code: str, prefix: str = "") -> str:
    """Canonical page for a species. Never rots: it is always current."""
    return f"{prefix}{species_filename(species_code)}"


def feed_guid(species_code: str, date: str) -> str:
    """Feed item identity, deliberately not the HTML anchor format.

    This string was already delivered to every subscriber; changing it
    would resurface the whole history as unread items.
    """
    return f"bird-of-the-day-{species_code}-{date}"


def absolute(base: str, path: str) -> str:
    """Join a configured base URL and a root-relative path."""
    if not base:
        return path
    return f"{base.rstrip('/')}/{path}"
