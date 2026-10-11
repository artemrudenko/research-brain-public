"""End-to-end tests for update.sh — the shipped assisted-upgrade path.

The distribution model is a zip handoff (ADR 0004): to update, a user overlays a
newer archive's CODE onto their install while KEEPING their data (brain/,
pipeline/, config/.env, and the customized config files). update.sh is the shipped,
user-facing tool for exactly that. Its `DATA_EXCLUDES` defines the update
code/data boundary (ADR 0019). These tests build a fake
install + a fake newer archive in a sandbox and assert code is overlaid while data
survives.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPDATE_SH = PROJECT_ROOT / "update.sh"
VERSION_PY = PROJECT_ROOT / "scripts" / "version.py"

_BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(_BASH is None, reason="bash required for update.sh")


def _make_pyproject(version: str) -> str:
    return f'[project]\nname = "research-brain"\nversion = "{version}"\n'


def _make_install(root: Path, *, version: str) -> None:
    """A minimal fake install: shipped code + the real version.py, plus user data."""
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text(_make_pyproject(version), encoding="utf-8")
    # Shipped code the update must overlay.
    (root / "scripts").mkdir()
    (root / "scripts" / "version.py").write_bytes(VERSION_PY.read_bytes())
    (root / "scripts" / "collect.py").write_text("# OLD collect\n", encoding="utf-8")
    (root / "skills").mkdir()
    (root / "skills" / "old.md").write_text("old skill\n", encoding="utf-8")
    (root / "update.sh").write_bytes(UPDATE_SH.read_bytes())
    (root / "update.sh").chmod(0o755)
    # ── user data + secrets + customized config (MUST all be preserved) ──
    (root / "config").mkdir()
    # schedule.yaml holds the user's timezone + cadence — it is USER config, must
    # survive an update (this was the P1 the review caught).
    (root / "config" / "schedule.yaml").write_text("timezone: Europe/Kyiv\n", encoding="utf-8")
    (root / "config" / ".env").write_text("TELEGRAM_BOT_TOKEN=secret123\n", encoding="utf-8")
    (root / "config" / "sources.md").write_text("my sources\n", encoding="utf-8")
    (root / "config" / "topics.md").write_text("my topics\n", encoding="utf-8")
    (root / "config" / "channels.yaml").write_text("my channels\n", encoding="utf-8")
    (root / "config" / "tags.yaml").write_text("my tags\n", encoding="utf-8")
    (root / "brain").mkdir()
    (root / "brain" / "concepts").mkdir()
    (root / "brain" / "concepts" / "my-note.md").write_text("my knowledge\n", encoding="utf-8")
    (root / "pipeline").mkdir()
    (root / "pipeline" / "registry.md").write_text("my registry\n", encoding="utf-8")


def _make_incoming(root: Path, *, version: str) -> None:
    """A fake newer archive: new code + shipped config defaults, NO user data."""
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text(_make_pyproject(version), encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "version.py").write_bytes(VERSION_PY.read_bytes())
    (root / "scripts" / "collect.py").write_text("# NEW collect (fixed)\n", encoding="utf-8")
    (root / "scripts" / "brand_new.py").write_text("# a new script\n", encoding="utf-8")
    (root / "skills").mkdir()
    (root / "skills" / "old.md").write_text("new skill body\n", encoding="utf-8")
    (root / "update.sh").write_bytes(UPDATE_SH.read_bytes())
    (root / "update.sh").chmod(0o755)
    (root / "config").mkdir()
    # Shipped config DEFAULTS — the archive carries them, but they must never
    # overwrite a user's existing config (only genuinely NEW config files land).
    (root / "config" / "schedule.yaml").write_text("timezone: UTC\n", encoding="utf-8")
    (root / "config" / "channels.yaml").write_text("SHIPPED DEFAULT channels\n", encoding="utf-8")
    # A config file this release introduces that the install does not have yet.
    (root / "config" / "newfeature.yaml").write_text("shipped: default\n", encoding="utf-8")


def _run_update(install: Path, incoming: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_BASH, str(install / "update.sh"), "--yes", *extra, str(incoming)],
        cwd=install, capture_output=True, text=True,
    )


def test_post_update_config_check_prefers_the_venv_python(tmp_path: Path) -> None:
    # The post-update validate_config check must run with the install's venv python
    # (it has PyYAML → full-fidelity schema checks), not a bare system python3 that
    # may lack it. Prove it: make the venv python record that it was the one invoked.
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.1.0")
    _make_incoming(incoming, version="0.2.0")
    # The check only fires when scripts/validate_config.py is present post-overlay.
    (incoming / "scripts" / "validate_config.py").write_text("print('ok')\n", encoding="utf-8")
    # A fake venv interpreter that drops a marker when invoked (ignores its args, exits 0).
    # The overlay excludes .venv, so this survives the update and is used for the check.
    venv_bin = install / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    marker = tmp_path / "venv-python-was-used"
    (venv_bin / "python3").write_text(
        f'#!/bin/sh\ntouch "{marker}"\nexit 0\n', encoding="utf-8"
    )
    (venv_bin / "python3").chmod(0o755)
    res = _run_update(install, incoming)
    assert res.returncode == 0, res.stderr
    assert marker.exists(), "post-update config check did not use the venv python"


def test_update_overlays_code_and_preserves_data(tmp_path: Path) -> None:
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.1.0")
    _make_incoming(incoming, version="0.2.0")

    res = _run_update(install, incoming)
    assert res.returncode == 0, res.stderr

    # Code overlaid: existing scripts updated, brand-new script added.
    assert (install / "scripts" / "collect.py").read_text() == "# NEW collect (fixed)\n"
    assert (install / "scripts" / "brand_new.py").exists()
    assert (install / "skills" / "old.md").read_text() == "new skill body\n"
    # Version advanced.
    assert 'version = "0.2.0"' in (install / "pyproject.toml").read_text()

    # DATA preserved: vault, pipeline, secrets, and ALL existing config untouched.
    assert (install / "brain" / "concepts" / "my-note.md").read_text() == "my knowledge\n"
    assert (install / "pipeline" / "registry.md").read_text() == "my registry\n"
    assert (install / "config" / ".env").read_text() == "TELEGRAM_BOT_TOKEN=secret123\n"
    assert (install / "config" / "sources.md").read_text() == "my sources\n"
    assert (install / "config" / "topics.md").read_text() == "my topics\n"
    assert (install / "config" / "tags.yaml").read_text() == "my tags\n"
    assert (install / "config" / "channels.yaml").read_text() == "my channels\n"
    # The user's timezone/cadence survives — schedule.yaml is user config (P1 fix).
    assert (install / "config" / "schedule.yaml").read_text() == "timezone: Europe/Kyiv\n"
    # A config file the new release introduces IS added (only new ones land).
    assert (install / "config" / "newfeature.yaml").read_text() == "shipped: default\n"


def test_update_delivers_new_brain_frontdoor_but_not_user_concepts(tmp_path: Path) -> None:
    # A release that introduces brain/ scaffolding (templates, .base views) must
    # deliver those NEW files to an updated install — otherwise the flagship vault
    # feature is broken on every install that updated rather than reinstalled. But the
    # add-only mirror must never overwrite the user's notes, nor inject example
    # concepts into their curated concept space.
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.4.1")
    _make_incoming(incoming, version="0.5.0")
    (incoming / "brain").mkdir()
    (incoming / "brain" / "lesson-template.md").write_text("template body\n", encoding="utf-8")
    (incoming / "brain" / "lessons.base").write_text("base view\n", encoding="utf-8")
    (incoming / "brain" / "concepts").mkdir()
    (incoming / "brain" / "concepts" / "example-concept-a.md").write_text(
        "shipped example\n", encoding="utf-8"
    )

    res = _run_update(install, incoming)
    assert res.returncode == 0, res.stderr

    # NEW front-door files the release ships ARE delivered.
    assert (install / "brain" / "lesson-template.md").read_text() == "template body\n"
    assert (install / "brain" / "lessons.base").read_text() == "base view\n"
    # The user's existing concept note is untouched.
    assert (install / "brain" / "concepts" / "my-note.md").read_text() == "my knowledge\n"
    # Example concepts are NOT injected into the user's curated vault.
    assert not (install / "brain" / "concepts" / "example-concept-a.md").exists()


def test_update_takes_a_backup(tmp_path: Path) -> None:
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.1.0")
    _make_incoming(incoming, version="0.2.0")
    backup_dir = tmp_path / "backups"

    res = _run_update(install, incoming, "--backup-dir", str(backup_dir))
    assert res.returncode == 0, res.stderr
    backups = list(backup_dir.glob("*.tgz"))
    assert backups, "update.sh took no backup"


def test_update_refuses_downgrade(tmp_path: Path) -> None:
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.3.0")
    _make_incoming(incoming, version="0.2.0")

    res = _run_update(install, incoming)
    assert res.returncode != 0
    assert "downgrade" in (res.stdout + res.stderr).lower()
    # Nothing changed — old code stays.
    assert (install / "scripts" / "collect.py").read_text() == "# OLD collect\n"


def test_update_downgrade_allowed_with_force(tmp_path: Path) -> None:
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.3.0")
    _make_incoming(incoming, version="0.2.0")

    res = _run_update(install, incoming, "--force")
    assert res.returncode == 0, res.stderr
    assert (install / "scripts" / "collect.py").read_text() == "# NEW collect (fixed)\n"


def test_update_dry_run_changes_nothing(tmp_path: Path) -> None:
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.1.0")
    _make_incoming(incoming, version="0.2.0")

    res = _run_update(install, incoming, "--dry-run")
    assert res.returncode == 0, res.stderr
    # Code untouched in a dry run.
    assert (install / "scripts" / "collect.py").read_text() == "# OLD collect\n"
    assert not (install / "scripts" / "brand_new.py").exists()
    assert 'version = "0.1.0"' in (install / "pyproject.toml").read_text()


def test_update_reports_version_transition(tmp_path: Path) -> None:
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.1.0")
    _make_incoming(incoming, version="0.2.0")

    res = _run_update(install, incoming, "--dry-run")
    out = res.stdout + res.stderr
    assert "0.1.0" in out and "0.2.0" in out


def test_update_target_mode_bootstraps_a_pre_0_2_install(tmp_path: Path) -> None:
    # The first hop: an OLD install has no update.sh / version.py of its own. The
    # user runs the NEW archive's update.sh with --target pointing at that install.
    # Version comparison must still work (version.py read from the incoming archive).
    install = tmp_path / "old_install"
    incoming = tmp_path / "new_archive"
    _make_install(install, version="0.1.0")
    _make_incoming(incoming, version="0.2.0")
    # Simulate a genuinely pre-update install: no update.sh, no version.py.
    (install / "update.sh").unlink()
    (install / "scripts" / "version.py").unlink()

    res = subprocess.run(
        [_BASH, str(incoming / "update.sh"), "--yes", "--target", str(install)],
        cwd=incoming, capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    # The install now HAS the update machinery and the new code, data preserved.
    assert (install / "update.sh").exists()
    assert (install / "scripts" / "version.py").exists()
    assert (install / "scripts" / "collect.py").read_text() == "# NEW collect (fixed)\n"
    assert (install / "brain" / "concepts" / "my-note.md").read_text() == "my knowledge\n"
    assert (install / "config" / ".env").read_text() == "TELEGRAM_BOT_TOKEN=secret123\n"


def test_update_accepts_zip_archive(tmp_path: Path) -> None:
    install = tmp_path / "install"
    staging = tmp_path / "staging"
    _make_install(install, version="0.1.0")
    _make_incoming(staging / "research-brain", version="0.2.0")
    # Zip it the way `make dist` does: a single research-brain/ prefix dir.
    archive = tmp_path / "research-brain-new.zip"
    shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=staging)

    res = _run_update(install, archive)
    assert res.returncode == 0, res.stderr
    assert (install / "scripts" / "collect.py").read_text() == "# NEW collect (fixed)\n"
    assert (install / "brain" / "concepts" / "my-note.md").read_text() == "my knowledge\n"


def test_update_self_guard_survives_symlinked_source(tmp_path: Path) -> None:
    # A symlinked SOURCE that resolves to the install must be caught (rsync-on-self):
    # the guard compares PHYSICAL paths (pwd -P), so a symlink can't slip past it.
    install = tmp_path / "install"
    _make_install(install, version="0.2.0")
    link = tmp_path / "install-link"
    link.symlink_to(install)

    # SOURCE=link resolves to install; force clears the same-version gate so only the
    # physical-path self-guard stands between us and rsync copying a dir onto itself.
    res = _run_update(install, link, "--force")
    assert res.returncode != 0
    assert "itself" in (res.stdout + res.stderr).lower()


def test_update_refuses_backup_dir_inside_install(tmp_path: Path) -> None:
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.1.0")
    _make_incoming(incoming, version="0.2.0")

    res = _run_update(install, incoming, "--backup-dir", str(install / "backups"))
    assert res.returncode != 0
    assert "backup-dir" in (res.stdout + res.stderr).lower()
    # Nothing applied.
    assert (install / "scripts" / "collect.py").read_text() == "# OLD collect\n"


def test_update_clean_error_on_non_numeric_version(tmp_path: Path) -> None:
    # A pre-release / non-numeric version must produce a clean message + non-zero
    # exit, not a Python traceback, and must not touch the install.
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.1.0")
    _make_incoming(incoming, version="0.2.0rc1")

    res = _run_update(install, incoming)
    assert res.returncode != 0
    assert "traceback" not in (res.stdout + res.stderr).lower()
    assert (install / "scripts" / "collect.py").read_text() == "# OLD collect\n"


def test_update_does_not_execute_incoming_version_py_before_confirm(tmp_path: Path) -> None:
    # SECURITY: the preflight must read the incoming version as DATA (pyproject.toml),
    # never by EXECUTING the archive's scripts/version.py. Otherwise a tampered ZIP
    # runs arbitrary code the moment update.sh starts — before the user confirms.
    # A booby-trapped version.py drops a marker at import; it must never appear, and
    # the update must still succeed by reading the version from pyproject.toml.
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.1.0")
    _make_incoming(incoming, version="0.2.0")
    marker = tmp_path / "PWNED"
    (incoming / "scripts" / "version.py").write_text(
        "import pathlib\n"
        f"pathlib.Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    res = _run_update(install, incoming)
    assert not marker.exists(), "update.sh executed the incoming archive's version.py"
    assert res.returncode == 0, res.stderr
    assert 'version = "0.2.0"' in (install / "pyproject.toml").read_text()


def test_update_refuses_source_inside_install(tmp_path: Path) -> None:
    # SOURCE nested inside INSTALL (unpacked the new archive into the install) must
    # be refused — overlaying a tree into its own subdir leaves recursive junk.
    install = tmp_path / "install"
    _make_install(install, version="0.1.0")
    inside = install / "new-archive"
    _make_incoming(inside, version="0.2.0")

    res = _run_update(install, inside)
    assert res.returncode != 0
    assert "inside" in (res.stdout + res.stderr).lower()
    assert (install / "scripts" / "collect.py").read_text() == "# OLD collect\n"


def test_update_force_repairs_install_with_unreadable_version(tmp_path: Path) -> None:
    # A corrupt install (unreadable [project] version) must be repairable with
    # --force, treating the unknown installed version as older.
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.1.0")
    _make_incoming(incoming, version="0.2.0")
    (install / "pyproject.toml").write_text("[project]\nname = 'broken'\n", encoding="utf-8")

    # Without --force it refuses; with --force it repairs.
    assert _run_update(install, incoming).returncode != 0
    res = _run_update(install, incoming, "--force")
    assert res.returncode == 0, res.stderr
    assert (install / "scripts" / "collect.py").read_text() == "# NEW collect (fixed)\n"
    assert (install / "brain" / "concepts" / "my-note.md").read_text() == "my knowledge\n"


def test_update_dry_run_reports_orphaned_code_file(tmp_path: Path) -> None:
    # A code file present in the install but absent from the new release is an
    # orphan (removed/renamed upstream — the overlay never deletes it). The dry
    # run must surface it in a labeled report block with a review hint.
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.1.0")
    _make_incoming(incoming, version="0.2.0")
    (install / "scripts" / "legacy.py").write_text("# dropped upstream\n", encoding="utf-8")

    res = _run_update(install, incoming, "--dry-run")
    assert res.returncode == 0, res.stderr
    assert "orphaned (present here, not in the new release):" in res.stdout
    assert "scripts/legacy.py" in res.stdout
    assert "review & delete manually" in res.stdout


def test_update_orphan_report_never_lists_user_data(tmp_path: Path) -> None:
    # Preserved user data (config/, brain/, pipeline/, secrets) exists only in
    # the install by nature — it must NEVER appear in the orphan report.
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.1.0")
    _make_incoming(incoming, version="0.2.0")
    # Extra user files the incoming release knows nothing about.
    (install / "config" / "my-extra.yaml").write_text("mine\n", encoding="utf-8")
    (install / "pipeline" / "1-incoming").mkdir()
    (install / "pipeline" / "1-incoming" / "saved.md").write_text("mine\n", encoding="utf-8")
    # Opt-in tier-grading registry files the user creates by dropping `.example` — they
    # exist only in the install and must NOT be reported as deletable leftovers.
    (install / "sources").mkdir()
    (install / "sources" / "trusted-registry.md").write_text("my tiers\n", encoding="utf-8")
    (install / "sources" / "always-volatile-domains.md").write_text("mine\n", encoding="utf-8")
    # One genuine code orphan so the report block itself is exercised.
    (install / "scripts" / "legacy.py").write_text("# dropped upstream\n", encoding="utf-8")

    res = _run_update(install, incoming, "--dry-run")
    assert res.returncode == 0, res.stderr
    # Scope to the orphan block itself (label line through the review hint) so
    # unrelated informational lines ("preserved: brain/, ...") don't interfere.
    lines = res.stdout.splitlines()
    start = lines.index("orphaned (present here, not in the new release):")
    end = next(i for i, ln in enumerate(lines) if "review & delete manually" in ln)
    block = "\n".join(lines[start : end + 1])
    assert "scripts/legacy.py" in block
    for preserved in (
        "my-extra.yaml", "saved.md", ".env",
        "config/sources.md", "config/topics.md", "config/tags.yaml",
        "brain/", "pipeline/registry.md", "my-note.md",
        "sources/trusted-registry.md", "sources/always-volatile-domains.md",
    ):
        assert preserved not in block, f"user data leaked into report: {preserved}"


def test_update_dry_run_reports_no_orphans_line(tmp_path: Path) -> None:
    # The base fixtures ship no extra code files, so the dry run must say so
    # explicitly rather than staying silent.
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.1.0")
    _make_incoming(incoming, version="0.2.0")

    res = _run_update(install, incoming, "--dry-run")
    assert res.returncode == 0, res.stderr
    assert "no orphaned files." in res.stdout
    assert "orphaned (present here, not in the new release):" not in res.stdout


def test_update_real_run_never_deletes_orphans(tmp_path: Path) -> None:
    # The report is informational only: a real update still leaves the orphan
    # in place (safe overlay, never --delete) and exits 0.
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.1.0")
    _make_incoming(incoming, version="0.2.0")
    (install / "scripts" / "legacy.py").write_text("# dropped upstream\n", encoding="utf-8")

    res = _run_update(install, incoming)
    assert res.returncode == 0, res.stderr
    assert (install / "scripts" / "legacy.py").read_text() == "# dropped upstream\n"
    # The overlay itself still applied.
    assert (install / "scripts" / "collect.py").read_text() == "# NEW collect (fixed)\n"


def test_update_applies_same_length_code_change(tmp_path: Path) -> None:
    # rsync's default size+mtime quick-check would SKIP a same-length edit; the -c
    # checksum flag must catch it. Both strings are the same byte length.
    install = tmp_path / "install"
    incoming = tmp_path / "incoming"
    _make_install(install, version="0.1.0")
    _make_incoming(incoming, version="0.2.0")
    (install / "scripts" / "collect.py").write_text("# collect vA\n", encoding="utf-8")
    (incoming / "scripts" / "collect.py").write_text("# collect vB\n", encoding="utf-8")

    res = _run_update(install, incoming)
    assert res.returncode == 0, res.stderr
    assert (install / "scripts" / "collect.py").read_text() == "# collect vB\n"


def test_update_runs_post_update_config_check(tmp_path: Path) -> None:
    """After the overlay, update.sh runs the NEW validate_config so a schema
    change surfaces immediately — not at the next failed cron run."""
    install, incoming = tmp_path / "install", tmp_path / "incoming"
    _make_install(install, version="0.3.0")
    _make_incoming(incoming, version="0.4.0")
    (incoming / "scripts" / "validate_config.py").write_text(
        "print('CONFIG-CHECK-RAN')\n", encoding="utf-8"
    )
    result = _run_update(install, incoming)
    assert result.returncode == 0, result.stderr
    assert "CONFIG-CHECK-RAN" in result.stdout
    assert "config check" in result.stdout.lower()


def test_update_config_check_failure_warns_but_update_succeeds(tmp_path: Path) -> None:
    install, incoming = tmp_path / "install", tmp_path / "incoming"
    _make_install(install, version="0.3.0")
    _make_incoming(incoming, version="0.4.0")
    (incoming / "scripts" / "validate_config.py").write_text(
        "import sys; print('bad key'); sys.exit(2)\n", encoding="utf-8"
    )
    result = _run_update(install, incoming)
    assert result.returncode == 0, result.stderr  # the update itself succeeded
    assert "update itself succeeded" in result.stdout.lower()


def test_update_ps1_exists_and_keeps_the_same_safety_contract() -> None:
    """Windows installs could never update (install.ps1 but no update.ps1).
    The PowerShell port must preserve the same guarantees; this static check
    pins the load-bearing ones."""
    ps1 = PROJECT_ROOT / "update.ps1"
    assert ps1.exists(), "update.ps1 missing — Windows installs cannot update"
    text = ps1.read_text(encoding="utf-8")
    # Preserved user data: the same exclusion set as update.sh's DATA_EXCLUDES.
    for name in ("brain", "pipeline", "config", ".venv", "__pycache__", ".git"):
        assert name in text, f"update.ps1 lost the {name!r} exclusion"
    # Backup before any change, no-downgrade guard, dry-run, config preserved.
    for needle in ("backup", "DryRun", "downgrade", "version.py"):
        assert needle.lower() in text.lower(), f"update.ps1 lost {needle!r}"
    # Overlay must never mirror-delete user files.
    assert "/MIR" not in text and "/PURGE" not in text
    # Parity with update.sh (docs/updating.md promises BOTH on Windows under
    # "same contract"): add-only brain/ scaffolding with concepts/ never
    # injected, and the informational orphan report.
    assert "concepts" in text, "update.ps1 lost the brain-scaffolding concepts/ exclusion"
    assert "orphaned (present here, not in the new release)" in text, (
        "update.ps1 lost the orphan report"
    )
    for flag in ("/XC", "/XN", "/XO"):
        assert flag in text, f"update.ps1 lost the add-only {flag} robocopy flag"
    # User-created sources/*.md are data: never listed as orphans.
    assert "*.example.md" in text, "update.ps1 orphan walk lost the sources/*.example.md boundary"
    # The YAML config-format migration OFFER (surfaced, never auto-applied).
    assert "migrate-config" in text, "update.ps1 lost the YAML config migration offer"


_PWSH = shutil.which("pwsh")


@pytest.mark.skipif(
    sys.platform != "win32" or _PWSH is None,
    reason="native Windows and pwsh are required for the robocopy lifecycle",
)
def test_update_ps1_end_to_end_overlay_preserve_backup_downgrade() -> None:
    """The .ps1 twin is destructive-overlay code that had ZERO executions
    anywhere (CI only AST-parses it; the bash twin gets ~25 real e2e tests) —
    its first real run used to be on a user's Windows box against their vault.
    This is the real lifecycle, mirroring the bash e2e: refuse a downgrade
    before any change, then overlay code, preserve every byte of user data,
    and take the backup zip first. Runs on windows-latest in CI; skipped on
    other platforms even when cross-platform PowerShell is installed."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        install, incoming = tmp_path / "install", tmp_path / "incoming"
        _make_install(install, version="0.3.0")
        _make_incoming(incoming, version="0.4.0")
        older = tmp_path / "older"
        _make_incoming(older, version="0.2.0")
        backups = tmp_path / "backups"
        backups.mkdir()

        def run_ps(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [_PWSH, "-NoProfile", "-File", str(PROJECT_ROOT / "update.ps1"), *args],
                capture_output=True, text=True, timeout=300,
            )

        # 1. Downgrade refused BEFORE any change — no overlay, no backup.
        refused = run_ps(str(older), "-Target", str(install), "-Yes",
                         "-BackupDir", str(backups))
        assert refused.returncode != 0
        assert "downgrade" in (refused.stdout + refused.stderr).lower()
        assert (install / "scripts" / "collect.py").read_text() == "# OLD collect\n"
        assert not list(backups.glob("*.zip")), "refused run must not write a backup"

        # 2. Real update: overlay lands, data survives, backup exists.
        result = run_ps(str(incoming), "-Target", str(install), "-Yes",
                        "-BackupDir", str(backups))
        assert result.returncode == 0, result.stdout + result.stderr
        assert (install / "scripts" / "collect.py").read_text() == "# NEW collect (fixed)\n"
        assert (install / "scripts" / "brand_new.py").exists()
        assert (install / "skills" / "old.md").read_text() == "new skill body\n"
        # User data + secrets + customized config: byte-for-byte survivors.
        assert (install / "config" / ".env").read_text() == "TELEGRAM_BOT_TOKEN=secret123\n"
        assert (install / "config" / "schedule.yaml").read_text() == "timezone: Europe/Kyiv\n"
        assert (install / "config" / "sources.md").read_text() == "my sources\n"
        assert (install / "brain" / "concepts" / "my-note.md").read_text() == "my knowledge\n"
        assert (install / "pipeline" / "registry.md").read_text() == "my registry\n"
        assert list(backups.glob("research-brain-backup-0.3.0-*.zip")), "backup zip missing"


@pytest.mark.skipif(_PWSH is None, reason="pwsh is not installed on this box")
def test_powershell_scripts_parse_cleanly() -> None:
    """A syntax error in the PowerShell ports would otherwise ship undetected —
    the POSIX suite never executes them (CI runs this on windows-latest)."""
    for name in ("install.ps1", "update.ps1"):
        path = PROJECT_ROOT / name
        command = (
            "$t=$null;$e=$null;"
            f"[System.Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$t,[ref]$e)|Out-Null;"
            "if($e.Count){$e|ForEach-Object{Write-Error $_.Message}; exit 1}"
        )
        result = subprocess.run(
            [_PWSH, "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"{name} does not parse: {result.stderr}"


def test_update_surfaces_yaml_config_migration_offer(tmp_path: Path) -> None:
    """A legacy install (sources.md, no sources.yaml) gets the migration OFFER —
    plain text naming `schema.py migrate-config` — and nothing is auto-rewritten
    (BACKLOG plan step 2: surface, never auto-rewrite)."""
    install, incoming = tmp_path / "install", tmp_path / "incoming"
    _make_install(install, version="0.6.0")
    _make_incoming(incoming, version="0.7.0")
    result = _run_update(install, incoming)
    assert result.returncode == 0, result.stderr
    assert "migrate-config" in result.stdout
    assert "sources.md" in result.stdout
    # Surfaced only — the update itself never creates the YAML twins.
    assert not (install / "config" / "sources.yaml").exists()
    assert not (install / "config" / "topics.yaml").exists()


def test_update_offers_no_migration_when_yaml_already_active(tmp_path: Path) -> None:
    install, incoming = tmp_path / "install", tmp_path / "incoming"
    _make_install(install, version="0.6.0")
    (install / "config" / "sources.yaml").write_text("categories: []\n", encoding="utf-8")
    _make_incoming(incoming, version="0.7.0")
    result = _run_update(install, incoming)
    assert result.returncode == 0, result.stderr
    assert "migrate-config" not in result.stdout


def test_archive_shipped_yaml_twins_never_orphan_a_legacy_config(tmp_path: Path) -> None:
    """0.8.0 ships EMPTY config/sources.yaml + topics.yaml in the archive. The
    add-only config merge must NOT inject them onto an unmigrated legacy
    install: a twin appearing next to real sources.md flips
    legacy_md_needs_migration() to False, silences every migrate-config
    pointer, and the runtime then reads an empty config — the exact silent
    orphan the loud-refusal contract exists to prevent (found by review on a
    simulated 0.7.0 install)."""
    install, incoming = tmp_path / "install", tmp_path / "incoming"
    _make_install(install, version="0.6.0")
    _make_incoming(incoming, version="0.8.0")
    # A REAL, parseable legacy config (the fixture's placeholder text is opaque
    # to the md parser, and this scenario is precisely about real user rows).
    (install / "config" / "sources.md").write_text(
        "## Category: ai-agents\n\n"
        "| URL | Type | Tier | Priority | Filter | Active |\n"
        "|---|---|---|---|---|---|\n"
        "| https://example.com/feed.xml | rss | high | medium | all | yes |\n",
        encoding="utf-8",
    )
    # The 0.8.0 archive ships the empty twins.
    (incoming / "config").mkdir(exist_ok=True)
    (incoming / "config" / "sources.yaml").write_text(
        "schema_version: 2\ncategories: []\n", encoding="utf-8"
    )
    (incoming / "config" / "topics.yaml").write_text(
        "schema_version: 2\ntopics: []\n", encoding="utf-8"
    )
    result = _run_update(install, incoming)
    assert result.returncode == 0, result.stderr
    # The twins were NOT injected next to the user's real .md config…
    assert not (install / "config" / "sources.yaml").exists()
    assert not (install / "config" / "topics.yaml").exists()
    # …so the migration offer still prints, and the legacy state stays loud.
    assert "migrate-config" in result.stdout

    from scripts.sources import store

    assert store.legacy_md_needs_migration(install / "config") is True
