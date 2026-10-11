#!/usr/bin/env python3
"""
frontmatter_lint.py — SKILL.md frontmatter linter.

Every skill ships as `skills/{name}/SKILL.md` (docs/CONVENTIONS.md §4). This
linter checks each SKILL.md for a well-formed YAML frontmatter block carrying
the keys a skill needs to be discoverable:

  - `name`        — required; kebab-case `{entity}-{action}`, ≤3 words.
  - `description`  — required; non-empty trigger description.

Usage:
    python3 scripts/frontmatter_lint.py [SKILLS_DIR] [--enforce] [--json]

Arguments:
    SKILLS_DIR   Directory containing `*/SKILL.md` (default: skills/, relative
                 to the project root).

Modes:
    default     warn-only — print findings, always exit 0.
    --enforce   blocking gate — exit 1 if any violation is found.
    --json      emit a machine-readable summary instead of plain text.
"""
import argparse
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

# Project root: scripts/<name>.py -> one parent up is scripts/, two is root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SKILLS_DIR = "skills"

REQUIRED_KEYS = ("name", "description")
# kebab-case, 1-3 words: `entity` or `entity-action` or `entity-action-qualifier`.
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){0,2}$")


def frontmatter_block(text: str) -> str:
    """Return the body between the leading `---` fences, or '' if absent."""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[3:end] if end != -1 else ""


def field(block: str, key: str) -> str | None:
    """Return the value of a top-level `key:` line in the block, or None."""
    m = re.search(rf"^{re.escape(key)}:\s*(.*?)\s*$", block, re.M)
    if not m:
        return None
    val = m.group(1).strip().strip("'\"")
    return val or None


def iter_skill_files(skills_dir: Path) -> Iterator[Path]:
    if skills_dir.exists():
        yield from sorted(skills_dir.glob("*/SKILL.md"))


def lint_file(path: Path) -> list[str]:
    """Return a list of warning strings for one SKILL.md (empty == clean)."""
    rel = _relpath(path)
    block = frontmatter_block(path.read_text(encoding="utf-8", errors="ignore"))
    if not block:
        return [f"WARN: {rel} :: missing YAML frontmatter block"]

    warnings = []
    for key in REQUIRED_KEYS:
        if field(block, key) is None:
            warnings.append(f"WARN: {rel} :: missing required key `{key}`")

    name = field(block, "name")
    if name is not None and not NAME_PATTERN.match(name):
        warnings.append(
            f"WARN: {rel} :: name=`{name}` not kebab-case `{{entity}}-{{action}}` (≤3 words)"
        )
    return warnings


def _relpath(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "skills_dir",
        nargs="?",
        default=DEFAULT_SKILLS_DIR,
        help=f"directory containing */SKILL.md (default: {DEFAULT_SKILLS_DIR})",
    )
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--enforce",
        action="store_true",
        help="blocking gate: exit 1 if any violation found (default warn-only / exit 0)",
    )
    args = ap.parse_args()

    skills_dir = Path(args.skills_dir)
    if not skills_dir.is_absolute():
        skills_dir = PROJECT_ROOT / skills_dir

    warnings, scanned = [], 0
    for p in iter_skill_files(skills_dir):
        scanned += 1
        warnings.extend(lint_file(p))

    violations = len(warnings)
    exit_code = 1 if (args.enforce and violations) else 0

    if args.json:
        print(json.dumps(
            {
                "scanned": scanned,
                "violations": violations,
                "mode": "enforce" if args.enforce else "warn-only",
                "blocking": exit_code != 0,
                "warnings": warnings,
            },
            indent=2,
            ensure_ascii=False,
        ))
        return exit_code

    for w in warnings:
        print(w)
    if exit_code:
        gate = f"ENFORCE — BLOCKING: {violations} violation(s), exit 1"
    elif args.enforce:
        gate = "enforce: clean, exit 0"
    else:
        gate = "warn-only, exit 0"
    print(f"[frontmatter_lint] SUMMARY scanned={scanned} violations={violations} ({gate})")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
