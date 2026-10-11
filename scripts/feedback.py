#!/usr/bin/env python3
"""
feedback.py — append-only reader-feedback event log (the durable half of the
digest feedback loop).

The `digest-feedback` skill turns a reader's reaction to a delivered digest
("too technical", "less of <topic>", "mute <source>", 👍/👎) into a concrete
config change via the existing surfaces (the audience knob, `source-manage`
pause). What that conversational half cannot give the product is MEMORY:
whether readers keep saying the same thing, which topics got muted, when the
level was stepped down. This CLI records each feedback event as one JSONL line
so value metrics can count reader signal instead of guessing.

Storage: `pipeline/.feedback/feedback.jsonl` — append-only, one O_APPEND write
per event — relocatable via `RESEARCH_BRAIN_STATE_DIR` exactly like the
delivery receipts and the health event log (see scripts/state.py). No rotation:
feedback arrives at human cadence (a few lines a week), so the log stays tiny.

CLI:
    python3 scripts/feedback.py record --kind too_technical [--target ai-ml] \
        [--note "reader said X"] [--action "technical_level balanced->non-technical"]
    python3 scripts/feedback.py list [--limit N] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.state import state_root  # noqa: E402

# Machine-countable feedback kind: a short slug the skill maps NL phrases onto
# (too_technical / too_simple / mute_topic / mute_source / useful / other, …).
# Open vocabulary on purpose — metrics group by string; only the shape is fixed.
_KIND_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")

# Free-text fields come from chat; cap them so a runaway paste can't bloat the log.
NOTE_CAP = 500
TARGET_CAP = 120
ACTION_CAP = 200

_LIST_LIMIT_DEFAULT = 20


def feedback_log_path(root: Path) -> Path:
    """The JSONL log path for `root`, honoring RESEARCH_BRAIN_STATE_DIR."""
    default = root / "pipeline" / ".feedback" / "feedback.jsonl"
    return state_root(default, project_root=root)


def record(
    root: Path,
    kind: str,
    *,
    target: str = "",
    note: str = "",
    action: str = "",
) -> dict[str, str]:
    """Append one feedback event; returns the entry as written.

    Raises ValueError on a malformed kind (the only field metrics key on).
    """
    if not _KIND_RE.match(kind):
        raise ValueError(
            f"invalid feedback kind {kind!r} — expected a short slug like "
            "'too_technical' or 'mute_topic' (lowercase, digits, -/_)"
        )
    entry = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "kind": kind,
        "target": target[:TARGET_CAP],
        "note": note[:NOTE_CAP],
        "action": action[:ACTION_CAP],
    }
    path = feedback_log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    # A single O_APPEND write is atomic enough for this human-cadence log
    # (same reasoning as the health event log's append side).
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)
    return entry


def list_entries(root: Path, *, limit: int = _LIST_LIMIT_DEFAULT) -> list[dict[str, str]]:
    """Recent feedback entries, newest first; malformed lines are skipped."""
    path = feedback_log_path(root)
    if not path.exists():
        return []
    entries: list[dict[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue  # a torn/hand-mangled line must not break the whole list
        if isinstance(parsed, dict) and "kind" in parsed:
            entries.append({str(k): str(v) for k, v in parsed.items()})
    entries.reverse()
    return entries[: max(limit, 0)]


def _render_line(entry: dict[str, str]) -> str:
    parts = [entry.get("ts", "?"), entry.get("kind", "?")]
    if entry.get("target"):
        parts.append(f"target={entry['target']}")
    if entry.get("action"):
        parts.append(f"action={entry['action']}")
    if entry.get("note"):
        parts.append(f"— {entry['note']}")
    return "  ".join(parts)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feedback.py",
        description="Record / list reader-feedback events (append-only JSONL).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="append one feedback event")
    rec.add_argument("--kind", required=True, help="slug, e.g. too_technical, mute_topic")
    rec.add_argument("--target", default="", help="what it concerns (topic, source, …)")
    rec.add_argument("--note", default="", help="reader's wording, for later reading")
    rec.add_argument("--action", default="", help="what was changed in response, if anything")
    rec.add_argument("--root", default=str(PROJECT_ROOT), help="project root")

    lst = sub.add_parser("list", help="print recent feedback, newest first")
    lst.add_argument("--limit", type=int, default=_LIST_LIMIT_DEFAULT)
    lst.add_argument("--json", action="store_true", help="machine-readable output")
    lst.add_argument("--root", default=str(PROJECT_ROOT), help="project root")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = Path(args.root)

    if args.command == "record":
        try:
            entry = record(
                root, args.kind, target=args.target, note=args.note, action=args.action
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"recorded: {_render_line(entry)}")
        return 0

    entries = list_entries(root, limit=args.limit)
    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
    elif not entries:
        print("no feedback recorded yet.")
    else:
        for entry in entries:
            print(_render_line(entry))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
