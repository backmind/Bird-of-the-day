"""Internationalization: catalog loader + language detection.

Two responsibilities live in this module:

1. **Catalog** — loads ``data/i18n/{lang}.json`` files and exposes a
   ``t(key, **kwargs)`` method with a fallback chain (target language →
   English → key name as a visible bug). Constructed once in
   ``generate.py`` and passed explicitly to all builders.

2. **Language detection** — wraps `langid` constrained to the languages
   that have a catalog file. Used by ``content_scraper.py`` to validate
   that scraped texts actually match the configured language before
   showing them to the reader.

The catalog file format is a flat dict of dotted keys::

    {
      "nav.home": "Today",
      "footer.author_template": "Non-commercial project by Yass Fuentes © {year}.",
      ...
    }

Adding a new language is a single PR: drop ``data/i18n/{lang}.json`` and
``discover_languages()`` picks it up automatically. No code changes needed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CATALOG_DIR = BASE_DIR / "data" / "i18n"

DEFAULT_FALLBACK = "en"

# Mappings used by the Catalog properties. The eBird API and Wikipedia
# happen to use ISO 639-1 codes for our four targets so the maps are
# identity, but they exist as a hook for future regional variants
# (e.g. pt_BR vs pt_PT, en_US vs en_GB).
_EBIRD_LOCALE_MAP: dict[str, str] = {
    "es": "es",
    "en": "en",
    "fr": "fr",
    "pt": "pt",
}

_WIKIPEDIA_SUBDOMAIN_MAP: dict[str, str] = {
    "es": "es",
    "en": "en",
    "fr": "fr",
    "pt": "pt",
}

_ACCEPT_LANGUAGE_MAP: dict[str, str] = {
    "es": "es-ES,es;q=0.9,en;q=0.8",
    "en": "en-US,en;q=0.9",
    "fr": "fr-FR,fr;q=0.9,en;q=0.8",
    "pt": "pt-PT,pt;q=0.9,en;q=0.8",
}


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

# Process-wide cache for parsed catalog files. Loaded lazily, persists for
# the lifetime of the script (which matches the single-run nature of
# generate.py — the cache effectively lasts one cron tick).
_file_cache: dict[str, dict[str, str]] = {}


def discover_languages() -> tuple[str, ...]:
    """Return the languages that have a catalog file in ``data/i18n/``.

    A contributor adds support for ``xx`` simply by dropping
    ``data/i18n/xx.json`` into the repo — no code changes.
    """
    if not CATALOG_DIR.exists():
        return ()
    return tuple(sorted(p.stem for p in CATALOG_DIR.glob("*.json")))


def _load_catalog_file(language: str) -> dict[str, str]:
    if language in _file_cache:
        return _file_cache[language]
    path = CATALOG_DIR / f"{language}.json"
    if not path.exists():
        logger.warning("Catalog file not found: %s", path)
        _file_cache[language] = {}
        return _file_cache[language]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load catalog %s: %s", path, e)
        _file_cache[language] = {}
        return _file_cache[language]
    if not isinstance(data, dict):
        logger.error("Catalog %s is not a dict", path)
        _file_cache[language] = {}
        return _file_cache[language]
    _file_cache[language] = data
    return data


@dataclass
class Catalog:
    """A loaded translation catalog with a fallback chain.

    Construct via :meth:`load`. The active language and a fallback are
    loaded eagerly so ``t()`` never has to do disk I/O at render time.
    """

    language: str
    fallback: str
    _strings: dict[str, str] = field(default_factory=dict)
    _fallback_strings: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, language: str, fallback: str = DEFAULT_FALLBACK) -> "Catalog":
        primary = _load_catalog_file(language)
        if language == fallback:
            fb = primary
        else:
            fb = _load_catalog_file(fallback)
        return cls(
            language=language,
            fallback=fallback,
            _strings=primary,
            _fallback_strings=fb,
        )

    def t(self, key: str, **kwargs: object) -> str:
        """Translate ``key``. Falls back to fallback language, then to the key.

        Supports ``str.format``-style named placeholders via kwargs::

            catalog.t("footer.author_template", year=2026)

        If a key is missing in BOTH the active language and the fallback,
        the key itself is returned and a warning is logged. This is a
        visible bug, never a crash.
        """
        raw = self._strings.get(key)
        if raw is None:
            raw = self._fallback_strings.get(key)
        if raw is None:
            logger.warning("Missing i18n key: %s (lang=%s)", key, self.language)
            raw = key
        if kwargs:
            try:
                return raw.format(**kwargs)
            except (KeyError, IndexError, ValueError) as e:
                logger.warning(
                    "Format failed for key %s with args %s: %s", key, kwargs, e
                )
                return raw
        return raw

    @property
    def html_lang(self) -> str:
        """Value suitable for ``<html lang="...">`` and RSS ``<language>``."""
        return self.language

    @property
    def wikipedia_subdomain(self) -> str:
        return _WIKIPEDIA_SUBDOMAIN_MAP.get(self.language, self.language)

    @property
    def ebird_locale(self) -> str:
        return _EBIRD_LOCALE_MAP.get(self.language, self.language)

    @property
    def accept_language_header(self) -> str:
        return _ACCEPT_LANGUAGE_MAP.get(
            self.language, f"{self.language},en;q=0.8"
        )


# ---------------------------------------------------------------------------
# Language detection (langid, constrained)
# ---------------------------------------------------------------------------

# Reject langid verdicts below this probability. Calibrated for 100-800 char
# prose. Conservative because the foreign-text-shown failure mode is worse
# than the description-empty failure mode.
MIN_PROB = 0.85
# Below this length langid is noise-dominated.
MIN_TEXT_LENGTH = 40

_identifier = None  # holds the langid LanguageIdentifier instance, lazy


def _get_identifier(candidates: Iterable[str]):
    """Return a langid identifier constrained to ``candidates``.

    The model is loaded once per process and the language set is updated
    on each call. langid's API allows changing the constraint without
    rebuilding the model.
    """
    global _identifier
    if _identifier is None:
        from langid.langid import LanguageIdentifier, model
        _identifier = LanguageIdentifier.from_modelstring(model, norm_probs=True)
    _identifier.set_languages(list(candidates))
    return _identifier


def detect_language(
    text: str, candidates: Iterable[str] | None = None
) -> tuple[str, float] | None:
    """Classify ``text`` against ``candidates`` (or all known languages).

    Returns ``(lang, probability)`` if langid is confident enough,
    otherwise ``None``. The probability is normalized 0-1 (langid is
    initialized with ``norm_probs=True``).
    """
    if not text or len(text) < MIN_TEXT_LENGTH:
        return None
    pool = tuple(candidates) if candidates is not None else discover_languages()
    if not pool:
        return None
    try:
        ident = _get_identifier(pool)
        lang, prob = ident.classify(text)
    except Exception:
        logger.debug("langid classify failed", exc_info=True)
        return None
    if prob < MIN_PROB:
        return None
    return lang, prob


def matches_language(text: str, target: str) -> bool:
    """True iff ``text`` is confidently classified as ``target``.

    The classifier is constrained to the languages that have a catalog
    file, so ``target`` must be one of those (otherwise we get unconstrained
    classification which defeats the precision win). For an unrecognized
    target this returns ``False`` and logs a warning.
    """
    known = discover_languages()
    if target not in known:
        if known:
            logger.warning(
                "matches_language: target %r not in known catalogs %s", target, known
            )
        return False
    result = detect_language(text, candidates=known)
    if result is None:
        return False
    lang, _prob = result
    return lang == target
