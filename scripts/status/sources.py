from __future__ import annotations

import re
from pathlib import Path

from scripts.status.model import SourceRecord

ROW_COMMENT_RE = re.compile(r"<!--.*?-->")
EXAMPLE_MARKER = "# EXAMPLE — replace"


def is_example_row(line: str) -> bool:
    """True when a row carries the shipped `# EXAMPLE — replace` marker."""
    comment = ROW_COMMENT_RE.search(line)
    return comment is not None and EXAMPLE_MARKER in comment.group(0)


def split_row(line: str) -> list[str]:
    """Split a pipe-delimited markdown table row into trimmed cells."""
    line = ROW_COMMENT_RE.sub("", line).strip()
    return [cell.strip() for cell in line.strip("|").split("|")]


def is_separator_row(line: str) -> bool:
    """True for a markdown table separator row like `|---|---|`."""
    return bool(re.fullmatch(r"\|[\s\-:|]+\|", line.strip()))


def monitored_sources(
    *, root: Path, active_only: bool = True
) -> list[SourceRecord]:
    """Parse the active sources config into structured source records.

    Reads config/sources.yaml (the only format since 0.8.0) through the shared
    store loader. A missing or malformed file degrades to an EMPTY list — this
    is a read-only status path (health/doctor/brain-ask must keep answering);
    the loud failures live where they belong: validate_config/doctor report
    parse errors AND the unmigrated-legacy migrate-config pointer, and the
    brain_status CLI prints that pointer alongside its empty listing.
    """
    from scripts.sources import store  # local import keeps this module light

    path = store.active_sources_path(root / "config")
    if not path.exists():
        return []
    try:
        categories = store.load_categories(path)
    except (ValueError, RuntimeError):
        return []

    return [
        SourceRecord(
            category=cat.name,
            url=src.url,
            type=src.type,
            tier=src.tier,
            priority=src.priority,
            filter=src.filter_note,
            active=src.active,
        )
        for cat in categories
        for src in cat.sources
        if src.active or not active_only
    ]


__all__ = [
    "EXAMPLE_MARKER",
    "ROW_COMMENT_RE",
    "is_example_row",
    "is_separator_row",
    "monitored_sources",
    "split_row",
]
