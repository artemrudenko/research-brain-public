#!/usr/bin/env python3
"""
model.py — the value types the metadata extractor returns.

`ContentMetadata` is what both intake and collection read: one shape, whether
the facts came from a JSON-LD block, a meta tag, or an RSS entry. `evidence`
records WHERE each field came from, which is what makes a wrong author
debuggable later ("this byline came from a meta tag, not schema.org") and what a
future source/author report needs to weigh a claim.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AuthorIdentity:
    """One credited author.

    `name` is the only required part — plenty of bylines are a bare name, and a
    name alone deliberately yields no `identifier`, because inventing one would
    let two different people who share a name merge in a later aggregation.
    `identifier` is normalised to `type:local` (e.g. `orcid:0000-0002-1825-0097`).
    """

    name: str
    url: str = ""
    identifier: str = ""
    identifier_type: str = ""


@dataclass(frozen=True)
class ContentMetadata:
    """Everything the extractor could establish about one document.

    Every field defaults to empty rather than None: callers render these into
    frontmatter and prose, and a missing value is always "nothing to say", never
    a distinct state worth branching on. `authors` is a tuple so the frozen
    dataclass is genuinely immutable and comparable (two extractions of the same
    document must be `==`, which the determinism test pins).
    """

    title: str = ""
    authors: tuple[AuthorIdentity, ...] = ()
    publication: str = ""
    published_at: str = ""
    canonical_url: str = ""
    feed_url: str = ""
    content_type: str = ""
    # field name → provenance token: jsonld | rss | meta | rel-author | og |
    # byline | hostname | manual. Absent key means the field was never resolved.
    evidence: dict[str, str] = field(default_factory=dict)
