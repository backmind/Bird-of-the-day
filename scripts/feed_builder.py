"""RSS 2.0 feed builder with content:encoded support.

Every user-facing string is sourced from the i18n catalog. The builder
takes a ``Catalog`` instance and renders both the channel chrome and the
per-item ``content:encoded`` HTML in the configured language.
"""

from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from scripts import atomic_io, esc_html as _esc, name_linker

if TYPE_CHECKING:
    from scripts.i18n import Catalog

logger = logging.getLogger(__name__)

CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
ATOM_NS = "http://www.w3.org/2005/Atom"

ET.register_namespace("content", CONTENT_NS)
ET.register_namespace("atom", ATOM_NS)


@dataclass
class FeedEntry:
    species_code: str
    common_name: str
    scientific_name: str
    description_html: str
    image_url: str | None
    image_attribution: str
    ml_search_url: str
    pub_date: str
    guid: str


def build_entry_html(
    species_code: str,
    common_name: str,
    scientific_name: str,
    image_url: str | None,
    image_attribution: str,
    ml_search_url: str,
    description: str,
    description_source: str,
    bow_intro: str,
    taxonomy: dict,
    catalog: "Catalog",
    wikipedia_url: str = "",
    wikipedia_language: str = "",
    fallback_language: str = "",
    distribution_map_url: str = "",
    gbif_taxon_key: int | None = None,
    composed_map_url: str = "",
    iucn_code: str = "",
    iucn_birdlife_url: str = "",
    enriched_prose: str = "",
    enriched_identification: list[str] | None = None,
    english_name_index: dict | None = None,
    code_to_localized: dict | None = None,
    published_anchors: dict | None = None,
    number: int = 0,
    date: str = "",
    species_page_url: str = "",
) -> str:
    """Build the HTML body of one RSS item.

    Built out of semantic elements with almost no inline styling. Feed
    readers re-style what they receive and many strip style attributes
    outright, so hierarchy has to live in the elements themselves: a
    heading is an ``<h3>``, a list is a ``<ul>``, the map is a
    ``<figure>``. Colours are never declared, so the item inherits the
    reader's own light or dark theme instead of fighting it.

    The order of the parts is fixed by the project's design: head line,
    photo, credit, name, taxonomy and conservation status, prose,
    identification, map, sources. All user-supplied data is escaped and
    all chrome comes from the catalog.
    """
    parts: list[str] = []
    code_e = _esc(species_code)
    ebird_url = f"https://ebird.org/species/{code_e}?siteLanguage={catalog.language}"
    # The photo takes the reader to the same place the item's <link>
    # does: our own species page, which never rots. Without a configured
    # feed_link there is no absolute URL to point at, so it degrades to
    # eBird rather than emitting a path no reader could resolve.
    photo_target = _esc(species_page_url) if species_page_url else ebird_url

    # Head line: the same publication number and dotted date the web
    # plate shows, so an item and its page are recognisably the same
    # thing.
    head_bits: list[str] = []
    if number:
        head_bits.append(f"№ {number}")
    if date:
        head_bits.append(_esc(date.replace("-", " · ")))
    if head_bits:
        parts.append(f"<p><small>{' · '.join(head_bits)}</small></p>")

    # Photo, then its credit on its own line.
    if image_url:
        parts.append(
            f'<p><a href="{photo_target}">'
            f'<img src="{_esc(image_url)}" alt="{_esc(common_name)}" '
            f'style="max-width:100%;height:auto" /></a></p>'
        )
        parts.append(
            f"<p><small><em>© {_esc(image_attribution)}</em></small></p>"
        )
    else:
        parts.append(f'<p><a href="{_esc(ml_search_url)}">Macaulay Library</a></p>')

    # Name + scientific name.
    parts.append(
        f"<h2>{_esc(common_name)} — <em>{_esc(scientific_name)}</em></h2>"
    )

    # Taxonomy and conservation status on one line. The two separator
    # levels are deliberate: "·" joins things of the same kind, "//"
    # marks the change of register from taxonomy to conservation. In a
    # reader that strips styling they are the only hierarchy left. The
    # link sits on the IUCN code, mirroring the badge on the web.
    family_sci = taxonomy.get("familySciName", "")
    order = taxonomy.get("order", "")
    tax_parts = [f"<em>{_esc(p)}</em>" for p in (family_sci, order) if p]
    line = " · ".join(tax_parts)
    if iucn_code:
        code_html = _esc(iucn_code)
        if iucn_birdlife_url:
            code_html = f'<a href="{_esc(iucn_birdlife_url)}">{code_html}</a>'
        iucn_html = f"{code_html} · {_esc(catalog.t(f'iucn.{iucn_code}'))}"
        line = f"{line} // {iucn_html}" if line else iucn_html
    if line:
        parts.append(f"<p><small>{line}</small></p>")

    # Description: enriched (LLM) or programmatic (scraped).
    _eni = english_name_index or {}
    _c2l = code_to_localized or {}
    _pa = published_anchors or {}
    if enriched_prose:
        for para in (p.strip() for p in enriched_prose.split("\n\n") if p.strip()):
            parts.append(
                f"<p>{name_linker.process_description(para, _eni, _c2l, _pa, catalog.language)}</p>"
            )
        if enriched_identification:
            # The heading the front has always had and the feed never
            # did: without it the bullets hang off the prose with no
            # indication of what they are.
            parts.append(f'<h3>{_esc(catalog.t("identification.label"))}</h3>')
            bullets = "".join(f"<li>{_esc(b)}</li>" for b in enriched_identification)
            parts.append(f"<ul>{bullets}</ul>")
    else:
        if description:
            parts.append(
                f"<p>{name_linker.process_description(description, _eni, _c2l, _pa, catalog.language)}</p>"
            )
            if description_source == "ebird-foreign":
                lang_name = catalog.t(f"language_name.{fallback_language or 'en'}")
                disclaimer = catalog.t(
                    "description.foreign_disclaimer", source_language=lang_name
                )
                parts.append(f"<p><small><em>{_esc(disclaimer)}</em></small></p>")
        if bow_intro:
            parts.append(
                f"<p>{name_linker.process_description(bow_intro, _eni, _c2l, _pa, catalog.language)}</p>"
            )

    # GBIF distribution map. The pre-composed PNG (basemap and density
    # baked into one image) is what every reader can render; when
    # composition has not happened yet the density layer goes out on its
    # own. The old two-layer version stacked images with absolute
    # positioning, which no feed reader honours and which collapses into
    # two unrelated pictures wherever styles are stripped.
    map_url = composed_map_url or distribution_map_url
    if map_url:
        map_alt = catalog.t("map.alt_template", scientific_name=scientific_name)
        map_target = (
            f"https://www.gbif.org/species/{gbif_taxon_key}"
            if gbif_taxon_key
            else map_url
        )
        parts.append(
            '<figure style="margin:1.5rem 0;text-align:center">'
            f'<a href="{_esc(map_target)}">'
            f'<img src="{_esc(map_url)}" alt="{_esc(map_alt)}" '
            'style="max-width:100%;height:auto" />'
            '</a>'
            f'<figcaption><small>{_esc(catalog.t("map.label"))}</small></figcaption>'
            '</figure>'
        )

    # Link list, mirroring the front's plate-foot: eBird, Wikipedia when
    # we have one, Birds of the World, Macaulay Library.
    link_parts = [f'<a href="{ebird_url}">eBird</a>']
    if wikipedia_url:
        wiki_label = "Wikipedia"
        if wikipedia_language and wikipedia_language != catalog.language:
            wiki_label = f"Wikipedia ({wikipedia_language})"
        link_parts.append(f'<a href="{_esc(wikipedia_url)}">{wiki_label}</a>')
    link_parts.append(
        f'<a href="https://birdsoftheworld.org/bow/species/{code_e}'
        '/cur/introduction">Birds of the World</a>'
    )
    link_parts.append(f'<a href="{_esc(ml_search_url)}">Macaulay Library</a>')
    parts.append(f'<p><small>{" · ".join(link_parts)}</small></p>')

    return "\n".join(parts)


def build_feed(
    entries: list[FeedEntry], config: dict, catalog: "Catalog"
) -> str:
    """Build an RSS 2.0 XML feed string. All chrome from the catalog."""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    # Channel metadata
    ET.SubElement(channel, "title").text = catalog.t("feed.title")
    feed_link = config.get("feed_link", "")
    ET.SubElement(channel, "link").text = feed_link
    ET.SubElement(channel, "description").text = catalog.t("feed.description")
    ET.SubElement(channel, "language").text = catalog.html_lang

    # Atom self-link
    if feed_link:
        atom_link = ET.SubElement(channel, f"{{{ATOM_NS}}}link")
        atom_link.set("href", f"{feed_link.rstrip('/')}/feed.xml")
        atom_link.set("rel", "self")
        atom_link.set("type", "application/rss+xml")

    # Copyright. Author is hardcoded in the per-language template.
    year = datetime.now(timezone.utc).year
    author_line = catalog.t("feed.copyright_author_template", year=year)
    ET.SubElement(channel, "copyright").text = (
        catalog.t("feed.copyright_data_prefix") + author_line
    )

    # Items
    for entry in entries:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = (
            f"{entry.common_name} ({entry.scientific_name})"
        )
        ET.SubElement(item, "link").text = (
            f"https://ebird.org/species/{entry.species_code}"
        )
        guid = ET.SubElement(item, "guid")
        guid.text = entry.guid
        guid.set("isPermaLink", "false")
        ET.SubElement(item, "pubDate").text = entry.pub_date

        # content:encoded — will be wrapped in CDATA during post-processing
        content_elem = ET.SubElement(item, f"{{{CONTENT_NS}}}encoded")
        content_elem.text = entry.description_html

    # Serialize to string
    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    xml_bytes = ET.tostring(rss, encoding="unicode", xml_declaration=False)
    xml_string = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes

    # Post-process: wrap content:encoded in CDATA
    xml_string = _wrap_cdata(xml_string)

    return xml_string


def _wrap_cdata(xml_string: str) -> str:
    """Wrap content:encoded text in CDATA sections."""
    def replacer(match: re.Match) -> str:
        tag_open = match.group(1)
        content = match.group(2)
        tag_close = match.group(3)
        content = html.unescape(content)
        return f"{tag_open}<![CDATA[{content}]]>{tag_close}"

    return re.sub(
        r"(<content:encoded>)(.*?)(</content:encoded>)",
        replacer,
        xml_string,
        flags=re.DOTALL,
    )


def load_existing_feed(feed_path: str) -> list[FeedEntry]:
    """Parse an existing feed.xml and return its entries.

    The CDATA-wrapped ``<content:encoded>`` bodies are extracted via a
    regex pre-pass keyed by guid, then merged back after ElementTree
    parses the rest of the channel chrome. The naïve approach (strip
    CDATA, parse with ET, read ``content_elem.text``) silently loses
    every prior entry's rich HTML: ET treats the inner ``<h2>``/``<p>``/…
    as element children rather than text, leaving ``.text`` as ``None``.
    We round-trip the feed every day, so that bug would clear the body
    of every entry except today's after the second publication.
    """
    path = Path(feed_path)
    if not path.exists():
        return []

    try:
        raw = path.read_text(encoding="utf-8")

        # Pre-pass: pull each item's CDATA body out, indexed by guid. The
        # regex is intentionally simple because feed.xml is always our own
        # output — never a third-party feed — so we control its shape.
        item_re = re.compile(r"<item\b[^>]*>(.*?)</item>", re.DOTALL)
        guid_re = re.compile(r"<guid\b[^>]*>(.*?)</guid>", re.DOTALL)
        content_re = re.compile(
            r"<content:encoded\b[^>]*>\s*<!\[CDATA\[(.*?)\]\]>\s*</content:encoded>",
            re.DOTALL,
        )
        content_by_guid: dict[str, str] = {}
        for item_match in item_re.finditer(raw):
            inner = item_match.group(1)
            g = guid_re.search(inner)
            c = content_re.search(inner)
            if g and c:
                content_by_guid[g.group(1).strip()] = c.group(1)

        # Empty out each CDATA block entirely before handing the
        # remaining XML to ElementTree. We've already captured the
        # content in ``content_by_guid``, so the parser doesn't need to
        # see it again — and crucially, *can't*: ET only knows the five
        # XML entities, so any HTML entity inside the CDATA (``&middot;``,
        # ``&copy;``, ``&nbsp;``, …) would trip ``undefined entity`` if
        # we naively stripped just the ``<![CDATA[`` markers.
        stripped = re.sub(
            r"<content:encoded\b[^>]*>\s*<!\[CDATA\[.*?\]\]>\s*</content:encoded>",
            "<content:encoded></content:encoded>",
            raw,
            flags=re.DOTALL,
        )
        root = ET.fromstring(stripped)
        entries: list[FeedEntry] = []

        for item in root.findall(".//item"):
            title_elem = item.find("title")
            link_elem = item.find("link")
            guid_elem = item.find("guid")
            pub_date_elem = item.find("pubDate")

            if guid_elem is None or guid_elem.text is None:
                continue
            guid_text = guid_elem.text.strip()

            # Extract species code from link
            species_code = ""
            if link_elem is not None and link_elem.text:
                parts = link_elem.text.rstrip("/").split("/")
                species_code = parts[-1] if parts else ""

            # Parse common_name and scientific_name from title
            common_name = ""
            scientific_name = ""
            if title_elem is not None and title_elem.text:
                title_match = re.match(r"^(.*?)\s*\(([^)]+)\)$", title_elem.text)
                if title_match:
                    common_name = title_match.group(1).strip()
                    scientific_name = title_match.group(2).strip()
                else:
                    common_name = title_elem.text.strip()

            entries.append(
                FeedEntry(
                    species_code=species_code,
                    common_name=common_name,
                    scientific_name=scientific_name,
                    description_html=content_by_guid.get(guid_text, ""),
                    image_url=None,
                    image_attribution="",
                    ml_search_url="",
                    pub_date=pub_date_elem.text if pub_date_elem is not None and pub_date_elem.text else "",
                    guid=guid_text,
                )
            )

        return entries
    except (OSError, ET.ParseError, KeyError):
        logger.warning("Failed to parse existing feed at %s", feed_path, exc_info=True)
        return []


def write_feed(xml_string: str, feed_path: str = "feed.xml") -> bool:
    """Write the feed atomically, only when the bytes actually change.

    Returns whether anything was written. The feed is a published file
    in a git repository: rewriting identical bytes costs a commit and a
    cache invalidation for every subscriber for nothing.
    """
    written = atomic_io.write_text_if_changed(Path(feed_path), xml_string)
    if written:
        logger.info("Feed written to %s", feed_path)
    else:
        logger.info("Feed unchanged at %s", feed_path)
    return written
