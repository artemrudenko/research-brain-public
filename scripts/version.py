#!/usr/bin/env python3
"""version.py — read and compare the project version for the shipped update flow.

`update.sh` overlays a newer archive's code onto an existing install while
preserving the user's data. Before it does, it must know whether the incoming
archive is actually newer — to refuse a silent downgrade and to print an honest
"updating X → Y" line. That decision is a numeric version comparison, which is
fiddly and non-portable in pure shell (`sort -V` is absent on BSD/macOS). So the
comparison lives here: deterministic, stdlib-only, identical on every platform,
and unit-tested.

The version is the single `[project] version` in `pyproject.toml`, which travels
inside every archive, so both the installed copy and the incoming one carry it.

CLI (called by update.sh):
    python3 scripts/version.py current [--root DIR]
    python3 scripts/version.py relation --installed DIR --incoming DIR
        -> prints one of: older | same | newer   (incoming relative to installed)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# `version = "1.2.3"` under [project]. We do not depend on a TOML parser (the
# stdlib `tomllib` is 3.11+, but this keeps the reader trivial and dependency-free
# for the flat, machine-written field), matching the line-based readers elsewhere.
_VERSION_RE = re.compile(r'^\s*version\s*=\s*"([^"]+)"', re.MULTILINE)


def read_version(root: Path) -> str:
    """Return the `[project] version` string from `root/pyproject.toml`.

    Raises FileNotFoundError if the file is absent, ValueError if it has no
    version field — both are hard errors for the update flow (a copy with no
    version is not a valid archive to compare against)."""
    pyproject = root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")  # FileNotFoundError propagates
    # Scope to the [project] table so a tool's version line can't be picked up.
    project_section = text.split("[project]", 1)
    if len(project_section) == 2:
        # Stop at the next top-level table header so we stay inside [project].
        body = re.split(r"\n\[", project_section[1], maxsplit=1)[0]
        match = _VERSION_RE.search(body)
        if match:
            return match.group(1).strip()
    raise ValueError(f"no [project] version in {pyproject}")


def _parts(version: str) -> list[int]:
    """Split a dotted numeric version into ints. Raises ValueError on non-numeric."""
    try:
        return [int(p) for p in version.split(".")]
    except ValueError as exc:
        raise ValueError(f"non-numeric version component in {version!r}") from exc


def compare(a: str, b: str) -> int:
    """Return -1 / 0 / 1 for a < b / a == b / a > b, comparing numeric components.

    Shorter forms are zero-padded (`1.0` == `1.0.0`), so a two-part and a
    three-part version compare as a reader expects."""
    pa, pb = _parts(a), _parts(b)
    width = max(len(pa), len(pb))
    pa += [0] * (width - len(pa))
    pb += [0] * (width - len(pb))
    return (pa > pb) - (pa < pb)


def _relation(installed: str, incoming: str) -> str:
    """Describe `incoming` relative to `installed` for the update preflight."""
    return {-1: "older", 0: "same", 1: "newer"}[compare(incoming, installed)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_current = sub.add_parser("current", help="Print this copy's version.")
    p_current.add_argument(
        "--root", default=None, help="Project root (default: the repo this script ships in)."
    )

    p_rel = sub.add_parser(
        "relation", help="Print incoming's relation to installed: older|same|newer."
    )
    p_rel.add_argument("--installed", required=True, help="Root of the installed copy.")
    p_rel.add_argument("--incoming", required=True, help="Root of the incoming archive.")

    args = parser.parse_args(argv)

    # Surface bad input as a clean message + exit 2, never a traceback: update.sh
    # runs this under `set -e`, so a stray traceback would abort it opaquely.
    try:
        if args.command == "current":
            root = Path(args.root) if args.root else Path(__file__).resolve().parents[1]
            print(read_version(root))
            return 0

        if args.command == "relation":
            rel = _relation(read_version(Path(args.installed)), read_version(Path(args.incoming)))
            print(rel)
            return 0
    except (FileNotFoundError, ValueError) as exc:
        print(f"version error: {exc}", file=sys.stderr)
        return 2

    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
