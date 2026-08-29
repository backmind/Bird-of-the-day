"""Structural validation of LLM enrichment output.

The enrichment prompt asks for a precise shape (two paragraphs, 800-1800
characters, 3-5 identification bullets, target language). Models mostly
comply; this module is the contract that turns "mostly" into "always or
fall back". Hard violations reject the draft (the caller may retry with
corrective feedback); soft issues are accepted and logged.

Language detection reuses ``i18n.matches_language`` (langid constrained
to the catalog languages), the same detector the scraper trusts.
"""

from __future__ import annotations

import re

from scripts import i18n

PROSE_MIN = 800
PROSE_MAX = 1800
HARD_TOLERANCE = 0.10
IDENT_MIN = 3
IDENT_MAX = 5

# i18n.matches_language's confidence floor is calibrated for 100-800 char
# prose. Joined identification bullets are often much shorter (40-70
# chars), where the constrained en/es/fr/pt pool makes Spanish/Portuguese
# confusion common enough to burn the corrective retry on already-correct
# output. Below this length the bullets-language check is skipped
# entirely; at or above it, a mismatch is only a soft issue.
BULLETS_LANG_MIN_CHARS = 100

_MARKDOWN_RE = re.compile(r"```|(?:^|\n)#{1,6} |\*\*")


def validate_enrichment(
    result: dict, language: str
) -> tuple[list[str], list[str]]:
    """Validate a parsed LLM response.

    Returns ``(hard, soft)``: hard violations mean the draft must be
    rejected; soft issues are tolerable deviations worth logging. The
    strings are written to be sent back to the model as correction
    feedback, so they state the rule, not just the failure.
    """
    hard: list[str] = []
    soft: list[str] = []

    prose = result.get("prose")
    if not isinstance(prose, str) or not prose.strip():
        hard.append("prose must be a non-empty string")
        return hard, soft

    ident = result.get("identification")
    if (
        not isinstance(ident, list)
        or not (IDENT_MIN <= len(ident) <= IDENT_MAX)
        or not all(isinstance(b, str) and b.strip() for b in ident)
    ):
        hard.append(
            f"identification must be a list of {IDENT_MIN}-{IDENT_MAX} "
            "non-empty strings"
        )

    paragraphs = [p for p in prose.split("\n\n") if p.strip()]
    if len(paragraphs) != 2:
        hard.append(
            "prose must contain exactly 2 paragraphs separated by a blank "
            f"line (got {len(paragraphs)})"
        )

    n = len(prose)
    lo_hard = int(PROSE_MIN * (1 - HARD_TOLERANCE))
    hi_hard = int(PROSE_MAX * (1 + HARD_TOLERANCE))
    if n < lo_hard or n > hi_hard:
        hard.append(
            f"prose must be {PROSE_MIN}-{PROSE_MAX} characters (got {n})"
        )
    elif n < PROSE_MIN or n > PROSE_MAX:
        soft.append(f"prose length {n} outside {PROSE_MIN}-{PROSE_MAX}")

    if _MARKDOWN_RE.search(prose):
        hard.append(
            "prose must be plain text without markdown fences, headings "
            "or bold markers"
        )

    if len(prose) >= i18n.MIN_TEXT_LENGTH and not i18n.matches_language(
        prose, language
    ):
        hard.append(f"prose must be written entirely in language '{language}'")

    if isinstance(ident, list):
        bullets_text = " ".join(str(b) for b in ident)
        if len(bullets_text) >= BULLETS_LANG_MIN_CHARS and not i18n.matches_language(
            bullets_text, language
        ):
            soft.append(
                "identification bullets may not be written in language "
                f"'{language}'"
            )

    return hard, soft
