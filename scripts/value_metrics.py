#!/usr/bin/env python3
"""
value_metrics.py — read-only value evidence from the durable artifacts.

The activation half of "is this worth running?" lives in `setup_check.py`;
this is the RECURRING-value half (product-audit item 11), computed locally
from what the pipeline already persists — no counters of its own, no writes:

  retention  — of the last N ISO weeks (default 4), how many saw at least one
               delivery receipt (any channel) under `pipeline/3-synthesis/.delivered/`
  yield      — collected → processed conversion from `pipeline/registry.md`
               (the `status` column), overall and per topic
  reuse      — created / updated / reused from the newest synthesis run log
               (`scripts.digest.scan.latest_value_evidence`)
  feedback   — reader-signal counts by kind from `pipeline/.feedback/feedback.jsonl`
               within the same window

**Cost per digest is deliberately NOT computed** — the headless runtime has no
token/price meter, so the honest number is the manual pilot-evidence field
(docs/PILOT.md). The report says so instead of guessing.

Receipts and the feedback log relocate with RESEARCH_BRAIN_STATE_DIR
(scripts/state.py); this reader follows them.

CLI:
    python3 scripts/value_metrics.py report [--json] [--root R] [--today D] [--weeks N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.delivery.paths import receipt_dir  # noqa: E402
from scripts.digest.scan import latest_value_evidence  # noqa: E402
from scripts.feedback import feedback_log_path  # noqa: E402
from scripts.registry import iter_registry_rows  # noqa: E402
from scripts.state import state_root  # noqa: E402

# digest_2026-06-15.json / digest_2026-06-15.telegram.json → the delivery date.
_RECEIPT_DATE_RE = re.compile(r"digest_(\d{4}-\d{2}-\d{2})")

DEFAULT_RETENTION_WEEKS = 4
DEFAULT_FEEDBACK_DAYS = 28
COST_PER_DIGEST = "manual (docs/PILOT.md)"


def retention(
    root: Path, *, today: date, weeks: int = DEFAULT_RETENTION_WEEKS
) -> tuple[int, int]:
    """(ISO weeks with ≥1 delivery receipt, window size) over the last `weeks`.

    Multiple receipts in one week (several channels, MCP sidecars) count once —
    retention asks "did a digest reach the reader that week?", not "how many
    sends happened".
    """
    # Same resolver the delivery runtime uses, so receipts relocated via
    # RESEARCH_BRAIN_STATE_DIR are counted from their real home.
    directory = receipt_dir(root, state_root=lambda p: state_root(p, project_root=root))
    if not directory.is_dir():
        return 0, weeks
    window_start = today - timedelta(weeks=weeks)
    seen: set[tuple[int, int]] = set()
    for path in directory.glob("*.json"):
        m = _RECEIPT_DATE_RE.search(path.name)
        if m is None:
            continue
        try:
            delivered = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if window_start < delivered <= today:
            iso = delivered.isocalendar()
            seen.add((iso.year, iso.week))
    return len(seen), weeks


@dataclass(frozen=True)
class SourceYield:
    """Collected → processed conversion, from the registry `status` column."""

    total: int = 0
    processed: int = 0
    rejected: int = 0
    pending: int = 0  # blank status: collected but not yet judged
    per_category: dict[str, tuple[int, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "processed": self.processed,
            "rejected": self.rejected,
            "pending": self.pending,
            "per_category": {
                cat: {"processed": p, "total": t}
                for cat, (p, t) in sorted(self.per_category.items())
            },
        }


def classify_status(raw: str) -> str:
    """Normalise a registry `status` cell to `processed` / `rejected` / `pending`.

    ONE definition, shared with the per-source report (`source_report/metrics.py`).
    Two reports disagreeing about the same registry — because one of them folded
    case differently, or treated a blank cell as rejected — would be worse than
    having only one report, so the rule lives here and is imported, not copied.
    """
    status = raw.strip().lower()
    if status in ("processed", "rejected"):
        return status
    return "pending"


def source_yield(registry_path: Path) -> SourceYield:
    """Tally registry rows by status; a missing registry is an empty yield."""
    if not registry_path.exists():
        return SourceYield()
    total = processed = rejected = pending = 0
    per: dict[str, list[int]] = {}
    for row in iter_registry_rows(registry_path):
        total += 1
        cat = per.setdefault(row.category, [0, 0])
        cat[1] += 1
        status = classify_status(row.status)
        if status == "processed":
            processed += 1
            cat[0] += 1
        elif status == "rejected":
            rejected += 1
        else:
            pending += 1
    return SourceYield(
        total, processed, rejected, pending,
        {cat: (p, t) for cat, (p, t) in per.items()},
    )


def feedback_counts(
    root: Path, *, today: date, days: int = DEFAULT_FEEDBACK_DAYS
) -> dict[str, int]:
    """Feedback events by kind within the window; corrupt lines are skipped."""
    log = feedback_log_path(root)
    if not log.exists():
        return {}
    cutoff = datetime.combine(today, datetime.max.time(), tzinfo=UTC) - timedelta(days=days)
    counts: dict[str, int] = {}
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            ts = datetime.fromisoformat(str(entry["ts"]))
            kind = str(entry["kind"])
        except (ValueError, KeyError, TypeError):
            continue  # an unreadable line must never kill the report
        if ts >= cutoff:
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def build_report(
    root: Path, *, today: date, weeks: int = DEFAULT_RETENTION_WEEKS
) -> dict[str, object]:
    """The machine-readable report every renderer keys on."""
    hit, window = retention(root, today=today, weeks=weeks)
    created, updated, reused = latest_value_evidence(
        root / "pipeline" / "3-synthesis", today=today
    )
    return {
        "retention": {"weeks_with_delivery": hit, "window_weeks": window},
        "yield": source_yield(root / "pipeline" / "registry.md").to_dict(),
        "reuse": {"created": created, "updated": updated, "reused": reused},
        "feedback": feedback_counts(root, today=today),
        "cost_per_digest": COST_PER_DIGEST,
    }


def render_human(report: dict[str, object]) -> str:
    # build_report's shape is fixed above; cast (no runtime effect) instead of
    # assert, which bandit rightly flags in runtime code (stripped under -O).
    ret = cast(dict[str, object], report["retention"])
    yld = cast(dict[str, object], report["yield"])
    reuse = cast(dict[str, object], report["reuse"])
    feedback = cast(dict[str, int], report["feedback"])
    fb = (
        ", ".join(f"{kind}: {n}" for kind, n in sorted(feedback.items()))
        if feedback
        else "none recorded"
    )
    return "\n".join([
        "Value evidence (read-only, from durable artifacts)",
        f"Retention: delivered in {ret['weeks_with_delivery']} of last "
        f"{ret['window_weeks']} weeks",
        f"Yield: {yld['processed']}/{yld['total']} processed "
        f"({yld['pending']} pending, {yld['rejected']} rejected)",
        f"Reuse (latest synthesis): created: {reuse['created']}, "
        f"updated: {reuse['updated']}, reused: {reuse['reused']}",
        f"Feedback (last {DEFAULT_FEEDBACK_DAYS}d): {fb}",
        f"Cost per digest: {COST_PER_DIGEST}",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="value_metrics.py",
        description="Read-only recurring-value report from durable artifacts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report", help="print the value-evidence report")
    report.add_argument("--root", default=str(PROJECT_ROOT), help="project root to read")
    report.add_argument("--today", default=None, help="override 'today' (YYYY-MM-DD, tests)")
    report.add_argument("--weeks", type=int, default=DEFAULT_RETENTION_WEEKS)
    report.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    today = date.fromisoformat(args.today) if args.today else datetime.now(UTC).date()
    data = build_report(Path(args.root), today=today, weeks=args.weeks)
    print(json.dumps(data, indent=2, sort_keys=True) if args.json else render_human(data))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
