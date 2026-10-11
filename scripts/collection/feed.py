from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree  # parsed only via _hardened_parse (DOCTYPE-guarded)  # nosec B405
from dataclasses import dataclass

_NS_CONTENT = "http://purl.org/rss/1.0/modules/content/"
_NS_DC = "http://purl.org/dc/elements/1.1/"
_NS_ATOM = "http://www.w3.org/2005/Atom"
_NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


class FeedParseError(Exception):
    """Raised when a feed's XML cannot be parsed (malformed / not a feed)."""


@dataclass(frozen=True)
class FeedItem:
    """One parsed feed entry — RSS `<item>` or Atom `<entry>`.

    `body` is the RAW (still-HTML) full body, preferring `content:encoded` /
    Atom `<content>` over the short `<description>` / `<summary>`. `date_published`
    is the raw feed string (RFC822 or ISO8601); the caller normalises it via
    `to_iso_date`. Missing fields are the empty string, never None.
    """

    url: str
    title: str
    author: str
    date_published: str
    body: str
    guid: str
    categories: list[str]


# --------------------------------------------------------------------------- #


def _text(element: ElementTree.Element | None) -> str:
    """The stripped text of an element, or "" when the element/text is absent."""
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def _find_text(parent: ElementTree.Element, *paths: str) -> str:
    """First non-empty stripped text among several child paths (tolerant)."""
    for path in paths:
        value = _text(parent.find(path))
        if value:
            return value
    return ""


def _parse_rss_item(item: ElementTree.Element) -> FeedItem:
    """Build a FeedItem from an RSS 2.0 `<item>` element."""
    # Author: prefer dc:creator, fall back to the plain <author> element.
    author = _find_text(item, f"{{{_NS_DC}}}creator", "author")
    # Body: prefer the full content:encoded over the (often summary-only) description.
    body = _find_text(item, f"{{{_NS_CONTENT}}}encoded", "description")
    categories = [c for c in (_text(el) for el in item.findall("category")) if c]
    return FeedItem(
        url=_find_text(item, "link"),
        title=_find_text(item, "title"),
        author=author,
        date_published=_find_text(item, "pubDate"),
        body=body,
        guid=_find_text(item, "guid"),
        categories=categories,
    )


def _atom_link(entry: ElementTree.Element) -> str:
    """The article URL from an Atom `<entry>`: prefer rel="alternate", else first link."""
    links = entry.findall(f"{{{_NS_ATOM}}}link")
    for link in links:
        if link.get("rel", "alternate") == "alternate" and link.get("href"):
            return link.get("href", "").strip()
    # No explicit alternate — take the first article-pointing link, but NEVER a
    # rel="self"/"enclosure"/"related" link (those point at the feed itself or an
    # attachment; adopting one as the article url collides every entry on one key).
    for link in links:
        href = link.get("href")
        if href and link.get("rel") not in ("self", "enclosure", "related"):
            return href.strip()
    return ""


def _atom_content_body(entry: ElementTree.Element) -> str:
    """Full body for an Atom entry, preferring <content> over <summary>.

    For `type="xhtml"` content the real body lives in child elements, not the
    element's `.text` — reading `.text` yields "" and silently falls back to the short
    `<summary>`. Serialize the children (as markup for the downstream strip_html) when
    present; otherwise use the escaped-HTML/plain `.text` (`type="html"`/`"text"`).
    """
    content = entry.find(f"{{{_NS_ATOM}}}content")
    if content is not None:
        children = list(content)
        if children:
            serialized = "".join(
                ElementTree.tostring(child, encoding="unicode") for child in children
            ).strip()
            if serialized:
                return serialized
        direct = (content.text or "").strip()
        if direct:
            return direct
    return _text(entry.find(f"{{{_NS_ATOM}}}summary"))


def _parse_atom_entry(entry: ElementTree.Element) -> FeedItem:
    """Build a FeedItem from an Atom `<entry>` element."""
    author = _text(entry.find(f"{{{_NS_ATOM}}}author/{{{_NS_ATOM}}}name"))
    # Body: prefer the full <content> over the <summary> (handles type="xhtml").
    body = _atom_content_body(entry)
    date = _find_text(entry, f"{{{_NS_ATOM}}}published", f"{{{_NS_ATOM}}}updated")
    categories = [
        term
        for el in entry.findall(f"{{{_NS_ATOM}}}category")
        if (term := (el.get("term") or "").strip())
    ]
    return FeedItem(
        url=_atom_link(entry),
        title=_text(entry.find(f"{{{_NS_ATOM}}}title")),
        author=author,
        date_published=date,
        body=body,
        guid=_text(entry.find(f"{{{_NS_ATOM}}}id")),
        categories=categories,
    )


# Matches an XML `<!DOCTYPE …>` declaration anywhere in the prolog. A DOCTYPE is
# the entry point for both the billion-laughs entity bomb and external-entity (XXE)
# references, so we refuse any feed that declares one.
_DOCTYPE_RE = re.compile(r"<!DOCTYPE", re.IGNORECASE)


def _hardened_parse(xml_text: str) -> ElementTree.Element:
    """Parse untrusted feed XML with the DTD / external-entity surface removed.

    Feeds are UNTRUSTED remote input, so the stdlib parser is hardened against the
    two classic XML attacks (CWE-20) WITHOUT a third-party dependency (the module
    is stdlib-only by design — `defusedxml` is not a project dep):

      - billion-laughs / entity expansion AND XXE / external entities both require a
        `<!DOCTYPE …>` to declare the offending entities. We REJECT any feed whose
        document declares a DOCTYPE up front, so neither attack can be staged.
      - With no DTD, the stdlib `ElementTree` parser (which already never resolves
        external entities and raises on an undefined entity) is safe for the rest.

    A real RSS/Atom feed never needs a DOCTYPE, so this is a precise guard, not a
    blunt one. This is why the scoped `# nosec` on the parse call is accurate.

    Raises `FeedParseError` on a DOCTYPE, malformed XML, or a non-feed document.
    """
    if _DOCTYPE_RE.search(xml_text):
        raise FeedParseError("feed declares a DTD/DOCTYPE — refused (XXE / entity-bomb guard)")
    try:
        # B314 rationale: a DOCTYPE (the sole entry point for the entity-expansion / XXE
        # vectors B314 warns about) is rejected just above, and ElementTree never
        # resolves external entities — so this parse of the now-DTD-free text is safe.
        return ElementTree.fromstring(xml_text)  # nosec B314
    except ElementTree.ParseError as error:
        raise FeedParseError(f"could not parse feed XML: {error}") from error


def parse_feed(xml_text: str) -> list[FeedItem]:
    """Parse RSS 2.0 `<item>`s AND Atom `<entry>`s into FeedItems.

    Both feed dialects are handled in one pass: RSS items are matched anywhere in
    the tree (so the channel wrapper is irrelevant), and Atom entries are matched
    by their namespaced tag. Missing fields degrade to "" rather than raising. The
    XML is parsed with DTD / external-entity processing disabled (`_hardened_parse`)
    since feeds are untrusted remote input.

    Raises `FeedParseError` when the XML is malformed or is not a feed at all.
    """
    root = _hardened_parse(xml_text)

    # RSS 1.0 / RDF puts <item> in the RSS-1.0 namespace, which `root.iter("item")`
    # below would NOT match — the feed would parse to zero items and masquerade as
    # an empty feed. Reject it loudly so a dead/unsupported feed is visible, not silent.
    if root.tag == f"{{{_NS_RDF}}}RDF":
        raise FeedParseError("RSS 1.0 / RDF feeds are not supported — use RSS 2.0 or Atom")

    # A document that is valid XML but not a feed at all (e.g. an HTML error page
    # served with a 200, or a stray `<html>…`) must NOT parse to an empty list —
    # that would record `status=ok, items=0` and let a broken endpoint stay green
    # forever. Accept only the two real feed roots; a genuinely empty `<rss>` /
    # `<feed>` still parses fine (to zero items), so liveness isn't punished.
    if root.tag != "rss" and root.tag != f"{{{_NS_ATOM}}}feed":
        raise FeedParseError(
            f"document root <{root.tag}> is not an RSS 2.0 <rss> or Atom <feed>"
        )

    items: list[FeedItem] = []
    # RSS 2.0: <item> lives under <channel>; `.//item` finds them regardless of depth.
    for rss_item in root.iter("item"):
        items.append(_parse_rss_item(rss_item))
    # Atom: namespaced <entry> elements.
    for atom_entry in root.iter(f"{{{_NS_ATOM}}}entry"):
        items.append(_parse_atom_entry(atom_entry))
    return items

