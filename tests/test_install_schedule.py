"""Tests for scripts/install_schedule.py — one-time schedule registration.

Writing `config/schedule.yaml` only declares a cadence; something still has to
register a recurring run, and until now that was a hand-copied crontab block.
`setup_check.py` already DETECTS registration (it greps `crontab -l` for a line
naming this install), so the missing half was generation — this script closes
it, and its output is shaped so that detection succeeds.

The contract under test:

  - the emitted block is derived from `config/schedule.yaml` (cadence + timezone),
    never invented: `CRON_TZ` mirrors `timezone:`, the weekly line runs at
    `digest.cron`, the headless collect line at `collect.cron`;
  - every command names this install by ABSOLUTE path — that is exactly what
    `setup_check.py`'s probe looks for, and cron has no useful cwd;
  - `%` is escaped as `\\%` in cron commands (an unescaped `%` becomes a newline
    in crontab, silently truncating the command);
  - the three run paths emit the documented commands for that path and nothing
    from another path;
  - `--apply` MERGES into the existing crontab (never replaces it) and is
    idempotent — a second apply does not duplicate the block;
  - without `--apply` nothing is registered; the file is written and the exact
    manual command is printed.

The `crontab` binary is faked on PATH, so no test ever touches the real one.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import install_schedule

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SCHEDULE_YAML = """\
collect:
  cron: "0 7 */2 * *"
curate:
  cron: "0 8 * * 1"
synthesis:
  cron: "30 8 * * 1"
digest:
  cron: "0 9 * * 1"
timezone: "Europe/Berlin"
"""


@pytest.fixture()
def install(tmp_path: Path) -> Path:
    """A minimal fake install root: config/schedule.yaml + the wrappers."""
    root = tmp_path / "research-brain"
    (root / "config").mkdir(parents=True)
    (root / "schedule").mkdir(parents=True)
    (root / "config" / "schedule.yaml").write_text(SCHEDULE_YAML, encoding="utf-8")
    for wrapper in ("claude-run.sh", "codex-run.sh"):
        (root / "schedule" / wrapper).write_text("#!/bin/sh\n", encoding="utf-8")
    return root


def _block(root: Path, path: str = "claude") -> str:
    return install_schedule.render_block(root=root, run_path=path)


# --------------------------------------------------------------------------- #
# Derived from config, not invented
# --------------------------------------------------------------------------- #


def test_cron_tz_mirrors_the_configured_timezone(install: Path) -> None:
    assert "CRON_TZ=Europe/Berlin" in _block(install)


def test_weekly_line_runs_at_the_configured_digest_cron(install: Path) -> None:
    weekly = [ln for ln in _block(install).splitlines() if "claude-run.sh" in ln]
    assert len(weekly) == 1, "expected exactly one weekly line"
    assert weekly[0].startswith("0 9 * * 1 "), weekly[0]


def test_headless_collect_line_runs_at_the_configured_collect_cron(install: Path) -> None:
    collect = [ln for ln in _block(install, "headless").splitlines() if "collect.py" in ln]
    assert len(collect) == 1
    assert collect[0].startswith("0 7 */2 * * "), collect[0]


def test_missing_schedule_config_is_a_clean_error(tmp_path: Path) -> None:
    with pytest.raises(install_schedule.ScheduleInstallError) as excinfo:
        install_schedule.render_block(root=tmp_path, run_path="claude")
    assert "schedule.yaml" in str(excinfo.value)


def test_unknown_run_path_is_rejected(install: Path) -> None:
    with pytest.raises(install_schedule.ScheduleInstallError):
        install_schedule.render_block(root=install, run_path="telepathy")


# --------------------------------------------------------------------------- #
# Cron mechanics
# --------------------------------------------------------------------------- #


def test_every_command_names_the_install_by_absolute_path(install: Path) -> None:
    """setup_check.py detects registration by finding this path in `crontab -l`."""
    for run_path in ("claude", "codex", "headless"):
        for line in _block(install, run_path).splitlines():
            if not line or line.startswith("#") or line.startswith("CRON_TZ="):
                continue
            assert str(install.resolve()) in line, f"{run_path}: {line}"


def test_percent_is_escaped_for_crontab(install: Path) -> None:
    """An unescaped `%` becomes a newline in crontab — it would truncate the
    command and leave a half-written digest path behind."""
    block = _block(install, "headless")
    assert "date +\\%F" in block
    for line in block.splitlines():
        # every literal % must be backslash-escaped
        for idx, ch in enumerate(line):
            if ch == "%":
                assert idx and line[idx - 1] == "\\", f"unescaped % in: {line}"


def test_the_watchdog_is_included_and_daily(install: Path) -> None:
    lines = [ln for ln in _block(install).splitlines() if "health_alert.py" in ln]
    assert len(lines) == 1
    assert lines[0].startswith("0 10 * * * "), lines[0]


# --------------------------------------------------------------------------- #
# The three run paths
# --------------------------------------------------------------------------- #


def test_claude_path_uses_the_claude_wrapper_only(install: Path) -> None:
    block = _block(install, "claude")
    assert "schedule/claude-run.sh" in block
    assert "codex-run.sh" not in block
    assert "build_digest.py" not in block, "the agentic wrapper runs weekly-run, not the headless chain"


def test_codex_path_uses_the_codex_wrapper_only(install: Path) -> None:
    block = _block(install, "codex")
    assert "schedule/codex-run.sh" in block
    assert "claude-run.sh" not in block


def test_codex_cron_pins_a_cli_outside_minimal_cron_path(
    install: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import install_schedule

    original_which = install_schedule.shutil.which
    monkeypatch.setattr(
        install_schedule.shutil,
        "which",
        lambda name: "/opt/app/Codex/codex" if name == "codex" else original_which(name),
    )
    block = _block(install, "codex")
    assert "CODEX_RUN_BIN=/opt/app/Codex/codex " in block


def test_headless_path_runs_the_documented_chain(install: Path) -> None:
    """sanitize → build → deliver → heartbeat, in one gated `&&` chain."""
    weekly = [ln for ln in _block(install, "headless").splitlines() if "build_digest.py" in ln]
    assert len(weekly) == 1
    line = weekly[0]
    order = [
        line.index("sanitize_incoming.py"),
        line.index("build_digest.py"),
        line.index("delivery/deliver.py"),
        line.index("health.py record"),
    ]
    assert order == sorted(order), f"chain out of order: {line}"
    assert "&&" in line, "steps must be gated, not sequenced with ;"


def test_agentic_paths_use_the_wrapper_not_a_bare_interpreter(install: Path) -> None:
    """The wrappers own the venv/python guard — cron must call them directly."""
    for run_path, wrapper in (("claude", "claude-run.sh"), ("codex", "codex-run.sh")):
        weekly = [ln for ln in _block(install, run_path).splitlines() if wrapper in ln]
        assert weekly and ".venv/bin/python3" not in weekly[0]


# --------------------------------------------------------------------------- #
# Registering
# --------------------------------------------------------------------------- #


def _fake_crontab(tmp_path: Path, *, existing: str = "") -> Path:
    """A `crontab` shim: `-l` prints the store, `-` replaces it from stdin."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    store = tmp_path / "crontab.store"
    store.write_text(existing, encoding="utf-8")
    shim = bindir / "crontab"
    # Absolute /bin/cat: PATH deliberately holds only this bin dir (see _run_cli),
    # so the shim cannot rely on PATH lookups of its own.
    shim.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "-l" ]; then /bin/cat "{store}"; exit 0; fi\n'
        f'if [ "$1" = "-" ]; then /bin/cat > "{store}"; exit 0; fi\n'
        "exit 2\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return store


def _run_cli(install: Path, tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # PATH holds ONLY the test's own bin dir — never /usr/bin. `--apply` runs
    # `crontab -`, which REPLACES the invoking user's real crontab: a PATH that
    # can reach /usr/bin/crontab makes this suite rewrite the developer's
    # schedule (it did, once, in exactly the test that provides no shim). The
    # script needs nothing else from PATH — python is invoked by absolute path.
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    env = {
        "PATH": str(bindir),
        "HOME": str(tmp_path),
        "LC_ALL": "C",
        "PYTHONPATH": str(PROJECT_ROOT),
    }
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "install_schedule.py"), *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_writes_the_paste_ready_file_and_registers_nothing(install: Path, tmp_path: Path) -> None:
    store = _fake_crontab(tmp_path, existing="# pre-existing\n")
    res = _run_cli(install, tmp_path, "--root", str(install), "--path", "claude")
    assert res.returncode == 0, res.stderr
    out_file = install / "crontab-research-brain.txt"
    assert out_file.is_file(), "paste-ready file not written"
    assert "claude-run.sh" in out_file.read_text(encoding="utf-8")
    # Nothing registered without --apply, and the printed next step says how.
    assert store.read_text(encoding="utf-8") == "# pre-existing\n"
    assert "crontab" in res.stdout


def test_apply_merges_into_the_existing_crontab(install: Path, tmp_path: Path) -> None:
    store = _fake_crontab(tmp_path, existing="0 5 * * * /usr/bin/backup.sh\n")
    res = _run_cli(install, tmp_path, "--root", str(install), "--path", "claude", "--apply")
    assert res.returncode == 0, res.stderr
    registered = store.read_text(encoding="utf-8")
    assert "/usr/bin/backup.sh" in registered, "an unrelated entry was destroyed"
    assert "claude-run.sh" in registered


def test_apply_twice_does_not_duplicate(install: Path, tmp_path: Path) -> None:
    store = _fake_crontab(tmp_path)
    for _ in range(2):
        res = _run_cli(install, tmp_path, "--root", str(install), "--path", "claude", "--apply")
        assert res.returncode == 0, res.stderr
    registered = store.read_text(encoding="utf-8")
    assert registered.count("claude-run.sh") == 1, registered


def test_apply_replaces_a_previously_installed_block(install: Path, tmp_path: Path) -> None:
    """Switching paths rewrites our block instead of stacking a second one."""
    store = _fake_crontab(tmp_path)
    assert _run_cli(install, tmp_path, "--root", str(install), "--path", "codex", "--apply").returncode == 0
    assert _run_cli(install, tmp_path, "--root", str(install), "--path", "claude", "--apply").returncode == 0
    registered = store.read_text(encoding="utf-8")
    assert "claude-run.sh" in registered
    assert "codex-run.sh" not in registered, "the old block was left behind"


def test_missing_crontab_binary_fails_loudly(install: Path, tmp_path: Path) -> None:
    """No scheduler on the box → a clear message, not a silent no-op.

    The bin dir is deliberately empty AND PATH excludes the system dirs, so the
    real `/usr/bin/crontab` cannot be reached (see `_run_cli`).
    """
    res = _run_cli(install, tmp_path, "--root", str(install), "--path", "claude", "--apply")
    assert res.returncode != 0
    assert "crontab" in (res.stderr + res.stdout).lower()
