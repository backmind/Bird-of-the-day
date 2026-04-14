"""Bird of the Day — scripts package."""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


def esc_html(value: str) -> str:
    """HTML-escape user-supplied text (escapes &, <, >, ", ')."""
    return html.escape(value or "", quote=True)


def load_json_cache(path: Path, label: str = "cache") -> dict | list | None:
    """Read and parse a JSON cache file, returning ``None`` on failure."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _logger.warning("Invalid %s at %s, ignoring", label, path)
        return None
