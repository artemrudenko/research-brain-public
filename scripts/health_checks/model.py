"""Shared health verdict model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from scripts.health_checks.signals import FeedStatus


class Status(str, Enum):
    """A 4-state operational-health verdict, in precedence order."""

    OK = "OK"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"
    UNCONFIGURED = "UNCONFIGURED"


@dataclass
class HealthSummary:
    """A single rolled-up view of system health, ready to print."""

    status: Status = Status.UNCONFIGURED
    last_event_ts: str | None = None
    last_event_kind: str | None = None
    last_digest_age_days: int | None = None
    digest_stale: bool = False
    delivery: dict[str, str] = field(default_factory=dict)
    dead_feeds: list[FeedStatus] = field(default_factory=list)
    live_feed_count: int = 0
    failed_run: bool = False
    run_overdue: bool = False
    gate_skipped: list[str] = field(default_factory=list)
    stale_feeds: list[str] = field(default_factory=list)
    brain_health: str | None = None
    # Stem of the newest digest that was BUILT but never reached any enabled
    # channel (no `sent` receipt past the grace window) — the last-mile signal.
    undelivered_digest: str | None = None

    @property
    def ok(self) -> bool:
        """Back-compat green/red flag — True only in the fully-OK state."""
        return self.status is Status.OK


def classify(
    *, configured: bool, has_digest: bool, has_activity: bool, has_failure: bool
) -> Status:
    """Map raw health signals to one of the four states, in strict precedence."""
    if not configured:
        return Status.UNCONFIGURED
    if has_failure:
        return Status.DEGRADED
    if not has_digest and not has_activity:
        return Status.UNKNOWN
    return Status.OK


__all__ = [
    "HealthSummary",
    "Status",
    "classify",
]
