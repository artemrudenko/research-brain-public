"""Frontmatter and date parsing helpers for digest scans."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from scripts.fm import parse_scalars, split_frontmatter

BODY_LAST_UPDATED_RE = re.compile(
    r"last[ _-]?updated[^0-9]*([0-9]{4}-[0-9]{2}-[0-9]{2})", re.IGNORECASE
)


def split_flat_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a markdown file into flat frontmatter scalars and body."""
    block, body = split_frontmatter(text)
    return parse_scalars(block), body


def parse_iso_date(value: str | None) -> date | None:
    """Parse a `YYYY-MM-DD` date or datetime string into a date."""
    if not value:
        return None
    cleaned = value.strip().strip("\"'")
    if not cleaned:
        return None
    cleaned = cleaned.split("T")[0].split(" ")[0]
    try:
        return datetime.strptime(cleaned, "%Y-%m-%d").date()
    except ValueError:
        return None


def concept_last_updated(fields: dict[str, str], body: str) -> date | None:
    """Find a concept's `last_updated` date from frontmatter, then body."""
    from_fm = parse_iso_date(fields.get("last_updated"))
    if from_fm is not None:
        return from_fm
    match = BODY_LAST_UPDATED_RE.search(body)
    return parse_iso_date(match.group(1)) if match else None


def within_lookback(value: date | None, *, today: date, lookback_days: int) -> bool:
    """True when `value` falls in the inclusive lookback window ending today."""
    if value is None:
        return False
    cutoff = today - timedelta(days=lookback_days - 1)
    return cutoff <= value <= today


__all__ = [
    "BODY_LAST_UPDATED_RE",
    "concept_last_updated",
    "parse_iso_date",
    "split_flat_frontmatter",
    "within_lookback",
]
