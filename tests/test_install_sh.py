"""
test_install_sh.py — behavioral contract of the POSIX installer.

`./install.sh` (and `make install`, which is just a wrapper) used to end with the
FULL interactive config interview by default, while FIRST-RUN.md billed the step
as "installs uv, venv, dependencies" and then told the user to configure AGAIN
via the spoken wizard. The contract is now: bare install = dependencies only,
ending with a hint naming both configuration paths; the terminal interview runs
only behind the explicit `--configure` flag.

The tests run the real script with a stubbed `uv` on PATH (every invocation is
logged, nothing is installed), so the flow is exercised hermetically: no
network, no venv, no real config touched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(_BASH is None, reason="bash is not available on this box")


@pytest.fixture
def install_root(tmp_path: Path) -> Path:
    """A throwaway 'unpacked archive': install.sh + the config template it seeds."""
    root = tmp_path / "unpacked"
    (root / "config").mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "install.sh", root / "install.sh")
    (root / "config" / ".env.example").write_text(
        "SMTP_PASSWORD=\nTELEGRAM_BOT_TOKEN=\n", encoding="utf-8"
    )

    # Stub `uv`: log every invocation, answer --version, succeed at everything —
    # unless UV_FAIL_ON is set and matches the argv (fault injection for the
    # configure-failure envelope test).
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_stub = bin_dir / "uv"
    uv_stub.write_text(
        '#!/bin/sh\nprintf \'uv %s\\n\' "$*" >> "$UV_LOG"\n'
        'if [ "$1" = "--version" ]; then echo "uv 0.0.0"; fi\n'
        'case "$*" in *"${UV_FAIL_ON:-@@never@@}"*) exit 1 ;; esac\nexit 0\n',
        encoding="utf-8",
    )
    uv_stub.chmod(0o755)
    return root


def _run_install(
    root: Path, *args: str, uv_fail_on: str | None = None
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run install.sh with the stub uv first on PATH; return (result, uv call log)."""
    uv_log = root.parent / "uv-calls.log"
    uv_log.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = f"{root.parent / 'bin'}{os.pathsep}{env['PATH']}"
    env["UV_LOG"] = str(uv_log)
    if uv_fail_on is not None:
        env["UV_FAIL_ON"] = uv_fail_on
    result = subprocess.run(
        [str(_BASH), str(root / "install.sh"), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    return result, uv_log.read_text(encoding="utf-8")


def test_bare_install_is_dependencies_only(install_root: Path) -> None:
    """No flag = deps + .env seed, and NEVER the config interview."""
    result, uv_calls = _run_install(install_root)
    assert result.returncode == 0, result.stderr
    assert "sync --no-dev" in uv_calls
    assert "configure.py" not in uv_calls, (
        "bare install.sh must not ambush the user with the full config interview"
    )
    # The .env template was still seeded (that's setup, not configuration).
    assert (install_root / "config" / ".env").exists()


def test_bare_install_hint_names_both_config_paths(install_root: Path) -> None:
    """The closing hint must name the recommended spoken wizard AND the advanced
    terminal interview, so a deps-only install never dead-ends."""
    result, _ = _run_install(install_root)
    assert result.returncode == 0, result.stderr
    assert "let's set up sources" in result.stdout
    assert "--configure" in result.stdout


def test_configure_flag_runs_the_interview(install_root: Path) -> None:
    result, uv_calls = _run_install(install_root, "--configure")
    assert result.returncode == 0, result.stderr
    assert "configure.py" in uv_calls


def test_legacy_no_configure_flag_still_accepted(install_root: Path) -> None:
    """--no-configure predates the flip (docs and muscle memory may carry it);
    it must stay a valid spelling of the new default, not an unknown-arg error."""
    result, uv_calls = _run_install(install_root, "--no-configure")
    assert result.returncode == 0, result.stderr
    assert "configure.py" not in uv_calls


def test_help_documents_the_configure_flag(install_root: Path) -> None:
    result, _ = _run_install(install_root, "--help")
    assert result.returncode == 0, result.stderr
    assert "--configure" in result.stdout


def test_configure_failure_envelope_defers_to_the_configurator(install_root: Path) -> None:
    """configure.py may exit non-zero having KEPT the user's answers (the no-RSS
    advisory) or having restored them (invalid config) — the wrapper can't know
    which, so its envelope must not overclaim 'configuration failed'; it defers
    to the configurator's own message. The exit stays non-zero for automation."""
    result, uv_calls = _run_install(
        install_root, "--configure", uv_fail_on="configure.py"
    )
    assert result.returncode == 1
    assert "configure.py" in uv_calls
    combined = result.stdout + result.stderr
    assert "configuration failed" not in combined
    assert "message above" in combined
    assert "--configure" in combined  # re-run path named
