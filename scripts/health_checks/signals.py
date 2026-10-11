"""Health signals derived from already-loaded run-history events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

# A feed with this many consecutive empty/error collect runs is treated as dead.
DEAD_FEED_THRESHOLD = 2

# Statuses that count as a failure on any event. "skipped-mcp-only" is a
# delivery that reached nobody: a headless run whose every enabled channel is
# MCP-only — expected in agent mode, a standing outage under cron. The MCP
# skill's post-send `record --status sent` overwrites it per channel.
FAILURE_STATUSES = ("failed", "error", "skipped-mcp-only")


@dataclass
class FeedStatus:
    """Liveness of one collection source, derived from its `collect` events."""

    source: str
    last_items: int
    consecutive_failures: int
    healthy: bool


def feed_health(
    events: list[dict], *, threshold: int = DEAD_FEED_THRESHOLD
) -> list[FeedStatus]:
    """Per-source liveness from `collect` events, newest run last."""
    order: list[str] = []
    runs: dict[str, list[dict]] = {}
    for event in events:
        if event.get("kind") != "collect":
            continue
        source = str(event.get("source", "")).strip()
        if not source:
            continue
        if source not in runs:
            runs[source] = []
            order.append(source)
        runs[source].append(event)

    statuses: list[FeedStatus] = []
    for source in order:
        source_runs = runs[source]
        consecutive = 0
        for event in reversed(source_runs):
            if event.get("status") in FAILURE_STATUSES:
                consecutive += 1
            else:
                break
        statuses.append(
            FeedStatus(
                source=source,
                last_items=event_items(source_runs[-1]),
                consecutive_failures=consecutive,
                healthy=consecutive < threshold,
            )
        )
    return statuses


def event_items(event: dict) -> int:
    """Best-effort integer item count from a collect event (0 when absent/bad)."""
    try:
        return int(event.get("items", 0))
    except (TypeError, ValueError):
        return 0


def delivery_health(events: list[dict]) -> dict[str, str]:
    """Latest delivery status per channel (newest event wins)."""
    latest: dict[str, str] = {}
    for event in events:
        if event.get("kind") != "deliver":
            continue
        channel = str(event.get("channel", "")).strip()
        if channel:
            latest[channel] = str(event.get("status", "unknown"))
    return latest


def last_run_failed(events: list[dict]) -> bool:
    """True when the most recent `run` event ended in a failure status."""
    latest: dict | None = None
    for event in events:
        if event.get("kind") == "run":
            latest = event
    return latest is not None and latest.get("status") in FAILURE_STATUSES


def gate_skipped_topics(events: list[dict], *, today: date, window: int) -> list[str]:
    """Topics the sanitize/synthesis gate skipped, from recent degraded hygiene events."""
    topics: list[str] = []
    for event in events:
        if event.get("kind") != "hygiene" or event.get("status") != "degraded":
            continue
        try:
            parsed = datetime.fromisoformat(str(event.get("ts", ""))).date()
        except ValueError:
            continue
        if not (0 <= (today - parsed).days <= window):
            continue
        topic = str(event.get("note", "")).strip() or "(unnamed)"
        if topic not in topics:
            topics.append(topic)
    return topics


def last_run_age_days(
    events: list[dict], *, today: date, expected_run_days: int
) -> int | None:
    """Days since the newest valid `run` event's date, or None when none was recorded."""
    latest: date | None = None
    saw_run = False
    for event in events:
        if event.get("kind") != "run":
            continue
        saw_run = True
        ts = str(event.get("ts", ""))
        try:
            parsed = datetime.fromisoformat(ts).date()
        except ValueError:
            continue
        if parsed > today:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    if latest is not None:
        return (today - latest).days
    return expected_run_days + 1 if saw_run else None


__all__ = [
    "DEAD_FEED_THRESHOLD",
    "FAILURE_STATUSES",
    "FeedStatus",
    "delivery_health",
    "event_items",
    "feed_health",
    "gate_skipped_topics",
    "last_run_age_days",
    "last_run_failed",
]
