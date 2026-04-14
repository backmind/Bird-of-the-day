"""LLM-based content enrichment for Bird of the Day.

When ``content_mode`` is ``enriched``, this module sends scraped species
data to an OpenAI-compatible chat completions endpoint and receives a
cohesive, accessible text with field identification tips.

The enriched content is cached as ``cache/{code}.enriched.json`` so the
LLM is called at most once per species. If the API call fails after
retries, the caller falls back to the programmatic (scrape-only) mode.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from scripts.content_scraper import SpeciesContent
    from scripts.i18n import Catalog

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30

# Upper bound on scraped context sent to the LLM (chars, all sources
# combined). Keeps token costs predictable (~1500 input tokens).
MAX_CONTEXT_CHARS = 5000

_SYSTEM_PROMPT = (
    "You are a wildlife narrator in the spirit of David Attenborough "
    "and Félix Rodríguez de la Fuente. Your voice is warm, curious "
    "and grounded in real observation. You make ornithology accessible "
    "to a general audience without dumbing it down. You never fabricate facts."
)


@dataclass
class EnrichedContent:
    prose: str
    identification: list[str]
    model: str
    timestamp: str


def _truncate_context(text: str, budget: int) -> str:
    """Trim *text* to *budget* chars at the last sentence boundary."""
    if not text or len(text) <= budget:
        return text
    cut = text[:budget]
    for boundary in (". ", "! ", "? ", ".\n"):
        idx = cut.rfind(boundary)
        if idx > budget * 0.4:
            return cut[: idx + 1].strip()
    return cut.rsplit(" ", 1)[0].strip() + "…"


def _build_context(content: SpeciesContent) -> str:
    """Assemble scraped sources into a single context string within budget."""
    # Label each source explicitly. The description may come from
    # eBird or Wikipedia depending on what the scraper found.
    source_label = {
        "ebird": "eBird",
        "wikipedia": "Wikipedia",
    }.get(content.description_source, "Description")

    parts: list[tuple[str, str]] = []
    if content.description:
        parts.append((source_label, content.description))
    # Wikipedia summary is always captured independently of which
    # source won the description slot. Avoid duplicating if the
    # description already came from Wikipedia.
    if content.wikipedia_summary and content.description_source != "wikipedia":
        parts.append(("Wikipedia", content.wikipedia_summary))
    if content.bow_intro:
        parts.append(("Birds of the World", content.bow_intro))
    if content.fallback_text:
        parts.append(("Additional notes", content.fallback_text))

    total = sum(len(v) for _, v in parts)
    if total <= MAX_CONTEXT_CHARS:
        return "\n\n".join(f"[{k}]\n{v}" for k, v in parts)

    # Proportionally trim each source to fit the budget.
    result_parts: list[str] = []
    for label, text in parts:
        budget = int(MAX_CONTEXT_CHARS * len(text) / total)
        result_parts.append(f"[{label}]\n{_truncate_context(text, budget)}")
    return "\n\n".join(result_parts)


def _build_messages(
    english_name: str,
    scientific_name: str,
    content: SpeciesContent,
    language_name: str,
    name_pairs: dict[str, str] | None = None,
) -> list[dict]:
    """Build chat completions messages.

    *english_name* is the English common name from the eBird taxonomy.
    *language_name* is the full English name of the target language
    (e.g. "Spanish", "Brazilian Portuguese"), not the ISO code.
    """
    context = _build_context(content)

    parts = [
        f"Write a short entry about {english_name} ({scientific_name}) "
        f"for a daily Bird of the Day publication.",
        "",
        "Rules:",
        "- Use ONLY verifiable information. Do NOT fabricate data.",
        "- You may add well-known facts beyond the reference data, "
        "but only if you are certain they are accurate.",
        "- If information is scarce, write less. Never invent.",
        "- Do not cite sources or say things like 'according to Wikipedia'.",
        "- When mentioning a bird species for the first time, use its "
        "full common name followed by the scientific name in parentheses, "
        "e.g. 'Masked Booby (Sula dactylatra)'. Subsequent mentions use "
        "only the common name.",
        f"- Write entirely in {language_name}.",
        "- Do not assume the reader's location. Avoid possessives like "
        "'our mountains' or 'our forests'. Describe habitats in third person.",
        "",
        "Reference data:",
        context,
    ]

    # Name pairs: English → locale, so the LLM uses exact taxonomy names.
    if name_pairs:
        pair_lines = [f"  {en} → {loc}" for en, loc in sorted(name_pairs.items())]
        parts.append("")
        parts.append(f"Species names in {language_name}:")
        parts.extend(pair_lines)
        parts.append("Use these exact names when referring to these species.")

    # Output format at the end (closest to where the model generates).
    parts.append("")
    parts.append(
        'Respond with valid JSON (no markdown fences, no commentary):\n'
        '{\n'
        '  "prose": "Two paragraphs separated by \\n\\n, '
        '800-1800 characters total. '
        'First: habitat, behaviour, what makes the species remarkable. '
        'Second: curiosities, surprising facts, ecological role.",\n'
        '  "identification": [\n'
        '    "Visual or auditory trait for field identification",\n'
        '    "Another distinctive feature",\n'
        '    "3-5 bullets total"\n'
        '  ]\n'
        '}'
    )

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(parts)},
    ]


def _call_llm(
    messages: list[dict], config: dict
) -> dict | None:
    """POST to an OpenAI-compatible chat completions endpoint.

    Returns the parsed JSON content on success, ``None`` on failure.
    Retries with exponential backoff.
    """
    llm_cfg = config.get("llm", {})
    endpoint = llm_cfg.get("endpoint", "")
    model = llm_cfg.get("model", "")
    temperature = llm_cfg.get("temperature", 0)
    max_retries = llm_cfg.get("max_retries", 2)

    api_key = os.environ.get("BOTD_LLM_API_KEY", "")
    if not api_key:
        logger.warning("BOTD_LLM_API_KEY not set; skipping LLM enrichment")
        return None
    if not endpoint or not model:
        logger.warning("LLM endpoint/model not configured; skipping")
        return None

    url = f"{endpoint.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": messages,
    }

    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            # Strip markdown fences if the model wraps them anyway.
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            text = text.strip()
            return json.loads(text)
        except (requests.RequestException, KeyError, json.JSONDecodeError) as exc:
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning(
                    "LLM call attempt %d failed (%s), retrying in %ds",
                    attempt + 1, exc, wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "LLM call failed after %d attempts: %s",
                    max_retries + 1, exc,
                )
    return None


def enrich_species(
    species_code: str,
    common_name: str,
    scientific_name: str,
    content: SpeciesContent,
    config: dict,
    catalog: Catalog,
    english_name_index: dict[str, str] | None = None,
    code_to_localized: dict[str, str] | None = None,
) -> EnrichedContent | None:
    """Generate enriched content for a species via LLM.

    Returns ``None`` when the LLM call fails or produces invalid output,
    signalling the caller to fall back to programmatic mode.
    """
    # Extract English→locale name pairs from scraped context so the
    # LLM uses the exact eBird taxonomy names in the target language.
    name_pairs: dict[str, str] = {}
    if english_name_index and code_to_localized:
        from scripts.name_linker import extract_name_pairs
        context_text = _build_context(content)
        name_pairs = extract_name_pairs(
            context_text, english_name_index, code_to_localized
        )
    # Resolve English common name for the hero species.
    english_name = common_name  # fallback if index unavailable
    if english_name_index:
        code_to_english = {c: n for n, c in english_name_index.items()}
        english_name = code_to_english.get(species_code, common_name)

    # Always include the hero's name pair.
    if english_name != common_name:
        name_pairs[english_name] = common_name

    # Resolve the full language name (e.g. "Spanish" not "es").
    from scripts import i18n as _i18n
    try:
        _en = _i18n.Catalog.load("en")
        language_name = _en.t(f"language_name.{catalog.language}")
    except (OSError, json.JSONDecodeError, KeyError):
        language_name = catalog.language

    # Skip name pairs if locale is plain English (no variant) — the
    # reference data and English names already match.
    if catalog.language == "en":
        name_pairs = {}

    messages = _build_messages(
        english_name, scientific_name, content, language_name, name_pairs
    )
    result = _call_llm(messages, config)
    if result is None:
        return None

    prose = result.get("prose", "")
    identification = result.get("identification", [])
    if not prose:
        logger.warning("LLM returned empty prose for %s", species_code)
        return None
    if not isinstance(identification, list):
        identification = []

    model = config.get("llm", {}).get("model", "unknown")
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    logger.info(
        "LLM enrichment for %s: %d chars prose, %d ID bullets (model=%s)",
        species_code, len(prose), len(identification), model,
    )
    return EnrichedContent(
        prose=prose,
        identification=identification,
        model=model,
        timestamp=timestamp,
    )


def _enrichment_cache_path(species_code: str, cache_dir: str) -> Path:
    return Path(cache_dir) / f"{species_code}.enriched.json"


def load_cached_enrichment(
    species_code: str, cache_dir: str = "cache"
) -> EnrichedContent | None:
    from scripts import load_json_cache
    data = load_json_cache(
        _enrichment_cache_path(species_code, cache_dir),
        f"enrichment cache for {species_code}",
    )
    if data is None:
        return None
    return EnrichedContent(
        prose=data.get("prose", ""),
        identification=data.get("identification", []),
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
    )


def save_cached_enrichment(
    species_code: str, enriched: EnrichedContent, cache_dir: str = "cache"
) -> None:
    path = _enrichment_cache_path(species_code, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(enriched), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
