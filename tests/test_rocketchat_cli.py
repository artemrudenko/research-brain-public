"""Tests for the Rocket.Chat send CLI — the guarded transport the AGENT path uses.

External review 2026-07-25 P1: `skills/digest-deliver/SKILL.md` told the agent to
POST the webhook with `curl` / WebFetch in MCP mode. That bypassed every guard in
`rocketchat_webhook.send()` (scheme check, private-IP literal check, host
resolution via `assert_public_host`, redirect re-validation) — so the SSRF
hardening added in 0.10.3 only ever protected the headless path. It also put the
webhook URL, which carries a secret token, into a process argv: visible in `ps`,
in shell history, and in the persisted tool transcript.

The root cause was that `rocketchat_webhook.py` had no CLI at all — the skill
*could not* call the safe sender from Bash, so it reached for curl. This module
pins the CLI's contract:

  1. the message body arrives via stdin or a file, never as an argument;
  2. the webhook URL is resolved from the environment (config/.env), and there is
     no flag that accepts it — so it cannot reach argv even by mistake;
  3. an unsafe URL exits non-zero WITHOUT posting;
  4. a missing secret is an actionable error, not a silent skip.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.delivery import rocketchat_webhook

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI = PROJECT_ROOT / "scripts" / "delivery" / "rocketchat_webhook.py"

SAFE_URL = "https://rc.example/hooks/tok3n"


@pytest.fixture
def channels(tmp_path: Path) -> Path:
    """A minimal channels.yaml with Rocket.Chat enabled."""
    config = tmp_path / "channels.yaml"
    config.write_text(
        "delivery:\n  rocketchat:\n    enabled: true\n", encoding="utf-8"
    )
    return config


def _body_file(tmp_path: Path, text: str = "# Digest\n\nbody") -> Path:
    path = tmp_path / "digest.md"
    path.write_text(text, encoding="utf-8")
    return path


# ── the body travels by file/stdin, the URL by environment ────────────────────


def test_cli_sends_body_from_file(
    tmp_path: Path, channels: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        rocketchat_webhook,
        "send",
        lambda text, *, webhook_url: sent.append((text, webhook_url)) or True,
    )
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", SAFE_URL)

    code = rocketchat_webhook.main(
        ["--text-file", str(_body_file(tmp_path)), "--config", str(channels)]
    )

    assert code == 0
    assert sent == [("# Digest\n\nbody", SAFE_URL)]


def test_cli_reads_body_from_stdin(
    channels: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--stdin` is the piping form the skill uses for a rendered body."""
    import io

    sent: list[str] = []
    monkeypatch.setattr(
        rocketchat_webhook,
        "send",
        lambda text, *, webhook_url: sent.append(text) or True,
    )
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", SAFE_URL)
    monkeypatch.setattr(sys, "stdin", io.StringIO("piped body"))

    assert rocketchat_webhook.main(["--stdin", "--config", str(channels)]) == 0
    assert sent == ["piped body"]


def test_cli_has_no_flag_that_accepts_the_webhook_url(channels: Path) -> None:
    """The secret must be unreachable from argv.

    A `--webhook-url` style flag would reintroduce exactly the leak the CLI
    exists to remove (argv is world-readable via `ps` and is persisted in the
    agent's tool transcript), so argparse must reject it outright.
    """
    with pytest.raises(SystemExit) as exc:
        rocketchat_webhook.main(
            ["--stdin", "--config", str(channels), "--webhook-url", SAFE_URL]
        )
    assert exc.value.code != 0


def test_cli_requires_exactly_one_body_source(channels: Path) -> None:
    """No implicit stdin: a bare invocation must fail fast, not hang on a tty."""
    with pytest.raises(SystemExit) as exc:
        rocketchat_webhook.main(["--config", str(channels)])
    assert exc.value.code != 0


# ── the guards actually bind on this path ─────────────────────────────────────


def test_cli_refuses_unsafe_url_without_posting(
    tmp_path: Path, channels: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: a private/loopback target is refused before any HTTP.

    This is the case `curl` happily performed.
    """
    def must_not_post(url: str, payload: dict[str, object]) -> int:
        raise AssertionError(f"posted to an unsafe URL: {url}")

    monkeypatch.setattr(rocketchat_webhook, "_post_json", must_not_post)
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "http://169.254.169.254/latest/meta-data")

    code = rocketchat_webhook.main(
        ["--text-file", str(_body_file(tmp_path)), "--config", str(channels)]
    )

    assert code != 0, "an unsafe webhook URL must be a non-zero exit, not a silent skip"


def test_cli_missing_secret_is_actionable(
    tmp_path: Path, channels: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ROCKETCHAT_WEBHOOK_URL", raising=False)

    code = rocketchat_webhook.main(
        [
            "--text-file", str(_body_file(tmp_path)),
            "--config", str(channels),
            "--env-file", str(tmp_path / "absent.env"),
        ]
    )

    assert code != 0
    assert "ROCKETCHAT_WEBHOOK_URL" in capsys.readouterr().err


def test_cli_honours_a_custom_webhook_url_env_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """channels.yaml may rename the secret (`webhook_url_env`) — the agent path
    must respect that exactly as `channels.deliver_rocketchat` does, or a custom
    config silently breaks only in MCP mode."""
    config = tmp_path / "channels.yaml"
    config.write_text(
        "delivery:\n  rocketchat:\n    enabled: true\n"
        "    webhook_url_env: RC_HOOK_ALT\n",
        encoding="utf-8",
    )
    sent: list[str] = []
    monkeypatch.setattr(
        rocketchat_webhook,
        "send",
        lambda text, *, webhook_url: sent.append(webhook_url) or True,
    )
    monkeypatch.setenv("RC_HOOK_ALT", SAFE_URL)

    code = rocketchat_webhook.main(
        ["--text-file", str(_body_file(tmp_path)), "--config", str(config)]
    )

    assert code == 0
    assert sent == [SAFE_URL]


def test_cli_reports_a_failed_send_as_non_zero(
    tmp_path: Path, channels: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed POST must not look like success — the skill keys the receipt
    stamp off this exit code, and a stamped failure is a lost digest."""
    monkeypatch.setattr(rocketchat_webhook, "send", lambda text, *, webhook_url: False)
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", SAFE_URL)

    code = rocketchat_webhook.main(
        ["--text-file", str(_body_file(tmp_path)), "--config", str(channels)]
    )
    assert code != 0


def test_cli_runs_directly_without_installation(tmp_path: Path, channels: Path) -> None:
    """The zip-run contract: `python3 scripts/delivery/rocketchat_webhook.py` must
    work from a bare interpreter in an uninstalled checkout — the skill invokes it
    that way, like every other documented CLI."""
    result = subprocess.run(
        [sys.executable, str(CLI), "--text-file", str(_body_file(tmp_path)),
         "--config", str(channels), "--env-file", str(tmp_path / "absent.env")],
        capture_output=True, text=True, cwd=tmp_path, timeout=60,
        env={"PATH": "/usr/bin:/bin"},  # no inherited secret, no PYTHONPATH help
    )
    # No secret is set, so it must fail — but with the actionable config error,
    # proving the module imported and the CLI ran (not an ImportError traceback).
    assert result.returncode != 0
    assert "ROCKETCHAT_WEBHOOK_URL" in result.stderr
    assert "Traceback" not in result.stderr


# ── the skill must actually use it ────────────────────────────────────────────


def _rocketchat_step() -> str:
    """The Rocket.Chat bullet of the digest-deliver skill (its agentic instruction)."""
    skill = (PROJECT_ROOT / "skills" / "digest-deliver" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    start = skill.index("**Rocket.Chat**")
    return skill[start : skill.index("\n6. ", start)]


def test_digest_deliver_skill_commands_the_guarded_cli_not_curl() -> None:
    """Docs contract, not a style check: the skill IS the agentic implementation.

    While the Rocket.Chat step's command is a raw POST, the guarded transport is
    dead code on the path that matters. We assert on the COMMANDS the agent will
    actually run (the fenced blocks) rather than on the prose, so the step can
    still say the word "curl" in order to forbid it.
    """
    step = _rocketchat_step()
    commands = re.findall(r"```(?:bash|sh)?\n(.*?)```", step, re.DOTALL)
    assert commands, "the Rocket.Chat step must show the concrete send command"
    for command in commands:
        lowered = command.lower()
        assert "curl" not in lowered, (
            "digest-deliver still runs a raw curl POST for Rocket.Chat — that "
            f"bypasses the SSRF guard and leaks the webhook token into argv: {command!r}"
        )
        assert "webfetch" not in lowered, (
            f"digest-deliver still runs WebFetch for Rocket.Chat — same bypass: {command!r}"
        )
    assert any("rocketchat_webhook.py" in command for command in commands), (
        "the Rocket.Chat step must invoke the guarded CLI"
    )


def test_digest_deliver_skill_forbids_passing_the_webhook_url_as_an_argument() -> None:
    """The secret-in-argv half of the finding needs its own instruction.

    An agent handed a URL in the environment will still paste it onto a command
    line unless told not to — and that is what lands the token in the transcript.
    """
    step = _rocketchat_step().lower()
    assert "argv" in step or "as an argument" in step, (
        "the Rocket.Chat step must explicitly forbid passing the webhook URL on "
        "the command line (argv reaches ps, shell history, and this transcript)"
    )
