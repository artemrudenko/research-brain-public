from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from scripts.normalize_url import normalize_or_raw
from scripts.registry import iter_registry_rows

# --------------------------------------------------------------------------- #


def load_known_urls(registry_path: Path) -> set[str]:
    """Normalized-URL dedup keys for every existing registry row ([] if missing).

    Uses `normalize_or_raw` so one malformed stored URL (e.g. a bad port) degrades
    to its raw key instead of aborting the whole dedup scan."""
    return {normalize_or_raw(row.url) for row in iter_registry_rows(registry_path)}


def _source_domain(url: str) -> str:
    """The bare host of a source URL (the frontmatter `source:` value)."""
    host = (urlsplit(url).hostname or "").strip()
    return host or "rss"


def _is_valid_article_url(url: str) -> bool:
    """True iff `url` is a fetchable http(s) link with a real host and valid port.

    A scheme check alone is not enough: `https:///path` has the right scheme but no
    host (it would be stored mangled), and a malformed/out-of-range port such as
    `https://h:99999/x` makes `urlsplit(...).port` raise `ValueError` — which, left
    unguarded, aborted the entire category mid-loop. Validate all three here so a
    single bad item is skipped, never written and never fatal.
    """
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in ("http", "https"):
            return False
        if not parts.hostname:  # scheme but no host (e.g. https:///path)
            return False
        _ = parts.port  # raises ValueError on an out-of-range port (e.g. 99999)
    except ValueError:
        return False
    return True


