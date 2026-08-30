"""Species name substitution, cross-linking, and scientific-name italicisation.

Pipeline over raw description text:

  1. **English → locale substitution** — 2+ word English names matched
     with word boundaries, longest-first. Replaces with the localised
     name and wraps in a link (archive or eBird fallback). When a real
     substitution happens (a localized name is actually known for the
     species), an immediately preceding singular determiner is
     rewritten to agree with the localised name's gender: "el"/"un"/
     "del"/"al" toward feminine, or "la"/"una"/"de la"/"a la" toward
     masculine. Adjective agreement is out of scope.
  2. **Locale → link** — localized names matched with word boundaries.
     Wraps in a link without substitution (the name is already in the
     target language). This pass always runs, catching names written
     in the locale by the LLM or by locale-aware scraping.
  3. **Scientific-name pass** — binomial names from the eBird taxonomy,
     case-insensitive, word-boundary. Wraps in ``<em>``. Runs ahead of
     the two speculative passes below: a binomial is an exact
     two-word match from the taxonomy, so it outranks a single word
     guessed to refer to a species.
  4. **Short-form pass** — the first (head) word of the localized name
     of species confirmed in passes 1-2, when it is ≥ 4 chars,
     case-sensitive, word-boundary. Spanish species names are
     head-first, so only that first word can stand alone as a
     reference to the species; the matched text is kept verbatim
     (never replaced by the full name).
  5. **Dirty-substring pass** — full confirmed names as substrings
     (no word boundaries). Catches formatting artifacts.

Input is normalised first: Markdown emphasis the model sometimes adds
around a binomial is dropped, since pass 3 supplies those italics.

Processing happens at render time (not cached) because the set of
published species changes daily.
"""

from __future__ import annotations

import html
import re

_MIN_SHORTFORM_LEN = 4  # words shorter than this are skipped in pass 4

# The prompt asks for plain text and the validator rejects bold, but the
# model still reaches for single-asterisk emphasis around a binomial
# ("(*Aegypius monachus*)"). Nothing downstream renders Markdown, so the
# markers surfaced on the page as literal asterisks. Pass 3 italicises
# the same binomials from the taxonomy, so the markers are dropped
# rather than translated. The lookahead and the trailing character class
# require non-space either side of the run, which leaves arithmetic and
# footnote asterisks ("5 * 3") untouched.
_MD_EMPHASIS_RE = re.compile(r"\*(?=[^\s*])([^*\n]*[^\s*])\*")

# Feminine Spanish nouns that take the masculine-looking article "el"/"un"
# in the singular (stressed initial a-). Determiner rewriting is skipped
# for these heads: "el aguila" is already correct Spanish.
_FEMININE_EL_HEADS = {"águila", "ave"}


def _localized_gender(localized: str) -> str:
    """Best-effort grammatical gender ("m"/"f") of a Spanish species name.

    Uses the head noun's ending: -a is feminine, everything else
    masculine. Bird head nouns follow this rule almost without
    exception (gaviota, cotorra, curruca / azor, milano, halcon); a
    masculine exception set for -a-ending heads would go here if one
    is ever needed.
    """
    head = (localized.split() or [""])[0].lower() if localized else ""
    return "f" if head.endswith("a") else "m"


_DETERMINER_RE = re.compile(
    r"(?P<det>\b(?:de la|a la|el|la|un|una|del|al))(?P<ws>\s+)$",
    re.IGNORECASE,
)

# masculine form -> feminine form; the reverse map is derived below.
_DET_M2F = {"el": "la", "un": "una", "del": "de la", "al": "a la"}
_DET_F2M = {"la": "el", "una": "un", "de la": "del", "a la": "al"}


def _agree_determiner(det: str, gender: str) -> str | None:
    """Return the gender-agreeing form of *det*, or None if no change.

    Preserves the capitalization of the first letter. Only singular
    determiners are handled; plurals and demonstratives are left alone.
    """
    lower = det.lower()
    if gender == "f" and lower in _DET_M2F:
        fixed = _DET_M2F[lower]
    elif gender == "m" and lower in _DET_F2M:
        fixed = _DET_F2M[lower]
    else:
        return None
    if det[0].isupper():
        fixed = fixed[0].upper() + fixed[1:]
    return fixed


def _extend_with_determiner(
    raw_text: str, start: int, end: int, localized: str
) -> tuple[int, int, str]:
    """Extend a match span backwards to cover a determiner needing agreement.

    Returns ``(start, end, det_prefix)``. ``det_prefix`` is the corrected
    determiner text plus its trailing whitespace, or ``""`` when no
    correction is needed (the original *start* is returned unchanged).
    """
    head = (localized.split() or [""])[0].lower() if localized else ""
    if head in _FEMININE_EL_HEADS:
        return start, end, ""

    det_match = _DETERMINER_RE.search(raw_text[:start])
    if not det_match:
        return start, end, ""

    gender = _localized_gender(localized)
    corrected = _agree_determiner(det_match.group("det"), gender)
    if corrected is None:
        return start, end, ""

    new_start = det_match.start("det")
    prefix = corrected + det_match.group("ws")
    return new_start, end, prefix


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

    The five passes are documented at the top of this module. They run
    in decreasing order of certainty and share one ``occupied`` set, so
    an earlier pass's span is never re-matched by a later one: that
    ordering is what decides every collision.
    """
    raw_text = _MD_EMPHASIS_RE.sub(r"\1", raw_text or "")

    if not raw_text or (not english_name_index and not code_to_localized):
        return html.escape(raw_text)

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
        link = _make_link(code, localized, published_anchors, ebird_locale)

        # Only rewrite the preceding determiner when a real substitution
        # happens: code_to_localized.get(code, matched) falls back to the
        # English matched text itself when the code is absent (e.g. a
        # degraded taxonomy fetch), and the English head must never be
        # used to infer Spanish gender.
        substituted = code in code_to_localized and code_to_localized[code] != matched
        det_prefix = ""
        ext_start, ext_end = start, end
        if substituted:
            ext_start, ext_end, det_prefix = _extend_with_determiner(
                raw_text, start, end, localized
            )

        if _try_add(ext_start, ext_end, det_prefix + link):
            confirmed_species[code] = matched
        elif det_prefix and _try_add(start, end, link):
            # The extended span (covering the determiner) collided with
            # an already-occupied region; fall back to the plain span so
            # an occupied determiner cannot silently drop the match.
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

    # ── Pass 3: scientific name italicisation ────────────────────
    # Ahead of passes 4 and 5 on purpose. Spanish bird names routinely
    # reuse the genus as their head noun (Atlapetes de Anteojos /
    # Atlapetes melanopsis, Curruca Rabilarga / Curruca undata), and
    # the head-word pass claimed that first word inside the binomial:
    # the name came out split across an anchor and never italicised.
    # An exact two-word match from the taxonomy outranks a single word
    # guessed to stand for a species.

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

    # ── Pass 4: head-word references from confirmed species ─────
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
        head = (localized.split() or [""])[0] if localized else ""
        if len(head) < _MIN_SHORTFORM_LEN:
            continue
        pattern = re.compile(r"\b" + re.escape(head) + r"\b")
        for m in pattern.finditer(raw_text):
            repl = _make_link(code, m.group(), published_anchors, ebird_locale)
            _try_add(m.start(), m.end(), repl)

    # ── Pass 5: dirty-substring cleanup for confirmed species ───

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
