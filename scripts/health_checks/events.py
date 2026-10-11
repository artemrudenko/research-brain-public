"""Append-only health event log storage."""

from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path

from scripts.registry import advisory_lock
from scripts.state import state_root

HEALTH_DIRNAME = ".health"
EVENTS_FILENAME = "events.jsonl"


def events_lock(path: Path) -> AbstractContextManager[None]:
    """Cross-process lock serialising event-log appends and compaction.

    A lone O_APPEND write is safe by itself, but rotation's read-filter-replace
    is not: an append landing between rotation's read and its atomic replace was
    rewritten away from a stale snapshot. Every event-log writer — `record_event`
    here and `rotate_pipeline._compact_events` — must hold this lock.
    """
    return advisory_lock(path.with_name(path.name + ".lock"))


def events_path(root: Path) -> Path:
    """Absolute path to the JSONL event log for a project `root`.

    Default (env unset): the in-repo `pipeline/.health/events.jsonl` under `root`.
    With `RESEARCH_BRAIN_STATE_DIR` set, the log relocates onto that persistent
    volume (via `state_root`) so run history survives a redeploy / state-wipe.
    """
    in_repo = root / "pipeline" / HEALTH_DIRNAME / EVENTS_FILENAME
    return state_root(in_repo, project_root=root)


def record_event(
    root: Path,
    kind: str,
    *,
    status: str = "ok",
    timestamp: str | None = None,
    details: Mapping[str, object] | None = None,
    **kwargs: object,
) -> None:
    """Append one event to the log. Best-effort: never raises."""
    record = {
        "ts": timestamp or datetime.now(UTC).isoformat(timespec="seconds"),
        "kind": kind,
        "status": status,
        **(details or {}),
        **kwargs,
    }
    try:
        path = events_path(Path(root))  # coerce so a bad `root` can't escape below
        path.parent.mkdir(parents=True, exist_ok=True)
        with events_lock(path), path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001 — a logging failure must NEVER break a real run  # nosec B110
        pass


def load_events(root: Path) -> list[dict]:
    """Read every event from the log, skipping blank/corrupt lines. [] if absent."""
    path = events_path(root)
    if not path.exists():
        return []
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


__all__ = [
    "EVENTS_FILENAME",
    "HEALTH_DIRNAME",
    "events_lock",
    "events_path",
    "load_events",
    "record_event",
]
