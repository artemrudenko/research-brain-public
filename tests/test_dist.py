"""Acceptance tests for the `make dist` distribution build.

`make dist` wraps `git archive` so the shipped archive honors the
`.gitattributes` `export-ignore` rules: contributor-only files (DEVELOPING.md,
tests/, .github/, .planning/, .gitattributes) must never reach an end user, while the
runtime (scripts/, skills/) and the product contract (AGENTS.md, CLAUDE.md)
must be present. The archive is built from committed state, so it can never
leak live run data (untracked brain/ + pipeline/ output) or secrets (config/.env).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PREFIX = "research-brain/"

# Files that must never reach an end user: contributor-only files (export-ignored) and
# the secrets file. config/.env is gitignored so `git archive` can't ship it today — the
# assertion is a regression guard so a stray `git add -f config/.env` during debugging
# can never silently leak secrets into a shipped archive (the docstring's guarantee).
# pytest.ini and requirements-dev.txt are dev tooling for the (export-ignored) tests/
# tree — dead weight in a shipped install.
# The Claude-Code/Cowork DEV layer is excluded too: settings.json wires a
# contributor's local hooks (uv/ruff and a development guard) and
# security-gate-reviewer is a hand-written dev subagent — both reference paths
# that do not exist in a shipped install. The six GENERATED pipeline-role agents
# under .claude/agents/ are product and must still ship (asserted below).
EXCLUDED_FILES = (
    "DEVELOPING.md",
    ".gitattributes",
    "config/.env",
    "pytest.ini",
    "requirements-dev.txt",
    ".claude/settings.json",
    ".claude/agents/security-gate-reviewer.md",
    "docs/PUBLIC_RELEASE_PREP.md",
    "docs/BACKLOG.md",
    "docs/adr/0024-scholarly-author-ingestion.md",
    "docs/product-audit-2026-07-05.md",
    "pipeline/registry.md",
)
# skills/release/ is the contributor release ritual (make dist, live update) — it
# drives dev-only tooling, so it is export-ignored while the rest of skills/ ships.
EXCLUDED_DIRS = (
    "tests/", ".github/", ".planning/", "skills/release/",
    "docs/publications/",
    "docs/private-history/",
    "tools/",
)
# Files/dirs that an end user genuinely needs and must survive the build.
# requirements.txt is pinned here because it is the only pip-install path the
# shipped docs and the runtime PyYAML error messages point at — an over-broad
# future export-ignore (e.g. `requirements*`) must fail this test, not ship.
REQUIRED_DIRS = ("scripts/", "skills/")
REQUIRED_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "requirements.txt",
    # Terms must travel with the code: an archive that drops LICENSE leaves its
    # recipient with no grant at all, whatever the repository says.
    "LICENSE",
    "pipeline/README.md",
    # The generated pipeline-role subagents are product (CLAUDE.md documents them
    # as the least-privilege delegation layer). Pinned individually so the DEV-layer
    # export-ignore above can never widen into `.claude/` and silently strip them.
    ".claude/agents/collector.md",
    ".claude/agents/curator.md",
    ".claude/agents/synthesizer.md",
    ".claude/agents/critic.md",
    ".claude/agents/digest-maker.md",
    ".claude/agents/deliverer.md",
)

_TOOLING = shutil.which("make") and shutil.which("git")
pytestmark = pytest.mark.skipif(
    not _TOOLING, reason="make and git are required to build the distribution archive"
)


@pytest.fixture(scope="module")
def dist_archives(tmp_path_factory: pytest.TempPathFactory) -> list[Path]:
    """Build the archive once and return the produced zip paths.

    The build is redirected into a temp dir (Makefile `DIST_DIR` override) so the
    test never writes into the checkout's `dist/`."""
    dist_dir = tmp_path_factory.mktemp("dist")
    subprocess.run(
        ["make", "dist", f"DIST_DIR={dist_dir}"],
        cwd=PROJECT_ROOT, check=True, capture_output=True, text=True,
    )
    archives = sorted(dist_dir.glob("research-brain-*.zip"))
    assert archives, "`make dist` produced no archive under the temp dist dir"
    return archives


@pytest.fixture(scope="module")
def archive_names(dist_archives: list[Path]) -> list[str]:
    """The newest archive's entry names (prefix stripped)."""
    with zipfile.ZipFile(dist_archives[-1]) as zf:
        names = zf.namelist()
    # Every entry is rooted at the prefix dir; strip it for path assertions.
    assert all(n.startswith(ARCHIVE_PREFIX) for n in names), "archive missing the prefix dir"
    return [n[len(ARCHIVE_PREFIX) :] for n in names if n != ARCHIVE_PREFIX]


def test_dist_archive_is_version_named(dist_archives: list[Path]) -> None:
    """The archive is the user-facing release artifact: its name must carry the
    product version (`update.sh` prints "updating X → Y" from it), not a bare
    git SHA that means nothing to a recipient — releases used to rename it by
    hand (RESUME 0.5.1)."""
    result = subprocess.run(
        [sys.executable, "scripts/version.py", "current"],
        cwd=PROJECT_ROOT, check=True, capture_output=True, text=True,
    )
    version = result.stdout.strip()
    assert version, "version.py current printed nothing"
    expected = f"research-brain-{version}.zip"
    names = [path.name for path in dist_archives]
    assert expected in names, f"`make dist` must produce {expected}, got {names}"


def test_dist_excludes_contributor_files(archive_names: list[str]) -> None:
    for name in EXCLUDED_FILES:
        assert name not in archive_names, f"{name} leaked into the distribution archive"
    for prefix in EXCLUDED_DIRS:
        leaked = [n for n in archive_names if n.startswith(prefix)]
        assert not leaked, f"{prefix} leaked into the distribution archive: {leaked[:3]}"


def test_dist_includes_runtime_and_contract(archive_names: list[str]) -> None:
    for prefix in REQUIRED_DIRS:
        assert any(n.startswith(prefix) for n in archive_names), f"{prefix} missing from archive"
    for name in REQUIRED_FILES:
        assert name in archive_names, f"{name} missing from the distribution archive"


def test_dist_ships_skill_acceptance_tests(archive_names: list[str]) -> None:
    """`skills/{name}/tests/acceptance.md` is part of the shipped skill contract.

    The root `tests/` suite is contributor-only and must NOT ship (asserted
    above). But the export-ignore pattern was written unanchored (`tests/`), and
    gitattributes patterns without a leading slash match at ANY depth — so it
    silently stripped all 18 per-skill acceptance files too, while three files
    that DO ship keep promising they exist (docs/CONVENTIONS.md §"Skills →
    skills/{name}/tests/acceptance.md", and the wiki-ingest / research-build
    AGENTS.md). A shipped install therefore had documentation pointing at absent
    files. `test_dist_excludes_contributor_files` could not catch it because it
    prefix-matches from the archive root only.
    """
    shipped = [n for n in archive_names if n.startswith("skills/") and "/tests/" in n]
    assert shipped, (
        "no skills/*/tests/ files reached the archive — the `tests/` export-ignore "
        "is matching at depth; anchor it as `/tests/` so only the root suite is stripped"
    )
    # Every skill that has acceptance tests in git must have them in the archive.
    expected = subprocess.run(
        ["git", "ls-files", "skills/*/tests/acceptance.md"],
        cwd=PROJECT_ROOT, check=True, capture_output=True, text=True,
    ).stdout.split()
    assert expected, "no skill acceptance tests tracked in git — test assumption broke"
    missing = [path for path in expected if path not in archive_names]
    assert not missing, f"skill acceptance tests missing from the archive: {missing}"


def test_dist_still_excludes_the_root_test_suite(archive_names: list[str]) -> None:
    """Anchoring `tests/` must not let the contributor suite leak.

    Guards the other side of the fix above: `tests/` at the root is thousands of
    lines of pytest that no end user runs, and it is the reason the pattern
    existed in the first place.
    """
    leaked = [n for n in archive_names if n.startswith("tests/")]
    assert not leaked, f"the root test suite leaked into the archive: {leaked[:5]}"


def test_dev_only_make_targets_refuse_to_run_in_a_shipped_install(
    dist_archives: list[Path], tmp_path: Path
) -> None:
    """`make export` / `make exports-check` are dev-checkout tools: in a shipped
    install (no DEVELOPING.md) they must fail fast with a clear message instead
    of resurrecting the export-ignored requirements-dev.txt (or git-diffing in a
    git-less install)."""
    with zipfile.ZipFile(dist_archives[-1]) as zf:
        zf.extractall(tmp_path)
    install = tmp_path / "research-brain"
    assert not (install / "DEVELOPING.md").exists(), "dev marker leaked into the archive"
    for target in ("export", "exports-check"):
        result = subprocess.run(
            ["make", target],
            cwd=install, capture_output=True, text=True,
        )
        assert result.returncode != 0, f"`make {target}` must refuse outside the dev checkout"
        assert "dev checkout" in (result.stdout + result.stderr), (
            f"`make {target}` should explain it is dev-checkout-only, got:\n"
            f"{result.stdout}{result.stderr}"
        )
    assert not (install / "requirements-dev.txt").exists(), (
        "the refused targets must not have written requirements-dev.txt"
    )
