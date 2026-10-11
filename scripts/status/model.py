from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class SourceRecord:
    """One monitored source row from config/sources.md (active or parked)."""

    category: str
    url: str
    type: str
    tier: str
    priority: str
    filter: str
    active: bool


@dataclass
class CadenceBlock:
    """One scheduled block (collect / curate / synthesis / digest)."""

    name: str
    cron: str
    description: str


@dataclass
class CadenceSummary:
    """The whole schedule rendered for a non-technical reader."""

    blocks: list[CadenceBlock] = field(default_factory=list)
    timezone: str = "UTC"
    lookback_days: int = 7


@dataclass
class DigestEntry:
    """A produced digest file: its date, one-line summary, and quiet flag."""

    date: date
    path: Path
    summary: str
    is_quiet: bool


@dataclass
class Findings:
    """Key findings extracted from the latest digest."""

    digest_date: date | None = None
    highlights: list[str] = field(default_factory=list)
    is_quiet: bool = False
    no_digests: bool = False
    message: str = ""


__all__ = [
    "CadenceBlock",
    "CadenceSummary",
    "DigestEntry",
    "Findings",
    "SourceRecord",
]
