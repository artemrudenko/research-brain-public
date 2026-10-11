"""CLI entrypoint for the stable scripts/delivery/deliver.py facade."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api import DeliveryApi


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deliver.py",
        description="Deliver a built digest to the configured channels (headless mode).",
    )
    parser.add_argument(
        "pos1",
        nargs="?",
        metavar="digest_file.md",
        help=(
            "digest markdown to deliver (the channels.yaml when --rehearse; "
            "optional in --dry-run, which uses a built-in sample)"
        ),
    )
    parser.add_argument(
        "pos2",
        nargs="?",
        metavar="channels.yaml",
        help="channels config (default: config/channels.yaml)",
    )
    parser.add_argument("--dry-run", action="store_true", help="report targets, send nothing")
    parser.add_argument(
        "--force", action="store_true", help="re-send even if a delivery receipt exists"
    )
    parser.add_argument("--skip-quiet", action="store_true", help="no-op on a quiet-week digest")
    parser.add_argument(
        "--rehearse",
        action="store_true",
        help="build today's digest + dry-run-deliver it, end-to-end",
    )
    parser.add_argument(
        "--allow-unsanitized",
        action="store_true",
        help=(
            "(with --rehearse) opt out of the builder's fail-closed sanitize gate "
            "— only for fully-controlled feeds, mirrors build_digest.py --allow-unsanitized"
        ),
    )
    parser.add_argument(
        "--mcp-status",
        action="store_true",
        help=(
            "report each enabled MCP channel's receipt state for this digest "
            "(PENDING / DELIVERED) — the digest-deliver skill's pre-send idempotency check"
        ),
    )
    parser.add_argument(
        "--reserve-mcp",
        metavar="CHANNEL",
        help=(
            "claim CHANNEL for this digest BEFORE sending it — exit 0 means you "
            "own it and may send; any non-zero exit means do not send (another "
            "sender has it, it is already delivered, or delivery is locked)"
        ),
    )
    parser.add_argument(
        "--record-mcp",
        metavar="CHANNEL",
        help=(
            "stamp CHANNEL as delivered for this digest in the shared receipt — "
            "the digest-deliver skill calls this right after a successful MCP send"
        ),
    )
    parser.add_argument(
        "--chunks-sent",
        metavar="N",
        type=int,
        help=(
            "(with --record-mcp) record PARTIAL progress on a split body: N "
            "messages already reached the user. Keeps the channel reserved and "
            "lets an interrupted send resume instead of re-delivering them"
        ),
    )
    return parser


def main(argv: list[str] | None = None, *, api: DeliveryApi) -> int:
    """Run the deliver.py CLI using the supplied facade module as the API surface."""
    parser = _build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.record_mcp or args.reserve_mcp or args.mcp_status:
        api.load_dotenv()
        if not args.pos1:
            parser.print_usage(sys.stderr)
            return 2
        mcp_digest = Path(args.pos1)
        if not mcp_digest.exists():
            print(f"digest file not found: {mcp_digest}", file=sys.stderr)
            return 2
        mcp_config = Path(args.pos2) if args.pos2 else api.DEFAULT_CHANNELS_CONFIG
        try:
            if args.reserve_mcp:
                return api.reserve_mcp(mcp_digest, args.reserve_mcp, mcp_config)
            if args.record_mcp:
                return api.record_mcp(
                    mcp_digest, args.record_mcp, mcp_config, chunks_sent=args.chunks_sent
                )
            return api.mcp_status(mcp_digest, mcp_config)
        except api.DeliveryError as error:
            print(f"delivery error: {error}", file=sys.stderr)
            return 1

    dry_run, force, skip_quiet, rehearse = (
        args.dry_run,
        args.force,
        args.skip_quiet,
        args.rehearse,
    )

    api.load_dotenv()

    if rehearse:
        rehearse_config = Path(args.pos1) if args.pos1 else api.DEFAULT_CHANNELS_CONFIG
        try:
            return api._rehearse(
                rehearse_config, allow_unsanitized=args.allow_unsanitized
            )
        except api.DeliveryError as error:
            print(f"delivery error: {error}", file=sys.stderr)
            return 1

    config_path = Path(args.pos2) if args.pos2 else api.DEFAULT_CHANNELS_CONFIG

    if not args.pos1 and not dry_run:
        parser.print_usage(sys.stderr)
        return 2

    sample_path: Path | None = None
    if args.pos1:
        digest_path = Path(args.pos1)
        if not digest_path.exists():
            print(f"digest file not found: {digest_path}", file=sys.stderr)
            return 2
    else:
        fd, name = tempfile.mkstemp(suffix=".md", prefix="deliver-sample-")
        os.write(fd, api.SAMPLE_MESSAGE.encode("utf-8"))
        os.close(fd)
        sample_path = digest_path = Path(name)
        print("(no digest given — using built-in test message for dry-run)")

    try:
        attempted: set[str] = set()
        rc = api.deliver(
            digest_path,
            config_path,
            dry_run=dry_run,
            force=force,
            skip_quiet=skip_quiet,
            attempted=attempted,
        )
        if not dry_run:
            api._record_delivery_health(digest_path, channels=attempted)
        return rc
    except api.DeliveryError as error:
        print(f"delivery error: {error}", file=sys.stderr)
        return 1
    finally:
        if sample_path is not None:
            sample_path.unlink(missing_ok=True)


__all__ = [
    "_build_parser",
    "main",
]
