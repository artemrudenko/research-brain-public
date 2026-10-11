#!/usr/bin/env python3
"""
html.py — one HTML pass producing both intake's classification signals and the
document's metadata.

This absorbs what used to be `intake_flow/evidence.py`. That parser answered
only "does this URL look like an article, an index, or a feed?"; the same pass
already walks every meta tag and JSON-LD block, so pulling the *values* out
costs nothing and means the repo has one HTML metadata parser instead of two.

Two contracts inherited from the parser it replaces, both load-bearing:

  - **`parse_html` never raises.** `classify_url` calls it without a try/except,
    so a malformed document must degrade to weak evidence, not a crash.
  - **`og_article` is the OR of two signals** — an `og:type=article` meta *or* a
    JSON-LD `@type` in the article set. Intake's confidence values are pinned to
    that union.

(Body-text extraction stays in `collection/text.py`: it selects a main container
and flattens prose, which is a different job from reading metadata off the head.)
"""
from __future__ import annotations

import re
from contextlib import suppress
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from scripts.content_metadata.jsonld import JsonLdFacts, parse_blocks
from scripts.content_metadata.normalize import safe_url

# A path that looks like a permalink: a year, or a post/article/story/blog slug.
# Unchanged from the parser this replaces — intake's "≥3 article links ⇒ blog
# index" rule and its 0.7 confidence are pinned to exactly this pattern.
ARTICLE_LINK_RE = re.compile(r"/(?:20[0-9]{2}|[^/]*(?:post|article|story|blog)[^/]*)", re.I)

_FEED_MIME_TYPES = frozenset({"application/rss+xml", "application/atom+xml"})

# Meta keys whose mere presence signals "this page has a publication date".
# Substring match on "published" plus these exact keys, preserved verbatim from
# the old parser so classification outcomes cannot shift.
_DATE_KEYS = frozenset({"date", "datepublished"})


class MetadataParser(HTMLParser):
    """Collects classification signals and raw metadata in a single pass.

    Raw is the operative word: values land here as the document wrote them.
    Normalisation and the precedence ladder live in `content_metadata/__init__`,
    so this class stays a transcriber and the "which source wins" policy is
    readable in one place.
    """

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url

        # ── classification signals (the absorbed evidence.py surface) ──
        self.feed_url = ""
        self.og_article = False
        self.has_published_time = False
        self.has_article_element = False
        self.article_links: set[str] = set()
        self.title = ""

        # ── metadata values ──
        self.canonical_url = ""
        self.og_title = ""
        self.site_name = ""
        self.published_time = ""
        self.meta_author = ""
        self.meta_byl = ""
        self.article_author = ""
        self.rel_authors: list[tuple[str, str]] = []
        self.byline = ""
        self.jsonld_blocks: list[str] = []
        # Filled by `parse_html` once every block has been collected, so the
        # document's JSON-LD is parsed exactly once per pass.
        self.jsonld = JsonLdFacts()

        # ── capture state ──
        self._in_title = False
        self._script_is_jsonld = False
        self._script_chunks: list[str] = []
        self._rel_author_href: str | None = None
        self._rel_author_chunks: list[str] = []
        self._byline_tag = ""
        self._byline_depth = 0
        self._byline_chunks: list[str] = []

    # ── tag dispatch ──────────────────────────────────────────────────────────

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {name.lower(): (value or "") for name, value in attrs}
        lowered = tag.lower()

        if lowered == "title":
            self._in_title = True
        elif lowered == "article":
            self.has_article_element = True
        elif lowered == "link":
            self._handle_link(attr)
        elif lowered == "meta":
            self._handle_meta(attr)
        elif lowered == "script":
            self._script_is_jsonld = attr.get("type", "").lower() == "application/ld+json"
            self._script_chunks = []
        elif lowered == "a":
            self._handle_anchor(attr)

        # A byline can be marked up on any element, so this check is tag-agnostic
        # and runs after the specific handlers.
        if self._byline_depth:
            if lowered == self._byline_tag:
                self._byline_depth += 1
        elif self._is_byline_marker(attr):
            self._byline_tag = lowered
            self._byline_depth = 1
            self._byline_chunks = []

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "title":
            self._in_title = False
        elif lowered == "script" and self._script_is_jsonld:
            self.jsonld_blocks.append("".join(self._script_chunks))
            self._script_is_jsonld = False
            self._script_chunks = []
        elif lowered == "a" and self._rel_author_href is not None:
            name = " ".join("".join(self._rel_author_chunks).split())
            if name:
                self.rel_authors.append((name, self._rel_author_href))
            self._rel_author_href = None
            self._rel_author_chunks = []

        if self._byline_depth and lowered == self._byline_tag:
            self._byline_depth -= 1
            if self._byline_depth == 0 and not self.byline:
                self.byline = " ".join("".join(self._byline_chunks).split())

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._script_is_jsonld:
            self._script_chunks.append(data)
        if self._rel_author_href is not None:
            self._rel_author_chunks.append(data)
        if self._byline_depth:
            self._byline_chunks.append(data)

    # ── per-tag helpers ───────────────────────────────────────────────────────

    def _handle_link(self, attr: dict[str, str]) -> None:
        rel = attr.get("rel", "").lower()
        href = attr.get("href", "").strip()
        if not href:
            return
        if "alternate" in rel and attr.get("type", "").lower() in _FEED_MIME_TYPES:
            # First feed wins, matching the previous parser's last-write semantics
            # closely enough for classification while preferring the head's order.
            if not self.feed_url:
                self.feed_url = safe_url(href, self.base_url)
        elif "canonical" in rel:
            self.canonical_url = safe_url(href, self.base_url)

    def _handle_meta(self, attr: dict[str, str]) -> None:
        key = (attr.get("property") or attr.get("name") or "").lower()
        raw = attr.get("content", "")
        lowered = raw.lower()

        if key == "og:type" and lowered == "article":
            self.og_article = True
        if "published" in key or key in _DATE_KEYS:
            self.has_published_time = True
            if raw and not self.published_time:
                self.published_time = raw
        if key == "og:title" and not self.og_title:
            self.og_title = raw
        elif key == "og:site_name" and not self.site_name:
            self.site_name = raw
        elif key == "author" and not self.meta_author:
            self.meta_author = raw
        elif key == "byl" and not self.meta_byl:
            self.meta_byl = raw
        elif key == "article:author" and not self.article_author:
            self.article_author = raw

    def _handle_anchor(self, attr: dict[str, str]) -> None:
        href = attr.get("href", "").strip()
        if not href:
            return
        if "author" in attr.get("rel", "").lower():
            # Capture the link text as the name; the href is validated here so a
            # `javascript:` profile link is dropped while the name survives.
            self._rel_author_href = safe_url(href, self.base_url)
            self._rel_author_chunks = []
        absolute = urljoin(self.base_url, href)
        if ARTICLE_LINK_RE.search(urlsplit(absolute).path):
            self.article_links.add(absolute)

    @staticmethod
    def _is_byline_marker(attr: dict[str, str]) -> bool:
        """Is this element the visible byline? Class name or schema.org itemprop."""
        return "byline" in attr.get("class", "").lower() or (
            attr.get("itemprop", "").lower() == "author"
        )


def parse_html(body: str, url: str) -> MetadataParser:
    """Parse `body` and return the collected signals — never raises.

    Malformed markup degrades to whatever was collected before the parser gave
    up, which is exactly the "weak evidence ⇒ ambiguous" path intake expects.
    """
    parser = MetadataParser(url)
    # Whatever the parser collected before giving up is kept: that is exactly the
    # "weak evidence ⇒ ambiguous" path intake expects, and `classify_url` has no
    # try/except of its own, so raising here would turn a bad page into a crash.
    with suppress(Exception):
        parser.feed(body)

    # Parse the collected JSON-LD once and fold its article typing into
    # `og_article`, preserving the union intake's confidence values depend on.
    parser.jsonld = parse_blocks(parser.jsonld_blocks, url)
    parser.og_article = parser.og_article or parser.jsonld.has_article_type
    return parser
