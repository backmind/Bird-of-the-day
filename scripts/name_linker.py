"""Species name substitution, cross-linking, and scientific-name italicisation.

Four-pass pipeline over raw description text:

  1. **Word-boundary pass** — 2+ word English names, longest-first.
     Establishes confirmed species with high confidence.
  2. **Short-form pass** — individual words (≥ 4 chars) from confirmed
     species, case-sensitive, word-boundary. Catches "de adultos de
     Masked" after "Masked Booby" was already confirmed.
  3. **Dirty-substring pass** — the full English name as a substring
     (no word boundaries). Catches formatting artifacts like
     "laMasked BoobySula" where scraping lost whitespace.
  4. **Scientific-name pass** — binomial names from the eBird taxonomy,
     case-insensitive, word-boundary. Wraps in ``<em>`` with canonical
     capitalisation (genus upper, epithet lower).

Passes 2-3 only run for species confirmed in pass 1. Pass 4 runs
independently (any taxonomic binomial, whether or not the common name
was found).

Processing happens at render time (not cached) because the set of
published species changes daily.
"""

from __future__ import annotations

import html
import re

_MIN_SHORTFORM_LEN = 4  # words shorter than this are skipped in pass 2


def _make_species_replacement(
    code: str,
    fallback: str,
    code_to_localized: dict[str, str],
    published_anchors: dict[str, str],
    ebird_locale: str = "",
) -> str:
    """Build the HTML replacement for a species common-name match.

    Links to the published archive entry when available, otherwise
    falls back to the eBird species page.
    """
    localized = code_to_localized.get(code, fallback)
    escaped = html.escape(localized)
    if code in published_anchors:
        anchor = html.escape(published_anchors[code], quote=True)
        return f'<a href="{anchor}">{escaped}</a>'
    # Fallback: link to eBird species page with "(eBird)" hint.
    lang = f"?siteLanguage={html.escape(ebird_locale)}" if ebird_locale else ""
    ebird_url = f"https://ebird.org/species/{html.escape(code)}{lang}"
    return (
        f'<a href="{ebird_url}" target="_blank" rel="noopener">'
        f"{escaped}</a> (eBird)"
    )


def process_description(
    raw_text: str,
    english_name_index: dict[str, str],
    code_to_localized: dict[str, str],
    published_anchors: dict[str, str],
    ebird_locale: str = "",
) -> str:
    """Substitute English bird names, hyperlink, and italicise binomials.

    Parameters
    ----------
    raw_text:
        The raw description string (not HTML-escaped).
    english_name_index:
        English ``comName`` → ``speciesCode`` mapping.
    code_to_localized:
        ``speciesCode`` → localised ``comName`` mapping.
    published_anchors:
        ``speciesCode`` → anchor URL for published species.

    Returns
    -------
    str
        HTML string.  The caller inserts as raw HTML — do NOT escape.
    """
    if not raw_text or not english_name_index:
        return html.escape(raw_text or "")

    text_lower = raw_text.lower()

    # Each match: (start, end, replacement_html)
    matches: list[tuple[int, int, str]] = []
    occupied: set[int] = set()

    def _try_add(start: int, end: int, replacement: str) -> bool:
        if any(pos in occupied for pos in range(start, end)):
            return False
        matches.append((start, end, replacement))
        occupied.update(range(start, end))
        return True

    # ── Pass 1: word-boundary, 2+ word names, longest first ──────

    candidates = [
        (name, code)
        for name, code in english_name_index.items()
        if " " in name
    ]
    candidates.sort(key=lambda x: len(x[0]), reverse=True)

    confirmed_species: dict[str, str] = {}  # code → English name

    for name, code in candidates:
        if not all(w in text_lower for w in name.lower().split()):
            continue
        pattern = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
        for m in pattern.finditer(raw_text):
            repl = _make_species_replacement(
                code, m.group(), code_to_localized, published_anchors, ebird_locale
            )
            if _try_add(m.start(), m.end(), repl):
                confirmed_species[code] = name

    # ── Pass 2: short-form abbreviations from confirmed species ──

    for code, full_name in confirmed_species.items():
        for word in full_name.split():
            if len(word) < _MIN_SHORTFORM_LEN:
                continue
            # Case-sensitive: "Masked" (proper noun) not "masked".
            pattern = re.compile(r"\b" + re.escape(word) + r"\b")
            for m in pattern.finditer(raw_text):
                repl = _make_species_replacement(
                    code, m.group(), code_to_localized, published_anchors
                )
                _try_add(m.start(), m.end(), repl)

    # ── Pass 3: dirty-substring cleanup for confirmed species ────

    for code, full_name in confirmed_species.items():
        name_lower = full_name.lower()
        idx = 0
        while True:
            pos = text_lower.find(name_lower, idx)
            if pos < 0:
                break
            end_pos = pos + len(full_name)
            repl = _make_species_replacement(
                code, raw_text[pos:end_pos], code_to_localized, published_anchors
            )
            _try_add(pos, end_pos, repl)
            idx = pos + 1

    # ── Pass 4: scientific name italicisation ─────────────────────
    #
    # Uses the taxonomy index already loaded in ebird_client (the
    # configured-locale one). sciName is locale-independent (always
    # Latin) so any loaded taxonomy works. Match case-insensitively,
    # output with canonical capitalisation (genus upper, epithet lower)
    # wrapped in <em>.

    from scripts import ebird_client  # deferred to avoid circular import

    sciname_canonical = ebird_client.get_sciname_index()

    if sciname_canonical:
        for lower_sci, canonical in sciname_canonical.items():
            words = lower_sci.split()
            if not all(w in text_lower for w in words):
                continue
            pattern = re.compile(
                r"\b" + re.escape(canonical) + r"\b", re.IGNORECASE
            )
            for m in pattern.finditer(raw_text):
                _try_add(
                    m.start(),
                    m.end(),
                    f"<em>{html.escape(canonical)}</em>",
                )

    if not matches:
        return html.escape(raw_text)

    # ── Assembly ─────────────────────────────────────────────────

    matches.sort(key=lambda x: x[0])

    parts: list[str] = []
    prev_end = 0
    for start, end, replacement in matches:
        gap = raw_text[prev_end:start]
        parts.append(html.escape(gap))

        # Spacing fix for dirty substrings (pass 3): insert a space
        # if the gap ends flush against the match with no whitespace.
        if parts and parts[-1] and parts[-1][-1].isalpha():
            parts.append(" ")

        parts.append(replacement)

        # Spacing fix after: if next char is a word char, insert space.
        if end < len(raw_text) and raw_text[end].isalpha():
            parts.append(" ")

        prev_end = end

    parts.append(html.escape(raw_text[prev_end:]))

    return "".join(parts)
