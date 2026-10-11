"""Metric builders for the deterministic weekly trends report."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date, datetime

from scripts.registry import RegistryRow
from scripts.trend_report.model import (
    PERIOD_DAYS,
    ActivitySummary,
    ConceptGrowth,
    ConceptRecord,
    TagTrend,
    TopicTrend,
)


def period_index(collected: date, today: date, period_days: int = PERIOD_DAYS) -> int | None:
    """Which rolling period a date falls in: 0 = current week, 1 = prior, ...

    A future date (after `today`) yields None so a bad/forward-dated row is never
    counted; the current period includes `today` and the six days before it.
    """
    days_ago = (today - collected).days
    if days_ago < 0:
        return None
    return days_ago // period_days


def parse_date(value: object) -> date | None:
    """Parse a `YYYY-MM-DD` (date/datetime) value into a date, else None.

    Tolerant of surrounding quotes and a time/zone tail so a malformed stamp is
    simply treated as out of window rather than crashing a scan.
    """
    if value is None:
        return None
    if isinstance(value, date):  # PyYAML may already have parsed it
        return value
    cleaned = str(value).strip().strip("\"'")
    if not cleaned:
        return None
    cleaned = cleaned.split("T")[0].split(" ")[0]
    try:
        return datetime.strptime(cleaned, "%Y-%m-%d").date()
    except ValueError:
        return None


def topic_trends(rows: Iterable[RegistryRow], today: date) -> list[TopicTrend]:
    """Per-topic collected-source counts, current period vs prior, from the registry.

    Sorted by current volume (descending), then topic name -- so the busiest
    topics lead. Only rows whose `collected` date falls in period 0 or 1 count.
    """
    current: Counter[str] = Counter()
    prior: Counter[str] = Counter()
    for row in rows:
        collected = parse_date(row.collected)
        if collected is None:
            continue
        idx = period_index(collected, today)
        if idx == 0:
            current[row.category] += 1
        elif idx == 1:
            prior[row.category] += 1
    topics = set(current) | set(prior)
    trends = [TopicTrend(topic, current[topic], prior[topic]) for topic in topics]
    trends.sort(key=lambda t: (-t.current, t.topic))
    return trends


def activity_summary(rows: Iterable[RegistryRow], today: date) -> ActivitySummary:
    """Total inflow this period vs prior, plus the blank-status backlog count.

    The backlog is a durable local proxy: a registry row keeps a blank
    status until curation flips it to `processed`/`rejected`, so the count of
    blank rows is "collected but not yet curated" across all time.
    """
    current = prior = backlog = 0
    for row in rows:
        if not row.status.strip():
            backlog += 1
        collected = parse_date(row.collected)
        if collected is None:
            continue
        idx = period_index(collected, today)
        if idx == 0:
            current += 1
        elif idx == 1:
            prior += 1
    return ActivitySummary(current, prior, backlog)


def concept_growth(records: Iterable[ConceptRecord], today: date) -> ConceptGrowth:
    """Concepts created this period vs prior, and how many were updated this period."""
    created_current = created_prior = updated_current = 0
    for record in records:
        if record.created is not None:
            idx = period_index(record.created, today)
            if idx == 0:
                created_current += 1
            elif idx == 1:
                created_prior += 1
        if record.last_updated is not None and period_index(record.last_updated, today) == 0:
            updated_current += 1
    return ConceptGrowth(created_current, created_prior, updated_current)


# Sparkline window: two months of weekly periods — long enough to show a
# compounding trend, short enough to stay one glanceable line.
GROWTH_SERIES_WEEKS = 8


def growth_series(
    records: Iterable[ConceptRecord], today: date, *, weeks: int = GROWTH_SERIES_WEEKS
) -> list[int]:
    """Concepts created per rolling 7-day period, oldest → newest.

    Fixed length `weeks` (periods before the vault existed count 0) so the
    sparkline width is stable across runs; the last element is the current
    period. This is the longitudinal view `concept_growth` (this-vs-prior only)
    cannot give — the compounding story over time.
    """
    counts = [0] * weeks
    for record in records:
        if record.created is None:
            continue
        idx = period_index(record.created, today)
        if idx is not None and idx < weeks:
            counts[weeks - 1 - idx] += 1
    return counts


def top_linked(records: Sequence[ConceptRecord], limit: int = 5) -> list[tuple[str, int]]:
    """The most connected concepts by link degree (outbound + inbound).

    Degree = a concept's own outbound links plus how many other concepts point
    back at it (matched by file stem). Ties break on name for a stable ordering.
    """
    inbound: Counter[str] = Counter()
    for record in records:
        for target in record.out_targets:
            inbound[target] += 1
    ranked = [
        (record.name, len(record.out_targets) + inbound[record.stem])
        for record in records
    ]
    ranked.sort(key=lambda pair: (-pair[1], pair[0]))
    return [pair for pair in ranked[:limit] if pair[1] > 0]


def tag_trends(records: Iterable[ConceptRecord], today: date) -> list[TagTrend]:
    """Tag frequency among concepts updated this period vs the prior period.

    Uses concept `tags` (the controlled vocabulary), bucketed by each concept's
    `last_updated` period -- the durable signal for which themes are heating up.
    Sorted by current frequency (descending), then tag.
    """
    current: Counter[str] = Counter()
    prior: Counter[str] = Counter()
    for record in records:
        if record.last_updated is None:
            continue
        idx = period_index(record.last_updated, today)
        bucket = current if idx == 0 else prior if idx == 1 else None
        if bucket is None:
            continue
        for tag in record.tags:
            bucket[tag] += 1
    tags = set(current) | set(prior)
    trends = [TagTrend(tag, current[tag], prior[tag]) for tag in tags]
    trends.sort(key=lambda t: (-t.current, t.tag))
    return trends
