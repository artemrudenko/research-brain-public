#!/usr/bin/env python3
"""
metrics.py — per-source usefulness, joined from the journal and the registry.

Neither half answers "is this source worth keeping?" alone:

  - the **journal** knows what a source OFFERED and what the collector did with
    it — considered, selected, and the reason for every drop;
  - the **registry** knows what happened to the survivors — whether curation kept
    or rejected them.

Joining the two is the point. A feed whose articles are always collected and
always rejected downstream looks productive in the journal and is useless in
fact; a feed that offers three articles a month and gets all three into the vault
looks quiet and is excellent.

Two deliberate refusals:

  - **No single score.** One blended number would hide which signal moved it, and
    the whole reason for recording reason codes was that "rejected" means very
    different things (off-topic vs. a cookie wall vs. a duplicate).
  - **No automatic tier changes.** `tier` in `config/sources.yaml` is the user's
    stated trust and stays theirs. This module measures; it never edits config.

The status rule is imported from `value_metrics`, not re-implemented, so the two
reports can never disagree about the same registry.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.normalize_url import normalize_or_raw  # noqa: E402
from scripts.registry import iter_registry_rows  # noqa: E402
from scripts.source_report.events import read_decisions  # noqa: E402
from scripts.value_metrics import classify_status  # noqa: E402

# Observation thresholds. Below the first, a breakdown says more about when
# collection started than about the source; at weekly cadence `ESTABLISHED_AT`
# is several months of history, which is the point at which a quiet source's
# numbers become readable at all.
LOW_CONFIDENCE_AT = 5
ESTABLISHED_AT = 20


@dataclass(frozen=True)
class SourceMetrics:
    """What we can honestly say about one source. Counts, never a verdict."""

    source_url: str
    considered: int
    selected: int
    by_decision: dict[str, int]
    passed_curation: int
    rejected_curation: int
    pending_curation: int
    authors: tuple[str, ...] = ()
    last_seen: str = ""
    topics: tuple[str, ...] = ()

    @property
    def confidence(self) -> str:
        """`insufficient` / `low` / `established` — how much history backs this row."""
        if self.considered >= ESTABLISHED_AT:
            return "established"
        if self.considered >= LOW_CONFIDENCE_AT:
            return "low"
        return "insufficient"

    def to_dict(self) -> dict[str, object]:
        return {
            "source_url": self.source_url,
            "considered": self.considered,
            "selected": self.selected,
            "by_decision": self.by_decision,
            "passed_curation": self.passed_curation,
            "rejected_curation": self.rejected_curation,
            "pending_curation": self.pending_curation,
            "authors": list(self.authors),
            "topics": list(self.topics),
            "last_seen": self.last_seen,
            "confidence": self.confidence,
        }


@dataclass
class _Accumulator:
    """Mutable per-source tally, frozen into `SourceMetrics` at the end."""

    considered: int = 0
    selected: int = 0
    by_decision: dict[str, int] = field(default_factory=dict)
    authors: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    last_seen: str = ""


def _registry_status_by_url(registry_path: Path) -> dict[str, str]:
    """Canonical URL → curation status, for joining onto journal rows.

    Keyed by the NORMALIZED url because the journal records the link as the feed
    published it while the registry stores the canonical dedup key. Joining on
    the raw string would report zero curation outcomes for every source whose
    feed appends tracking parameters — a silent, plausible-looking wrong answer.
    """
    if not registry_path.exists():
        return {}
    return {
        normalize_or_raw(row.url): classify_status(row.status)
        for row in iter_registry_rows(registry_path)
    }


def source_metrics(root: Path, registry_path: Path) -> list[SourceMetrics]:
    """One row per source seen in the journal, sorted by URL for stable output."""
    statuses = _registry_status_by_url(registry_path)
    tallies: dict[str, _Accumulator] = {}

    for entry in read_decisions(root):
        source = str(entry.get("source_url", ""))
        if not source:
            continue
        tally = tallies.setdefault(source, _Accumulator())
        decision = str(entry.get("decision", ""))
        tally.considered += 1
        tally.by_decision[decision] = tally.by_decision.get(decision, 0) + 1
        if decision == "selected":
            tally.selected += 1
            tally.urls.append(normalize_or_raw(str(entry.get("candidate_url", ""))))

        author = entry.get("author")
        if isinstance(author, dict):
            name = str(author.get("name", ""))
            if name and name not in tally.authors:
                tally.authors.append(name)
        topic = str(entry.get("topic", ""))
        if topic and topic not in tally.topics:
            tally.topics.append(topic)
        ts = str(entry.get("ts", ""))
        if ts > tally.last_seen:
            tally.last_seen = ts

    rows: list[SourceMetrics] = []
    for source, tally in sorted(tallies.items()):
        outcomes = [statuses.get(url, "") for url in tally.urls]
        rows.append(
            SourceMetrics(
                source_url=source,
                considered=tally.considered,
                selected=tally.selected,
                by_decision=dict(sorted(tally.by_decision.items())),
                # Only rows the registry actually knows about are counted; a
                # selected article with no registry row is not "pending", it is
                # simply outside what this join can see.
                passed_curation=outcomes.count("processed"),
                rejected_curation=outcomes.count("rejected"),
                pending_curation=outcomes.count("pending"),
                authors=tuple(tally.authors),
                topics=tuple(tally.topics),
                last_seen=tally.last_seen,
            )
        )
    return rows
