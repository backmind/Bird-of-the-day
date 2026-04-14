"""Multi-strategy image fetcher for bird species photos.

Two live strategies + a fallback:
  1. Macaulay Library Search internal JSON API (returns assetId + photographer).
  2. eBird species page meta tags (og:image + og:image:alt). Requires a
     Session because eBird's CAS gateway needs cookies to resolve redirects.
  3. Fallback: link to ML Search without an inline image.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (compatible; bird-of-the-day-rss/1.0; "
    "+https://github.com/backmind/Bird-of-the-day)"
)
CDN_BASE = "https://cdn.download.ams.birds.cornell.edu/api/v2/asset"
ML_SEARCH_BASE = "https://search.macaulaylibrary.org"
DEFAULT_SIZE = 900


@dataclass
class ImageResult:
    url: str | None
    asset_id: str | None
    photographer: str
    attribution: str
    search_url: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ImageResult":
        return cls(
            url=data.get("url"),
            asset_id=data.get("asset_id"),
            photographer=data.get("photographer", ""),
            attribution=data.get("attribution", ""),
            search_url=data.get("search_url", ""),
        )


DEFAULT_ACCEPT_LANGUAGE = "en-US,en;q=0.9"


def new_session(accept_language: str = DEFAULT_ACCEPT_LANGUAGE) -> requests.Session:
    """Create a Session preloaded with headers we want everywhere.

    The ``Accept-Language`` header is parameterised so the caller can pass
    the configured language's quality string (typically from
    ``catalog.accept_language_header``). Default is English so the function
    is usable as a standalone helper without an i18n catalog.
    """
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": accept_language,
        }
    )
    return s


def _ml_search_url(species_code: str) -> str:
    return (
        f"{ML_SEARCH_BASE}/catalog"
        f"?taxonCode={species_code}&mediaType=photo&sort=rating_rank_desc"
    )


def _cdn_url(asset_id: str, size: int = DEFAULT_SIZE) -> str:
    return f"{CDN_BASE}/{asset_id}/{size}"


def _attribution(photographer: str) -> str:
    photographer = photographer.strip()
    if photographer:
        return f"{photographer} / Macaulay Library"
    return "Macaulay Library"


def _try_macaulay_api(
    species_code: str, session: requests.Session
) -> ImageResult | None:
    """Strategy 1: Macaulay Library Search internal JSON API.

    Confirmed shape: ``{"results": {"count": N, "content": [...], "nextCursorMark": ...}}``.
    Each item has ``assetId``, ``catalogId``, ``userDisplayName``, ``rating``, etc.
    """
    url = (
        f"{ML_SEARCH_BASE}/api/v1/search"
        f"?taxonCode={species_code}&mediaType=photo&sort=rating_rank_desc&count=1"
    )
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.debug("ML API failed for %s: %s", species_code, e)
        return None

    if not isinstance(data, dict):
        return None
    content = data.get("results", {}).get("content", []) or []
    if not content:
        return None

    first = content[0]
    asset_id = str(first.get("assetId") or first.get("catalogId") or "").strip()
    if not asset_id:
        return None

    photographer = (first.get("userDisplayName") or "").strip()
    return ImageResult(
        url=_cdn_url(asset_id),
        asset_id=asset_id,
        photographer=photographer,
        attribution=_attribution(photographer),
        search_url=_ml_search_url(species_code),
    )


_OG_ASSET_RE = re.compile(r"/asset/(\d+)")


def _try_ebird_og_image(
    species_code: str, session: requests.Session, locale: str = "en"
) -> ImageResult | None:
    """Strategy 2: og:image + og:image:alt from the eBird species page.

    Format observed:
      ``<meta property="og:image" content=".../api/v2/asset/{id}/{size}">``
      ``<meta property="og:image:alt" content="<Common Name> - <Photographer>">``

    The ``locale`` parameter controls the eBird language: with ``locale=es``
    the alt tag carries the Spanish common name, with ``locale=en`` the
    English one. Either way the asset id is the same.
    """
    url = f"https://ebird.org/species/{species_code}"
    try:
        resp = session.get(url, params={"locale": locale}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.debug("eBird species page failed for %s: %s", species_code, e)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    og_image = soup.find("meta", property="og:image")
    if not og_image or not og_image.get("content"):
        return None

    og_url = og_image["content"]
    match = _OG_ASSET_RE.search(og_url)
    if not match:
        # Not a Macaulay CDN URL: surface as-is, no asset_id.
        return ImageResult(
            url=og_url,
            asset_id=None,
            photographer="",
            attribution="Macaulay Library / Cornell Lab of Ornithology",
            search_url=_ml_search_url(species_code),
        )

    asset_id = match.group(1)
    photographer = ""
    og_alt = soup.find("meta", property="og:image:alt")
    if og_alt and og_alt.get("content"):
        alt = og_alt["content"]
        if " - " in alt:
            photographer = alt.rsplit(" - ", 1)[-1].strip()

    return ImageResult(
        url=_cdn_url(asset_id),
        asset_id=asset_id,
        photographer=photographer,
        attribution=_attribution(photographer),
        search_url=_ml_search_url(species_code),
    )


def _fallback(species_code: str) -> ImageResult:
    return ImageResult(
        url=None,
        asset_id=None,
        photographer="",
        attribution="Macaulay Library / Cornell Lab of Ornithology",
        search_url=_ml_search_url(species_code),
    )


def fetch_image(
    species_code: str,
    session: requests.Session | None = None,
    locale: str = "en",
) -> ImageResult:
    """Fetch the species image, prioritising eBird's curated hero.

    Strategy order, with rationale:

    1. **eBird species page og:image** — the photo eBird's editors have
       chosen as the canonical hero for that species. This is what a
       human visiting ``https://ebird.org/species/{code}`` sees, so it
       is the photo readers expect to be served.
    2. **Macaulay Library Search API** — the highest-rated photo from
       the public catalog. Reached when eBird hasn't curated a hero
       (rare; tends to happen with very recent splits or obscure
       endemics). Reliable fallback because it returns *something*
       whenever Macaulay has any photo at all.
    3. **No image + link to ML Search** — last-resort fallback. The
       reader can click through to find a photo manually.

    Earlier revisions had the order reversed (rating-first), which
    surfaced the highest-rated Macaulay photo regardless of eBird's
    curation. That picked technically beautiful but unfamiliar shots
    instead of the photo readers expected to see.

    ``locale`` is forwarded to the eBird species-page strategy. The
    Macaulay API strategy doesn't take a locale (asset metadata is
    language-agnostic).
    """
    sess = session or new_session()
    result = _try_ebird_og_image(species_code, sess, locale=locale)
    if result is not None:
        return result
    result = _try_macaulay_api(species_code, sess)
    if result is not None:
        return result
    return _fallback(species_code)


def _image_cache_path(species_code: str, cache_dir: str) -> Path:
    return Path(cache_dir) / f"{species_code}.image.json"


def load_cached_image(
    species_code: str, cache_dir: str = "cache"
) -> ImageResult | None:
    path = _image_cache_path(species_code, cache_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Invalid image cache for %s", species_code)
        return None
    if not data.get("asset_id") and not data.get("url"):
        return None
    return ImageResult.from_dict(data)


def save_cached_image(
    species_code: str, result: ImageResult, cache_dir: str = "cache"
) -> None:
    """Persist a successful image lookup. Failures are not cached so they retry."""
    if not result.asset_id and not result.url:
        return
    path = _image_cache_path(species_code, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
