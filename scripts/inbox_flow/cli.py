"""CLI parser and orchestration for the inbox queue facade."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from scripts.inbox_flow.model import DEFAULT_PROCESS_THRESHOLD


class AddArticle(Protocol):
    """Callable that captures an article."""

    def __call__(
        self,
        incoming_root: Path,
        *,
        url: str,
        title: str,
        body: str,
        source: str = "web",
        author: str = "",
        when: date | None = None,
        tags: list[str] | None = None,
        category: str = "_inbox",
        registry_path: Path | None = None,
    ) -> Path | None:
        """Capture an article and return the queued path, or None."""


@dataclass(frozen=True)
class CliOps:
    """Operations used by the command-line orchestration."""

    add_article: AddArticle
    pending: Callable[[Path], list[Path]]
    count: Callable[[Path], int]
    route: Callable[[Path, Path, str], Path]
    find_in_inbox_by_url: Callable[[Path, str], Path | None]


def build_parser(default_incoming: Path) -> argparse.ArgumentParser:
    """Build the inbox command parser."""
    parser = argparse.ArgumentParser(description="Ad-hoc article-capture queue.")
    sub = parser.add_subparsers(dest="command")

    def add_root(p: argparse.ArgumentParser) -> None:
        p.add_argument("--incoming", default=str(default_incoming), help="pipeline/1-incoming/ root.")

    p_add = sub.add_parser("add", help="Capture an article into the inbox.")
    add_root(p_add)
    p_add.add_argument("--url", required=True)
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--body-file", required=True, help="File holding the (stripped) article body.")
    p_add.add_argument("--source", default="web")
    p_add.add_argument("--author", default="")
    p_add.add_argument("--tags", default="", help="Comma-separated tags.")

    p_count = sub.add_parser("count", help="Print the queued-article count.")
    add_root(p_count)
    p_count.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_PROCESS_THRESHOLD,
        help="Also print READY when the count reaches this.",
    )

    p_pending = sub.add_parser("pending", help="List queued article paths.")
    add_root(p_pending)

    p_route = sub.add_parser("route", help="Move a queued article to its topic.")
    add_root(p_route)
    p_route.add_argument("article")
    p_route.add_argument("topic")

    return parser


def main(
    argv: list[str] | None,
    *,
    default_incoming: Path,
    ops: CliOps,
) -> int:
    """Run the inbox CLI."""
    parser = build_parser(default_incoming)
    args = parser.parse_args(argv)

    if args.command == "add":
        body = Path(args.body_file).read_text(encoding="utf-8")
        tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
        incoming = Path(args.incoming)
        try:
            already_queued = ops.find_in_inbox_by_url(incoming, args.url) is not None
            path = ops.add_article(
                incoming,
                url=args.url,
                title=args.title,
                body=body,
                source=args.source,
                author=args.author,
                tags=tags or None,
            )
        except ValueError as exc:
            # A malformed pasted URL (out-of-range port, bad IPv6 literal) must yield a
            # clean error, not a raw traceback (mirrors intake's run_cli).
            print(f"ERROR: invalid URL {args.url!r}: {exc}", file=sys.stderr)
            return 2
        n = ops.count(incoming)
        if path is None:
            print(f"SKIP: already known (in registry) → {args.url}")
        elif already_queued:
            print(f"OK: already queued → {path}")
        else:
            print(f"OK: captured → {path}")
        print(f"queued: {n}")
        return 0

    if args.command == "count":
        n = ops.count(Path(args.incoming))
        print(f"queued: {n}")
        if n >= args.threshold:
            print("READY: threshold reached — run /process.")
        return 0

    if args.command == "pending":
        for path in ops.pending(Path(args.incoming)):
            print(path)
        return 0

    if args.command == "route":
        dest = ops.route(Path(args.incoming), Path(args.article), args.topic)
        print(f"OK: routed → {dest}")
        return 0

    parser.print_help()
    return 0


__all__ = [
    "CliOps",
    "build_parser",
    "main",
]
