#!/usr/bin/env python3
"""
content_metadata — the one place that reads title/author/publication/date/feed.

Both intake (classifying a pasted link) and collection (saving an article) need
the same facts about a document. Before this package, intake had a signals-only
HTML parser and collection read a couple of RSS fields; neither produced authors
richer than a display string, and adding author extraction twice would have
guaranteed they drifted.

This module owns the PRECEDENCE POLICY — which source wins when several name an
author or a publication. The parsers below it stay dumb transcribers, so the
policy is reviewable in one screen:

    author       jsonld → rel=author → article:author → author/byl meta → byline
    publication  jsonld publisher → og:site_name → hostname
    title        og:title → jsonld headline → <title>
    published    article:published_time (or any date meta) → jsonld datePublished

RSS/Atom sits between JSON-LD and the meta tags for a feed-sourced article; that
merge is `merge_feed_author`, applied by the collector, because only it knows a
document arrived via a feed.

Every returned value is single-line and length-bounded (see `normalize`), and no
function here ever dereferences a URL — resolving an author profile by fetching
it is deliberately out of scope.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from scripts.content_metadata.html import MetadataParser, parse_html
from scripts.content_metadata.model import AuthorIdentity, ContentMetadata
from scripts.content_metadata.normalize import (
    MAX_TITLE_CHARS,
    author_identifier,
    clean_person_name,
    clean_text,
    safe_url,
)

__all__ = [
    "AuthorIdentity",
    "ContentMetadata",
    "MetadataParser",
    "author_identifier",
    "from_html",
    "metadata_from_signals",
    "merge_feed_author",
    "parse_html",
    "safe_url",
]


def _dedupe(authors: list[AuthorIdentity]) -> tuple[AuthorIdentity, ...]:
    """Drop exact repeats, preserving document order.

    Exact means every field matches — the same person credited twice. Names that
    merely look alike ("J. Doe" vs "Jane Doe") are left as two people: guessing
    they are one is how a byline gets misattributed, and the identity rules that
    can decide this safely need corroboration across documents, not a string
    comparison inside one.
    """
    seen: set[tuple[str, str, str]] = set()
    unique: list[AuthorIdentity] = []
    for author in authors:
        key = (author.name, author.url, author.identifier)
        if key not in seen:
            seen.add(key)
            unique.append(author)
    return tuple(unique)


def _authors_from_signals(
    parsed: MetadataParser,
) -> tuple[tuple[AuthorIdentity, ...], str]:
    """Walk the author precedence ladder; return `(authors, provenance)`."""
    if parsed.jsonld.authors:
        return _dedupe(list(parsed.jsonld.authors)), "jsonld"

    if parsed.rel_authors:
        found = [
            AuthorIdentity(name=clean_person_name(name), url=url)
            for name, url in parsed.rel_authors
            if clean_person_name(name)
        ]
        if found:
            return _dedupe(found), "rel-author"

    # The meta tags are one tier: they carry a name and nothing else, so the
    # order among them is only about which the publisher curated more carefully.
    for raw in (parsed.article_author, parsed.meta_author, parsed.meta_byl):
        name = clean_person_name(raw)
        if name:
            return (AuthorIdentity(name=name),), "meta"

    byline = clean_person_name(parsed.byline)
    if byline:
        return (AuthorIdentity(name=byline),), "byline"

    return (), ""


def _publication_from_signals(parsed: MetadataParser, url: str) -> tuple[str, str]:
    """Publisher name, falling back to the site name and finally the hostname."""
    if parsed.jsonld.publication:
        return parsed.jsonld.publication, "jsonld"
    site_name = clean_text(parsed.site_name, limit=MAX_TITLE_CHARS)
    if site_name:
        return site_name, "og"
    host = urlsplit(url).hostname or ""
    # `www.` is noise in a display name; the bare host reads as the publication.
    return host[4:] if host.startswith("www.") else host, "hostname"


def from_html(body: str, url: str) -> ContentMetadata:
    """Extract everything establishable about the document at `url`.

    Never raises: a hostile or malformed document yields sparse metadata, not an
    exception. Fields that could not be resolved are empty and absent from
    `evidence`, so a caller can distinguish "nobody was credited" from "credited
    by a meta tag".
    """
    return metadata_from_signals(parse_html(body, url), url)


def metadata_from_signals(parsed: MetadataParser, url: str) -> ContentMetadata:
    """Apply the precedence policy to an ALREADY-parsed document.

    Split out from `from_html` for callers that need both the raw classification
    signals and the metadata — intake reads `feed_url` / `og_article` to decide
    what a URL is, and would otherwise have to parse the same document twice.
    """
    evidence: dict[str, str] = {}

    authors, author_source = _authors_from_signals(parsed)
    if author_source:
        evidence["authors"] = author_source

    publication, publication_source = _publication_from_signals(parsed, url)
    if publication:
        evidence["publication"] = publication_source

    title = (
        clean_text(parsed.og_title, limit=MAX_TITLE_CHARS)
        or parsed.jsonld.title
        or clean_text(parsed.title, limit=MAX_TITLE_CHARS)
    )
    published_at = clean_text(parsed.published_time) or parsed.jsonld.published_at

    return ContentMetadata(
        title=title,
        authors=authors,
        publication=publication,
        published_at=published_at,
        canonical_url=parsed.canonical_url,
        feed_url=parsed.feed_url,
        content_type="article" if parsed.og_article else "",
        evidence=evidence,
    )


def merge_feed_author(
    metadata: ContentMetadata, feed_author: str, feed_title: str = ""
) -> ContentMetadata:
    """Fold an RSS/Atom entry's author and channel title into HTML metadata.

    A feed's `dc:creator` is a curated statement by the publisher, so it outranks
    every HTML meta tag — but not JSON-LD, which is the only source that can name
    several authors and link each to a profile. The feed's channel title serves
    the same role for `publication`: better than a hostname guess, worse than a
    declared publisher.
    """
    name = clean_person_name(feed_author)
    authors, evidence = metadata.authors, dict(metadata.evidence)

    if name and evidence.get("authors") != "jsonld":
        authors = (AuthorIdentity(name=name),)
        evidence["authors"] = "rss"

    publication = metadata.publication
    channel = clean_text(feed_title, limit=MAX_TITLE_CHARS)
    if channel and evidence.get("publication") in (None, "hostname"):
        publication = channel
        evidence["publication"] = "rss"

    return ContentMetadata(
        title=metadata.title,
        authors=authors,
        publication=publication,
        published_at=metadata.published_at,
        canonical_url=metadata.canonical_url,
        feed_url=metadata.feed_url,
        content_type=metadata.content_type,
        evidence=evidence,
    )
