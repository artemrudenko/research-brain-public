"""Registry and article-frontmatter lookup helpers for the inbox queue."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Protocol

from scripts.normalize_url import normalize_or_raw
from scripts.registry import RegistryRow, iter_registry_rows


class RegistryRowsReader(Protocol):
    """Callable that yields parsed registry rows."""

    def __call__(self, path: Path) -> Iterable[RegistryRow]:
        """Return iterable registry rows for `path`."""


def article_field(path: Path, field: str) -> str:
    """A top-level frontmatter `field:` value of an article, empty when absent."""
    pattern = re.compile(rf"(?m)^{re.escape(field)}:\s*(.+?)\s*$")
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def article_url(path: Path) -> str:
    """The `url:` frontmatter value of an inbox article, empty when absent.

    YAML-quoted values are unquoted so a quoted-empty `url: ''` reads as the
    empty string (falsy), not as a truthy two-character sentinel whose
    normalized key would match every URL-less article in route()'s adopt scan.
    """
    return _unquote(article_field(path, "url"))


def url_in_registry(
    registry_path: Path,
    url: str,
    *,
    rows_reader: Callable[[Path], Iterable[RegistryRow]] = iter_registry_rows,
) -> bool:
    """True when `url`, after tolerant normalization, already has a registry row."""
    key = normalize_or_raw(url)
    return any(normalize_or_raw(row.url) == key for row in rows_reader(registry_path))


def find_by_url(
    paths: Iterable[Path],
    url: str,
    *,
    article_url_reader: Callable[[Path], str] = article_url,
) -> Path | None:
    """First article in `paths` whose URL matches `url` after normalization.

    Uses the tolerant key (like `url_in_registry`) so a malformed pasted URL — a
    typo'd out-of-range port, a bad IPv6 literal — degrades to its raw string instead
    of raising a bare ValueError up through the `/save` CLI. An empty key never matches.
    """
    key = normalize_or_raw(url)
    if not key:
        return None
    for path in paths:
        if normalize_or_raw(article_url_reader(path)) == key:
            return path
    return None


def find_in_inbox_by_url(
    incoming_root: Path,
    url: str,
    pending_reader: Callable[[Path], list[Path]],
    article_url_reader: Callable[[Path], str] = article_url,
) -> Path | None:
    """Return the queued article whose URL matches `url`, or None."""
    return find_by_url(
        pending_reader(incoming_root), url, article_url_reader=article_url_reader
    )


__all__ = [
    "RegistryRowsReader",
    "article_field",
    "article_url",
    "find_by_url",
    "find_in_inbox_by_url",
    "url_in_registry",
]
