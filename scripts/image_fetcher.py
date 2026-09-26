"""Multi-strategy image fetcher for bird species photos.

Four live strategies + a fallback:
  1. Macaulay Library Search internal JSON API (returns assetId + photographer).
  2. eBird species page meta tags (og:image + og:image:alt). Requires a
     Session because eBird's CAS gateway needs cookies to resolve redirects.
  3. iNaturalist, through its public taxa API: the taxon's default photo,
     when its author has put a Creative Commons licence on it.
  4. Wikimedia Commons, through the Wikipedia article for the scientific
     name: a photograph of a live bird from that article, with author and
     licence from the file page.
  5. Fallback: link to ML Search without an inline image.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from scripts import http_client

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

    Built on ``http_client.build_session`` so every scrape shares the same
    retry policy.
    """
    s = http_client.build_session(accept_language=accept_language)
    s.headers["User-Agent"] = USER_AGENT
    return s


def ml_search_url(species_code: str) -> str:
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


MACAULAY_LOOKAHEAD = 5

# Cornell put Anubis, a proof-of-work gate against crawlers, in front of
# search.macaulaylibrary.org on 2026-08-30 and in front of ebird.org on
# 2026-09-22. Whatever the User-Agent, every request gets a 200 carrying
# an HTML challenge that only a browser running JavaScript can pass; for
# ebird.org that page even carries eBird's generic meta description, which
# is what the "generic page" detector was catching. Gating the site is the
# owner's decision, so this code does not try to pass the challenge: it
# recognises it, says so once per run and host, and lets the sources that
# do answer take over. The requests are still made, so the strategies come
# back by themselves the day the gate is lifted.
_BOT_GATE_MARKS = (
    "making sure you're not a bot",
    "making sure you&#39;re not a bot",
    "anubis",
)
_bot_gates_reported: set[str] = set()


def is_bot_gate(text: str) -> bool:
    """Whether an HTML body is a bot-gate challenge rather than content."""
    head = (text or "")[:4096].lower()
    return any(mark in head for mark in _BOT_GATE_MARKS)


def _report_bot_gate(host: str, species_code: str) -> None:
    """Log the gate as a warning the first time a host shows it, then as debug."""
    if host in _bot_gates_reported:
        logger.debug("%s is behind Cornell's bot gate; skipped for %s", host, species_code)
        return
    _bot_gates_reported.add(host)
    logger.warning(
        "%s answers with Cornell's bot gate (Anubis) instead of content "
        "(seen for %s); its strategy yields to iNaturalist and Commons "
        "for this run",
        host,
        species_code,
    )



def _try_macaulay_api(
    species_code: str,
    session: requests.Session,
    *,
    count: int = 1,
    skip: frozenset[str] = frozenset(),
) -> ImageResult | None:
    """Strategy 1: Macaulay Library Search internal JSON API.

    Confirmed shape: ``{"results": {"count": N, "content": [...], "nextCursorMark": ...}}``.
    Each item has ``assetId``, ``catalogId``, ``userDisplayName``, ``rating``, etc.

    ``skip`` holds the assets this species has already been published
    with, so a republication can walk down the rating order until it finds
    a photograph the reader has not seen.
    """
    url = (
        f"{ML_SEARCH_BASE}/api/v1/search"
        f"?taxonCode={species_code}&mediaType=photo&sort=rating_rank_desc"
        f"&count={count}"
    )
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("ML search API unavailable for %s: %s", species_code, e)
        return None
    if is_bot_gate(getattr(resp, "text", "")):
        _report_bot_gate("search.macaulaylibrary.org", species_code)
        return None
    try:
        data = resp.json()
    except ValueError as e:
        # Not debug: this strategy is the only one that can find a
        # photograph eBird has not curated, and the only one that can find
        # a *different* photograph for a republication. When it stops
        # answering, both features go quiet with nothing to show for it.
        logger.warning("ML search API unavailable for %s: %s", species_code, e)
        return None

    if not isinstance(data, dict):
        logger.warning("ML search API returned no object for %s", species_code)
        return None
    content = data.get("results", {}).get("content", []) or []

    for item in content:
        asset_id = str(item.get("assetId") or item.get("catalogId") or "").strip()
        if not asset_id or asset_id in skip:
            continue
        photographer = (item.get("userDisplayName") or "").strip()
        return ImageResult(
            url=_cdn_url(asset_id),
            asset_id=asset_id,
            photographer=photographer,
            attribution=_attribution(photographer),
            search_url=ml_search_url(species_code),
        )
    return None


_OG_ASSET_RE = re.compile(r"/asset/(\d+)")

# The meta description eBird serves on its generic landing page. From
# 2026-09-22 the species URL started answering the runner with that page
# instead of the species page on most requests: no hero, and this text in
# og:description, which the content scraper then cached as if it were the
# species' Merlin text (140 caches in four days).
_EBIRD_GENERIC_DESCRIPTIONS = (
    "ebird transforms your bird sightings",
)


def is_ebird_species_page(soup: BeautifulSoup, species_code: str) -> bool:
    """Whether a page fetched from ``/species/{code}`` is that species' page.

    eBird can answer the species URL with its generic landing page (an
    anti-bot interstitial or a redirect lands there). That page has meta
    tags too, and reading them as the species' would publish eBird's
    slogan as a description, or a hero that is not this bird. Declines
    when the page's own canonical URL names another page, or when its
    description is the known generic one. A page that states neither is
    given the benefit of the doubt, as before.
    """
    og_desc = soup.find("meta", property="og:description")
    desc = (og_desc.get("content") or "").strip().lower() if og_desc else ""
    if any(desc.startswith(g) for g in _EBIRD_GENERIC_DESCRIPTIONS):
        return False
    code = species_code.lower()
    og_url = soup.find("meta", property="og:url")
    canonical = soup.find("link", rel="canonical")
    for tag, attr in ((og_url, "content"), (canonical, "href")):
        if tag is not None and tag.get(attr):
            return f"/species/{code}" in tag[attr].lower()
    return True


def asset_id_from_url(url: str | None) -> str | None:
    """The Macaulay asset id embedded in a photo URL, if there is one.

    History records the URL a plate was published with, which makes it the
    only record of which photographs a reader has already been shown for a
    given species.
    """
    if not url:
        return None
    match = _OG_ASSET_RE.search(url)
    return match.group(1) if match else None


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

    Returns ``None`` when the page cannot be fetched, when it carries no
    ``og:image``, and when the tag it carries has no asset id in it. That
    last case is not theoretical: eBird emits the tag for species it has
    no curated hero for, with the id left out.
    """
    url = f"https://ebird.org/species/{species_code}"
    try:
        resp = session.get(url, params={"locale": locale}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.debug("eBird species page failed for %s: %s", species_code, e)
        return None

    if is_bot_gate(resp.text):
        _report_bot_gate("ebird.org", species_code)
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    if not is_ebird_species_page(soup, species_code):
        logger.warning(
            "eBird served a generic page instead of the species page for %s",
            species_code,
        )
        return None
    og_image = soup.find("meta", property="og:image")
    if not og_image or not og_image.get("content"):
        return None

    og_url = og_image["content"]
    match = _OG_ASSET_RE.search(og_url)
    if not match:
        # No asset id in the tag, so we do not know what this URL points
        # at. Earlier revisions surfaced it as-is, which published a
        # broken photograph twice: eBird serves the hero tag even for a
        # species it has no hero for, with the id left empty, and
        # ".../api/v2/asset//900" is a 404 the reader sees as a hole in
        # the plate. Decline and let the Macaulay strategy answer.
        logger.debug(
            "eBird og:image for %s carries no asset id (%s)",
            species_code,
            og_url,
        )
        return None

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
        search_url=ml_search_url(species_code),
    )


INATURALIST_TAXA_API = "https://api.inaturalist.org/v1/taxa"


def _without_query(url: str) -> str:
    """``url`` with its query string and fragment removed.

    The MediaWiki API started appending ``utm_source``/``utm_campaign``
    to the thumbnails it hands out, and the first Commons photograph this
    site published (gobfly2, 2026-09-25) went out carrying them. The site
    says it does not track its readers, and a hot link that reports where
    it was embedded is tracking, whoever does the counting.
    """
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _inat_licence(code: str) -> str:
    """``cc-by-nc-sa`` as the site shows licences: ``CC BY-NC-SA``."""
    code = code.strip().lower()
    if code == "cc0":
        return "CC0"
    if code.startswith("cc-"):
        return "CC " + code[3:].upper()
    return code.upper()


_INAT_ATTRIBUTION_RE = re.compile(
    r"^\s*(?:\(c\)|©)?\s*(?P<name>.+?),\s*(?:some|all|no) rights reserved",
    re.IGNORECASE,
)


def _inat_author(photo: dict) -> str:
    """Who took an iNaturalist photo, without iNat's own "(c)".

    iNaturalist writes the credit as ``(c) Name, some rights reserved
    (CC BY-NC)``. The plate already prints a "©" and the licence goes in
    its own parenthesis, so only the name is kept. ``attribution_name``
    is used when the API sends it, the parsed string otherwise.
    """
    name = (photo.get("attribution_name") or "").strip()
    if name:
        return name
    match = _INAT_ATTRIBUTION_RE.match(photo.get("attribution") or "")
    return match.group("name").strip() if match else ""


def _try_inaturalist(
    scientific_name: str, session: requests.Session
) -> ImageResult | None:
    """Strategy 3: the default photo of the iNaturalist taxon.

    One call to the public, documented, unauthenticated taxa endpoint.
    The default photo is the one the community chose to represent the
    taxon, taken from observations, which are overwhelmingly photographs
    of live birds rather than of a museum drawer: Commons gave this site
    a skin from Naturalis for gobfly2 on 2026-09-25.

    Only an exact match on the scientific name is taken: ``q`` is a
    fuzzy search, and a near neighbour's photograph under this bird's
    name would be worse than no photograph. A photo with no licence
    (``license_code`` null) is "all rights reserved" and is declined.
    The rest are all Creative Commons, including the NC variants, which
    this project can use because it is non-commercial (README). None of
    them is modified here: the ``large`` rendition is iNaturalist's own.

    ``medium`` is 500 px on the long side and ``large`` 1024; the
    renditions differ only in that path segment.
    """
    if not scientific_name:
        return None
    try:
        resp = session.get(INATURALIST_TAXA_API, params={
            "q": scientific_name, "rank": "species", "per_page": "10",
        }, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        results = resp.json().get("results", []) or []
    except (requests.RequestException, ValueError, AttributeError) as e:
        logger.warning("iNaturalist lookup failed for %s: %s", scientific_name, e)
        return None

    wanted = scientific_name.strip().casefold()
    taxon = next(
        (
            t for t in results
            if (t.get("name") or "").strip().casefold() == wanted
            and t.get("is_active", True) is not False
        ),
        None,
    )
    if taxon is None:
        logger.info("iNaturalist has no taxon named %s", scientific_name)
        return None
    photo = taxon.get("default_photo") or {}
    if not (photo.get("license_code") or "").strip():
        # The default photo of Stercorarius maccormicki and of Microeca
        # hemixantha was "all rights reserved" on 2026-09-25, which left
        # both to Commons. The taxon usually has other photos curated
        # alongside it; the first one with a licence will do.
        logger.info(
            "iNaturalist default photo for %s is all rights reserved",
            scientific_name,
        )
        photo = _licensed_taxon_photo(taxon.get("id"), session) or {}
    code = (photo.get("license_code") or "").strip()
    url = photo.get("medium_url") or photo.get("url") or ""
    if not url or not code:
        return None
    url = _without_query(url)
    url = re.sub(r"/(?:medium|square|small|thumb)(\.\w+)$", r"/large\1", url)
    author = _inat_author(photo)
    licence = _inat_licence(code)
    credit = " / ".join(x for x in (author, "iNaturalist") if x)
    return ImageResult(
        url=url,
        asset_id=None,
        photographer=author,
        attribution=f"{credit} ({licence})",
        search_url="",
    )


def _licensed_taxon_photo(
    taxon_id: int | str | None, session: requests.Session
) -> dict | None:
    """The first licensed photo among a taxon's curated photos.

    The search endpoint only carries the default photo; the taxon's own
    record (``/v1/taxa/{id}``) lists every photo curated for it, in the
    order the community ranked them, under ``taxon_photos``.
    """
    if not taxon_id:
        return None
    try:
        resp = session.get(
            f"{INATURALIST_TAXA_API}/{taxon_id}", timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        results = resp.json().get("results", []) or []
    except (requests.RequestException, ValueError, AttributeError) as e:
        logger.warning("iNaturalist taxon %s failed: %s", taxon_id, e)
        return None
    for taxon in results:
        for entry in taxon.get("taxon_photos") or []:
            photo = (entry or {}).get("photo") or {}
            if (photo.get("license_code") or "").strip() and (
                photo.get("medium_url") or photo.get("url")
            ):
                return photo
    logger.info("iNaturalist has no licensed photo for taxon %s", taxon_id)
    return None


WIKIPEDIA_API = "https://{lang}.wikipedia.org/w/api.php"
WIKIMEDIA_LANGUAGES = ("en",)
# Files looked at per article. The lead image comes first, then the rest
# of the article's files in the order MediaWiki lists them.
WIKIMEDIA_MAX_CANDIDATES = 20


def _plain(html: str) -> str:
    """Text of a Commons metadata field, which arrives as HTML."""
    return " ".join(BeautifulSoup(html or "", "html.parser").get_text(" ").split())


# What a bird-of-the-day plate must not be. Commons files a lot of
# museum material under the species, and an article's lead image can be
# one of them: on 2026-09-25 gobfly2 was published with a Naturalis skin
# ("... - bird skin specimen.jpeg"). Whole words only, so "range" does
# not reject "orange", and "plate" only when it is a book plate
# ("Plate 12", "plates from ..."), so the Plate-billed Mountain Toucan
# keeps its photographs.
_UNSUITABLE_RE = re.compile(
    r"\b(?:"
    r"specimens?|skins?|museums?|naturalis|taxiderm\w*"
    r"|eggs?|clutch|skeletons?|skulls?"
    r"|illustrations?|drawings?|paintings?|lithographs?|engravings?"
    r"|plates?\s+(?:no\.?\s*)?(?:\d+|[ivxlcdm]+\b)|plates?\s+(?:from|of|in)\b"
    r"|maps?|range|stamps?"
    r")\b",
    re.IGNORECASE,
)

# Categories MediaWiki adds for its own bookkeeping, which say nothing
# about what the picture shows: every geotagged photograph is in "Pages
# with maps", and that must not read as a map.
_MAINTENANCE_CATEGORY_RE = re.compile(
    r"^(?:(?:pages|files|media|images|items)\s+(?:with|without|missing|by|from)"
    r"|uploaded\b|taken with\b)",
    re.IGNORECASE,
)


def _unsuitable(name: str, meta: dict) -> str | None:
    """Why a Commons file is not a photograph of a live bird, or ``None``.

    Reads the file name, the description and the categories. Underscores
    and hyphens are word separators here: the names arrive as
    ``Naturalis_..._-_bird_skin_specimen.jpeg``.
    """
    description = _plain(meta.get("ImageDescription", {}).get("value", ""))
    categories = [
        c.strip()
        for c in (meta.get("Categories", {}).get("value", "") or "").split("|")
        if c.strip() and not _MAINTENANCE_CATEGORY_RE.match(c.strip())
    ]
    for text in (name, description, *categories):
        match = _UNSUITABLE_RE.search(re.sub(r"[_\-]+", " ", text))
        if match:
            return match.group(0)
    return None


# A taxonomic authority, "Sclater, 1883" or "(Linnaeus, 1758)". Naturalis
# uploads put it in the Artist field, and gobfly2 went out on 2026-09-25
# credited to a zoologist who died in 1913.
_AUTHORITY_RE = re.compile(r"^\(?[^\W\d][^,()]*,\s*1[789]\d\d\)?$")
_PLACEHOLDER_RE = re.compile(
    r"^(?:unknown|anonymous|anon\.?|unknown author|author unknown)$",
    re.IGNORECASE,
)
# What ``Credit`` holds when it names a source rather than a person.
_SOURCE_RE = re.compile(
    r"own work|https?:|www\.|flickr|transferred|wikipedia|commons|\bsource\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"\s*\(?\s*https?://\S+?\s*\)?(?=\s|$)")


def _commons_author(meta: dict) -> str:
    """The person to credit for a Commons file, or ``""``.

    ``Artist`` first, then ``Credit``, and neither when it reads as a
    taxonomic authority or a placeholder. ``Credit`` is usually the
    source ("Own work", a Flickr link) rather than a person, so it is
    only taken when it reads as neither. A bare URL next to a name
    ("JJ Harrison (https://...)") is dropped and the name kept. With no
    author the plate credits "Wikimedia Commons" and the licence alone,
    which is honest; a wrong name is not.
    """
    for field in ("Artist", "Credit"):
        value = _URL_RE.sub("", _plain(meta.get(field, {}).get("value", ""))).strip()
        if (
            not value
            or len(value) > 100
            or _AUTHORITY_RE.match(value)
            or _PLACEHOLDER_RE.match(value)
            or (field == "Credit" and _SOURCE_RE.search(value))
        ):
            continue
        return value
    return ""


def _names_species(name: str, meta: dict, scientific_name: str) -> bool:
    """Whether a Commons file says it shows ``scientific_name``.

    An article uses files of other birds too: relatives, look-alikes,
    the genus. On 2026-09-25 the Microeca hemixantha article offered
    "SouthIslandTomtit.jpg", a Petroica. The lead image is the article's
    own choice and is trusted; any other file has to carry the binomial
    in its name, description or categories.
    """
    wanted = " ".join(scientific_name.split()).casefold()
    if not wanted:
        return False
    fields = (
        name,
        _plain(meta.get("ImageDescription", {}).get("value", "")),
        meta.get("Categories", {}).get("value", "") or "",
    )
    return any(
        wanted in " ".join(re.sub(r"[_\-]+", " ", f).split()).casefold()
        for f in fields
    )


def _is_jpeg_name(name: str) -> bool:
    return name.lower().endswith((".jpg", ".jpeg"))


def _try_wikimedia(
    scientific_name: str,
    session: requests.Session,
    size: int = DEFAULT_SIZE,
) -> ImageResult | None:
    """Strategy 4: a photograph from the species' Wikipedia article.

    Two MediaWiki API calls, both documented and unauthenticated. The
    first resolves the scientific name (redirects followed, as the
    summary endpoint the content scraper uses does) and asks for the
    article's lead file (``pageimages``, which only offers freely
    licensed files) and every other file it uses (``images``). The
    second reads author, licence, description and categories for the
    JPEGs among them, in one request.

    Candidates are tried lead image first. A file is declined when it is
    not a JPEG (range maps and status icons are SVG or PNG), when it has
    no licence to show, or when its name, description or categories say
    it is a specimen, an egg, a drawing, a map or a stamp. The first one
    left is published, without the tracking parameters the API appends.

    This path does not go through Cornell at all, so it keeps answering
    when eBird and Macaulay put their pages behind a bot gateway, which
    is what they did on 2026-08-30 and 2026-09-22.
    """
    if not scientific_name:
        return None
    for lang in WIKIMEDIA_LANGUAGES:
        api = WIKIPEDIA_API.format(lang=lang)
        try:
            resp = session.get(api, params={
                "action": "query", "format": "json", "formatversion": "2",
                "redirects": "1", "titles": scientific_name,
                "prop": "pageimages|images", "piprop": "name",
                "imlimit": "max",
            }, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            pages = resp.json().get("query", {}).get("pages", [])
        except (requests.RequestException, ValueError, AttributeError) as e:
            logger.warning(
                "Wikipedia %s image lookup failed for %s: %s",
                lang, scientific_name, e,
            )
            continue

        names: list[str] = []
        leads: set[str] = set()
        for page in pages:
            lead = page.get("pageimage")
            if lead:
                names.append(lead.replace("_", " "))
                leads.add(lead.replace("_", " "))
            for image in page.get("images") or []:
                title = image.get("title") or ""
                names.append(title.split(":", 1)[-1] if ":" in title else title)
        candidates = list(dict.fromkeys(n for n in names if _is_jpeg_name(n)))
        candidates = candidates[:WIKIMEDIA_MAX_CANDIDATES]
        if not candidates:
            continue

        try:
            resp = session.get(api, params={
                "action": "query", "format": "json", "formatversion": "2",
                "titles": "|".join(f"File:{n}" for n in candidates),
                "prop": "imageinfo", "iiprop": "url|mime|extmetadata",
                "iiextmetadatafilter": (
                    "Artist|Credit|LicenseShortName|ImageDescription|Categories"
                ),
                "iiurlwidth": str(size),
            }, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            pages = resp.json().get("query", {}).get("pages", [])
        except (requests.RequestException, ValueError, AttributeError) as e:
            logger.warning(
                "Commons file info failed for %s: %s", scientific_name, e
            )
            continue
        infos = {
            (p.get("title") or "").split(":", 1)[-1].replace("_", " "):
                p["imageinfo"][0]
            for p in pages
            if p.get("imageinfo")
        }

        for name in candidates:
            info = infos.get(name)
            if not info:
                continue
            meta = info.get("extmetadata") or {}
            url = info.get("thumburl") or info.get("url")
            licence = _plain(meta.get("LicenseShortName", {}).get("value", ""))
            reason = None
            if info.get("mime", "image/jpeg") != "image/jpeg":
                reason = f"not a JPEG ({info.get('mime')})"
            elif not url or not licence:
                # No licence recorded, no licence to show: not publishable.
                reason = "no licence"
            elif name not in leads and not _names_species(
                name, meta, scientific_name
            ):
                reason = "does not name this species"
            else:
                why = _unsuitable(name, meta)
                if why:
                    reason = f"not a live bird ({why!r})"
            if reason:
                logger.info("Commons file %s declined: %s", name, reason)
                continue
            author = _commons_author(meta)
            credit = " / ".join(x for x in (author, "Wikimedia Commons") if x)
            return ImageResult(
                url=_without_query(url),
                asset_id=None,
                photographer=author,
                attribution=f"{credit} ({licence})",
                search_url="",
            )
    return None


def _fallback(species_code: str) -> ImageResult:
    return ImageResult(
        url=None,
        asset_id=None,
        photographer="",
        attribution="Macaulay Library / Cornell Lab of Ornithology",
        search_url=ml_search_url(species_code),
    )


def fetch_image(
    species_code: str,
    session: requests.Session | None = None,
    locale: str = "en",
    *,
    ordinal: int = 0,
    seen_asset_ids: frozenset[str] = frozenset(),
    scientific_name: str = "",
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
    3. **iNaturalist** — the default photo of the taxon named
       ``scientific_name``, when it carries a Creative Commons licence.
       Reached when Cornell answers neither of the above, which since its
       bot gateways went up is most days on a CI runner. Ahead of Commons
       because iNaturalist photographs are of observations, nearly
       always of a live bird, where Commons files museum skins too.
    4. **Wikimedia Commons** — a photograph from the Wikipedia article
       for ``scientific_name``, freely licensed, credited with author and
       licence, specimens, drawings and maps declined.
    5. **No image + link to ML Search** — last-resort fallback. The
       reader can click through to find a photo manually.

    Earlier revisions had the order reversed (rating-first), which
    surfaced the highest-rated Macaulay photo regardless of eBird's
    curation. That picked technically beautiful but unfamiliar shots
    instead of the photo readers expected to see.

    ``locale`` is forwarded to the eBird species-page strategy. The
    Macaulay API strategy doesn't take a locale (asset metadata is
    language-agnostic).

    ``ordinal`` is how many times this species has been published before.
    On a republication the curated eBird hero is skipped: it is a single
    fixed photograph, and showing it twice is exactly what the ordinal
    exists to avoid. The rated Macaulay list is walked instead, past every
    asset in ``seen_asset_ids``. If the library has nothing new the normal
    order runs anyway: repeating a photograph beats publishing without one.
    """
    sess = session or new_session()
    # A debut normally has nothing to skip, so the ordinal alone used to
    # decide this. The backfill breaks that: it re-fetches the photograph
    # of an entry published long ago, and the species may have come round
    # again since, with a photograph the reader has already seen. Whenever
    # there is something to skip, walk the rated list.
    if ordinal or seen_asset_ids:
        result = _try_macaulay_api(
            species_code, sess,
            count=ordinal + MACAULAY_LOOKAHEAD,
            skip=seen_asset_ids,
        )
        if result is not None:
            return result
    result = _try_ebird_og_image(species_code, sess, locale=locale)
    if result is not None:
        return result
    result = _try_macaulay_api(species_code, sess)
    if result is not None:
        return result
    for strategy in (_try_inaturalist, _try_wikimedia):
        result = strategy(scientific_name, sess)
        if result is not None:
            result.search_url = ml_search_url(species_code)
            return result
    return _fallback(species_code)


def image_cache_path(
    species_code: str, cache_dir: str, ordinal: int = 0
) -> Path:
    """Cache file for one publication's photograph.

    A debut keeps the historical name so the caches already on disk stay
    valid; later publications are numbered, so a repeat's photograph never
    overwrites the original's.
    """
    suffix = f"-{ordinal + 1}" if ordinal else ""
    return Path(cache_dir) / f"{species_code}.image{suffix}.json"


def load_cached_image(
    species_code: str, cache_dir: str = "cache", ordinal: int = 0
) -> ImageResult | None:
    from scripts import load_json_cache
    data = load_json_cache(
        image_cache_path(species_code, cache_dir, ordinal),
        f"image cache for {species_code}",
    )
    if data is None:
        return None
    if not data.get("asset_id") and not data.get("url"):
        return None
    return ImageResult.from_dict(data)


def save_cached_image(
    species_code: str,
    result: ImageResult,
    cache_dir: str = "cache",
    ordinal: int = 0,
) -> None:
    """Persist a successful image lookup. Failures are not cached so they retry."""
    if not result.asset_id and not result.url:
        return
    path = image_cache_path(species_code, cache_dir, ordinal)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
