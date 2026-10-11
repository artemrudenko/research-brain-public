"""Smoke tests for schedule/codex-run.sh — the Codex/Cowork cron wrapper.

This is the "C. Codex" scheduling path (docs/scheduling.md): OS cron calls the
wrapper, which `exec`s `codex exec` non-interactively against the gated weekly
pipeline. Its whole job is a correct hand-off, so the contract under test is:

  - it invokes the `exec` subcommand of the `codex` CLI;
  - the weekly-run task reaches codex as ONE argv argument: a prompt naming
    `schedule/weekly-run.md` (path, not content) plus the take-the-run-lock
    instruction (the wrapper itself takes no lock — serialization is delegated
    to weekly-run.md / scripts/run_lock.py);
  - `--cd` points at the project root resolved from the script's own location,
    so cron needs no pre-set cwd (the wrapper never cd's, reads no config);
  - the non-interactive sandbox flags are pinned: `--sandbox workspace-write`,
    `-c approval_policy=never`, and network access for source collection;
  - `CODEX_PROFILE` (set and non-empty) adds `--profile <name>`, otherwise the
    flag is absent — including when the variable is set but EMPTY;
  - the exit status is codex's own (`exec` replaces the shell), so cron sees
    failures.

Everything runs against a fake `codex` shim on a controlled PATH — hermetic,
no Codex CLI required, nothing real executes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODEX_RUN_SH = PROJECT_ROOT / "schedule" / "codex-run.sh"
WEEKLY_RUN_MD = PROJECT_ROOT / "schedule" / "weekly-run.md"
SHARED_LIB_SH = PROJECT_ROOT / "schedule" / "_agentic-run.sh"

# `or ""` keeps the type a plain str for subprocess argv; "" still skips.
_BASH = shutil.which("bash") or ""
pytestmark = pytest.mark.skipif(not _BASH, reason="bash required for codex-run.sh")

# System dirs that provide the script's only external helper (`dirname`).
# Deliberately excludes /usr/local/bin, /opt/homebrew/bin, ~/.local/bin etc.,
# so a REAL codex install on the developer's box can never be picked up.
_SYSTEM_PATH = "/usr/bin:/bin"


def _write_codex_shim(bindir: Path, record_dir: Path, *, exit_code: int) -> None:
    """A fake `codex` that records argv, stdin, $PATH and OPENAI_API_KEY, then exits."""
    argv_file = record_dir / "argv.txt"
    stdin_file = record_dir / "stdin.txt"
    path_file = record_dir / "path.txt"
    key_file = record_dir / "key.txt"
    shim = bindir / "codex"
    shim.write_text(
        "#!/bin/sh\n"
        f'printf \'%s\\n\' "$@" > "{argv_file}"\n'
        f'cat > "{stdin_file}"\n'
        f'printf \'%s\' "$PATH" > "{path_file}"\n'
        f'printf \'%s\' "${{OPENAI_API_KEY:-}}" > "{key_file}"\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)


def _write_python_shim(path: Path, *, version: str, ok: bool) -> None:
    """A fake `python3`: prints `Python <version>` for -V, and for the guard's
    `-c 'import sys; ...'` snippet exits 0 (>=3.11) or 1 (too old)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f'  -V|--version) echo "Python {version}"; exit 0 ;;\n'
        "esac\n"
        f"exit {0 if ok else 1}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _copy_wrapper_into_fake_root(root: Path) -> Path:
    """Copy codex-run.sh into <root>/schedule/ so its ROOT resolves to <root>.

    This lets a test own the whole tree the wrapper reads (.venv, config/.env)
    without touching the real repo — the wrapper derives ROOT from its own
    location, so a copy relocates every ROOT-relative lookup. The shared
    preamble it sources (`_agentic-run.sh`, which owns that ROOT resolution and
    the interpreter guard) travels with it.
    """
    sched = root / "schedule"
    sched.mkdir(parents=True, exist_ok=True)
    for src in (CODEX_RUN_SH, SHARED_LIB_SH):
        dest = sched / src.name
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        dest.chmod(0o755)
    return sched / CODEX_RUN_SH.name


def _run_fake_root_wrapper(
    tmp_path: Path,
    *,
    venv_python: tuple[str, bool] | None = None,
    path_python: tuple[str, bool] | None = None,
    env_file: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str], str, str]:
    """Run codex-run.sh from a fully test-owned fake install root.

    Returns (process, recorded codex argv, recorded $PATH, recorded OPENAI_API_KEY).
    `venv_python`/`path_python` are (version, is_ge_311) for the shims placed at
    <root>/.venv/bin/python3 and on PATH respectively; `env_file` seeds
    <root>/config/.env.
    """
    root = tmp_path / "install"
    wrapper = _copy_wrapper_into_fake_root(root)
    bindir = tmp_path / "bin"
    record_dir = tmp_path / "record"
    bindir.mkdir(parents=True, exist_ok=True)
    record_dir.mkdir(parents=True, exist_ok=True)
    _write_codex_shim(bindir, record_dir, exit_code=0)
    if venv_python is not None:
        _write_python_shim(
            root / ".venv" / "bin" / "python3", version=venv_python[0], ok=venv_python[1]
        )
    if path_python is not None:
        _write_python_shim(bindir / "python3", version=path_python[0], ok=path_python[1])
    if env_file is not None:
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "config" / ".env").write_text(env_file, encoding="utf-8")

    env: dict[str, str] = {
        "PATH": f"{bindir}:{_SYSTEM_PATH}",
        "HOME": str(tmp_path),
        "LC_ALL": "C",
    }
    if extra_env:
        env.update(extra_env)

    res = subprocess.run(
        [_BASH, str(wrapper)],
        cwd=tmp_path,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    argv_file = record_dir / "argv.txt"
    argv = argv_file.read_text(encoding="utf-8").splitlines() if argv_file.exists() else []
    path_file = record_dir / "path.txt"
    recorded_path = path_file.read_text(encoding="utf-8") if path_file.exists() else ""
    key_file = record_dir / "key.txt"
    recorded_key = key_file.read_text(encoding="utf-8") if key_file.exists() else ""
    return res, argv, recorded_path, recorded_key


def _run_wrapper(
    tmp_path: Path,
    *,
    shim_exit: int = 0,
    extra_env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str], str]:
    """Run the real codex-run.sh with the shim first on PATH.

    Returns (completed process, recorded argv lines, recorded stdin). The env is
    built from scratch (not inherited) so the test is immune to a real `codex`
    or a leaked CODEX_PROFILE in the developer's environment.
    """
    bindir = tmp_path / "bin"
    record_dir = tmp_path / "record"
    bindir.mkdir(exist_ok=True)
    record_dir.mkdir(exist_ok=True)
    _write_codex_shim(bindir, record_dir, exit_code=shim_exit)

    env: dict[str, str] = {
        "PATH": f"{bindir}:{_SYSTEM_PATH}",
        "HOME": str(tmp_path),
        "LC_ALL": "C",
    }
    if extra_env:
        env.update(extra_env)

    res = subprocess.run(
        [_BASH, str(CODEX_RUN_SH)],
        cwd=cwd or tmp_path,  # never the repo: proves no-cwd-assumption (cron)
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    argv_file = record_dir / "argv.txt"
    stdin_file = record_dir / "stdin.txt"
    argv = argv_file.read_text(encoding="utf-8").splitlines() if argv_file.exists() else []
    stdin = stdin_file.read_text(encoding="utf-8") if stdin_file.exists() else ""
    return res, argv, stdin


def _flag_value(argv: list[str], flag: str) -> str:
    """The argument following `flag` (asserts the flag is present exactly once)."""
    assert argv.count(flag) == 1, f"{flag} appears {argv.count(flag)} times in {argv}"
    return argv[argv.index(flag) + 1]


def test_wrapper_is_executable_for_direct_cron_invocation() -> None:
    # The documented crontab line calls the script by absolute path with no
    # `bash` prefix, so the exec bit (tracked as 100755 in git) is contractual.
    assert os.access(CODEX_RUN_SH, os.X_OK), "codex-run.sh lost its executable bit"


def test_codex_run_bash_syntax_ok() -> None:
    res = subprocess.run(
        [_BASH, "-n", str(CODEX_RUN_SH)], capture_output=True, text=True, timeout=30
    )
    assert res.returncode == 0, res.stderr


def test_invokes_codex_exec_with_noninteractive_sandbox_flags(tmp_path: Path) -> None:
    res, argv, _ = _run_wrapper(tmp_path)
    assert res.returncode == 0, res.stderr
    assert argv, "codex shim was never invoked"
    # `codex exec` — the non-interactive subcommand, not a bare `codex` REPL.
    assert argv[0] == "exec"
    # Unattended-run flags the header documents for cron: sandboxed writes, no
    # approval prompts (a prompt would hang a cron run forever).
    assert _flag_value(argv, "--sandbox") == "workspace-write"
    configs = [argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "-c"]
    assert configs == ["approval_policy=never", "sandbox_workspace_write.network_access=true"]


def test_weekly_run_task_reaches_codex_as_single_prompt_arg(tmp_path: Path) -> None:
    res, argv, stdin = _run_wrapper(tmp_path)
    assert res.returncode == 0, res.stderr
    # The task travels by argv, not stdin.
    assert stdin == ""
    # Exactly one argv entry names the task file — and that same entry carries
    # the run-lock instruction. Both living in ONE argument proves $PROMPT kept
    # its quoting (a de-quoting regression would shatter it into many words).
    prompt_args = [a for a in argv if "schedule/weekly-run.md" in a]
    assert len(prompt_args) == 1, f"expected one prompt arg, got {argv}"
    prompt = prompt_args[0]
    assert prompt == argv[-1], "prompt must be the final codex argument"
    # The wrapper itself takes no lock — it delegates serialization to the
    # prompt ("take the run lock first"), so that instruction is load-bearing.
    assert "run lock" in prompt.lower()
    # Steps are gated and a failed step aborts the run — the whole point of
    # weekly-run.md over four independent timers.
    assert "gated" in prompt.lower()
    assert "stop" in prompt.lower()


def test_prompt_references_a_real_task_file() -> None:
    # The prompt hands codex a PATH (relative to --cd), not file content — so
    # the referenced file must exist at the root the wrapper passes.
    assert WEEKLY_RUN_MD.is_file(), "prompt points codex at a missing task file"


def test_cd_flag_resolves_project_root_from_any_cwd(tmp_path: Path) -> None:
    # Cron starts the wrapper from an arbitrary cwd ($HOME, typically). ROOT is
    # resolved from the script's own location, so --cd must still name the repo.
    elsewhere = tmp_path / "some" / "random" / "cwd"
    elsewhere.mkdir(parents=True)
    res, argv, _ = _run_wrapper(tmp_path, cwd=elsewhere)
    assert res.returncode == 0, res.stderr
    assert Path(_flag_value(argv, "--cd")).resolve() == PROJECT_ROOT


def test_codex_exit_status_propagates_exactly(tmp_path: Path) -> None:
    # `exec` replaces the shell with codex, so the wrapper's status IS codex's —
    # a distinctive non-zero code must come through unchanged for cron to report.
    res, argv, _ = _run_wrapper(tmp_path, shim_exit=7)
    assert argv, "codex shim was never invoked"
    assert res.returncode == 7


def test_codex_profile_env_adds_profile_flag(tmp_path: Path) -> None:
    res, argv, _ = _run_wrapper(tmp_path, extra_env={"CODEX_PROFILE": "rb-synthesizer"})
    assert res.returncode == 0, res.stderr
    assert argv[0] == "exec"
    assert _flag_value(argv, "--profile") == "rb-synthesizer"
    # The tiered invocation keeps the same task and sandbox flags.
    assert _flag_value(argv, "--sandbox") == "workspace-write"
    assert "schedule/weekly-run.md" in argv[-1]


def test_blank_codex_profile_is_ignored(tmp_path: Path) -> None:
    # `CODEX_PROFILE=` (set but empty, e.g. from a crontab line) must behave
    # like unset — the script guards with [ -n "${CODEX_PROFILE:-}" ], so no
    # `--profile ""` may leak into the codex invocation.
    res, argv, _ = _run_wrapper(tmp_path, extra_env={"CODEX_PROFILE": ""})
    assert res.returncode == 0, res.stderr
    assert "--profile" not in argv


def test_missing_codex_binary_fails_loudly(tmp_path: Path) -> None:
    # No shim on PATH: the exec fails with bash's command-not-found status, so
    # cron sees a failure instead of a silent no-op. (System dirs only — a real
    # codex install lives in /usr/local, homebrew, or npm prefixes, never here.)
    env: dict[str, str] = {"PATH": _SYSTEM_PATH, "HOME": str(tmp_path), "LC_ALL": "C"}
    res = subprocess.run(
        [_BASH, str(CODEX_RUN_SH)],
        cwd=tmp_path,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 127
    assert "codex" in res.stderr


# ── #1 interpreter: the pipeline's bare `python3` must be the locked 3.11+ ────
# In a minimal cron environment PATH resolves `python3` to the system Python
# (macOS ships 3.9, which lacks datetime.UTC), so the whole run dies with
# `ImportError: cannot import name 'UTC'`. The wrapper must put the project venv
# first and refuse to hand off to an interpreter older than 3.11.


def test_prepends_project_venv_bin_to_path(tmp_path: Path) -> None:
    # With a project .venv present, its bin/ must lead the PATH codex inherits,
    # so the bare `python3` in weekly-run.md steps is the locked interpreter.
    res, argv, recorded_path, _ = _run_fake_root_wrapper(
        tmp_path, venv_python=("3.12.3", True)
    )
    assert res.returncode == 0, res.stderr
    assert argv and argv[0] == "exec", "codex should still be invoked after the guard"
    venv_bin = str(tmp_path / "install" / ".venv" / "bin")
    assert recorded_path.split(":")[0] == venv_bin, (
        f".venv/bin must lead PATH; got {recorded_path!r}"
    )


def test_refuses_python_older_than_311(tmp_path: Path) -> None:
    # No project venv, and the only python3 on PATH is an ancient one: the
    # wrapper must fail loudly BEFORE handing off to codex, so cron reports it
    # instead of a step dying with a cryptic ImportError.
    res, argv, _, _ = _run_fake_root_wrapper(
        tmp_path, venv_python=None, path_python=("3.9.6", False)
    )
    assert res.returncode != 0
    assert argv == [], "codex must NOT be invoked when the interpreter is too old"
    assert "3.11" in res.stderr


# ── #2 secret: OPENAI_API_KEY must load from config/.env for headless cron ────
# docs/scheduling.md tells users to put the key in config/.env for a fully
# headless run, but the wrapper never read it — so a non-interactive cron with
# no saved Codex login could not authenticate. It must load that one key.


def test_loads_openai_api_key_from_env_file(tmp_path: Path) -> None:
    res, argv, _, recorded_key = _run_fake_root_wrapper(
        tmp_path,
        venv_python=("3.12.3", True),
        env_file="OPENAI_API_KEY=sk-from-dotenv\n",
    )
    assert res.returncode == 0, res.stderr
    assert argv and argv[0] == "exec"
    assert recorded_key == "sk-from-dotenv"


def test_env_file_key_may_be_quoted(tmp_path: Path) -> None:
    res, _, _, recorded_key = _run_fake_root_wrapper(
        tmp_path,
        venv_python=("3.12.3", True),
        env_file='export OPENAI_API_KEY="sk-quoted-value"\n',
    )
    assert res.returncode == 0, res.stderr
    assert recorded_key == "sk-quoted-value"


def test_existing_openai_api_key_is_not_overridden_by_env_file(tmp_path: Path) -> None:
    # A key already exported in the cron environment always wins over config/.env.
    res, _, _, recorded_key = _run_fake_root_wrapper(
        tmp_path,
        venv_python=("3.12.3", True),
        env_file="OPENAI_API_KEY=sk-from-dotenv\n",
        extra_env={"OPENAI_API_KEY": "sk-from-environment"},
    )
    assert res.returncode == 0, res.stderr
    assert recorded_key == "sk-from-environment"
