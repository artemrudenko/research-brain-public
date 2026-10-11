#!/usr/bin/env python3
"""
brain_status.py — read-only Q&A over the system's OWN state.

This module answers questions about *us* — what this brain monitors, on what
cadence, and what it has produced — as opposed to questions about external
*topics* (those go through the `wiki-query` skill against `brain/concepts/`).
It is the deterministic engine behind the `brain-ask` skill.

Four queries, all pure read-only (nothing is ever written or mutated), each
resolving its inputs relative to the project root regardless of cwd
(CONVENTIONS §1):

  - `monitored_sources()` — parse `config/sources.yaml` into structured records
    (category, url, type, tier, priority, filter, active). Active-only by
    default; `active_only=False` includes parked rows too.
  - `cadence()` — parse `config/schedule.yaml` into a plain-language schedule
    summary: each block (collect / curate / synthesis / digest) with its cron
    rendered as a human phrase, plus the shared timezone and digest lookback.
  - `list_digests(n)` — newest-first list of `pipeline/3-synthesis/digest_*.md`
    with each file's date and a one-line summary (its volume headline, or a
    quiet-week note).
  - `latest_findings()` — extract the highlight bullets from the most recent
    digest. A quiet-week digest yields a clear "nothing new" signal; no digests
    at all yields a clear "no digests yet" signal — never a crash.

Frontmatter / date parsing and the schedule lookback reader are reused from
`scripts.build_digest` (DRY); the digest highlight extraction parses the exact
format `build_digest.render` writes.

CLI (read-only; prints, never writes):
    python3 scripts/brain_status.py sources [--all]
    python3 scripts/brain_status.py cadence
    python3 scripts/brain_status.py digests [-n N]
    python3 scripts/brain_status.py findings
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the `scripts` package importable when run directly as a script
# (`python3 scripts/brain_status.py`), not only as a module (`-m scripts...`).
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(_PROJECT_ROOT))

# Reuse the project-root resolution and the default lookback constant — no
# reimplementation.
from scripts.build_digest import (  # noqa: E402
    DEFAULT_LOOKBACK_DAYS as _BUILD_DIGEST_DEFAULT_LOOKBACK_DAYS,
)
from scripts.build_digest import PROJECT_ROOT  # noqa: E402
from scripts.status import cadence as status_cadence  # noqa: E402
from scripts.status import digests as status_digests  # noqa: E402
from scripts.status import sources as status_sources  # noqa: E402
from scripts.status.model import (  # noqa: E402
    CadenceBlock,
    CadenceSummary,
    DigestEntry,
    Findings,
    SourceRecord,
)

# Default timezone when schedule.yaml is missing/unreadable (CONVENTIONS §2.2).
DEFAULT_TIMEZONE = status_cadence.DEFAULT_TIMEZONE
DEFAULT_LOOKBACK_DAYS = _BUILD_DIGEST_DEFAULT_LOOKBACK_DAYS

__all__ = [
    "CadenceBlock",
    "CadenceSummary",
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_TIMEZONE",
    "DigestEntry",
    "Findings",
    "SourceRecord",
    "_BLOCK_LABELS",
    "_BLOCK_ORDER",
    "_DIGEST_NAME_RE",
    "_EXAMPLE_MARKER",
    "_HIGHLIGHT_SECTIONS",
    "_QUIET_RE",
    "_ROW_COMMENT_RE",
    "_at",
    "_digest_summary",
    "_extract_highlights",
    "_format_time",
    "_is_example_row",
    "_is_separator_row",
    "_load_schedule",
    "_split_row",
    "cadence",
    "describe_cron",
    "latest_findings",
    "list_digests",
    "main",
    "monitored_sources",
]


# --------------------------------------------------------------------------- #
# Markdown-table helpers
# --------------------------------------------------------------------------- #


# The shipped template marks its placeholder source rows with this marker inside
# the trailing HTML comment. A row carrying it is an EXAMPLE, not a real
# monitored source, and must be excluded from the monitored list (FIX 3). The
# identical marker is used by manage_sources so the two readers stay in agreement.
_ROW_COMMENT_RE = status_sources.ROW_COMMENT_RE
_EXAMPLE_MARKER = status_sources.EXAMPLE_MARKER
_is_example_row = status_sources.is_example_row
_split_row = status_sources.split_row
_is_separator_row = status_sources.is_separator_row


# --------------------------------------------------------------------------- #
# monitored_sources
# --------------------------------------------------------------------------- #


def monitored_sources(
    *, root: Path = PROJECT_ROOT, active_only: bool = True
) -> list[SourceRecord]:
    """Parse config/sources.yaml into structured source records.

    Walks the file line by line tracking the current `## Category:` heading and
    only reads rows inside an `### Active sources` table (the `### Candidates`
    table is ignored — those are parked, not monitored). Active-only by default;
    `active_only=False` also returns rows whose `Active` cell is `no`.

    A missing file yields an empty list (never an exception) — read-only and
    crash-free per the project's soft-skip convention.
    """
    return status_sources.monitored_sources(root=root, active_only=active_only)


# --------------------------------------------------------------------------- #
# cadence
# --------------------------------------------------------------------------- #

_BLOCK_ORDER = status_cadence._BLOCK_ORDER
_BLOCK_LABELS = status_cadence._BLOCK_LABELS
_WEEKDAYS = status_cadence._WEEKDAYS
_format_time = status_cadence._format_time
_at = status_cadence._at
_load_schedule = status_cadence._load_schedule


def describe_cron(cron: str) -> str:
    """Render a 5-field cron string as a short plain-language cadence phrase.

    Handles the patterns this project actually uses (CONVENTIONS §2.2): a fixed
    daily time, an "every N days" step, and a weekly day-of-week. Anything it
    does not recognize falls back to echoing the raw cron, so it never lies.
    """
    return status_cadence.describe_cron(cron)


def cadence(*, root: Path = PROJECT_ROOT) -> CadenceSummary:
    """Parse config/schedule.yaml into a plain-language cadence summary.

    Reuses `build_digest.read_lookback_days` for the digest lookback. Missing
    file / parser yields defaults (UTC, default lookback, blocks omitted) rather
    than an exception.
    """
    return status_cadence.cadence(root=root)


# --------------------------------------------------------------------------- #
# list_digests
# --------------------------------------------------------------------------- #

_DIGEST_NAME_RE = status_digests._DIGEST_NAME_RE
_QUIET_RE = status_digests._QUIET_RE
_digest_summary = status_digests._digest_summary


def list_digests(*, n: int | None = None, root: Path = PROJECT_ROOT) -> list[DigestEntry]:
    """List produced digests newest-first, optionally truncated to `n`.

    Reads `pipeline/3-synthesis/digest_YYYY-MM-DD.md` files, sorts by the date
    in the filename (descending), and attaches a one-line summary to each. A
    missing directory or zero digests yields an empty list (never an exception).
    """
    return status_digests.list_digests(n=n, root=root)


# --------------------------------------------------------------------------- #
# latest_findings
# --------------------------------------------------------------------------- #

# Section headings in a rendered digest that carry the highlight bullets.
_HIGHLIGHT_SECTIONS = status_digests._HIGHLIGHT_SECTIONS
_extract_highlights = status_digests._extract_highlights


def latest_findings(*, root: Path = PROJECT_ROOT) -> Findings:
    """Extract key findings from the most recent digest.

    Three graceful outcomes (never a crash):
      - no digests at all → `no_digests=True` with a plain-language message;
      - the latest digest is a quiet week → `is_quiet=True`, no highlights;
      - otherwise → `highlights` carries the extracted bullets.
    """
    return status_digests.latest_findings(root=root)


# --------------------------------------------------------------------------- #
# CLI (read-only — prints, never writes)
# --------------------------------------------------------------------------- #


def _print_sources(records: list[SourceRecord]) -> None:
    if not records:
        print("No monitored sources configured.")
        return
    for rec in records:
        state = "active" if rec.active else "inactive"
        print(f"- [{rec.category}] {rec.url} ({rec.type}, tier {rec.tier}, {state})")


def _print_cadence(summary: CadenceSummary) -> None:
    print(f"Timezone: {summary.timezone}")
    print(f"Digest lookback: {summary.lookback_days} days")
    for block in summary.blocks:
        print(f"- {block.description}")


def _print_digests(entries: list[DigestEntry]) -> None:
    if not entries:
        print("No digests produced yet.")
        return
    for entry in entries:
        print(f"- {entry.date.isoformat()}: {entry.summary}")


def _print_findings(findings: Findings) -> None:
    print(findings.message)
    for item in findings.highlights:
        print(f"- {item}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the four read-only queries."""
    parser = argparse.ArgumentParser(
        prog="brain_status.py",
        description="Read-only status & findings queries over this brain's own state.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_sources = sub.add_parser("sources", help="List monitored sources.")
    p_sources.add_argument(
        "--all", action="store_true", help="Include inactive (parked) sources too."
    )
    sub.add_parser("cadence", help="Show the collection/digest schedule.")
    p_digests = sub.add_parser("digests", help="List produced digests, newest first.")
    p_digests.add_argument(
        "-n", type=int, default=None, metavar="N", help="Limit to the N newest."
    )
    sub.add_parser("findings", help="Show key findings from the latest digest.")

    args = parser.parse_args(argv)

    if args.command == "sources":
        from scripts.sources import store as _store  # noqa: PLC0415 — CLI-only seam

        if _store.legacy_md_needs_migration(_PROJECT_ROOT / "config"):
            print(
                "NOTE: your config is still in the retired .md format — run "
                "`python3 scripts/schema.py migrate-config` to convert it; "
                "until then nothing is monitored.",
                file=sys.stderr,
            )
        _print_sources(monitored_sources(active_only=not args.all))
    elif args.command == "cadence":
        _print_cadence(cadence())
    elif args.command == "digests":
        _print_digests(list_digests(n=args.n))
    elif args.command == "findings":
        _print_findings(latest_findings())
    return 0


if __name__ == "__main__":
    sys.exit(main())
