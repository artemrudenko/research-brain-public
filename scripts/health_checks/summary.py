"""Roll health signals into the public health summary."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from scripts.brain_status import monitored_sources
from scripts.build_digest import latest_brain_health
from scripts.health_checks import artifacts, events, signals
from scripts.health_checks.model import HealthSummary, classify

# A digest older than this many days is treated as stale (weekly cadence + slack).
STALE_DIGEST_DAYS = 8
# A built, non-quiet digest with delivery enabled must reach a channel within
# this many days — after that, "built but never delivered" is a failure. Small
# on purpose: the send runs minutes after the build; the slack covers a manual
# build the user reviews before sending.
UNDELIVERED_DIGEST_DAYS = 2
# A configured system that has run before but hasn't recorded a `run` event within
# this many days is "overdue" — the expected weekly run silently didn't happen.
EXPECTED_RUN_DAYS = STALE_DIGEST_DAYS
# A monitored feed/topic whose newest registry collection is older than this many
# days is treated as quiet. It is informational, not a failure verdict.
STALE_FEED_DAYS = STALE_DIGEST_DAYS


def health_summary(root: Path, *, today: date | None = None) -> HealthSummary:
    """Roll the event log + on-disk artifacts into one health verdict."""
    today = today or datetime.now(UTC).date()
    loaded_events = events.load_events(root)

    feeds = signals.feed_health(loaded_events)
    dead = [feed for feed in feeds if not feed.healthy]
    delivery = signals.delivery_health(loaded_events)
    age = artifacts.last_digest_age_days(root, today=today)
    stale = age is not None and age > STALE_DIGEST_DAYS
    failed_run = signals.last_run_failed(loaded_events)
    gate_skipped = signals.gate_skipped_topics(
        loaded_events, today=today, window=STALE_DIGEST_DAYS
    )
    stale_feed_topics = artifacts.stale_feeds(
        root, today=today, window=STALE_FEED_DAYS
    )

    run_age = signals.last_run_age_days(
        loaded_events, today=today, expected_run_days=EXPECTED_RUN_DAYS
    )
    run_overdue = run_age is not None and run_age > EXPECTED_RUN_DAYS
    delivery_failed = any(
        status in signals.FAILURE_STATUSES for status in delivery.values()
    )
    undelivered = artifacts.undelivered_digest(
        root, today=today, window=UNDELIVERED_DIGEST_DAYS
    )
    configured = bool(monitored_sources(root=root)) or bool(feeds)

    return HealthSummary(
        status=classify(
            configured=configured,
            has_digest=age is not None,
            has_activity=bool(delivery) or failed_run,
            has_failure=(
                bool(dead)
                or delivery_failed
                or stale
                or failed_run
                or run_overdue
                or bool(gate_skipped)
                or bool(undelivered)
            ),
        ),
        last_event_ts=loaded_events[-1].get("ts") if loaded_events else None,
        last_event_kind=loaded_events[-1].get("kind") if loaded_events else None,
        last_digest_age_days=age,
        digest_stale=stale,
        delivery=delivery,
        dead_feeds=dead,
        live_feed_count=len(feeds) - len(dead),
        failed_run=failed_run,
        run_overdue=run_overdue,
        gate_skipped=gate_skipped,
        stale_feeds=stale_feed_topics,
        brain_health=latest_brain_health(root / "pipeline" / "3-synthesis"),
        undelivered_digest=undelivered,
    )


__all__ = [
    "EXPECTED_RUN_DAYS",
    "UNDELIVERED_DIGEST_DAYS",
    "STALE_DIGEST_DAYS",
    "STALE_FEED_DAYS",
    "health_summary",
]
