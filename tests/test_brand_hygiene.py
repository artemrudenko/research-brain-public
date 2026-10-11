"""Guard: the current tracked tree never names the former internal toolkit.

The public repository starts at a clean root commit. This check catches an
accidental literal in today's source tree before it can be published.

An earlier commit scrubbed the internal design docs, but four comments survived
it, two of them in modules that ship inside the distribution archive. Nothing in
the suite ever read for the name, so they stayed green for months. This test is
that missing reader.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Assembled from parts so the guard does not itself reintroduce the literal it
# forbids — the assertion below holds for EVERY tracked file, this one included.
_INTERNAL_NAME = "Ari" + "stek"


def _tracked_paths() -> list[str]:
    """Every path `git ls-files` reports, NUL-separated so odd names survive."""
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [entry for entry in listing.split("\0") if entry]


def test_no_tracked_file_names_the_internal_toolkit() -> None:
    needle = _INTERNAL_NAME.lower()
    offenders: list[str] = []
    for relative in _tracked_paths():
        path = PROJECT_ROOT / relative
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            # Binary blob, a submodule entry, or a path deleted in the working
            # tree since `git ls-files` ran — nothing to read either way.
            continue
        for number, line in enumerate(content.splitlines(), start=1):
            if needle in line.lower():
                offenders.append(f"{relative}:{number}")
    assert not offenders, (
        "tracked files name the internal toolkit this project was extracted "
        "from; remove the reference before public export (describe the "
        "thing, not its origin):\n  " + "\n  ".join(offenders)
    )
