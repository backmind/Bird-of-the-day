"""Shared HTTP session and download helpers.

Centralizes the retry policy for the pipeline's outbound GET traffic
(eBird, Wikipedia, GBIF, Birds of the World, Macaulay). Retries with
exponential backoff on 429 and 5xx, honoring Retry-After.

LLM calls do NOT go through this session: their retry loop lives in
``llm_enricher`` because POST retries with model fallback don't fit
urllib3's Retry semantics.

``download_image`` is the single choke point for turning a URL into a
validated PIL image: the body is fully decoded before being accepted, so
an HTML error page or truncated tile served with HTTP 200 (the failure
mode that put a watermarked basemap into production) is rejected here.
"""

from __future__ import annotations

import logging
from io import BytesIO

import requests
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15


def build_session(
    total_retries: int = 4,
    backoff_factor: float = 2.0,
    accept_language: str | None = None,
) -> requests.Session:
    """Build a Session with a uniform retry policy on both schemes."""
    session = requests.Session()
    retry = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if accept_language:
        session.headers["Accept-Language"] = accept_language
    return session


def download_image(
    url: str,
    session: requests.Session | None = None,
    timeout: int = REQUEST_TIMEOUT,
) -> Image.Image | None:
    """Download ``url`` and return it as a fully decoded RGBA image.

    Returns ``None`` on any network error or when the body is not a
    decodable image (HTML error pages, truncated files).
    """
    sess = session or build_session()
    try:
        resp = sess.get(url, timeout=timeout)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content))
        img.load()
        return img.convert("RGBA")
    except (requests.RequestException, OSError):
        logger.warning("Failed to download image from %s", url, exc_info=True)
        return None
