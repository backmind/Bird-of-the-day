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

_SYSTEM_PROMPT = """\
You are a wildlife narrator in the spirit of David Attenborough and \
Félix Rodríguez de la Fuente. You write warm, accessible prose that \
invites readers to discover the world of birds.

Your task: given a bird species name and reference data, write a short \
entry for a daily "Bird of the Day" publication.

STRICT RULES:
- Use ONLY verifiable information. Do NOT fabricate data.
- You MAY include well-known factual knowledge about the species \
beyond the provided sources, but ONLY if you are certain of its accuracy.
- If you lack sufficient information, write less — never invent more.
- Do NOT cite sources or say "according to Wikipedia".
- When mentioning other bird species, always use their full common \
name on first mention.
- Respond in {locale}.

Output format (valid JSON, no markdown fences):
{{
  "prose": "Two paragraphs separated by \\n\\n. 800-1800 characters \
total. First paragraph: introduce the species — habitat, behaviour \
and what makes it remarkable. Second paragraph: curiosities, \
surprising facts, cultural connections or ecological role. \
Each paragraph should be 4-6 sentences.",
  "identification": [
    "Key visual or auditory trait for field identification",
    "Another distinctive feature",
    "3-5 bullets total"
  ]
}}"""


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
    parts: list[tuple[str, str]] = []
    if content.description:
        parts.append(("Description", content.description))
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
    common_name: str,
    scientific_name: str,
    content: SpeciesContent,
    locale: str,
) -> list[dict]:
    """Build chat completions messages."""
    context = _build_context(content)
    user_msg = (
        f"Species: {common_name} ({scientific_name})\n\n"
        f"Reference data:\n{context}"
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT.format(locale=locale)},
        {"role": "user", "content": user_msg},
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
) -> EnrichedContent | None:
    """Generate enriched content for a species via LLM.

    Returns ``None`` when the LLM call fails or produces invalid output,
    signalling the caller to fall back to programmatic mode.
    """
    messages = _build_messages(common_name, scientific_name, content, catalog.language)
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
    path = _enrichment_cache_path(species_code, cache_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Invalid enrichment cache for %s, ignoring", species_code)
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
