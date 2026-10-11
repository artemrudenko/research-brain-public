from __future__ import annotations

import re

# Allowed enum values per CONVENTIONS §2 / the shipped sources.md record format.
SOURCE_TYPES = ("rss", "blog", "medium-tag", "webpage")
TIERS = ("high", "medium", "low")
PRIORITIES = ("high", "medium", "low")

# A topic / category name is a lowercase slug (folder-safe): the same shape the
# setup-wizard derives. Keeps topics.md, sources.md and folder paths consistent.
_TOPIC_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# The canonical Active-sources table header + separator written for a new topic.
_TABLE_HEADER = "| URL | Type | Tier | Priority | Filter | Active |"
_TABLE_SEP = "|-----|------|------|----------|--------|--------|"

# Trailing inline HTML comments (`<!-- ... -->`) annotate the shipped EXAMPLE
# rows. The SAME rule brain_status._split_row uses — strip the comment before
# counting/splitting cells so both readers agree (FIX 1; keep DRY/consistent).
_ROW_COMMENT_RE = re.compile(r"<!--.*?-->")

# The shipped template marks its placeholder source rows with this marker inside
# the trailing comment. A row carrying it is an EXAMPLE, not a real monitored
# source, so it must be excluded from list/summary counts (FIX 3). brain_status
# uses the identical marker so the two readers agree on a fresh install.
_EXAMPLE_MARKER = "# EXAMPLE — replace"


def _strip_row_comment(line: str) -> str:
    """Drop a trailing HTML comment from a table row, mirroring brain_status."""
    return _ROW_COMMENT_RE.sub("", line)


def _is_example_row(line: str) -> bool:
    """True when a table row carries the shipped `# EXAMPLE — replace` marker.

    The marker lives in the row's trailing HTML comment; this is checked on the
    raw line BEFORE the comment is stripped for cell-counting (FIX 3).
    """
    comment = _ROW_COMMENT_RE.search(line)
    return comment is not None and _EXAMPLE_MARKER in comment.group(0)


# --------------------------------------------------------------------------- #


def _validate_topic_name(name: str) -> str:
    """Return a normalized topic name or raise ValueError on a malformed one."""
    normalized = (name or "").strip()
    if not _TOPIC_NAME_RE.fullmatch(normalized):
        raise ValueError(
            f"invalid topic name {name!r}: use a lowercase slug like "
            f"`ai-agents` (letters, digits, single hyphens; no spaces/slashes)"
        )
    return normalized


# Characters that would break the markdown table the URL is written into: a `|`
# splits the row into extra cells (so the parser drops it), and `<!--` / `-->`
# get comment-stripped at parse time (so the row never matches again). We reject
# any value containing them rather than silently corrupting the table (FIX 2).
_TABLE_BREAKERS = ("|", "<!--", "-->")


def _reject_table_breakers(value: str, label: str) -> None:
    """Raise ValueError if `value` contains a markdown-table-breaking sequence."""
    for token in _TABLE_BREAKERS:
        if token in value:
            raise ValueError(
                f"invalid {label} {value!r}: must not contain {token!r} "
                f"(it would corrupt the sources.md table)"
            )


def _validate_url(url: str) -> str:
    """Return the URL or raise ValueError if it is not a plain http(s) URL.

    Also rejects table-breaking characters (`|`, `<!--`, `-->`) so the URL can
    be written into — and later parsed back out of — the markdown table (FIX 2).
    """
    candidate = (url or "").strip()
    _reject_table_breakers(candidate, "URL")
    match = re.fullmatch(r"https?://[^\s/]+(?:/[^\s]*)?", candidate)
    if not match:
        raise ValueError(
            f"invalid URL {url!r}: must start with http:// or https:// and "
            f"include a host (e.g. https://example.com/feed.xml)"
        )
    return candidate


def _validate_enum(value: str, allowed: tuple[str, ...], label: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in allowed:
        raise ValueError(
            f"invalid {label} {value!r}: choose one of {', '.join(allowed)}"
        )
    return normalized


