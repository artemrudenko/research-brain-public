#!/usr/bin/env python3
"""
health.py — transparent operational health + run history for research-brain.

Two jobs, one append-only event log:
  1. **Observability** — a single rolled-up "is the system healthy?" verdict:
     are feeds still alive, did delivery succeed, when was the last digest, what
     does the latest brain-hygiene report say.
  2. **Traceability** — a lightweight per-run history of collection / search /
     delivery sessions, so "why was last week's digest empty?" has an answer.

The store is a gitignored JSONL event log under `pipeline/.health/events.jsonl`
(runtime state, never shipped — like the delivery receipts). It is written from
BOTH execution modes: the headless scripts (`deliver.py`) and the agent skills
(`collect-base`, `digest-deliver`, `weekly-run`) via the `record` CLI below.

This is deliberately NOT the `remember` plugin: that tracks developer sessions
across context resets; this tracks the PRODUCT's own runs. Keeping them separate
stops "the developer edited code" and "the weekly job ran" from polluting each
other.

Design: stdlib only, best-effort (recording never raises — a logging failure must
never break a real run), append-only, tolerant of a missing/partly-corrupt log.

CLI:
    python3 scripts/health.py                      # print the health report
    python3 scripts/health.py report               # same
    python3 scripts/health.py record --kind collect --source URL --items 3
    python3 scripts/health.py record --kind deliver --channel telegram --status sent
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Make `scripts` importable when run directly (`python3 scripts/health.py`).
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.health_checks import (  # noqa: E402
    artifacts,
    rendering,
)
from scripts.health_checks import (  # noqa: E402
    cli as health_cli,
)
from scripts.health_checks import (  # noqa: E402
    events as event_log,
)
from scripts.health_checks import (  # noqa: E402
    signals as event_signals,
)
from scripts.health_checks import (  # noqa: E402
    summary as health_rollup,
)
from scripts.health_checks.model import HealthSummary, Status, classify  # noqa: E402

# Where the event log lives (relative to the project root). Gitignored.
# Re-exported from scripts.health_checks.events for CLI/import compatibility.
HEALTH_DIRNAME = event_log.HEALTH_DIRNAME
EVENTS_FILENAME = event_log.EVENTS_FILENAME
events_path = event_log.events_path
record_event = event_log.record_event
load_events = event_log.load_events

# A feed with this many consecutive empty/error collect runs is treated as dead.
DEAD_FEED_THRESHOLD = event_signals.DEAD_FEED_THRESHOLD
# A digest older than this many days is treated as stale (weekly cadence + slack).
STALE_DIGEST_DAYS = health_rollup.STALE_DIGEST_DAYS
# A configured system that has run before but hasn't recorded a `run` event within
# this many days is "overdue" — the expected weekly run silently didn't happen.
# Kept equal to STALE_DIGEST_DAYS so both staleness axes share one weekly+slack window.
EXPECTED_RUN_DAYS = health_rollup.EXPECTED_RUN_DAYS
# A monitored feed/topic whose newest registry collection is older than this many
# days is treated as a dead feed. Read from `pipeline/registry.md`, NOT from collect
# events, so it works on the pure-headless cron path (collection writes the registry
# regardless of agent vs headless). Shares the weekly+slack window with the axes above.
STALE_FEED_DAYS = health_rollup.STALE_FEED_DAYS

# Statuses that count as a failure on any event (mirrors feed_health's verb set).
FAILURE_STATUSES = event_signals.FAILURE_STATUSES


# Re-exported for import compatibility with older callers/tests.
_STATUS_BANNER = rendering.STATUS_BANNER


# --------------------------------------------------------------------------- #
# Derived health signals
# --------------------------------------------------------------------------- #


FeedStatus = event_signals.FeedStatus


def feed_health(
    events: list[dict], *, threshold: int = DEAD_FEED_THRESHOLD
) -> list[FeedStatus]:
    """Per-source liveness from `collect` events, newest run last."""
    return event_signals.feed_health(events, threshold=threshold)


def _event_items(event: dict) -> int:
    """Best-effort integer item count from a collect event (0 when absent/bad)."""
    return event_signals.event_items(event)


def delivery_health(events: list[dict]) -> dict[str, str]:
    """Latest delivery status per channel (newest event wins)."""
    return event_signals.delivery_health(events)


def last_run_failed(events: list[dict]) -> bool:
    """True when the most recent `run` event ended in a failure status."""
    return event_signals.last_run_failed(events)


def gate_skipped_topics(
    events: list[dict], *, today: date, window: int = STALE_DIGEST_DAYS
) -> list[str]:
    """Topics the sanitize/synthesis gate skipped, from RECENT `degraded` hygiene events.

    A `hygiene` event with status `degraded` records that a topic was dropped by
    the gate (a silently-degraded signal). The topic name is carried in the event
    `note`. Returns the distinct topics in first-seen order; an unnamed event still
    counts (rendered as a generic "(unnamed)" so the DEGRADED verdict isn't lost).

    Bounded to a one-sided `window`-day recency band — today-or-recent only, never
    the future (shared window with the other staleness axes) — so a one-time
    gate-skip ages out once the topic is fixed and re-synthesized; otherwise a
    single event would pin the verdict to DEGRADED forever and the push-alert would
    cry wolf on every run. A future-dated event (clock skew / CI) is excluded
    immediately, matching the future-date guards on the run/digest axes. An event
    with a missing or unparseable `ts` is treated as NOT recent (excluded), so an
    ancient or ts-less skip also ages out.
    """
    return event_signals.gate_skipped_topics(events, today=today, window=window)


def _last_run_age_days(events: list[dict], *, today: date) -> int | None:
    """Days since the newest VALID `run` event's date, or None when none was recorded.

    None means "no run cadence established yet" — the caller must treat that as
    not-overdue (a never-run system can't be late on a run it never started).

    A `run` event whose date is future-dated (clock skew / CI) is NOT a valid run:
    it is ignored, so it can't become `latest` and permanently suppress run_overdue
    (which would mask a real DEGRADED). But its presence still proves the cadence
    was established — so if `run` events exist yet none has a valid (non-future,
    parseable) date, the system has no valid recent run and is reported overdue (a
    just-over-window age) rather than None (which would falsely read "never ran").
    """
    return event_signals.last_run_age_days(
        events, today=today, expected_run_days=EXPECTED_RUN_DAYS
    )


def _registry_last_collected(root: Path) -> dict[str, date]:
    """Map `category` -> its newest `collected` date from `pipeline/registry.md`.

    The registry table is `collected | category | status | url | title` (see
    CONVENTIONS §9). Each collection appends one row, so the freshest `collected`
    date per category is that topic's last-successful-collection timestamp —
    written on BOTH the agent and headless paths, unlike the `collect` event log.

    Rows that are blank/commented/header, or whose `collected` cell is unparseable
    (an older registry format), are skipped — so an old-format registry degrades
    to "no usable dates" (an empty map) rather than crashing or false-alarming.

    Row extraction (and the table schema) lives in `scripts.registry`; here we
    only interpret the `collected`/`category` columns.
    """
    return artifacts.registry_last_collected(root)


def stale_feeds(root: Path, *, today: date, window: int = STALE_FEED_DAYS) -> list[str]:
    """Monitored categories whose newest registry collection is older than `window`.

    This is an **informational** signal (publish frequency), NOT a failure verdict:
    a registry row only appears when NEW content is collected, so a quiet category
    can't be distinguished from a slow-but-healthy feed — `health_summary` therefore
    surfaces these as a note and does NOT let them drive DEGRADED. It is the
    headless-independent counterpart to `feed_health` (which reads `collect` events,
    written only on the agent path). A category is reported ONLY when it is both
    monitored AND was actually being collected (≥1 dated registry row) and has since
    gone quiet — so a never-collected category (no row, or an unparseable old-format
    row) is treated as "unknown" and never reported on a fresh/unconfigured vault.

    Returns the quiet categories in monitored (sources.yaml) order.
    """
    return artifacts.stale_feeds(root, today=today, window=window)


def _last_digest_age_days(root: Path, *, today: date) -> int | None:
    """Days since the newest `digest_YYYY-MM-DD.md`, or None when none exist."""
    return artifacts.last_digest_age_days(root, today=today)


# --------------------------------------------------------------------------- #
# Roll-up summary
# --------------------------------------------------------------------------- #


def health_summary(root: Path, *, today: date | None = None) -> HealthSummary:
    """Roll the event log + on-disk artifacts into one health verdict."""
    return health_rollup.health_summary(root, today=today)


def _classify(
    *, configured: bool, has_digest: bool, has_activity: bool, has_failure: bool
) -> Status:
    """Map the raw signals to one of the four states, in strict precedence.

    Precedence (first match wins):
      1. UNCONFIGURED — no sources at all (a fresh repo wins over everything).
      2. DEGRADED     — configured, but an active failure signal is present.
      3. UNKNOWN      — configured, but nothing has run yet (no digest, no
                        delivery/run activity), so we can't claim health.
      4. OK           — configured, produced a digest, no failures.

    `configured` is "is a real source set up?" (≥1 non-EXAMPLE source row in
    config/sources.yaml, with seen collect events as a fallback); `has_digest` /
    `has_activity` are the "did it actually function?" evidence.
    """
    return classify(
        configured=configured,
        has_digest=has_digest,
        has_activity=has_activity,
        has_failure=has_failure,
    )


def render(summary: HealthSummary) -> str:
    """A plain-language, marker-prefixed health report (for brain-ask / CLI)."""
    return rendering.render(summary, stale_feed_days=STALE_FEED_DAYS)


def ops_headline(summary: HealthSummary) -> str | None:
    """One plain-language line naming why the system is DEGRADED; None otherwise.

    The digest is the one artifact an operator reliably reads, so a degraded
    system must say so THERE — not only when someone asks `status`. Kept to a
    single newline-free line so the digest renders it next to the brain-health
    line without reflowing.
    """
    return rendering.ops_headline(summary)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    """CLI: `report` (default) prints the health summary; `record` appends an event."""
    return health_cli.main(argv, project_root=_PROJECT_ROOT)


if __name__ == "__main__":
    sys.exit(main())
