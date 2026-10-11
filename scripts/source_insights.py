#!/usr/bin/env python3
"""
source_insights.py — read the collection-decision journal (ADR 0021 facade).

The journal (`pipeline/.source-insights/events.jsonl`) records one row per
candidate the collector considered and what became of it. This is the stable
CLI over `scripts/source_report/`; the metrics and HTML report land on top of
the same data once enough runs have accumulated.

Read-only by design — it never writes, never fetches, and never changes config.

Numbers here are counts, not verdicts. A source with three rejections is not
"bad": the reason codes say whether it was off-topic, duplicated, or merely
short, and those mean very different things. Judging usefulness needs many runs
of history, which is why the journal is retained longer than other artifacts.

CLI:
    python3 scripts/source_insights.py summary [--json] [--root R]
    python3 scripts/source_insights.py list [--limit N] [--json] [--root R]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.authors.store import roster_identity_keys  # noqa: E402
from scripts.registry import atomic_write_text  # noqa: E402
from scripts.source_report.authors import (  # noqa: E402
    author_metrics,
    monitoring_suggestions,
)
from scripts.source_report.events import journal_path, read_decisions  # noqa: E402
from scripts.source_report.metrics import source_metrics  # noqa: E402
from scripts.source_report.render import render_source_report  # noqa: E402

_LIST_LIMIT_DEFAULT = 20

# Below this many observations a per-source breakdown says more about when we
# started collecting than about the source. Stated in the output rather than
# silently rendering a confident-looking table.
MIN_OBSERVATIONS = 5


def _followed_keys(root: Path) -> set[str]:
    """Identity keys of everyone already in the roster (`config/authors.yaml`).

    Passed to `monitoring_suggestions` so the report never proposes following
    someone the user already follows. A thin alias over the shared
    `roster_identity_keys` accessor so this filter, and the author-node
    cross-reference, read the roster through ONE ladder and cannot drift.
    """
    return roster_identity_keys(root)


@dataclass(frozen=True)
class SourceSummary:
    """What the journal knows about one source."""

    source_url: str
    considered: int
    by_decision: dict[str, int]
    # False when there is too little history to read anything into the numbers.
    confident: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "source_url": self.source_url,
            "considered": self.considered,
            "by_decision": self.by_decision,
            "confident": self.confident,
        }


@dataclass(frozen=True)
class JournalSummary:
    """The whole journal, grouped by source."""

    total: int
    runs: int
    sources: list[SourceSummary]

    def to_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "runs": self.runs,
            "sources": [s.to_dict() for s in self.sources],
        }


def summarize(root: Path) -> JournalSummary:
    """Per-source decision counts plus the totals."""
    entries = read_decisions(root)
    per_source: dict[str, Counter[str]] = {}
    for entry in entries:
        source = str(entry.get("source_url", ""))
        per_source.setdefault(source, Counter())[str(entry.get("decision", ""))] += 1

    return JournalSummary(
        total=len(entries),
        runs=len({str(e.get("run_id", "")) for e in entries if e.get("run_id")}),
        sources=[
            SourceSummary(
                source_url=source,
                considered=sum(counts.values()),
                by_decision=dict(sorted(counts.items())),
                confident=sum(counts.values()) >= MIN_OBSERVATIONS,
            )
            for source, counts in sorted(per_source.items())
        ],
    )


def _render_summary(data: JournalSummary) -> str:
    if not data.total:
        return (
            "No collection decisions recorded yet.\n"
            "The journal fills up as `python3 scripts/collect.py` runs "
            "(a dry run deliberately records nothing)."
        )
    lines = [f"{data.total} decision(s) across {data.runs} run(s)", ""]
    for source in data.sources:
        breakdown = ", ".join(f"{name} {count}" for name, count in source.by_decision.items())
        note = "" if source.confident else "  (too few observations to read into)"
        lines.append(
            f"{source.source_url}\n  {source.considered} considered: {breakdown}{note}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PROJECT_ROOT), help="project root")
    sub = parser.add_subparsers(dest="command", required=True)

    summary = sub.add_parser("summary", help="per-source decision counts")
    summary.add_argument("--json", action="store_true", help="machine-readable output")

    listing = sub.add_parser("list", help="recent decisions, newest first")
    listing.add_argument("--limit", type=int, default=_LIST_LIMIT_DEFAULT)
    listing.add_argument("--json", action="store_true", help="machine-readable output")

    report = sub.add_parser("report", help="write the standalone HTML page")
    report.add_argument("--out", help="output path (default: pipeline/3-synthesis/…)")
    report.add_argument("--today", default="", help="ISO date for the title")
    report.add_argument("--registry", default="", help="registry path override")

    args = parser.parse_args(argv)
    root = Path(args.root)

    if args.command == "report":
        registry = Path(args.registry) if args.registry else root / "pipeline" / "registry.md"
        # The date is an input, never read from the clock inside the renderer, so
        # the page stays deterministic and diffable.
        today = args.today or date.today().isoformat()
        out = (
            Path(args.out)
            if args.out
            else root / "pipeline" / "3-synthesis" / f"source-insights_{today}.report.html"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        people = author_metrics(root, registry)
        atomic_write_text(
            out,
            render_source_report(
                source_metrics(root, registry),
                generated_for=today,
                authors=people,
                suggestions=monitoring_suggestions(people, followed=_followed_keys(root)),
            ),
        )
        print(f"wrote {out}")
        return 0

    if args.command == "summary":
        data = summarize(root)
        print(json.dumps(data.to_dict(), indent=2) if args.json else _render_summary(data))
        return 0

    entries = list(reversed(read_decisions(root)))[: max(args.limit, 0)]
    if args.json:
        print(json.dumps(entries, indent=2))
        return 0
    if not entries:
        print(f"No decisions recorded yet ({journal_path(root)} is absent or empty).")
        return 0
    for entry in entries:
        # Rows come from a file other processes append to, so the shape is checked
        # rather than assumed — a hand-edited entry must not crash the reader.
        raw_reasons = entry.get("reason_codes")
        reasons = ", ".join(str(r) for r in raw_reasons) if isinstance(raw_reasons, list) else ""
        suffix = f" ({reasons})" if reasons else ""
        print(f"{entry.get('ts', '?')}  {entry.get('decision', '?')}{suffix}  "
              f"{entry.get('candidate_url', '?')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
