"""Data model for the deterministic weekly trends report."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

# Rolling window length: one "period" is a 7-day span (a week).
PERIOD_DAYS = 7


@dataclass(frozen=True)
class TopicTrend:
    """One topic's collection volume this period vs the prior period."""

    topic: str
    current: int
    prior: int

    @property
    def delta(self) -> int:
        return self.current - self.prior


def new_topics(trends: Sequence[TopicTrend]) -> list[str]:
    """Topics with activity this period but none last (newly appearing)."""
    return sorted(t.topic for t in trends if t.current > 0 and t.prior == 0)


def fading_topics(trends: Sequence[TopicTrend]) -> list[str]:
    """Topics active last period but silent this one (going quiet)."""
    return sorted(t.topic for t in trends if t.current == 0 and t.prior > 0)


@dataclass(frozen=True)
class ActivitySummary:
    """Inflow volume this vs prior period, and an all-time backlog proxy."""

    inflow_current: int
    inflow_prior: int
    backlog: int  # rows with blank status = collected but not yet curated

    @property
    def inflow_delta(self) -> int:
        return self.inflow_current - self.inflow_prior


@dataclass(frozen=True)
class ConceptRecord:
    """One real (non-SEED) concept note, reduced to what trends needs."""

    name: str
    stem: str
    created: date | None
    last_updated: date | None
    tags: list[str] = field(default_factory=list)
    out_targets: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ConceptGrowth:
    """Concept creation this vs prior period, and updates this period."""

    created_current: int
    created_prior: int
    updated_current: int

    @property
    def created_delta(self) -> int:
        return self.created_current - self.created_prior


@dataclass(frozen=True)
class TagTrend:
    """One tag's frequency among concepts updated this vs the prior period."""

    tag: str
    current: int
    prior: int

    @property
    def delta(self) -> int:
        return self.current - self.prior
