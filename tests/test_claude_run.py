"""Smoke tests for schedule/claude-run.sh — the Claude Code cron wrapper.

This is the "D. Claude Code (local cron)" scheduling path: OS cron calls the
wrapper, which runs `claude -p` non-interactively against the gated weekly
pipeline. It is the sibling of `codex-run.sh` and exists because the documented
Claude path — a `/schedule` cloud routine — runs **off-box** and therefore
cannot reach a local, git-less install (docs/scheduling.md admits as much when
it says cloud routines "cannot be probed" by `setup_check.py`).

The contract under test:

  - it invokes the `claude` CLI in print mode (`-p`), never an interactive REPL;
  - the weekly-run task reaches it as ONE argv argument: a prompt naming
    `schedule/weekly-run.md` (path, not content) plus the take-the-run-lock
    instruction (the wrapper takes no lock — serialization is delegated to
    weekly-run.md / scripts/run_lock.py);
  - **least privilege by construction**: `--tools` bounds the capability surface
    to exactly the union of the pipeline roles in `config/agents.yaml` (ADR
    0015). `--tools` is the hard bound — verified against the real CLI: with
    `--tools Read` the model reports it has no shell tool and a `Bash` write
    never happens, while `--allowedTools` only pre-approves what may run
    unprompted;
  - it never buys silence with `--dangerously-skip-permissions` /
    `bypassPermissions` — an unattended run must stay inside the allowlist, not
    escape the permission system;
  - it cd's to the project root resolved from the script's own location (the
    `claude` CLI has no `--cd`), so cron needs no pre-set cwd;
  - a spend ceiling is passed, so a runaway loop cannot bill unbounded;
  - the exit status is claude's own, so cron sees failures.

Everything runs against a fake `claude` shim on a controlled PATH — hermetic,
no Claude CLI required, nothing real executes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_RUN_SH = PROJECT_ROOT / "schedule" / "claude-run.sh"
CODEX_RUN_SH = PROJECT_ROOT / "schedule" / "codex-run.sh"
SHARED_LIB_SH = PROJECT_ROOT / "schedule" / "_agentic-run.sh"
WEEKLY_RUN_MD = PROJECT_ROOT / "schedule" / "weekly-run.md"
AGENTS_YAML = PROJECT_ROOT / "config" / "agents.yaml"

_BASH = shutil.which("bash") or ""
pytestmark = pytest.mark.skipif(not _BASH, reason="bash required for claude-run.sh")

# System dirs only — a REAL claude install (~/.local/bin, homebrew, npm prefix)
# can never be picked up by these tests.
_SYSTEM_PATH = "/usr/bin:/bin"


def _role_tool_union() -> set[str]:
    """Every tool any pipeline role is granted in config/agents.yaml (ADR 0015).

    Deriving the expectation from the spec — instead of hardcoding a list here —
    is what keeps the wrapper honest: granting a role a new tool without
    widening the wrapper (or vice versa) fails this test.
    """
    spec = yaml.safe_load(AGENTS_YAML.read_text(encoding="utf-8"))
    tools: set[str] = set()
    for role, cfg in spec.get("roles", {}).items():
        assert isinstance(cfg, dict), f"role {role} is not a mapping"
        tools.update(cfg.get("tools", []))
    assert tools, "config/agents.yaml granted no tools at all"
    return tools


# A `claude auth status` payload shaped like the real CLI's. Observed on a box
# where BOTH auth sources exist: the claude.ai login is reported even while the
# env var is what actually bills, which is exactly why the wrapper probes with
# the key unset (see AUTH_JSON_* below and the billing tests).
AUTH_JSON_SUBSCRIPTION = (
    '{"loggedIn": true, "authMethod": "claude.ai", "apiProvider": "firstParty", '
    '"email": "someone@example.com", "subscriptionType": "max"}'
)
AUTH_JSON_LOGGED_OUT = (
    '{"loggedIn": false, "authMethod": null, "apiProvider": "firstParty", '
    '"email": null, "subscriptionType": null}'
)
API_KEY = "sk-ant-test-key"
UNSET_MARKER = "<unset>"


def _write_claude_shim(
    bindir: Path,
    record_dir: Path,
    *,
    exit_code: int,
    auth_json: str = AUTH_JSON_LOGGED_OUT,
    auth_exit: int = 0,
) -> None:
    """A fake `claude` that records argv, stdin, cwd, $PATH and the key state.

    `claude auth status` is answered from a canned payload and deliberately
    recorded nowhere: it is a probe, not the run, so it must never clobber the
    argv/cwd records the other tests assert on.
    """
    shim = bindir / "claude"
    shim.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "auth" ]; then\n'
        f"  printf '%s' '{auth_json}'\n"
        f"  exit {auth_exit}\n"
        "fi\n"
        f'printf \'%s\\n\' "$@" > "{record_dir / "argv.txt"}"\n'
        f'cat > "{record_dir / "stdin.txt"}"\n'
        f'printf \'%s\' "$PWD" > "{record_dir / "cwd.txt"}"\n'
        f'printf \'%s\' "$PATH" > "{record_dir / "path.txt"}"\n'
        # Whether the API key survived to the run IS the billing outcome.
        f'printf \'%s\' "${{ANTHROPIC_API_KEY-{UNSET_MARKER}}}" > "{record_dir / "apikey.txt"}"\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)


def _run_wrapper(
    tmp_path: Path,
    *,
    cwd: Path | None = None,
    shim_exit: int = 0,
    extra_env: dict[str, str] | None = None,
    extra_path: str | None = None,
    auth_json: str = AUTH_JSON_LOGGED_OUT,
    auth_exit: int = 0,
) -> tuple[subprocess.CompletedProcess[str], list[str], str]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    record_dir = tmp_path / "rec"
    record_dir.mkdir(exist_ok=True)
    _write_claude_shim(
        bindir, record_dir, exit_code=shim_exit, auth_json=auth_json, auth_exit=auth_exit
    )

    path = f"{bindir}:{extra_path}:{_SYSTEM_PATH}" if extra_path else f"{bindir}:{_SYSTEM_PATH}"
    env: dict[str, str] = {"PATH": path, "HOME": str(tmp_path), "LC_ALL": "C"}
    if extra_env:
        env.update(extra_env)

    res = subprocess.run(
        [_BASH, str(CLAUDE_RUN_SH)],
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
    assert argv.count(flag) == 1, f"{flag} appears {argv.count(flag)} times in {argv}"
    return argv[argv.index(flag) + 1]


def _recorded(tmp_path: Path, name: str) -> str:
    return (tmp_path / "rec" / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #


def test_wrapper_is_executable_for_direct_cron_invocation() -> None:
    assert os.access(CLAUDE_RUN_SH, os.X_OK), "claude-run.sh lost its executable bit"


def test_claude_run_bash_syntax_ok() -> None:
    res = subprocess.run(
        [_BASH, "-n", str(CLAUDE_RUN_SH)], capture_output=True, text=True, timeout=30
    )
    assert res.returncode == 0, res.stderr


def test_invokes_claude_in_print_mode(tmp_path: Path) -> None:
    res, argv, _ = _run_wrapper(tmp_path)
    assert res.returncode == 0, res.stderr
    assert argv, "claude shim was never invoked"
    # `-p` is what makes the run non-interactive; without it the CLI opens a
    # REPL and a cron run hangs forever waiting on a TTY.
    assert "-p" in argv or "--print" in argv


def test_weekly_run_task_reaches_claude_as_single_prompt_arg(tmp_path: Path) -> None:
    res, argv, stdin = _run_wrapper(tmp_path)
    assert res.returncode == 0, res.stderr
    assert stdin == "", "the task travels by argv, not stdin"
    prompt_args = [a for a in argv if "schedule/weekly-run.md" in a]
    assert len(prompt_args) == 1, f"expected one prompt arg, got {argv}"
    prompt = prompt_args[0]
    assert prompt == argv[-1], "prompt must be the final claude argument"
    # The wrapper takes no lock itself — it delegates to the prompt.
    assert "run lock" in prompt.lower()
    assert "gated" in prompt.lower()
    assert "stop" in prompt.lower()


def test_prompt_references_a_real_task_file() -> None:
    assert WEEKLY_RUN_MD.is_file(), "prompt points claude at a missing task file"


# --------------------------------------------------------------------------- #
# Least privilege — the reason this wrapper exists in this shape
# --------------------------------------------------------------------------- #


def test_capability_surface_is_exactly_the_role_tool_union(tmp_path: Path) -> None:
    """`--tools` is the hard bound; it must equal the ADR 0015 role union.

    Wider means the unattended run can do things no documented pipeline role
    may do; narrower means a step dies mid-run on a missing tool.
    """
    res, argv, _ = _run_wrapper(tmp_path)
    assert res.returncode == 0, res.stderr
    granted = {t.strip() for t in _flag_value(argv, "--tools").split(",") if t.strip()}
    expected = _role_tool_union()
    assert granted == expected, (
        f"--tools drifted from config/agents.yaml "
        f"(missing: {sorted(expected - granted)}, extra: {sorted(granted - expected)})"
    )


def test_permission_mode_never_bypasses_the_permission_system(tmp_path: Path) -> None:
    """No prompts (cron would hang) — but no blanket bypass either."""
    res, argv, _ = _run_wrapper(tmp_path)
    assert res.returncode == 0, res.stderr
    joined = " ".join(argv)
    assert "--dangerously-skip-permissions" not in joined
    assert "--allow-dangerously-skip-permissions" not in joined
    assert "bypassPermissions" not in joined
    # A mode that answers permission questions without a TTY must still be set,
    # or the run stalls on the first gated tool call.
    assert _flag_value(argv, "--permission-mode") == "dontAsk"


def test_pre_approves_only_tools_inside_the_capability_surface(tmp_path: Path) -> None:
    """`--allowedTools` pre-approves; it must not name a tool `--tools` withheld."""
    res, argv, _ = _run_wrapper(tmp_path)
    assert res.returncode == 0, res.stderr
    allowed_raw = _flag_value(argv, "--allowedTools")
    # Rules may be scoped (`Bash(python3 *)`); the tool name is the head.
    allowed = {rule.split("(")[0].strip() for rule in allowed_raw.split(",") if rule.strip()}
    granted = {t.strip() for t in _flag_value(argv, "--tools").split(",") if t.strip()}
    assert allowed <= granted, f"pre-approved tools outside the capability surface: {allowed - granted}"


def test_spend_ceiling_is_passed(tmp_path: Path) -> None:
    """An unattended agentic loop bills real money — cron gets a hard cap."""
    res, argv, _ = _run_wrapper(tmp_path)
    assert res.returncode == 0, res.stderr
    assert float(_flag_value(argv, "--max-budget-usd")) > 0


def test_spend_ceiling_is_overridable(tmp_path: Path) -> None:
    res, argv, _ = _run_wrapper(tmp_path, extra_env={"CLAUDE_RUN_MAX_USD": "12.5"})
    assert res.returncode == 0, res.stderr
    assert _flag_value(argv, "--max-budget-usd") == "12.5"


# --------------------------------------------------------------------------- #
# Cron mechanics (shared with codex-run.sh)
# --------------------------------------------------------------------------- #


def test_runs_from_the_project_root_regardless_of_cron_cwd(tmp_path: Path) -> None:
    """The claude CLI has no `--cd`, so the wrapper must cd itself.

    Verified against the real CLI: a Read of a file outside the workspace root
    is denied even when the tool is allowed — the cwd IS the trust boundary.
    """
    elsewhere = tmp_path / "some" / "random" / "cwd"
    elsewhere.mkdir(parents=True)
    res, argv, _ = _run_wrapper(tmp_path, cwd=elsewhere)
    assert res.returncode == 0, res.stderr
    assert Path(_recorded(tmp_path, "cwd.txt")).resolve() == PROJECT_ROOT


def test_claude_exit_status_propagates_exactly(tmp_path: Path) -> None:
    res, argv, _ = _run_wrapper(tmp_path, shim_exit=7)
    assert argv, "claude shim was never invoked"
    assert res.returncode == 7


def test_model_env_adds_model_flag(tmp_path: Path) -> None:
    res, argv, _ = _run_wrapper(tmp_path, extra_env={"CLAUDE_RUN_MODEL": "sonnet"})
    assert res.returncode == 0, res.stderr
    assert _flag_value(argv, "--model") == "sonnet"


def test_blank_model_env_is_ignored(tmp_path: Path) -> None:
    res, argv, _ = _run_wrapper(tmp_path, extra_env={"CLAUDE_RUN_MODEL": ""})
    assert res.returncode == 0, res.stderr
    assert "--model" not in argv


def test_missing_claude_binary_fails_loudly(tmp_path: Path) -> None:
    env: dict[str, str] = {"PATH": _SYSTEM_PATH, "HOME": str(tmp_path), "LC_ALL": "C"}
    res = subprocess.run(
        [_BASH, str(CLAUDE_RUN_SH)],
        cwd=tmp_path,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode != 0
    assert "claude" in (res.stderr + res.stdout).lower()


def _write_python_shim(path: Path, *, version: str, ok: bool) -> None:
    """A python3 that answers `-V` and passes/fails the >=3.11 probe."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f'  -V|--version) echo "Python {version}"; exit 0 ;;\n'
        f"esac\nexit {0 if ok else 1}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run_in_fake_root(
    tmp_path: Path,
    *,
    venv_python: tuple[str, bool] | None = None,
    path_python: tuple[str, bool] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str], str]:
    """Run the wrapper from a fully test-owned fake install root.

    Copies the wrapper AND the shared preamble it sources, so the interpreter
    guard can be exercised against synthetic pythons without touching the real
    project `.venv`. Returns (process, recorded claude argv, recorded $PATH).
    """
    root = tmp_path / "install" / "schedule"
    root.mkdir(parents=True, exist_ok=True)
    for src in (CLAUDE_RUN_SH, SHARED_LIB_SH):
        dst = root / src.name
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        dst.chmod(0o755)
    bindir = tmp_path / "bin"
    record_dir = tmp_path / "rec"
    bindir.mkdir(parents=True, exist_ok=True)
    record_dir.mkdir(parents=True, exist_ok=True)
    _write_claude_shim(bindir, record_dir, exit_code=0)
    if venv_python is not None:
        _write_python_shim(
            tmp_path / "install" / ".venv" / "bin" / "python3",
            version=venv_python[0],
            ok=venv_python[1],
        )
    if path_python is not None:
        _write_python_shim(bindir / "python3", version=path_python[0], ok=path_python[1])

    res = subprocess.run(
        [_BASH, str(root / CLAUDE_RUN_SH.name)],
        cwd=tmp_path,
        env={"PATH": f"{bindir}:{_SYSTEM_PATH}", "HOME": str(tmp_path), "LC_ALL": "C"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    argv_file = record_dir / "argv.txt"
    path_file = record_dir / "path.txt"
    argv = argv_file.read_text(encoding="utf-8").splitlines() if argv_file.exists() else []
    recorded_path = path_file.read_text(encoding="utf-8") if path_file.exists() else ""
    return res, argv, recorded_path


def test_prepends_project_venv_bin_to_path(tmp_path: Path) -> None:
    """weekly-run.md's steps call a bare `python3` — cron's PATH finds the
    system one (macOS 3.9, no datetime.UTC) unless the venv goes first."""
    res, argv, recorded_path = _run_in_fake_root(tmp_path, venv_python=("3.12.3", True))
    assert res.returncode == 0, res.stderr
    assert argv, "claude should still be invoked after the guard"
    assert recorded_path.split(":")[0] == str(tmp_path / "install" / ".venv" / "bin")


def test_refuses_python_older_than_311(tmp_path: Path) -> None:
    """A stale interpreter must fail HERE, with a cron-visible message, rather
    than cryptically deep inside a pipeline step."""
    res, argv, _ = _run_in_fake_root(tmp_path, path_python=("3.9.6", False))
    assert res.returncode != 0
    assert argv == [], "claude must NOT be invoked when the interpreter is too old"
    assert "3.11" in res.stderr


# --------------------------------------------------------------------------- #
# Billing — the subscription is the default payer, the API key is opt-in
# --------------------------------------------------------------------------- #
#
# A stray ANTHROPIC_API_KEY silently outranks a claude.ai login, so an
# unattended run bills API credits while a paid subscription sits unused. The
# CLI does say so — "connectors are disabled because ANTHROPIC_API_KEY … takes
# precedence over your claude.ai login" — but it reads as a connectors notice,
# not a billing one. The wrapper therefore decides on purpose.
#
# The probe runs with the key ALREADY unset, because that is the only state
# that answers the real question ("would a run without the key be logged in?");
# with the key set, the CLI reports authMethod claude.ai *and* a null
# subscriptionType, which is too ambiguous to bill against.


def _api_key_seen_by_run(tmp_path: Path) -> str:
    """What ANTHROPIC_API_KEY looked like when `claude` was finally exec'd."""
    return _recorded(tmp_path, "apikey.txt")


def test_auto_prefers_the_subscription_when_a_claude_ai_login_exists(tmp_path: Path) -> None:
    res, argv, _ = _run_wrapper(
        tmp_path,
        extra_env={"ANTHROPIC_API_KEY": API_KEY},
        auth_json=AUTH_JSON_SUBSCRIPTION,
    )
    assert res.returncode == 0, res.stderr
    assert argv, "claude shim was never invoked"
    assert _api_key_seen_by_run(tmp_path) == UNSET_MARKER, (
        "the API key survived into the run — it would bill credits while a "
        "subscription login was available"
    )


def test_auto_keeps_the_api_key_when_no_subscription_login_exists(tmp_path: Path) -> None:
    """No login to fall back on: dropping the key would just break the run."""
    res, argv, _ = _run_wrapper(
        tmp_path,
        extra_env={"ANTHROPIC_API_KEY": API_KEY},
        auth_json=AUTH_JSON_LOGGED_OUT,
    )
    assert res.returncode == 0, res.stderr
    assert _api_key_seen_by_run(tmp_path) == API_KEY


def test_auto_fails_safe_when_the_probe_cannot_be_trusted(tmp_path: Path) -> None:
    """`claude auth status` output is an observed CLI shape, not a stable API.

    If it errors — or answers something this wrapper does not recognise — the
    run must proceed on the key it already had, and say so, rather than guess.
    """
    res, argv, _ = _run_wrapper(
        tmp_path,
        extra_env={"ANTHROPIC_API_KEY": API_KEY},
        auth_json="not json at all",
        auth_exit=1,
    )
    assert res.returncode == 0, res.stderr
    assert argv, "a failed probe must not stop the run"
    assert _api_key_seen_by_run(tmp_path) == API_KEY
    assert "auth" in res.stderr.lower(), "a fail-safe fallback must be visible in cron output"


def test_api_choice_keeps_the_key_even_when_a_subscription_exists(tmp_path: Path) -> None:
    """The explicit opt-in the user asked for: 'only if told, use the key'."""
    res, argv, _ = _run_wrapper(
        tmp_path,
        extra_env={"ANTHROPIC_API_KEY": API_KEY, "CLAUDE_RUN_AUTH": "api"},
        auth_json=AUTH_JSON_SUBSCRIPTION,
    )
    assert res.returncode == 0, res.stderr
    assert _api_key_seen_by_run(tmp_path) == API_KEY


def test_subscription_choice_drops_the_key_without_consulting_the_probe(tmp_path: Path) -> None:
    """An escape hatch for a probe that misreports — forced, and warned about."""
    res, argv, _ = _run_wrapper(
        tmp_path,
        extra_env={"ANTHROPIC_API_KEY": API_KEY, "CLAUDE_RUN_AUTH": "subscription"},
        auth_json=AUTH_JSON_LOGGED_OUT,
    )
    assert res.returncode == 0, res.stderr
    assert _api_key_seen_by_run(tmp_path) == UNSET_MARKER
    assert "subscription" in res.stderr.lower()


def test_unknown_auth_choice_fails_loudly_instead_of_guessing(tmp_path: Path) -> None:
    """A typo'd crontab variable must not silently pick a payer."""
    res, argv, _ = _run_wrapper(
        tmp_path,
        extra_env={"ANTHROPIC_API_KEY": API_KEY, "CLAUDE_RUN_AUTH": "subscribtion"},
        auth_json=AUTH_JSON_SUBSCRIPTION,
    )
    assert res.returncode != 0
    assert argv == [], "claude must not run under an unparsed billing choice"
    assert "CLAUDE_RUN_AUTH" in res.stderr


def test_blank_auth_choice_behaves_like_unset(tmp_path: Path) -> None:
    """An empty crontab variable is 'not configured', not an invalid value."""
    res, argv, _ = _run_wrapper(
        tmp_path,
        extra_env={"ANTHROPIC_API_KEY": API_KEY, "CLAUDE_RUN_AUTH": ""},
        auth_json=AUTH_JSON_SUBSCRIPTION,
    )
    assert res.returncode == 0, res.stderr
    assert _api_key_seen_by_run(tmp_path) == UNSET_MARKER


def test_no_api_key_at_all_runs_untouched(tmp_path: Path) -> None:
    """Nothing to decide: the CLI's own auth applies, and no probe is needed."""
    res, argv, _ = _run_wrapper(tmp_path, auth_json=AUTH_JSON_SUBSCRIPTION)
    assert res.returncode == 0, res.stderr
    assert argv, "claude shim was never invoked"
    assert _api_key_seen_by_run(tmp_path) == UNSET_MARKER


def test_billing_decision_never_prompts_under_cron(tmp_path: Path) -> None:
    """Cron has no TTY: a question here would hang the weekly run forever.

    The decision is automatic by design — subscription first, key on request —
    so there is nothing to ask.
    """
    res, argv, _ = _run_wrapper(
        tmp_path,
        extra_env={"ANTHROPIC_API_KEY": API_KEY},
        auth_json=AUTH_JSON_SUBSCRIPTION,
    )
    assert res.returncode == 0, res.stderr
    assert argv, "the run must reach claude without waiting on input"
    assert "[y/n]" not in (res.stdout + res.stderr).lower()


# --------------------------------------------------------------------------- #
# Parity with the Codex wrapper — one contract, two runtimes
# --------------------------------------------------------------------------- #


def test_both_wrappers_share_one_preamble() -> None:
    """The ROOT/venv/python-version preamble lives in ONE file.

    Duplicating a runtime contract across wrappers invites drift, so both
    wrappers source the same helper.
    """
    assert SHARED_LIB_SH.is_file(), "shared agentic-run preamble is missing"
    for wrapper in (CLAUDE_RUN_SH, CODEX_RUN_SH):
        text = wrapper.read_text(encoding="utf-8")
        assert "_agentic-run.sh" in text, f"{wrapper.name} does not source the shared preamble"


def test_both_wrappers_drive_the_same_task(tmp_path: Path) -> None:
    """Two runtimes, one orchestrator — neither may fork the pipeline."""
    _, claude_argv, _ = _run_wrapper(tmp_path)
    claude_prompt = claude_argv[-1]
    codex_text = CODEX_RUN_SH.read_text(encoding="utf-8")
    assert "schedule/weekly-run.md" in claude_prompt
    assert "schedule/weekly-run.md" in codex_text
