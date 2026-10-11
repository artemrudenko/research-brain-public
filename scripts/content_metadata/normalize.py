#!/usr/bin/env python3
"""
normalize.py — cleaning rules for metadata read out of untrusted remote documents.

Every value here came from someone else's HTML. Two hazards matter downstream:

  1. The values land in YAML frontmatter. Neutralising YAML structure is the
     emitter's job (`collection/article.py`), NOT this module's — an extractor
     that mangles `A: B` into something else would corrupt legitimate titles.
     What this module does guarantee is that a value is a SINGLE LINE of bounded
     length, because no emitter can escape its way out of an unbounded blob and
     a stray newline is the one thing that breaks a block-scalar writer.
  2. URLs are rendered as links and (later) polled as feeds, so a non-http(s)
     scheme is never carried forward.

Nothing here dereferences a URL. Resolving an author profile by fetching it is
explicitly out of scope (ADR: no auto-fetch of author_url).
"""
from __future__ import annotations

from urllib.parse import urljoin, urlsplit

# A display name / title longer than this is a parser accident (a whole page
# body captured as a byline, say), not a person. Truncating bounds what reaches
# frontmatter without dropping the signal entirely.
MAX_NAME_CHARS = 200

# Titles and publication names run longer than person names legitimately, so
# they get their own (still bounded) ceiling rather than being cut at a byline's.
MAX_TITLE_CHARS = 300

# Invisible characters that survive a naive `.strip()` and let two visually
# identical names compare unequal — the same class the S1 sanitizer strips.
# Removed outright rather than replaced with a space: `Ja<ZWSP>ne` is `Jane`.
_ZERO_WIDTH = str.maketrans(
    "",
    "",
    "​‌‍⁠﻿­᠎",
)

# Bylines are written for humans and carry a lead-in the name doesn't include.
_BYLINE_PREFIXES = ("by ", "By ", "BY ")

# The only schemes a downstream reader may follow.
_SAFE_SCHEMES = frozenset({"http", "https"})


def clean_text(value: str | None, *, limit: int = MAX_NAME_CHARS) -> str:
    """Collapse `value` to one bounded, whitespace-normalised line.

    Zero-width characters are removed, every whitespace run (newlines and tabs
    included) becomes a single space, and the result is truncated to `limit`.
    Returns "" for None/blank so callers can test truthiness rather than None.
    """
    if not value:
        return ""
    collapsed = " ".join(value.translate(_ZERO_WIDTH).split())
    return collapsed[:limit]


def clean_person_name(value: str | None) -> str:
    """`clean_text` plus the byline lead-in strip (`By Jane Doe` → `Jane Doe`)."""
    name = clean_text(value)
    for prefix in _BYLINE_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):].strip()
    return name


def safe_url(value: str | None, base: str = "") -> str:
    """Resolve `value` against `base` and return it only if it is http(s).

    A relative href becomes absolute (so a stored URL is meaningful away from
    the page it was found on); `javascript:`, `data:`, `mailto:` and friends
    yield "" — the caller keeps the name and loses only the link.
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    absolute = urljoin(base, raw) if base else raw
    try:
        scheme = urlsplit(absolute).scheme.lower()
    except ValueError:  # malformed port / IPv6 literal
        return ""
    return absolute if scheme in _SAFE_SCHEMES else ""


# Author identifier schemes we can recognise WITHOUT a network call, most
# specific first. A bare display name never yields an identifier — inventing one
# would let two different people with the same name merge later (ADR: no fuzzy
# author merging).
_ID_HOSTS = (
    ("orcid", "orcid.org"),
    ("openalex", "openalex.org"),
    ("semanticscholar", "semanticscholar.org"),
)


def author_identifier(value: str | None) -> tuple[str, str]:
    """Return `(identifier, identifier_type)` for a schema.org identifier value.

    Recognises the canonical profile URLs (`https://orcid.org/0000-…`) and the
    already-prefixed form (`orcid:0000-…`), normalising both to `type:id`.
    Anything unrecognised yields `("", "")` rather than a guess.
    """
    raw = clean_text(value)
    if not raw:
        return "", ""

    lowered = raw.lower()
    for kind, host in _ID_HOSTS:
        if lowered.startswith(f"{kind}:"):
            local = raw.split(":", 1)[1].strip()
            return (f"{kind}:{local}", kind) if local else ("", "")
        if host in lowered:
            local = urlsplit(raw).path.strip("/").split("/")[-1]
            if local:
                return f"{kind}:{local}", kind
    return "", ""
