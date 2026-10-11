#!/usr/bin/env python3
"""
concept_manage.py — user-facing management of the concept vault.

The synthesis pipeline CREATEs/UPDATEs concepts on its own (`wiki-ingest`), but a
user has no deterministic way to *browse* the vault, *soft-delete* a concept, or
*restore* one. This module is that backend — the mechanical core behind the
`concept-manage` skill (`/concept list | backlinks | archive | restore`).

Design rules it honours (ADR 0014; extends the CONVENTIONS §13 hygiene principle
that the system flags, never deletes):
  - **Never hard-delete.** Archiving MOVES a concept to `brain/.archive/concepts/`
    (a dot-folder Obsidian ignores) and leaves a restorable marker, so the graph
    is never silently broken and the note is always recoverable.
  - **Warn before orphaning.** Archive reports the inbound backlinks that will
    become broken links, so the caller can re-point or accept them knowingly.
  - **Atomic writes.** Every move writes the destination in full (temp sibling +
    os.replace via registry.atomic_write_text) before unlinking the source, so a
    crash mid-move can never lose or truncate a concept.

Frontmatter parsing and `[[concepts/X]]` link extraction are reused from
validate_brain (one parser, no drift). The `/concept new` wizard and
`/concept update` flows are skill-orchestration over the research chain, not
code, and live in the skill — not here.

CLI:
    python3 scripts/concept_manage.py list [--tag T] [--include-seed] [--include-archived] [--json]
    python3 scripts/concept_manage.py backlinks <stem>
    python3 scripts/concept_manage.py archive <stem> [--reason R] [--today YYYY-MM-DD]
    python3 scripts/concept_manage.py restore <stem> [--today YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Real project root (…/research-brain), two levels up from this file.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(_PROJECT_ROOT))

# Reuse the single frontmatter parser + link regex + atomic writer — no second
# implementation to drift from the hygiene pass.
from scripts.fm import insert_after_frontmatter  # noqa: E402
from scripts.registry import atomic_write_text  # noqa: E402
from scripts.validate_brain import (  # noqa: E402
    _is_seed_or_example,
    _outbound_targets,
    _parse_frontmatter,
    _split_frontmatter,
    load_concept,
)

# Concepts live here; archived ones move under a dot-folder Obsidian skips (so an
# archived note leaves the graph view) yet git tracks (so it is restorable).
_CONCEPTS_SUBDIR = ("brain", "concepts")
_ARCHIVE_SUBDIR = ("brain", ".archive", "concepts")

# Sentinel pair wrapping the human-readable deprecation callout. Static (no date
# inside the tags themselves) so restore can strip the block by exact match.
ARCHIVE_SENTINEL_OPEN = "<!-- concept-manage:archived -->"
ARCHIVE_SENTINEL_CLOSE = "<!-- /concept-manage:archived -->"

# Strips the whole archive block (and the blank line we add before it) on restore.
_ARCHIVE_BLOCK_RE = re.compile(
    r"\n*"
    + re.escape(ARCHIVE_SENTINEL_OPEN)
    + r".*?"
    + re.escape(ARCHIVE_SENTINEL_CLOSE)
    + r"\n*",
    re.DOTALL,
)


def concepts_dir(root: Path) -> Path:
    """The live concept directory under `root`."""
    return root / Path(*_CONCEPTS_SUBDIR)


def archive_dir(root: Path) -> Path:
    """The soft-delete archive directory under `root`."""
    return root / Path(*_ARCHIVE_SUBDIR)


@dataclass
class ConceptSummary:
    """One row in a `list` view — the fields a user scans to pick a concept."""

    stem: str
    title: str
    tags: list[str]
    sources: int
    last_updated: str
    created: str
    archived: bool


@dataclass
class ArchiveResult:
    """Outcome of an archive: where it went + the links it would break."""

    dest: Path
    backlinks: list[str]


# ── frontmatter helpers (title/dates not captured by validate_brain.Concept) ──


def _scalar_fields(path: Path) -> dict[str, object]:
    """Parse a concept's frontmatter to a dict (reuses the hygiene parser)."""
    block, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
    return _parse_frontmatter(block)


def _summary(path: Path, *, archived: bool) -> ConceptSummary:
    """Build a ConceptSummary from a concept file on disk."""
    concept = load_concept(path)
    fields = _scalar_fields(path)
    title = str(fields.get("title", path.stem)).strip().strip("\"'")
    return ConceptSummary(
        stem=path.stem,
        title=title or path.stem,
        tags=concept.tags,
        sources=len(concept.sources),
        last_updated=str(fields.get("last_updated", "")).strip().strip("\"'"),
        created=str(fields.get("created", "")).strip().strip("\"'"),
        archived=archived,
    )


def _tag_matches(tags: list[str], wanted: str) -> bool:
    """True when `wanted` matches a tag exactly or as its `domain` prefix."""
    return any(t == wanted or t.startswith(f"{wanted}/") for t in tags)


# ── public API ────────────────────────────────────────────────────────────────


def list_concepts(
    root: Path,
    *,
    include_seed: bool = False,
    include_archived: bool = False,
    tag: str | None = None,
) -> list[ConceptSummary]:
    """Enumerate concepts under `root`, sorted by stem.

    Seed/example demo notes are hidden unless `include_seed`; archived notes are
    hidden unless `include_archived`. `tag` filters by exact tag or domain prefix.
    """
    rows: list[ConceptSummary] = []
    live = concepts_dir(root)
    if live.exists():
        for path in sorted(live.glob("*.md")):
            summary = _summary(path, archived=False)
            if not include_seed and _is_seed_or_example(summary.tags):
                continue
            rows.append(summary)
    if include_archived:
        arch = archive_dir(root)
        if arch.exists():
            for path in sorted(arch.glob("*.md")):
                summary = _summary(path, archived=True)
                if not include_seed and _is_seed_or_example(summary.tags):
                    continue
                rows.append(summary)
    if tag is not None:
        rows = [r for r in rows if _tag_matches(r.tags, tag)]
    return sorted(rows, key=lambda r: r.stem)


def find_backlinks(root: Path, stem: str) -> list[str]:
    """Stems of LIVE concepts that link to `stem` (via related_concept/body).

    These are the links that turn into broken links if `stem` is archived — the
    set a caller must see before soft-deleting. Excludes self-links.
    """
    live = concepts_dir(root)
    if not live.exists():
        return []
    inbound: list[str] = []
    for path in sorted(live.glob("*.md")):
        if path.stem == stem:
            continue
        if stem in _outbound_targets(load_concept(path)):
            inbound.append(path.stem)
    return sorted(inbound)


def _archive_block(today: str, reason: str, stem: str) -> str:
    """The restorable deprecation callout inserted at the top of an archived note."""
    reason_txt = reason.strip() or "—"
    return (
        f"{ARCHIVE_SENTINEL_OPEN}\n"
        f"> 🗄️ **ARCHIVED {today}** — soft-deleted via concept-manage. "
        f"Reason: {reason_txt}. "
        f"Restore with `python3 scripts/concept_manage.py restore {stem}`.\n"
        f"{ARCHIVE_SENTINEL_CLOSE}"
    )


def _append_changelog_row(text: str, today: str, what: str) -> str:
    """Append a row to the `## Change log` table when the note has one."""
    if "## Change log" not in text:
        return text
    row = f"| {today} | {what} | concept-manage |"
    sep = "" if text.endswith("\n") else "\n"
    return f"{text}{sep}{row}\n"


def archive_concept(
    root: Path, stem: str, *, reason: str = "", today: str | None = None
) -> ArchiveResult:
    """Soft-delete `stem`: move it to the archive, mark it, report backlinks.

    Raises FileNotFoundError if no such live concept, ValueError if it is already
    archived. Backlinks are captured BEFORE the move (over the live set).
    """
    today = today or date.today().isoformat()
    src = concepts_dir(root) / f"{stem}.md"
    dest = archive_dir(root) / f"{stem}.md"
    if not src.exists():
        if dest.exists():
            raise ValueError(f"concept already archived: {stem}")
        raise FileNotFoundError(f"no such concept: {stem}")

    backlinks = find_backlinks(root, stem)
    text = src.read_text(encoding="utf-8")
    text = insert_after_frontmatter(text, _archive_block(today, reason, stem))
    text = _append_changelog_row(text, today, "Archived (soft-delete)")
    atomic_write_text(dest, text)
    src.unlink()
    return ArchiveResult(dest=dest, backlinks=backlinks)


def restore_concept(root: Path, stem: str, *, today: str | None = None) -> Path:
    """Move an archived concept back into the live vault, stripping its marker.

    Raises FileNotFoundError if not archived, ValueError if a live concept
    already claims that stem (restoring would clobber it).
    """
    today = today or date.today().isoformat()
    src = archive_dir(root) / f"{stem}.md"
    dest = concepts_dir(root) / f"{stem}.md"
    if not src.exists():
        raise FileNotFoundError(f"no archived concept: {stem}")
    if dest.exists():
        raise ValueError(f"a live concept already exists at {stem} — cannot restore")

    text = src.read_text(encoding="utf-8")
    text = _ARCHIVE_BLOCK_RE.sub("\n", text, count=1)
    text = _append_changelog_row(text, today, "Restored from archive")
    atomic_write_text(dest, text)
    src.unlink()
    return dest


# ── CLI ──────────────────────────────────────────────────────────────────────


def _print_list(rows: list[ConceptSummary], *, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {"concepts": [vars(r) for r in rows]},
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    if not rows:
        print("(no concepts)")
        return
    for r in rows:
        flag = " [archived]" if r.archived else ""
        tags = ", ".join(r.tags)
        print(
            f"- {r.stem}{flag} — {r.title}  "
            f"[{tags}] · {r.sources} src · updated {r.last_updated}"
        )
    print(f"\n{len(rows)} concept(s).")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    # `--root` is shared by every subcommand and accepted AFTER it (e.g.
    # `archive transformers --root X`), so it lives on a parent parser, not the
    # top-level one — matching how the skill invokes it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--root",
        default=str(_PROJECT_ROOT),
        help="project root containing brain/concepts (default: project root)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", parents=[common], help="enumerate concepts")
    p_list.add_argument("--tag", default=None, help="filter by tag or domain")
    p_list.add_argument("--include-seed", action="store_true")
    p_list.add_argument("--include-archived", action="store_true")
    p_list.add_argument("--json", action="store_true")

    p_bl = sub.add_parser(
        "backlinks", parents=[common], help="concepts linking TO a concept"
    )
    p_bl.add_argument("stem")

    p_arch = sub.add_parser("archive", parents=[common], help="soft-delete a concept")
    p_arch.add_argument("stem")
    p_arch.add_argument("--reason", default="")
    p_arch.add_argument("--today", default=None)

    p_rest = sub.add_parser(
        "restore", parents=[common], help="restore an archived concept"
    )
    p_rest.add_argument("stem")
    p_rest.add_argument("--today", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = Path(args.root)

    try:
        if args.command == "list":
            rows = list_concepts(
                root,
                include_seed=args.include_seed,
                include_archived=args.include_archived,
                tag=args.tag,
            )
            _print_list(rows, as_json=args.json)
        elif args.command == "backlinks":
            links = find_backlinks(root, args.stem)
            if links:
                print(f"{args.stem} ← " + ", ".join(links))
            else:
                print(f"{args.stem}: no inbound backlinks")
        elif args.command == "archive":
            result = archive_concept(
                root, args.stem, reason=args.reason, today=args.today
            )
            print(f"archived {args.stem} → {result.dest}")
            if result.backlinks:
                print(
                    "WARNING: these concepts now have a broken link to "
                    f"{args.stem}: " + ", ".join(result.backlinks)
                )
        elif args.command == "restore":
            dest = restore_concept(root, args.stem, today=args.today)
            print(f"restored {args.stem} → {dest}")
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
