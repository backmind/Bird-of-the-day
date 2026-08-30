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
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from scripts import atomic_io, esc_html as _esc, name_linker, urls

if TYPE_CHECKING:
    from scripts.i18n import Catalog

logger = logging.getLogger(__name__)

CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
ATOM_NS = "http://www.w3.org/2005/Atom"
MEDIA_NS = "http://search.yahoo.com/mrss/"

ET.register_namespace("content", CONTENT_NS)
ET.register_namespace("atom", ATOM_NS)
ET.register_namespace("media", MEDIA_NS)

# Version of the item body format. Written into <generator> and read
# back when deciding whether a stored feed's item bodies can be reused
# as-is; bump it whenever build_entry_html changes shape, so the next
# run re-renders the history instead of mixing two formats forever.
FEED_FORMAT = 3
GENERATOR = f"Bird of the Day (feed format {FEED_FORMAT})"
_GENERATOR_RE = re.compile(r"feed format (\d+)")


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
    # Absolute URL of the item on our own site. Empty when no feed_link
    # is configured, in which case the item falls back to eBird.
    link: str = ""


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
    previous_date: str = "",
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
    if previous_date:
        chip = catalog.t(
            "republished.chip_template",
            date=previous_date.replace("-", " · "),
        )
        # Without a feed_link there is no absolute URL to point at, so the
        # fact is stated without a link rather than dropped.
        head_bits.append(
            f'<a href="{_esc(species_page_url)}">{_esc(chip)}</a>'
            if species_page_url
            else _esc(chip)
        )
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
    elif ml_search_url:
        parts.append(f'<p><a href="{_esc(ml_search_url)}">Macaulay Library</a></p>')
    else:
        parts.append("<p>Macaulay Library</p>")

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
    # Prose and bullets are asked for separately and can arrive
    # separately, so they are rendered on their own conditions: nesting
    # the bullets inside the prose dropped both them and their heading
    # whenever an enrichment came back with one and not the other, and
    # published the scraped paragraph in their place. site_builder
    # renders the same two fields with the same three branches.
    if enriched_prose:
        for para in (p.strip() for p in enriched_prose.split("\n\n") if p.strip()):
            parts.append(
                f"<p>{name_linker.process_description(para, _eni, _c2l, _pa, catalog.language)}</p>"
            )
    if enriched_identification:
        # The heading the front has always had and the feed never did:
        # without it the bullets hang off the prose with no indication
        # of what they are.
        parts.append(f'<h3>{_esc(catalog.t("identification.label"))}</h3>')
        bullets = "".join(f"<li>{_esc(b)}</li>" for b in enriched_identification)
        parts.append(f"<ul>{bullets}</ul>")
    if not enriched_prose and not enriched_identification:
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
            wiki_label = f"Wikipedia ({_esc(wikipedia_language)})"
        link_parts.append(f'<a href="{_esc(wikipedia_url)}">{wiki_label}</a>')
    link_parts.append(
        f'<a href="https://birdsoftheworld.org/bow/species/{code_e}'
        '/cur/introduction">Birds of the World</a>'
    )
    if ml_search_url:
        link_parts.append(f'<a href="{_esc(ml_search_url)}">Macaulay Library</a>')
    else:
        link_parts.append("Macaulay Library")
    parts.append(f'<p><small>{" · ".join(link_parts)}</small></p>')

    return "\n".join(parts)


def build_feed(
    entries: list[FeedEntry],
    config: dict,
    catalog: "Catalog",
    *,
    self_path: str = urls.FEED_FILE,
    title: str = "",
) -> str:
    """Build an RSS 2.0 XML feed string. All chrome from the catalog.

    ``entries`` must be newest first: the channel ``<pubDate>`` is read
    off ``entries[0]``, so a list in the other order dates the whole feed
    to its oldest item.

    ``self_path`` is the file this XML will be written to, so the Atom
    self-link points at itself rather than always at feed.xml.
    ``title`` overrides the channel title, which the full-history feed
    uses to distinguish itself in a reader subscribed to both.
    """
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    # Channel metadata
    ET.SubElement(channel, "title").text = title or catalog.t("feed.title")
    feed_link = config.get("feed_link", "")
    ET.SubElement(channel, "link").text = feed_link
    ET.SubElement(channel, "description").text = catalog.t("feed.description")
    ET.SubElement(channel, "language").text = catalog.html_lang
    # The newest item's date, not the run's clock: a lastBuildDate would
    # change the file on every run and cost a commit for nothing.
    if entries:
        ET.SubElement(channel, "pubDate").text = entries[0].pub_date
    ET.SubElement(channel, "generator").text = GENERATOR

    # Atom self-link
    if feed_link:
        atom_link = ET.SubElement(channel, f"{{{ATOM_NS}}}link")
        atom_link.set("href", urls.absolute(feed_link, self_path))
        atom_link.set("rel", "self")
        atom_link.set("type", "application/rss+xml")

    # Copyright. The name comes from config, never from the template: a
    # clone with no site_author configured gets a copyright line naming
    # no one, not the original instance's owner. ``name_part`` folds in
    # its own trailing ", " so the template reduces to a clean sentence
    # with nothing missing when site_author is empty (no stray comma).
    # The value goes straight into an ElementTree ``.text``, which is
    # XML-escaped on serialization, so it is passed through unescaped
    # here on purpose.
    year = datetime.now(timezone.utc).year
    site_author = config.get("site_author", "")
    name_part = f"{site_author}, " if site_author else ""
    author_line = catalog.t(
        "feed.copyright_author_template", year=year, name=name_part
    )
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
            entry.link or f"https://ebird.org/species/{entry.species_code}"
        )
        guid = ET.SubElement(item, "guid")
        guid.text = entry.guid
        guid.set("isPermaLink", "false")
        ET.SubElement(item, "pubDate").text = entry.pub_date

        # Media RSS for the hero photo. Not <enclosure>, which requires
        # a byte length we do not know and would have to either fake or
        # fetch. Macaulay URLs carry no extension; the CDN serves JPEG.
        if entry.image_url:
            media = ET.SubElement(item, f"{{{MEDIA_NS}}}content")
            media.set("url", entry.image_url)
            media.set("medium", "image")
            media.set("type", "image/jpeg")
            if entry.image_attribution:
                credit = ET.SubElement(media, f"{{{MEDIA_NS}}}credit")
                credit.set("role", "photographer")
                credit.text = entry.image_attribution
            thumb = ET.SubElement(item, f"{{{MEDIA_NS}}}thumbnail")
            thumb.set("url", entry.image_url)

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


def feed_cap(config: dict) -> int:
    """How many items ``feed.xml`` carries. Zero means no cap.

    ``feed-full.xml`` exists if and only if this is above zero: without a
    cap ``feed.xml`` already holds the whole history and a second file
    would duplicate it byte for byte. Three callers have to agree on that
    (this module writes the files, the generator tells the site builder
    whether the pages may link the second one, and seed_mock reproduces
    both for a demo), and they agree by reading it here. The moment they
    stop agreeing, the pages advertise a file nothing writes.
    """
    return int(config.get("max_feed_entries", 0) or 0)


def write_feeds(
    entries: list[FeedEntry],
    config: dict,
    catalog: "Catalog",
    state_dir: Path,
    *,
    rebuild_all: bool = False,
    thaw: set[str] | None = None,
) -> dict:
    """Write the capped feed and, when a cap applies, the full history.

    ``entries`` are newest first with every body freshly rendered.

    The full feed freezes: items past the cap keep the body they were
    published with, read back from the previous file by guid. It makes
    that file effectively append-only, so its daily diff is one item
    instead of the whole history. What is given up is retroactive
    cross-linking in old items, and that costs little: a species that
    was not published yet already links to eBird, which is a permanent
    destination rather than a dead one.

    Frozen bodies are only trusted when the stored feed declares the
    current format version, so a change to the item's shape re-renders
    the history instead of leaving two formats mixed in one file.

    ``thaw`` names the guids that must be re-rendered even when they fall
    outside the window. Freezing is right for cross-linking and wrong for
    repair: an entry published with a failed enrichment and healed months
    later would otherwise keep its degraded body for as long as the file
    exists, with the fix visible on its species page and nowhere else.
    ``thawed`` in the result counts how many of those guids were old
    enough to have been frozen, so a run that healed nothing old reports
    zero rather than the size of the set it was handed.

    ``full_stale`` in the result flags the one state this function cannot
    fix on its own: an instance that had a cap and then removed it leaves
    a ``feed-full.xml`` behind that nothing rewrites and nothing links.
    Deleting a published file is out of scope for this module, so the
    condition is reported rather than acted on.
    """
    feed_path = state_dir / urls.FEED_FILE
    full_path = state_dir / urls.FEED_FULL_FILE
    cap = feed_cap(config)

    capped = entries[:cap] if cap > 0 else entries
    result = {
        "items": len(capped),
        "feed_written": write_feed(
            build_feed(capped, config, catalog, self_path=urls.FEED_FILE),
            str(feed_path),
        ),
        "full_items": 0,
        "full_written": False,
        "frozen": 0,
        "thawed": 0,
        "full_stale": cap <= 0 and full_path.exists(),
    }
    if cap <= 0:
        # Without a cap the full feed would be a byte-for-byte duplicate.
        return result

    frozen: dict[str, str] = {}
    if not rebuild_all and load_feed_format(str(full_path)) == FEED_FORMAT:
        frozen = {
            e.guid: e.description_html
            for e in load_existing_feed(str(full_path))
            if e.description_html
        }

    thawed = thaw or set()
    full_entries: list[FeedEntry] = []
    for index, entry in enumerate(entries):
        if index >= cap and entry.guid in frozen:
            if entry.guid in thawed:
                result["thawed"] += 1
            else:
                entry = replace(entry, description_html=frozen[entry.guid])
                result["frozen"] += 1
        full_entries.append(entry)

    result["full_items"] = len(full_entries)
    result["full_written"] = write_feed(
        build_feed(
            full_entries,
            config,
            catalog,
            self_path=urls.FEED_FULL_FILE,
            title=catalog.t(
                "feed.full_title_template", title=catalog.t("feed.title")
            ),
        ),
        str(full_path),
    )
    return result


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

            # Extract the species code from the link. It used to be an
            # eBird URL ending in the code; it is now our own species
            # page, so the .html suffix has to come off.
            species_code = ""
            if link_elem is not None and link_elem.text:
                tail = link_elem.text.rstrip("/").split("/")[-1]
                species_code = tail[:-5] if tail.endswith(".html") else tail

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
                    link=link_elem.text.strip() if link_elem is not None and link_elem.text else "",
                )
            )

        return entries
    except (OSError, ET.ParseError, KeyError):
        logger.warning("Failed to parse existing feed at %s", feed_path, exc_info=True)
        return []


def load_feed_format(feed_path: str) -> int | None:
    """Read the item body format version a stored feed declares.

    Returns None when the file is missing or predates the marker, which
    callers read as "do not reuse anything from it".
    """
    path = Path(feed_path)
    if not path.exists():
        return None
    try:
        match = _GENERATOR_RE.search(path.read_text(encoding="utf-8"))
    except OSError:
        logger.warning("Could not read %s", feed_path, exc_info=True)
        return None
    return int(match.group(1)) if match else None


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
