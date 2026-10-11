"""CLI parser for the stable scripts/health.py command."""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.health_checks import events, rendering, summary


def main(argv: list[str] | None = None, *, project_root: Path) -> int:
    """CLI: `report` prints the health summary; `record` appends an event."""
    parser = argparse.ArgumentParser(
        prog="health.py", description="System health report + run-history event log."
    )
    parser.add_argument(
        "--root", default=str(project_root), help="Project root (default: repo root)."
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("report", help="Print the rolled-up health report (default).")
    rec = sub.add_parser("record", help="Append one event to the log.")
    rec.add_argument("--kind", required=True, help="collect | deliver | hygiene | run | research")
    rec.add_argument(
        "--status",
        default="ok",
        help="ok | failed | error | sent | skipped | degraded "
        "(hygiene+degraded = a gate-skipped topic, named via --note).",
    )
    rec.add_argument("--source", help="Source URL (collect events).")
    rec.add_argument("--items", type=int, help="Items collected (collect events).")
    rec.add_argument("--channel", help="Delivery channel (deliver events).")
    rec.add_argument("--note", help="Free-text note.")

    args = parser.parse_args(argv)
    root = Path(args.root)

    if args.command == "record":
        details: dict[str, str | int] = {}
        if args.source is not None:
            details["source"] = args.source
        if args.items is not None:
            details["items"] = args.items
        if args.channel is not None:
            details["channel"] = args.channel
        if args.note is not None:
            details["note"] = args.note
        events.record_event(root, args.kind, status=args.status, details=details)
        return 0

    print(
        rendering.render(
            summary.health_summary(root), stale_feed_days=summary.STALE_FEED_DAYS
        )
    )
    return 0


__all__ = ["main"]
