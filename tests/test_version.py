"""Tests for scripts/version.py — the shipped version helper the update flow uses.

`update.sh` must decide, in pure shell, whether an incoming archive is newer than
the installed copy (to refuse a silent downgrade and to print an honest X→Y line).
That comparison lives here as a deterministic, stdlib-only helper so it is testable
and identical on every platform, rather than reimplemented with `sort -V` (absent
on BSD/macOS).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from scripts import version as ver  # noqa: E402

# ── parse_version ─────────────────────────────────────────────────────────────


def test_parse_version_reads_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    assert ver.read_version(tmp_path) == "1.2.3"


def test_parse_version_ignores_other_version_lines(tmp_path: Path) -> None:
    # Only the [project] version counts — not e.g. a tool's python_version.
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "0.9.0"\n\n[tool.mypy]\npython_version = "3.11"\n',
        encoding="utf-8",
    )
    assert ver.read_version(tmp_path) == "0.9.0"


def test_read_version_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ver.read_version(tmp_path)


def test_read_version_absent_field_raises(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        ver.read_version(tmp_path)


def test_read_version_ignores_non_project_version(tmp_path: Path) -> None:
    # A [tool.poetry] (or other) version before [project] must not be picked up.
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nversion = "9.9.9"\n\n[project]\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    assert ver.read_version(tmp_path) == "1.0.0"


def test_read_version_trims_whitespace(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "  1.2.3  "\n', encoding="utf-8"
    )
    assert ver.read_version(tmp_path) == "1.2.3"


def test_read_version_tolerates_crlf(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_bytes(b'[project]\r\nversion = "2.0.0"\r\n')
    assert ver.read_version(tmp_path) == "2.0.0"


# ── compare ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ("1.0.0", "1.0.0", 0),
        ("1.0.0", "1.0.1", -1),
        ("1.0.1", "1.0.0", 1),
        ("1.2.0", "1.10.0", -1),   # numeric compare, not lexical
        ("2.0.0", "1.9.9", 1),
        ("0.1.0", "0.2.0", -1),
        ("1.0", "1.0.0", 0),        # short form padded with zeros
        ("1.0.0", "1.0", 0),
    ],
)
def test_compare(a: str, b: str, expected: int) -> None:
    assert ver.compare(a, b) == expected


def test_compare_rejects_non_numeric() -> None:
    with pytest.raises(ValueError):
        ver.compare("1.0.0", "1.0.x")


# ── CLI ───────────────────────────────────────────────────────────────────────


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "version.py"), *args],
        capture_output=True, text=True,
    )


def test_cli_current_prints_installed_version() -> None:
    # The shipped script reads its OWN pyproject by default.
    res = _run("current")
    assert res.returncode == 0
    assert res.stdout.strip() == ver.read_version(PROJECT_ROOT)


def test_cli_relation_reports_incoming_newer(tmp_path: Path) -> None:
    installed = tmp_path / "installed"
    incoming = tmp_path / "incoming"
    installed.mkdir()
    incoming.mkdir()
    (installed / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    (incoming / "pyproject.toml").write_text('[project]\nversion = "0.2.0"\n', encoding="utf-8")

    res = _run("relation", "--installed", str(installed), "--incoming", str(incoming))
    assert res.returncode == 0
    assert res.stdout.strip() == "newer"


def test_cli_relation_reports_downgrade(tmp_path: Path) -> None:
    installed = tmp_path / "installed"
    incoming = tmp_path / "incoming"
    installed.mkdir()
    incoming.mkdir()
    (installed / "pyproject.toml").write_text('[project]\nversion = "0.3.0"\n', encoding="utf-8")
    (incoming / "pyproject.toml").write_text('[project]\nversion = "0.2.0"\n', encoding="utf-8")

    res = _run("relation", "--installed", str(installed), "--incoming", str(incoming))
    assert res.returncode == 0
    assert res.stdout.strip() == "older"


def test_cli_relation_reports_same(tmp_path: Path) -> None:
    for name in ("installed", "incoming"):
        d = tmp_path / name
        d.mkdir()
        (d / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    res = _run(
        "relation",
        "--installed", str(tmp_path / "installed"),
        "--incoming", str(tmp_path / "incoming"),
    )
    assert res.returncode == 0
    assert res.stdout.strip() == "same"


# ── release consistency: pyproject ↔ uv.lock ──────────────────────────────────
#
# `uv.lock` pins the project's OWN version alongside its dependencies. Bumping
# `[project] version` without re-running `uv lock` leaves the lock claiming the
# previous release, so a `uv sync` install reports a version the archive doesn't
# match — and `update.sh`'s X→Y line (which reads pyproject) disagrees with the
# installed metadata. This is the same drift class `make exports-check` guards
# for requirements*.txt, pinned here as a test because the lock is dev-only.

_LOCK_PACKAGE_RE = re.compile(
    r'^\[\[package\]\]\nname = "research-brain"\nversion = "([^"]+)"',
    re.MULTILINE,
)


def _lock_version(root: Path) -> str:
    """Return the `research-brain` package version recorded in `root/uv.lock`."""
    match = _LOCK_PACKAGE_RE.search((root / "uv.lock").read_text(encoding="utf-8"))
    assert match is not None, "uv.lock has no [[package]] block for research-brain"
    return match.group(1)


def test_uv_lock_version_matches_pyproject() -> None:
    """The lock's own project version tracks `[project] version`.

    CI is where this bites: it runs `uv sync --frozen` / `uv run --frozen`, so a
    stale lock stays stale and this fails. A plain local `uv run pytest` re-locks
    first and heals the drift silently, so a green local run is not evidence the
    committed lock is current — only the frozen run is.

    Fix a failure with `make lock` (or `uv lock`) — never by hand-editing the lock.
    """
    assert _lock_version(PROJECT_ROOT) == ver.read_version(PROJECT_ROOT), (
        "uv.lock is stale relative to pyproject.toml — run `make lock` and commit "
        "the refreshed uv.lock together with the version bump"
    )


# ── release consistency: pyproject ↔ .claude-plugin/plugin.json ───────────────
#
# The plugin manifest carries its own `version`, and it is the number Claude Code
# and Cowork show for the installed plugin. CLAUDE.md and skills/release/SKILL.md
# both call the two files a LOCKSTEP pair, but until this test nothing enforced
# it: 0.10.3 shipped with plugin.json still reading 0.9.1 through a fully green
# gate, because no check in the repo read that file at all.

_PLUGIN_MANIFEST = Path(".claude-plugin/plugin.json")


def _plugin_version(root: Path) -> str:
    """Return the `version` recorded in `root/.claude-plugin/plugin.json`."""
    manifest = json.loads((root / _PLUGIN_MANIFEST).read_text(encoding="utf-8"))
    version = manifest.get("version")
    assert isinstance(version, str), f"{_PLUGIN_MANIFEST} has no string `version` field"
    return version


def test_plugin_manifest_version_matches_pyproject() -> None:
    """The plugin manifest and `[project] version` move together.

    They are two halves of one release identity: `update.sh` compares
    pyproject's version to decide "updating X → Y" and refuse a downgrade, while
    the plugin host reads plugin.json to label what the user actually has
    installed. When they disagree, the user is told two different versions of
    the truth and neither the updater nor the host can detect it.

    Fix a failure by setting BOTH files to the target `X.Y.Z` (the bump step in
    skills/release/SKILL.md), never by editing just one.
    """
    assert _plugin_version(PROJECT_ROOT) == ver.read_version(PROJECT_ROOT), (
        f"{_PLUGIN_MANIFEST} is out of lockstep with pyproject.toml — bump both "
        "files to the same X.Y.Z in the release commit"
    )
