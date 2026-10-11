#!/usr/bin/env python3
"""
concept_write.py — atomically write a concept file for the `wiki-ingest` flow.

Why: `wiki-ingest` authors concept markdown straight into `brain/concepts/`. A plain
write can be interrupted mid-stream (a crash, a killed process) and leave a truncated
`brain/concepts/x.md` behind — a half-written concept the vault then treats as real.
This tiny CLI gives the skill an atomic write path: the body lands in a temp sibling
first, then `os.replace` swaps it into place in one step, so the final file is either
the old content or the complete new content — never a partial. The temp is cleaned up
on any failure. Mirrors `scripts/inbox.py`'s `_atomic_write_text`.

The caller (the skill) controls the destination path and the exact bytes; this module
adds no frontmatter and makes no content decisions — it only writes atomically.

CLI:
    python3 scripts/concept_write.py <path> --body-file <file>   # body from a file
    python3 scripts/concept_write.py <path>                      # body from STDIN
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Real project root (…/research-brain), two levels up from this file. The default
# containment anchor when no --root override is given on the CLI.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Make `scripts` importable when run directly (`python3 scripts/concept_write.py`).
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(_PROJECT_ROOT))

# The atomic-write idiom lives once in registry.py (random-suffixed temp + replace);
# re-export it so this module's public `atomic_write_text` keeps working for callers.
from scripts.hygiene.checks import index_lists_stem  # noqa: E402
from scripts.registry import atomic_write_text  # noqa: E402

# Concept files live only here; the guard rejects any destination resolving outside.
_CONCEPTS_SUBDIR = ("brain", "concepts")


def _contained_dest(path: Path, root: Path) -> Path:
    """Return `path` resolved, asserting it lands inside `<root>/brain/concepts`.

    The caller (`wiki-ingest`) derives the slug from untrusted article content, so a
    poisoned article could steer it into a `../` slug that escapes `brain/concepts/`.
    Resolve the path and require it under the concepts dir — reject (ValueError) a `..`
    traversal, an absolute path outside the tree, or anything else that lands elsewhere,
    so a bad destination surfaces a clear error instead of writing somewhere arbitrary.
    Mirrors `inbox.py`'s `_safe_topic` intent (containment, not silent mangling)."""
    concepts_root = (root / Path(*_CONCEPTS_SUBDIR)).resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(concepts_root):
        raise ValueError(
            f"unsafe concept path (must resolve inside {concepts_root}): {path}"
        )
    return resolved


# ── INDEX.md safety-net append ────────────────────────────────────────────────

_RECENT_HEADER = "### Recently added (file into a cluster)"
# The next `##`/`###` heading after "Recently added" bounds that section.
_NEXT_SECTION_RE = re.compile(r"\n(?=#{2,3} )")


def _first_h1(body: str) -> str | None:
    """The concept's `# H1` line — the MOC entry's one-line description."""
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or None
    return None


def ensure_index_entry(dest: Path, body: str, root: Path) -> bool:
    """Idempotently list a just-written concept in the `brain/INDEX.md` MOC.

    `wiki-query` navigates ONLY via the MOC (+ wikilinks), so a concept the MOC
    doesn't list is invisible to every vault query — and the hand-maintained
    MOC has already drifted this way on a live install. This is a safety net,
    not curation: the entry lands under a "Recently added" cluster for the
    agent/human to file properly later. Shares `index_lists_stem` with the
    hygiene check so writer and checker can never disagree on "listed". A
    missing INDEX.md is a permissive no-op (mirrors the check). Returns True
    when a line was appended.
    """
    index_path = root / "brain" / "INDEX.md"
    if not index_path.exists():
        return False
    text = index_path.read_text(encoding="utf-8")
    stem = dest.stem
    if index_lists_stem(text, stem):
        return False

    h1 = _first_h1(body)
    entry = f"- [[{stem}]] — {h1}" if h1 else f"- [[{stem}]]"
    if _RECENT_HEADER in text:
        # Insert at the END of the Recently-added section, not the end of the
        # file — a human may curate clusters below it.
        head, _, tail = text.partition(_RECENT_HEADER)
        cut = _NEXT_SECTION_RE.search(tail)
        if cut:
            section, rest = tail[: cut.start()], tail[cut.start():]
            new = f"{head}{_RECENT_HEADER}{section.rstrip()}\n{entry}\n{rest}"
        else:
            new = f"{head}{_RECENT_HEADER}{tail.rstrip()}\n{entry}\n"
    else:
        new = f"{text.rstrip()}\n\n{_RECENT_HEADER}\n\n{entry}\n"
    atomic_write_text(index_path, new)
    return True


# ── CLI ──────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Atomically write a concept file (temp sibling + os.replace)."
    )
    parser.add_argument("path", help="Destination concept file (e.g. brain/concepts/x.md).")
    parser.add_argument(
        "--body-file",
        default=None,
        help="File holding the concept body; omit to read the body from STDIN.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Containment root; the destination must resolve inside <root>/brain/concepts "
        "(default: the project root). Mainly for tests pointing at a tmp tree.",
    )
    parser.add_argument(
        "--index",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "After the atomic write, idempotently list the concept in the "
            "brain/INDEX.md MOC (under 'Recently added') when nothing there "
            "references it yet — an unlisted concept is invisible to wiki-query. "
            "--no-index skips; a missing INDEX.md is always a no-op."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    root = Path(args.root) if args.root is not None else _PROJECT_ROOT
    # Contain the destination before reading the body or touching disk: a bad path
    # exits non-zero and writes nothing (no parent dirs, no temp, no final file).
    try:
        dest = _contained_dest(Path(args.path), root)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.body_file is not None:
        text = Path(args.body_file).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    atomic_write_text(dest, text)
    print(f"OK: wrote → {dest}")
    if args.index and ensure_index_entry(dest, text, root):
        print(f"OK: listed [[{dest.stem}]] in brain/INDEX.md (Recently added)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
