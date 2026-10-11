#!/usr/bin/env python3
"""
trends.py — deterministic weekly TRENDS report (ADR 0017).

Where the weekly digest answers "what happened this week?", this builder answers
"how is it changing over time?" — from the two local, durable, dated
sources: the collection registry (`pipeline/registry.md`) and the concept notes
(`brain/concepts/*.md`). It is LLM-free, so it runs identically headless or in an
agent.

Windows are rolling 7-day periods anchored on `today` (period 0 = the last 7 days
including today, period 1 = the 7 before that, …), matching the digest's
calendar-day lookback. Four signals (ADR 0017):

  (a) Topic volume — registry rows by `category`, this period vs prior (+ new /
      fading topics).
  (b) Rising tags — concept `tags` (controlled vocabulary) bucketed by the
      concept's `last_updated` period.
  (c) Activity — registry inflow this vs prior, and a blank-status backlog proxy.
  (d) Knowledge growth — concepts created this vs prior period, and the most
      connected concepts by link degree (`related_concept` + inline wikilinks).

Output: `pipeline/3-synthesis/trends_YYYY-MM-DD.md`.
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.registry import atomic_write_text, iter_registry_rows  # noqa: E402
from scripts.trend_report.concepts import load_concept_records  # noqa: E402
from scripts.trend_report.metrics import (  # noqa: E402
    activity_summary,
    concept_growth,
    growth_series,
    period_index,
    tag_trends,
    top_linked,
    topic_trends,
)
from scripts.trend_report.metrics import (  # noqa: E402
    parse_date as _parse_date,
)
from scripts.trend_report.model import (  # noqa: E402
    PERIOD_DAYS,
    ActivitySummary,
    ConceptGrowth,
    ConceptRecord,
    TagTrend,
    TopicTrend,
    fading_topics,
    new_topics,
)
from scripts.trend_report.render import render_trends  # noqa: E402

__all__ = [
    "PERIOD_DAYS",
    "PROJECT_ROOT",
    "ActivitySummary",
    "ConceptGrowth",
    "ConceptRecord",
    "TagTrend",
    "TopicTrend",
    "_parse_date",
    "activity_summary",
    "build_trends",
    "build_trends_section",
    "concept_growth",
    "default_trends_path",
    "fading_topics",
    "growth_series",
    "load_concept_records",
    "main",
    "new_topics",
    "period_index",
    "render_trends",
    "tag_trends",
    "top_linked",
    "topic_trends",
]


# --------------------------------------------------------------------------- #
# Build + CLI
# --------------------------------------------------------------------------- #


def default_trends_path(root: Path, today: date) -> Path:
    """The conventional output path: pipeline/3-synthesis/trends_YYYY-MM-DD.md."""
    return root / "pipeline" / "3-synthesis" / f"trends_{today.isoformat()}.md"


def _render_from_sources(
    root: Path, today: date, *, level: int, language: str = "en"
) -> str:
    """Gather the registry + concept signals and render the trends markdown.

    Shared by the standalone report (`build_trends`, level 1) and the digest-
    embedded section (`build_trends_section`, level 2) so both read the exact
    same data and differ only in heading depth.
    """
    rows = list(iter_registry_rows(root / "pipeline" / "registry.md"))
    records = load_concept_records(root / "brain" / "concepts")
    return render_trends(
        topic_trends(rows, today),
        activity_summary(rows, today),
        concept_growth(records, today),
        tag_trends(records, today),
        top_linked(records),
        today=today,
        level=level,
        series=growth_series(records, today),
        language=language,
    )


def build_trends(out_path: Path, *, root: Path = PROJECT_ROOT, today: date | None = None) -> None:
    """Build the standalone trends report from the registry + concepts, written atomically."""
    if today is None:
        today = datetime.now(UTC).date()
    atomic_write_text(out_path, _render_from_sources(root, today, level=1))


def build_trends_section(
    *, root: Path = PROJECT_ROOT, today: date | None = None, language: str = "en"
) -> str:
    """Render the trends signals as an H2 section for embedding in the weekly digest.

    Returns the markdown to append (never writes a file); the digest build inlines
    it so the weekly digest carries "how it's changing" alongside "what happened".
    """
    if today is None:
        today = datetime.now(UTC).date()
    return _render_from_sources(root, today, level=2, language=language)


def main(argv: list[str] | None = None, *, today: date | None = None) -> int:
    """CLI entry point: `trends.py [out.md]`."""
    parser = argparse.ArgumentParser(
        prog="trends.py",
        description="Deterministically build the weekly trends report (ADR 0017).",
    )
    parser.add_argument(
        "out",
        nargs="?",
        default=None,
        help="Output path (default: pipeline/3-synthesis/trends_YYYY-MM-DD.md).",
    )
    args = parser.parse_args(argv)

    if today is None:
        today = datetime.now(UTC).date()
    out_path = Path(args.out) if args.out else default_trends_path(PROJECT_ROOT, today)
    build_trends(out_path, root=PROJECT_ROOT, today=today)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
