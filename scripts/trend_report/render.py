"""Markdown rendering for the deterministic weekly trends report."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from scripts.digest import strings as _strings
from scripts.trend_report.model import (
    PERIOD_DAYS,
    ActivitySummary,
    ConceptGrowth,
    TagTrend,
    TopicTrend,
    fading_topics,
    new_topics,
)


def _arrow(delta: int) -> str:
    """A trend arrow for a delta: ↑ up, ↓ down, → flat."""
    return "↑" if delta > 0 else "↓" if delta < 0 else "→"


def _signed(delta: int) -> str:
    """A signed delta string, e.g. '+3' / '-1' / '±0'."""
    return "±0" if delta == 0 else f"{delta:+d}"


# ▁ is reserved for zero; nonzero counts scale over the remaining 7 blocks.
_SPARK_BLOCKS = "▁▂▃▄▅▆▇█"


def _sparkline(counts: Sequence[int]) -> str:
    """One-line text sparkline of the series, peak-scaled (▁ = zero weeks)."""
    peak = max(counts)
    return "".join(
        _SPARK_BLOCKS[0] if c <= 0 else _SPARK_BLOCKS[-(-c * 7 // peak)]
        for c in counts
    )


def render_trends(
    topics: Sequence[TopicTrend],
    activity: ActivitySummary,
    growth: ConceptGrowth,
    tags: Sequence[TagTrend],
    linked: Sequence[tuple[str, int]],
    *,
    today: date,
    level: int = 1,
    series: Sequence[int] | None = None,
    language: str = "en",
) -> str:
    """Render the four trend signals to the trends markdown report.

    `level` sets the top heading depth: 1 (default) for the standalone report
    (`# Trends` + `## sections`), 2 to embed inside the weekly digest under a
    single H1 (`## Trends` + `### sections`), so the digest keeps one document
    title. Subsection headings are always one level below the title.
    """
    h_title = "#" * level  # the Trends title itself
    h_sec = "#" * (level + 1)  # each signal's subsection
    _t = lambda key, **fmt: _strings.tr(language, key, **fmt)  # noqa: E731
    out: list[str] = [
        f"{h_title} " + _t("trends_title", date=today.isoformat()), ""
    ]
    out.append(_t("trends_intro", days=PERIOD_DAYS))
    out.append("")

    # (a) Topic volume.
    out.append(f"{h_sec} " + _t("trends_volume_header"))
    out.append("")
    active = [t for t in topics if t.current > 0]
    if active:
        for topic in active:
            out.append(
                "- " + _t(
                    "trends_volume_line", topic=topic.topic, current=topic.current,
                    arrow=_arrow(topic.delta), delta=_signed(topic.delta),
                )
            )
    else:
        out.append(_t("trends_no_sources"))
    fresh, fading = new_topics(topics), fading_topics(topics)
    if fresh:
        out.append("- " + _t("trends_new_topics", topics=", ".join(fresh)))
    if fading:
        out.append("- " + _t("trends_fading_topics", topics=", ".join(fading)))
    out.append("")

    # (b) Rising tags.
    rising = [t for t in tags if t.delta > 0]
    if rising:
        out.append(f"{h_sec} " + _t("trends_tags_header"))
        out.append("")
        for tag in rising:
            out.append(
                "- " + _t(
                    "trends_tag_line", tag=tag.tag, current=tag.current,
                    arrow=_arrow(tag.delta), delta=_signed(tag.delta),
                )
            )
        out.append("")

    # (c) Activity.
    out.append(f"{h_sec} " + _t("trends_activity_header"))
    out.append("")
    out.append(
        "- " + _t(
            "trends_inflow_line", current=activity.inflow_current,
            arrow=_arrow(activity.inflow_delta), delta=_signed(activity.inflow_delta),
        )
    )
    out.append("- " + _t("trends_backlog_line", backlog=activity.backlog))
    out.append("")

    # (d) Knowledge growth.
    out.append(f"{h_sec} " + _t("trends_growth_header"))
    out.append("")
    out.append(
        "- " + _t(
            "trends_created_line", current=growth.created_current,
            arrow=_arrow(growth.created_delta), delta=_signed(growth.created_delta),
        )
    )
    # Longitudinal sparkline — the compounding story the this-vs-prior deltas
    # can't show. Omitted while all-zero (cold start) to avoid a flat-noise line.
    if series and any(series):
        out.append(
            "- " + _t(
                "trends_sparkline_line", weeks=len(series), spark=_sparkline(series),
                first=series[0], last=series[-1],
            )
        )
    out.append("- " + _t("trends_updated_line", count=growth.updated_current))
    if linked:
        pretty = ", ".join(f"{name} ({degree})" for name, degree in linked)
        out.append("- " + _t("trends_connected_line", pretty=pretty))
    out.append("")

    return "\n".join(out).rstrip() + "\n"

