#!/usr/bin/env python3
"""
events.py — the append-only collection-decision journal.

Deliberately the same shape as `scripts/feedback.py`: one JSONL line per event,
one `O_APPEND` write, path resolved through `scripts/state.py` so it relocates
onto a persistent volume with the delivery receipts and the health log. This is
the project's third such log and it reuses that convention rather than inventing
a fourth.

One rule separates it from those: **a journal failure is never the pipeline's
problem.** `record_decision` swallows every OSError and returns False. Losing an
observability row is an acceptable outcome; losing a collected article because
the metrics disk filled up is not. Callers are expected to ignore the result.

Volume is the one real difference from the feedback log. This records EVERY
candidate considered, not the handful a human reacts to — hundreds of rows per
weekly run — so unlike `feedback.jsonl` it is rotated (`rotate_pipeline.py`).
"""
from __future__ import annotations

import json
import os
import sys
import time
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.registry import advisory_lock, try_advisory_lock  # noqa: E402 — shared lock
from scripts.source_report.model import CandidateDecision  # noqa: E402
from scripts.state import state_root  # noqa: E402

# Upper bound (seconds) the WRITER will wait for the journal lock before giving up
# and dropping the row. The lock is only ever held by `rotate_pipeline`'s brief
# compaction, so a small budget absorbs that overlap without ever stalling the
# collect loop behind a stuck holder. Tests monkeypatch / pass 0.0 for determinism.
_WRITER_LOCK_TIMEOUT = 2.0

# ...but the budget is PER CALL, and `record_decision` runs once per candidate, so
# a held lock would cost `_WRITER_LOCK_TIMEOUT × candidates` — ~200 s over a
# 100-candidate collect, spent waiting for rows the failure contract says are
# droppable. After one contention the writer therefore backs off to a pure
# non-blocking attempt for a cooldown, capping the whole run's stall at roughly a
# single budget. Journal rows are observability; collection time is the product.
_CONTENTION_COOLDOWN = 60.0
_contended_until = 0.0


def _reset_lock_contention() -> None:
    """Clear the contention backoff (tests; a fresh process starts clear anyway)."""
    global _contended_until
    _contended_until = 0.0


def journal_path(root: Path) -> Path:
    """The journal path for `root`, honoring `RESEARCH_BRAIN_STATE_DIR`."""
    default = root / "pipeline" / ".source-insights" / "events.jsonl"
    return state_root(default, project_root=root)


def _journal_lock_path(journal: Path) -> Path:
    """The lock file guarding `journal` — one source of truth for writer + compactor."""
    return journal.with_name(journal.name + ".lock")


def journal_lock(path: Path) -> AbstractContextManager[None]:
    """Cross-process lock serialising journal appends and compaction.

    A lone O_APPEND write is safe by itself, but `rotate_pipeline`'s read-filter-
    replace compaction is not: an append landing between its read and its atomic
    replace is rewritten away from a stale snapshot and lost. Both the writer
    (`record_decision`) and the compactor (`rotate_pipeline._compact_journal`)
    must hold this lock — exactly the contract the health event log's
    `events_lock` enforces. (The run lock does NOT cover this: standalone
    `rotate_pipeline.py` never acquires it.)

    The COMPACTOR blocks on this (it must not skip compaction); the WRITER uses a
    bounded try instead (see `record_decision`), plus a contention backoff — the
    bound alone is PER CALL, and the writer runs per candidate, so without the
    backoff a held lock would still tax the whole collect loop.

    NOT reentrant: `advisory_lock` opens a fresh fd each call, so acquiring this
    twice in one thread self-deadlocks. Safe today — `record_decision` (the only
    writer) is never called under a held `journal_lock` — but a future caller that
    records a decision *inside* compaction would hang; keep the two paths disjoint.
    """
    return advisory_lock(_journal_lock_path(path))


def record_decision(
    root: Path, decision: CandidateDecision, *, lock_timeout: float = _WRITER_LOCK_TIMEOUT
) -> bool:
    """Append one decision. Returns False on any failure — never raises, never stalls.

    Called from inside the collection loop, so the failure contract is the whole
    point: a read-only volume, a full disk, OR a compaction holding the journal
    lock must cost a journal row, not an article. The write therefore takes the
    lock with a BOUNDED try (`lock_timeout`): if it cannot be had in time, the row
    is dropped rather than blocking collection behind the lock holder.
    """
    # Stamped at write time, not in the model: the timestamp is a property of the
    # append, and `rotate_pipeline` prunes on exactly this field.
    entry = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), **decision.to_entry()}
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    path = journal_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # A single O_APPEND write is atomic for a line this size, so concurrent
        # writers never interleave. The lock adds the OTHER half of the contract:
        # it serialises against `rotate_pipeline`'s read-filter-replace compaction,
        # which would otherwise drop an append landing mid-rewrite. The writer holds
        # it only briefly and NON-blockingly — losing a row to an in-progress
        # compaction is acceptable; stalling the collect loop is not.
        # Back off to a non-blocking attempt while a recent contention is still
        # cooling down, so one busy compaction cannot tax every candidate.
        global _contended_until
        budget = 0.0 if time.monotonic() < _contended_until else lock_timeout
        with try_advisory_lock(_journal_lock_path(path), timeout=budget) as got:
            if not got:
                if budget:
                    _contended_until = time.monotonic() + _CONTENTION_COOLDOWN
                return False
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)
    except (OSError, ValueError):
        return False
    return True


def read_decisions(root: Path) -> list[dict[str, object]]:
    """Every readable decision, oldest first; unreadable input yields [].

    Malformed lines are skipped rather than fatal: the log is appended to across
    crashes and processes, so a torn final line is an expected state, not a bug
    worth failing a report over.
    """
    path = journal_path(root)
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    entries: list[dict[str, object]] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict) and "decision" in parsed:
            entries.append(parsed)
    return entries
