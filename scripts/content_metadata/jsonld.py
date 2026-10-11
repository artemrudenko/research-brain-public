#!/usr/bin/env python3
"""
jsonld.py — read schema.org facts out of `<script type="application/ld+json">`.

JSON-LD is the richest metadata a page offers (it is the only source that names
several authors and links each to a profile) and also the most hostile: it is
attacker-authored JSON of arbitrary depth and size, embedded in a document we
fetched from the open web. So the reader is deliberately defensive:

  - a block larger than `MAX_BLOCK_BYTES` is skipped unparsed — a decompression
    bomb should cost us a length check, not a parse;
  - malformed JSON is skipped, never raised: one broken block must not deny
    metadata for the whole page (or crash intake classification);
  - recursion is depth-bounded, so a deeply nested `@graph` can't exhaust the
    stack.

Node selection: publishers routinely ship several nodes (WebSite, Organization,
BreadcrumbList, and the article itself), often wrapped in `@graph`. The article
node wins — picking "whichever node happened to have an author" is how a site's
Organization node ends up credited as the byline.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from scripts.content_metadata.model import AuthorIdentity
from scripts.content_metadata.normalize import (
    author_identifier,
    clean_person_name,
    clean_text,
    safe_url,
)

# Anything bigger is not metadata a browser would render either. 64 KiB is
# generous for real schema.org payloads (the largest observed are single-digit KB).
MAX_BLOCK_BYTES = 64 * 1024

# How deep we walk looking for article nodes. Real documents nest 3-4 levels.
_MAX_DEPTH = 12

# `@type` values that mark the node describing THIS page (as opposed to the site
# or its navigation). Kept identical to the set intake classified on before, so
# absorbing the old parser cannot change a single classification outcome.
ARTICLE_TYPES = frozenset({"Article", "NewsArticle", "BlogPosting"})


@dataclass(frozen=True)
class JsonLdFacts:
    """Facts lifted from the article node, plus the classification signal."""

    authors: tuple[AuthorIdentity, ...] = ()
    publication: str = ""
    title: str = ""
    published_at: str = ""
    has_article_type: bool = False


@dataclass
class _Node:
    """An `@type`-tagged mapping found while walking, kept with its priority."""

    data: dict[str, Any] = field(default_factory=dict)
    is_article: bool = False


def _iter_nodes(value: object, depth: int = 0) -> list[_Node]:
    """Collect every mapping in `value`, flagging the ones typed as an article.

    Walks lists and `@graph` wrappers transparently. Depth-bounded: past
    `_MAX_DEPTH` we stop descending rather than trusting the document's shape.
    """
    if depth > _MAX_DEPTH:
        return []
    if isinstance(value, list):
        found: list[_Node] = []
        for item in value:
            found.extend(_iter_nodes(item, depth + 1))
        return found
    if not isinstance(value, dict):
        return []

    raw_type = value.get("@type")
    types = raw_type if isinstance(raw_type, list) else [raw_type]
    is_article = any(isinstance(t, str) and t in ARTICLE_TYPES for t in types)

    nodes = [_Node(data=value, is_article=is_article)]
    for child in value.values():
        nodes.extend(_iter_nodes(child, depth + 1))
    return nodes


def _author_from(value: object, base_url: str) -> list[AuthorIdentity]:
    """Build authors from a schema.org `author` value.

    Handles the three shapes the spec allows — a bare string, a Person object,
    or a list mixing both — because all three occur in the wild and dropping one
    silently loses the byline for every article from that publisher.
    """
    if isinstance(value, str):
        name = clean_person_name(value)
        return [AuthorIdentity(name=name)] if name else []

    if isinstance(value, list):
        authors: list[AuthorIdentity] = []
        for item in value:
            authors.extend(_author_from(item, base_url))
        return authors

    if isinstance(value, dict):
        name = clean_person_name(_as_text(value.get("name")))
        if not name:
            return []
        # `@id` doubles as a profile URL on many sites; it is only used when it
        # is a real http(s) URL, and only if `url` didn't already supply one.
        url = safe_url(_as_text(value.get("url")), base_url) or safe_url(
            _as_text(value.get("@id")), base_url
        )
        identifier, identifier_type = author_identifier(_as_text(value.get("identifier")))
        if not identifier:
            identifier, identifier_type = author_identifier(_as_text(value.get("@id")))
        return [
            AuthorIdentity(
                name=name, url=url, identifier=identifier, identifier_type=identifier_type
            )
        ]

    return []


def _as_text(value: object) -> str:
    """Coerce a JSON scalar to text; anything structured yields ""."""
    return value if isinstance(value, str) else ""


def _publisher_name(value: object) -> str:
    """A `publisher` is normally an Organization object, sometimes a bare name."""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        return clean_text(_as_text(value.get("name")))
    if isinstance(value, list):
        for item in value:
            name = _publisher_name(item)
            if name:
                return name
    return ""


def parse_blocks(blocks: list[str], base_url: str = "") -> JsonLdFacts:
    """Merge the JSON-LD blocks of one document into a single set of facts.

    Oversized and malformed blocks are skipped. Facts are read from the first
    article-typed node; if the document has none, no facts are taken (a WebSite
    node's `name` is the site, not the headline — that path is `og:site_name`'s
    job) though `has_article_type` still reports honestly.
    """
    nodes: list[_Node] = []
    for block in blocks:
        raw = block.strip()
        if not raw or len(raw.encode("utf-8", "ignore")) > MAX_BLOCK_BYTES:
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError, RecursionError):
            continue
        nodes.extend(_iter_nodes(payload))

    article_nodes = [n for n in nodes if n.is_article]
    if not article_nodes:
        return JsonLdFacts()

    node = article_nodes[0].data
    authors = _author_from(node.get("author"), base_url)

    return JsonLdFacts(
        authors=tuple(authors),
        publication=_publisher_name(node.get("publisher")),
        title=clean_text(_as_text(node.get("headline"))),
        published_at=clean_text(_as_text(node.get("datePublished"))),
        has_article_type=True,
    )


def has_article_type(raw: str) -> bool:
    """Back-compat shim for the old `evidence.jsonld_has_article_type`."""
    return parse_blocks([raw]).has_article_type
