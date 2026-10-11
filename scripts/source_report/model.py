#!/usr/bin/env python3
"""
model.py — the shape of one collection decision.

The registry records what was collected. Everything the collector *rejected* —
the duplicate, the too-short summary, the cookie wall — has always been thrown
away, which is why "is this source worth keeping?" cannot be answered today: a
feed yielding fifty candidates and one keeper looks exactly like one yielding
two candidates and one keeper.

`decision` is a CLOSED vocabulary because metrics group on it — a typo would
silently open a new bucket that nobody notices. `reason_codes` are deliberately
OPEN (shape-validated only): they explain a decision and will grow as the
collector learns to distinguish cases, and that should not require a schema
change.

Not every code is emitted by every path. The headless RSS collector
(`scripts/collect.py`) can produce `selected`, `duplicate_url`, `too_short`,
`junk_wall`, `unsupported`, `below_topic_cap` and `fetch_failed`. The rest —
`off_topic`, `stale`, `role_balance`, `duplicate_story`, `saved_one_off` —
belong to the agentic `collect-base` path, which ranks a candidate pool and
balances source roles; they are defined here so both paths write one schema.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SCHEMA = "collection_candidate.v1"

DECISIONS = frozenset(
    {
        # Headless collector + agentic path
        "selected",
        "duplicate_url",
        "too_short",
        "junk_wall",
        "unsupported",
        "below_topic_cap",
        "fetch_failed",
        # Agentic `collect-base` only (ranking / role balancing / one-off capture)
        "duplicate_story",
        "off_topic",
        "stale",
        "role_balance",
        "saved_one_off",
    }
)

# Free-text and identifier ceilings. Everything here originates in a remote feed,
# so each field is bounded before it reaches an append-only file nobody prunes
# by hand.
TITLE_CAP = 300
URL_CAP = 2048
NAME_CAP = 200
TOPIC_CAP = 120
REASON_CODE_CAP = 40
MAX_REASON_CODES = 8

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def _flat(value: str, cap: int) -> str:
    """One bounded line — newlines collapsed so one record stays one JSONL line."""
    return " ".join(str(value or "").split())[:cap]


@dataclass(frozen=True)
class CandidateDecision:
    """One candidate the collector considered, and what became of it."""

    topic: str
    source_url: str
    candidate_url: str
    decision: str
    reason_codes: tuple[str, ...] = ()
    title: str = ""
    author_name: str = ""
    author_url: str = ""
    # A stable identifier (`orcid:0000-…`) when the document offered one. Today's
    # RSS path never does — a feed gives a bare name — but the schema carries it
    # so a richer extraction path does not need a migration.
    author_id: str = ""
    role: str = ""
    run_id: str = ""

    def __post_init__(self) -> None:
        if self.decision not in DECISIONS:
            raise ValueError(
                f"unknown decision {self.decision!r} — expected one of "
                f"{', '.join(sorted(DECISIONS))}"
            )
        for code in self.reason_codes:
            if not _SLUG_RE.match(code):
                raise ValueError(
                    f"invalid reason code {code!r} — expected a short slug like "
                    "'high_relevance' (lowercase, digits, -/_)"
                )

    def to_entry(self) -> dict[str, object]:
        """The JSON object written to the journal.

        Empty optionals are omitted rather than written blank: the RSS-lite path
        has no ranking and often no author, and a row full of empty scaffolding
        would misrepresent that as "we looked and found nothing".
        """
        entry: dict[str, object] = {
            "schema": SCHEMA,
            "topic": _flat(self.topic, TOPIC_CAP),
            "source_url": _flat(self.source_url, URL_CAP),
            "candidate_url": _flat(self.candidate_url, URL_CAP),
            "decision": self.decision,
        }
        if self.reason_codes:
            entry["reason_codes"] = list(self.reason_codes[:MAX_REASON_CODES])
        if self.title:
            entry["title"] = _flat(self.title, TITLE_CAP)
        if self.author_name:
            author = {"name": _flat(self.author_name, NAME_CAP)}
            if self.author_url:
                author["url"] = _flat(self.author_url, URL_CAP)
            if self.author_id:
                author["id"] = _flat(self.author_id, URL_CAP)
            entry["author"] = author
        if self.role:
            entry["role"] = _flat(self.role, REASON_CODE_CAP)
        if self.run_id:
            entry["run_id"] = _flat(self.run_id, REASON_CODE_CAP)
        return entry


@dataclass
class JournalStats:
    """Per-source tallies derived from the journal (used by the Stage-5 report)."""

    considered: int = 0
    by_decision: dict[str, int] = field(default_factory=dict)
