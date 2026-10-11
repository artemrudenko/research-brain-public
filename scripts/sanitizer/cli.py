from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api import SanitizerApi


def build_parser(default_incoming: Path) -> argparse.ArgumentParser:
    """Build the sanitize_incoming CLI parser."""
    parser = argparse.ArgumentParser(
        description="Sanitize incoming articles and gate synthesis on their companions."
    )
    sub = parser.add_subparsers(dest="command")

    def add_common_args(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--incoming", default=str(default_incoming), help="pipeline/1-incoming/ root."
        )
        command.add_argument(
            "--topic",
            action="append",
            dest="topics",
            metavar="NAME",
            help="Limit to this topic subdir (repeatable; default: all topics).",
        )

    add_common_args(sub.add_parser("sanitize", help="Write/refresh sanitized companions."))
    add_common_args(
        sub.add_parser("gate", help="Exit 1 if any article lacks a current companion.")
    )

    return parser


def main(argv: list[str] | None, *, api: SanitizerApi) -> int:
    """Run sanitize_incoming CLI commands through the stable facade API."""
    parser = api._build_parser()
    args = parser.parse_args(argv)
    incoming = Path(args.incoming)
    topics: list[str] | None = getattr(args, "topics", None)

    if args.command == "sanitize":
        if not incoming.exists():
            print(f"NOTE: {incoming} does not exist — nothing to sanitize.")
            return 0
        outcomes = []
        errors: list[tuple[Path, OSError]] = []
        for article in api._articles(incoming, topics):
            try:
                outcomes.append(api.sanitize_file(article))
            except OSError as exc:
                errors.append((article, exc))
        flagged = sum(1 for outcome in outcomes if outcome.result.findings)
        print(
            f"OK: sanitized {len(outcomes)} article(s); "
            f"{flagged} carried injection findings (see companion frontmatter)."
        )
        for article, error in errors:
            print(f"ERROR: could not sanitize {article}: {error}")
        return 1 if errors else 0

    if args.command == "gate":
        gate = api.gate_tree(incoming, topics)
        if gate.ok:
            print("OK: every incoming article has a current sanitized companion.")
            return 0
        if gate.missing:
            print(
                f"GATE FAILED: {len(gate.missing)} article(s) "
                "missing a sanitized companion:"
            )
            for path in gate.missing:
                print(f"  - {path}")
        if gate.stale:
            print(f"GATE FAILED: {len(gate.stale)} companion(s) stale (source changed):")
            for path in gate.stale:
                print(f"  - {path}")
        if gate.corrupt:
            print(
                f"GATE FAILED: {len(gate.corrupt)} companion(s) corrupt "
                "(body fails its sanitized_hash, or no recorded hash):"
            )
            for path in gate.corrupt:
                print(f"  - {path}")
        if gate.unreadable:
            print(
                f"GATE FAILED: {len(gate.unreadable)} source article(s) unreadable "
                "(cannot verify against companion — fix permissions/IO):"
            )
            for path in gate.unreadable:
                print(f"  - {path}")
        if gate.outdated:
            print(
                f"GATE FAILED: {len(gate.outdated)} companion(s) from a superseded "
                "ruleset (sanitizer_version bumped — re-sanitize before synthesis):"
            )
            for path in gate.outdated:
                print(f"  - {path}")
        print(
            "Run `sanitize_incoming.py sanitize` before synthesis; "
            "do NOT auto-ingest raw text."
        )
        return 1

    parser.print_help()
    return 0


__all__ = ["build_parser", "main"]
