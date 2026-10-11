#!/usr/bin/env python3
"""
validate-pipeline-frontmatter.py — verifies that every .md article in a target
directory starts with a YAML frontmatter block and carries the required keys.

Each pipeline article must begin with `---` and declare the keys defined in
docs/CONVENTIONS.md §5:
    source, url, title, author, date_published, collected, category, tags
The block is parsed with `yaml.safe_load`, and each required key must be
present AND carry a non-empty value of the right shape:
    - `url`              must look like an http(s) URL,
    - `date_published`   } must be ISO-ish dates (YYYY-MM-DD, optionally with a
    - `collected`        }   time component),
    - `tags`             must be a non-empty list (a bare scalar is rejected).
Files missing the block, carrying malformed YAML, or failing any required-key
check are reported (and dropped at collect time). This script is advisory: it
only reports — it never deletes.

Usage:
    python3 scripts/validate-pipeline-frontmatter.py [TARGET_DIR] [--strict]

Arguments:
    TARGET_DIR  Directory to scan recursively for .md files.
                Default: pipeline/1-incoming/ (relative to the project root).

Options:
    --strict    Exit with code 2 if any file is missing frontmatter or a
                required key (default: report and exit 0).

Output: markdown summary on stdout.
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

# Auto-detect the project root: this script lives at scripts/<name>.py, so one
# parent up is scripts/ and two parents up is the project root. Auto-detection
# keeps the script cwd-independent (Cowork VM mount vs. native path differ).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = "pipeline/1-incoming/"

# Required frontmatter keys per docs/CONVENTIONS.md §5.
REQUIRED_KEYS = (
    "source",
    "url",
    "title",
    "author",
    "date_published",
    "collected",
    "category",
    "tags",
)


# An http(s) URL — host required, anything after is accepted.
_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)

# Required keys whose value must be a valid ISO-ish date (YYYY-MM-DD, with an
# optional time component — both forms appear on real articles).
_DATE_KEYS = ("date_published", "collected")


def _extract_block(text: str) -> str | None:
    """Return the raw text inside the leading `---`-delimited frontmatter.

    Per CONVENTIONS §5 an article must *begin* with `---`: the fence must be
    the first line (byte 0), allowing only a leading UTF-8 BOM. A blank line
    (or any other content) before the fence means there is no block.

    Returns None when the first line is not exactly `---`, or no closing `---`
    is found (an unterminated block is treated as no block at all).
    """
    # Tolerate a single leading UTF-8 BOM, but nothing else, before the fence.
    if text.startswith("﻿"):
        text = text[1:]

    lines = text.splitlines()
    # The opening fence must be the very first line — no leading blank lines.
    if not lines or lines[0] != "---":
        return None

    body: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            return "\n".join(body)
        body.append(line)
    # Reached EOF without a closing `---` — treat as malformed (no block).
    return None


def _is_isoish_date(value: object) -> bool:
    """True iff value is a date, or a YYYY-MM-DD[...] string (optional time).

    PyYAML coerces a bare `YYYY-MM-DD` scalar to a date/datetime object, so we
    accept those directly; a quoted/odd string is validated by parsing its
    leading `YYYY-MM-DD`.
    """
    if isinstance(value, datetime):
        return True
    # datetime.date is the base class; a plain date also satisfies this.
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return True
    if not isinstance(value, str):
        return False
    head = value.strip()[:10]
    try:
        datetime.strptime(head, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def read_frontmatter(path: Path) -> tuple[bool, dict | None, str | None]:
    """Parse the leading `---`-delimited frontmatter block of a file.

    Returns a tuple (has_block, data, parse_error):
      - has_block: True iff a closed `---` block was found.
      - data: the parsed mapping (dict) when YAML parsed cleanly, else None.
      - parse_error: a message when the block exists but YAML failed to parse
        (so callers report it instead of crashing); None otherwise.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False, None, None

    block = _extract_block(text)
    if block is None:
        return False, None, None

    # Parse with PyYAML (a project dependency). Mirror the guarded-import
    # pattern used across scripts/ so a missing parser degrades gracefully
    # rather than crashing — without yaml we can only confirm the block exists.
    try:
        import yaml  # noqa: PLC0415 — lazy optional import
    except ImportError:
        return True, None, None
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as error:
        # A parse error is a finding, not a crash. Keep the message one line.
        message = " ".join(str(error).split())
        return True, None, message

    return True, data if isinstance(data, dict) else {}, None


def _is_empty(value: object) -> bool:
    """True for values that count as "blank": None, empty/whitespace strings,
    or empty collections (e.g. an empty `tags` list)."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def _check_values(data: dict) -> str | None:
    """Validate required keys' presence, non-emptiness, and shape.

    Returns a single human-readable reason string for the first class of
    problems found, or None when every required key is present and valid.
    """
    # Presence + non-empty value (a present-but-blank key is rejected).
    bad = [k for k in REQUIRED_KEYS if k not in data or _is_empty(data[k])]
    if bad:
        return "missing or empty required keys: " + ", ".join(bad)

    # Type/format checks on the keys that have a defined shape.
    if not _URL_RE.match(str(data["url"]).strip()):
        return "url is not an http(s) URL"
    for key in _DATE_KEYS:
        if not _is_isoish_date(data[key]):
            return f"{key} is not an ISO date (YYYY-MM-DD)"
    if not isinstance(data["tags"], list):
        return "tags must be a non-empty list"

    return None


def scan(root: Path) -> tuple[int, dict[str, str]]:
    """Scan root recursively for .md files (ignoring index.md).

    Returns (total, problems) where problems maps a project-relative path to a
    human-readable reason string.
    """
    total = 0
    problems = {}
    if not root.exists():
        return 0, {}
    for path in sorted(root.rglob("*.md")):
        if path.name == "index.md":
            continue
        total += 1
        has_block, data, parse_error = read_frontmatter(path)
        rel = _relpath(path)
        if not has_block:
            problems[rel] = "missing YAML frontmatter block"
            continue
        if parse_error is not None:
            problems[rel] = "invalid YAML frontmatter: " + parse_error
            continue
        if data is None:
            # Block present but PyYAML unavailable — can't validate values.
            problems[rel] = "cannot validate frontmatter: PyYAML not installed"
            continue
        reason = _check_values(data)
        if reason:
            problems[rel] = reason
    return total, problems


def _relpath(path: Path) -> str:
    """Path relative to the project root when possible, else the bare path."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=DEFAULT_TARGET,
        help=f"directory to scan (default: {DEFAULT_TARGET})",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit with code 2 if any file is missing frontmatter or a required key",
    )
    args = parser.parse_args()

    target = Path(args.target)
    if not target.is_absolute():
        target = PROJECT_ROOT / target

    total, problems = scan(target)

    print("# Pipeline Frontmatter Validation\n")
    print(f"## {_relpath(target)} — scanned {total} files\n")

    if problems:
        print(f"FAIL: {len(problems)} file(s) with frontmatter problems:\n")
        for rel, reason in sorted(problems.items()):
            print(f"- `{rel}` — {reason}")
        print()
        sys.exit(2 if args.strict else 0)

    print("OK: all files have a valid frontmatter block with required keys.\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
