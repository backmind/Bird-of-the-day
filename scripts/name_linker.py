"""Species name substitution, cross-linking, and scientific-name italicisation.

Pipeline over raw description text:

  1. **English → locale substitution** — 2+ word English names matched
     with word boundaries, longest-first. Replaces with the localised
     name and wraps in a link (archive or eBird fallback).
  2. **Locale → link** — localized names matched with word boundaries.
     Wraps in a link without substitution (the name is already in the
     target language). This pass always runs, catching names written
     in the locale by the LLM or by locale-aware scraping.
  3. **Short-form pass** — the first (head) word of the localized name
     of species confirmed in passes 1-2, when it is ≥ 4 chars,
     case-sensitive, word-boundary. Spanish species names are
     head-first, so only that first word can stand alone as a
     reference to the species; the matched text is kept verbatim
     (never replaced by the full name).
  4. **Dirty-substring pass** — full confirmed names as substrings
     (no word boundaries). Catches formatting artifacts.
  5. **Scientific-name pass** — binomial names from the eBird taxonomy,
     case-insensitive, word-boundary. Wraps in ``<em>``.

Processing happens at render time (not cached) because the set of
published species changes daily.
"""

from __future__ import annotations

import html
import re

_MIN_SHORTFORM_LEN = 4  # words shorter than this are skipped in pass 3


def _make_link(
    code: str,
    display: str,
    published_anchors: dict[str, str],
    ebird_locale: str = "",
) -> str:
    """Build an ``<a>`` tag for a species: archive link or eBird fallback."""
    escaped = html.escape(display)
    if code in published_anchors:
        anchor = html.escape(published_anchors[code], quote=True)
        return f'<a href="{anchor}">{escaped}</a>'
    lang = f"?siteLanguage={html.escape(ebird_locale)}" if ebird_locale else ""
    ebird_url = f"https://ebird.org/species/{html.escape(code)}{lang}"
    return (
        f'<a href="{ebird_url}" target="_blank" rel="noopener">'
        f"{escaped}</a>"
    )


def _find_english_names(
    text: str, english_name_index: dict[str, str]
) -> list[tuple[int, int, str, str]]:
    """Find English bird names in *text* using word-boundary matching.

    Returns ``(start, end, code, matched_text)`` tuples, longest-first,
    non-overlapping.
    """
    if not text or not english_name_index:
        return []

    text_lower = text.lower()
    results: list[tuple[int, int, str, str]] = []
    occupied: set[int] = set()

    candidates = [
        (name, code)
        for name, code in english_name_index.items()
        if " " in name
    ]
    candidates.sort(key=lambda x: len(x[0]), reverse=True)

    for name, code in candidates:
        if not all(w in text_lower for w in name.lower().split()):
            continue
        pattern = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
        for m in pattern.finditer(text):
            span = range(m.start(), m.end())
            if any(pos in occupied for pos in span):
                continue
            results.append((m.start(), m.end(), code, m.group()))
            occupied.update(span)

    return results


def extract_name_pairs(
    text: str,
    english_name_index: dict[str, str],
    code_to_localized: dict[str, str],
) -> dict[str, str]:
    """Extract ``{english_name: localized_name}`` pairs found in *text*.

    Used by the LLM enricher to tell the model the correct localized
    species names present in the scraped context.
    """
    # Reverse index to get canonical English name from code.
    code_to_english = {c: n for n, c in english_name_index.items()}
    pairs: dict[str, str] = {}
    for _start, _end, code, _matched in _find_english_names(text, english_name_index):
        canonical = code_to_english.get(code)
        localized = code_to_localized.get(code)
        if canonical and localized and canonical != localized:
            pairs[canonical] = localized
    return pairs


def process_description(
    raw_text: str,
    english_name_index: dict[str, str],
    code_to_localized: dict[str, str],
    published_anchors: dict[str, str],
    ebird_locale: str = "",
) -> str:
    """Substitute English bird names, link locale names, italicise binomials.

    Two-phase pipeline:
    1. English names → replace with localized name + link.
    2. Localized names → wrap in link (no substitution needed).

    Both phases feed into the same ``occupied`` set, so a span matched
    in phase 1 is never re-matched in phase 2.
    """
    if not raw_text or (not english_name_index and not code_to_localized):
        return html.escape(raw_text or "")

    text_lower = raw_text.lower()

    matches: list[tuple[int, int, str]] = []
    occupied: set[int] = set()

    def _try_add(start: int, end: int, replacement: str) -> bool:
        if any(pos in occupied for pos in range(start, end)):
            return False
        matches.append((start, end, replacement))
        occupied.update(range(start, end))
        return True

    # ── Pass 1: English names → localize + link ─────────────────

    confirmed_species: dict[str, str] = {}  # code → matched English name

    for start, end, code, matched in _find_english_names(raw_text, english_name_index):
        localized = code_to_localized.get(code, matched)
        repl = _make_link(code, localized, published_anchors, ebird_locale)
        if _try_add(start, end, repl):
            confirmed_species[code] = matched

    # ── Pass 2: Localized names → link (always runs) ───────────

    localized_name_index = {
        name: code for code, name in code_to_localized.items() if name
    }
    loc_candidates = [
        (name, code)
        for name, code in localized_name_index.items()
        if " " in name
    ]
    loc_candidates.sort(key=lambda x: len(x[0]), reverse=True)

    for name, code in loc_candidates:
        if not all(w in text_lower for w in name.lower().split()):
            continue
        pattern = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
        for m in pattern.finditer(raw_text):
            repl = _make_link(code, m.group(), published_anchors, ebird_locale)
            if _try_add(m.start(), m.end(), repl):
                confirmed_species[code] = name

    # ── Pass 3: head-word references from confirmed species ─────
    # Spanish species names are head-first ("Frailecillo Atlantico"),
    # so only the FIRST word of the localized name can stand alone as
    # a reference to the species. Matching later words produced false
    # positives in production ("archipielago de las Salomon" linked
    # "Salomon" to Paloma Perdiz de las Salomon). The link keeps the
    # matched text verbatim: substituting the full name mutated
    # sentences ("del Atlantico Norte" -> "del Frailecillo Atlantico
    # Norte").
    for code, full_name in confirmed_species.items():
        localized = code_to_localized.get(code, full_name)
        head = localized.split()[0] if localized else ""
        if len(head) < _MIN_SHORTFORM_LEN:
            continue
        pattern = re.compile(r"\b" + re.escape(head) + r"\b")
        for m in pattern.finditer(raw_text):
            repl = _make_link(code, m.group(), published_anchors, ebird_locale)
            _try_add(m.start(), m.end(), repl)

    # ── Pass 4: dirty-substring cleanup for confirmed species ───

    for code, full_name in confirmed_species.items():
        name_lower = full_name.lower()
        idx = 0
        while True:
            pos = text_lower.find(name_lower, idx)
            if pos < 0:
                break
            end_pos = pos + len(full_name)
            localized = code_to_localized.get(code, raw_text[pos:end_pos])
            repl = _make_link(code, localized, published_anchors, ebird_locale)
            _try_add(pos, end_pos, repl)
            idx = pos + 1

    # ── Pass 5: scientific name italicisation ────────────────────

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

        if parts and parts[-1] and parts[-1][-1].isalpha():
            parts.append(" ")

        parts.append(replacement)

        if end < len(raw_text) and raw_text[end].isalpha():
            parts.append(" ")

        prev_end = end

    parts.append(html.escape(raw_text[prev_end:]))

    return "".join(parts)
