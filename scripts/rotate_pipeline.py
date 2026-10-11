#!/usr/bin/env python3
"""
rotate_pipeline.py — bounded growth for pipeline artifacts. Moves, never deletes.

Without rotation two things grow forever: the dated artifacts in
`pipeline/3-synthesis/` (a digest + brain-health report every week, optional
trends and synthesis-run logs) and the append-only health event log
`pipeline/.health/events.jsonl`. After a year that is hundreds of files every
scan walks and an events file `health.py` re-reads whole.

What it does (all judged by the DATE IN THE FILENAME / event `ts`, never mtime):
  - Top-level `digest_*`, `digest_daily_*`, `brain-health_*`, `trends_*`,
    `synthesis-run_*` files in `pipeline/3-synthesis/` older than `--keep-days`
    (default 90) MOVE to `pipeline/0-archive/3-synthesis/` — still on disk,
    just out of the working set.
  - `events.jsonl` lines whose `ts` is older than the same cutoff are dropped
    (the compaction is the only destructive step, and it is a log); lines that
    do not parse are kept — never guess about data you can't read.

What it NEVER touches: `.delivered/` receipts (delivery idempotency), the
per-topic subdirectories (`{topic}/digest-lead.md`, `.synthesis-meta.json`
freshness sidecars), and any file without a dated name.

Run it as weekly-run's housekeeping step or manually:
    python3 scripts/rotate_pipeline.py [--keep-days 90] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.health_checks.events import (  # noqa: E402 — shared resolver + writer lock
    events_lock,
    events_path,
)
from scripts.registry import atomic_write_text  # noqa: E402 — shared atomic writer
from scripts.source_report.events import (  # noqa: E402 — shared resolver + writer lock
    journal_lock,
    journal_path,
)

DEFAULT_KEEP_DAYS = 90

# The decision journal is kept LONGER than the other artifacts on purpose. Source
# usefulness is judged over many runs — at a weekly cadence, 90 days is ~13 runs,
# which is under the threshold where a quiet source's numbers mean anything. 180
# days roughly doubles that. It is one row per candidate, so the file stays small.
JOURNAL_KEEP_DAYS = 180

# A rotatable artifact: known prefix + a YYYY-MM-DD stamp in the filename.
_DATED = re.compile(
    r"^(?:digest(?:_daily)?_|brain-health_|trends_|synthesis-run_|source-insights_)"
    r"(\d{4}-\d{2}-\d{2})"
)


@dataclass(frozen=True)
class RotateResult:
    moved: int
    events_dropped: int
    journal_dropped: int = 0


def _artifact_date(name: str) -> date | None:
    match = _DATED.match(name)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _rotate_synthesis(
    root: Path, *, cutoff: date, dry_run: bool
) -> int:
    synthesis = root / "pipeline" / "3-synthesis"
    if not synthesis.is_dir():
        return 0
    archive = root / "pipeline" / "0-archive" / "3-synthesis"
    moved = 0
    for path in sorted(synthesis.iterdir()):
        if not path.is_file():
            continue  # topic dirs, .delivered/ — never descended into
        stamp = _artifact_date(path.name)
        if stamp is None or stamp >= cutoff:
            continue
        dest = archive / path.name
        if dest.exists():
            # Same name already archived (e.g. a re-run) — leave the live copy
            # alone rather than overwrite history; the operator can reconcile.
            print(f"skip (already archived): {path.name}")
            continue
        print(f"{'would move' if dry_run else 'moved'}: {path.name}")
        if not dry_run:
            archive.mkdir(parents=True, exist_ok=True)
            path.rename(dest)
            moved += 1
    return moved


def _compact_jsonl(path: Path, *, cutoff: date, dry_run: bool, label: str) -> int:
    """Drop lines older than `cutoff` from an append-only JSONL log.

    Unparseable lines are KEPT, never guessed at — the same rule the health log
    has always used. Callers hold whatever lock the log requires; this function
    only rewrites.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return 0  # unreadable log — rotation must never make things worse
    kept: list[str] = []
    dropped = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            ts = str(json.loads(line).get("ts", ""))
            stamp = datetime.fromisoformat(ts).date()
        except (ValueError, TypeError):
            kept.append(line)  # unparseable — keep, never guess
            continue
        if stamp >= cutoff:
            kept.append(line)
        else:
            dropped += 1
    if dropped and not dry_run:
        atomic_write_text(path, "\n".join(kept) + ("\n" if kept else ""))
    if dropped:
        print(f"{'would drop' if dry_run else 'dropped'} {dropped} old event(s) from {label}")
    return dropped


def _compact_journal(root: Path, *, cutoff: date, dry_run: bool) -> int:
    """Compact the collection-decision journal.

    Held under `journal_lock` across the whole read-filter-replace: standalone
    rotation takes no run lock, so without this a `record_decision` append landing
    after the read would be rewritten away by the replace below (review 2026-07-22).
    Mirrors `_compact_events`; the writer holds the same lock.
    """
    journal = journal_path(root)
    if not journal.is_file():
        return 0
    with journal_lock(journal):
        return _compact_jsonl(
            journal, cutoff=cutoff, dry_run=dry_run, label="events.jsonl (journal)"
        )


def _compact_events(root: Path, *, cutoff: date, dry_run: bool) -> int:
    # Resolve via the shared resolver so rotation compacts the SAME file
    # record_event/load_events use — including the relocated log under
    # RESEARCH_BRAIN_STATE_DIR (otherwise rotation is a silent no-op there).
    events = events_path(root)
    if not events.is_file():
        return 0
    # Hold the shared event-log lock across the whole read-filter-replace:
    # standalone rotation takes no run lock, so without this a record_event
    # append landing after the read was rewritten away by the replace below.
    with events_lock(events):
        return _compact_jsonl(events, cutoff=cutoff, dry_run=dry_run, label="events.jsonl")


def rotate(
    root: Path = _PROJECT_ROOT,
    *,
    today: date | None = None,
    keep_days: int = DEFAULT_KEEP_DAYS,
    dry_run: bool = False,
) -> RotateResult:
    """Archive old dated synthesis artifacts and compact the health event log."""
    today = today or date.today()
    cutoff = today - timedelta(days=keep_days)
    moved = _rotate_synthesis(root, cutoff=cutoff, dry_run=dry_run)
    dropped = _compact_events(root, cutoff=cutoff, dry_run=dry_run)
    journal_dropped = _compact_journal(
        root, cutoff=today - timedelta(days=JOURNAL_KEEP_DAYS), dry_run=dry_run
    )
    return RotateResult(moved=moved, events_dropped=dropped, journal_dropped=journal_dropped)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Archive old pipeline artifacts (move, never delete) and "
        "compact the health event log."
    )
    parser.add_argument("--root", default=str(_PROJECT_ROOT), help="project root")
    parser.add_argument(
        "--keep-days", type=int, default=DEFAULT_KEEP_DAYS,
        help=f"artifacts newer than this stay in place (default {DEFAULT_KEEP_DAYS})",
    )
    parser.add_argument("--today", default=None, help="override today (YYYY-MM-DD, testing)")
    parser.add_argument("--dry-run", action="store_true", help="report only, change nothing")
    args = parser.parse_args(argv)

    if args.keep_days <= 0:
        print("error: --keep-days must be a positive integer", file=sys.stderr)
        return 2
    today = date.fromisoformat(args.today) if args.today else None
    result = rotate(
        Path(args.root), today=today, keep_days=args.keep_days, dry_run=args.dry_run
    )
    print(
        f"rotate: {result.moved} artifact(s) archived, "
        f"{result.events_dropped} old event(s) compacted"
        + (" (dry-run — nothing changed)" if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
