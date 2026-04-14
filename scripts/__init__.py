"""Bird of the Day — scripts package."""

import html


def esc_html(value: str) -> str:
    """HTML-escape user-supplied text (escapes &, <, >, ", ')."""
    return html.escape(value or "", quote=True)
