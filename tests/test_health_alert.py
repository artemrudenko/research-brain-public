"""
test_health_alert.py — offline tests for the opt-in PUSH health alert.

`health_alert.py` turns the PULL-only `/status` health verdict into a PUSH ping:
when health is DEGRADED *and* an operator has opted in via the `alerts:` block in
config/channels.yaml, it sends a one-line alert through the EXISTING delivery
adapter for the chosen channel.

Every test builds a self-contained fake vault (mirroring test_health.py) and
monkeypatches the adapter send so NOTHING real is ever sent. The opt-in config is
written into a tmp channels.yaml passed explicitly, so the real config is never
touched. PyYAML is required to read that config.
"""
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("yaml", reason="PyYAML required to read config/channels.yaml")

from scripts import health as h  # noqa: E402
from scripts import health_alert as ha  # noqa: E402
from scripts.delivery import email_smtp, rocketchat_webhook, telegram_botapi  # noqa: E402

TODAY = date(2026, 6, 19)


@pytest.fixture(autouse=True)
def _isolate_state_env(monkeypatch):
    """Clear RESEARCH_BRAIN_STATE_DIR so these in-repo tests are hermetic."""
    monkeypatch.delenv("RESEARCH_BRAIN_STATE_DIR", raising=False)


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "pipeline" / "3-synthesis").mkdir(parents=True)
    return tmp_path


# A sources.md with ONE real (non-EXAMPLE) active source row (category: ai).
_REAL_SOURCE_MD = """\
## Category: ai

### Active sources

| URL | Type | Tier | Priority | Filter | Active |
|-----|------|------|----------|--------|--------|
| https://real.com/feed.xml | rss | high | high | all | yes |
"""


def _write_sources(vault: Path, body: str) -> None:
    sources = vault / "config" / "sources.md"
    sources.parent.mkdir(parents=True, exist_ok=True)
    sources.write_text(body, encoding="utf-8")


def _write_channels(vault: Path, body: str) -> Path:
    """Write a tmp channels.yaml under the fake vault; return its path."""
    path = vault / "config" / "channels.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# An alerts-ENABLED channels.yaml routing alerts through the telegram channel
# (which is itself a valid bot-api channel with a chat_id + token env var).
_ALERTS_ENABLED_YAML = """\
delivery:
  alerts:
    enabled: true
    channel: telegram
  telegram:
    enabled: true
    transport: bot-api
    chat_id: "42"
    token_env: TELEGRAM_BOT_TOKEN
"""

# Alerts opted in, routed through telegram, but the telegram channel itself is
# DISABLED — the alert must NOT be sent through a channel the user turned off.
_ALERTS_TARGET_DISABLED_YAML = """\
delivery:
  alerts:
    enabled: true
    channel: telegram
  telegram:
    enabled: false
    transport: bot-api
    chat_id: "42"
    token_env: TELEGRAM_BOT_TOKEN
"""

# Same channels, but alerts NOT opted in (the default-OFF shape).
_ALERTS_DISABLED_YAML = """\
delivery:
  alerts:
    enabled: false
    channel: telegram
  telegram:
    enabled: true
    transport: bot-api
    chat_id: "42"
    token_env: TELEGRAM_BOT_TOKEN
"""

# No alerts block at all — the shipped default. Must behave as OFF.
_NO_ALERTS_BLOCK_YAML = """\
delivery:
  telegram:
    enabled: true
    transport: bot-api
    chat_id: "42"
    token_env: TELEGRAM_BOT_TOKEN
"""

# Alerts ENABLED but routed through the EMAIL channel (SMTP) instead of telegram.
_ALERTS_EMAIL_YAML = """\
delivery:
  alerts:
    enabled: true
    channel: email
  email:
    enabled: true
    to:
      - ops@example.com
    smtp:
      host: smtp.example.com
      port: 587
      user: bot@example.com
      password_env: SMTP_PASSWORD
"""

# Alerts ENABLED but routed through the ROCKET.CHAT incoming-webhook channel.
_ALERTS_ROCKETCHAT_YAML = """\
delivery:
  alerts:
    enabled: true
    channel: rocketchat
  rocketchat:
    enabled: true
    webhook_url_env: ROCKETCHAT_WEBHOOK_URL
"""

# Alerts ENABLED but pointed at a channel the dispatch doesn't know about. The
# 'bogus' channel IS present under delivery (so we reach _send_alert's raise),
# but _send_alert has no branch for it → DeliveryError → caught as best-effort.
_ALERTS_UNKNOWN_CHANNEL_YAML = """\
delivery:
  alerts:
    enabled: true
    channel: bogus
  bogus:
    enabled: true
"""


def _make_degraded_vault(tmp_path: Path) -> Path:
    """Build a configured vault whose health verdict is DEGRADED (failed run)."""
    vault = _vault(tmp_path)
    _write_sources(vault, _REAL_SOURCE_MD)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://real.com/feed.xml", items=3)
    h.record_event(vault, "run", status="failed")
    # Sanity: this vault really is DEGRADED.
    assert h.health_summary(vault, today=TODAY).status == h.Status.DEGRADED
    return vault


def _make_ok_vault(tmp_path: Path) -> Path:
    """Build a configured vault whose health verdict is OK."""
    vault = _vault(tmp_path)
    _write_sources(vault, _REAL_SOURCE_MD)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://real.com/feed.xml", items=3)
    h.record_event(vault, "deliver", status="sent", channel="telegram")
    # Deterministic in-window run ts so the run-recency axis stays OK regardless of
    # the wall clock relative to the fixture TODAY (a bare ts defaults to now()).
    h.record_event(vault, "run", status="ok", timestamp="2026-06-18T09:00:00+00:00")
    assert h.health_summary(vault, today=TODAY).status == h.Status.OK
    return vault


@pytest.fixture
def _token(monkeypatch):
    """Provide the telegram token env var so secret resolution succeeds."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")


@pytest.fixture
def _capture_send(monkeypatch):
    """Monkeypatch the telegram adapter send; return the recorded call list."""
    calls: list[dict] = []

    def _fake_send(text, *, token, chat_id, **kwargs):
        calls.append({"text": text, "token": token, "chat_id": chat_id})
        return True

    monkeypatch.setattr(telegram_botapi, "send", _fake_send)
    return calls


@pytest.fixture
def _smtp_secret(monkeypatch):
    """Provide the SMTP password env var so email secret resolution succeeds."""
    monkeypatch.setenv("SMTP_PASSWORD", "S")


@pytest.fixture
def _webhook_secret(monkeypatch):
    """Provide the Rocket.Chat webhook URL env var so secret resolution succeeds."""
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://chat.example.com/hook/abc")


@pytest.fixture
def _capture_email(monkeypatch):
    """Monkeypatch the email adapter send; return the recorded call list.

    Captures positional args AND kwargs so a test can assert the alert was passed
    as the PLAIN-TEXT body and that no `html` alternative was supplied.
    """
    calls: list[dict] = []

    def _fake_send(subject, body, **kwargs):
        calls.append({"subject": subject, "body": body, "kwargs": kwargs})
        return True

    monkeypatch.setattr(email_smtp, "send", _fake_send)
    return calls


@pytest.fixture
def _capture_rocketchat(monkeypatch):
    """Monkeypatch the rocketchat adapter send; return the recorded call list."""
    calls: list[dict] = []

    def _fake_send(text, **kwargs):
        calls.append({"text": text, "kwargs": kwargs})
        return True

    monkeypatch.setattr(rocketchat_webhook, "send", _fake_send)
    return calls


# --------------------------------------------------------------------------- #
# DEGRADED + opted in → exactly one one-line alert with the degraded reason
# --------------------------------------------------------------------------- #


def test_degraded_and_enabled_sends_one_line_alert(
    tmp_path, _token, _capture_send, capsys
) -> None:
    vault = _make_degraded_vault(tmp_path)
    cfg = _write_channels(vault, _ALERTS_ENABLED_YAML)

    rc = ha.main(["--root", str(vault), "--config", str(cfg), "--today", "2026-06-19"])

    assert rc == 0
    assert len(_capture_send) == 1  # the adapter was called exactly once
    msg = _capture_send[0]["text"]
    assert _capture_send[0]["chat_id"] == "42"
    # One line, naming the degraded reason (a failed run).
    assert "\n" not in msg.strip()
    assert "DEGRADED" in msg
    assert "research-brain" in msg
    assert "run" in msg.lower()  # the failed-run reason is surfaced


def test_degraded_but_target_channel_disabled_does_not_send(
    tmp_path, _token, _capture_send, capsys
) -> None:
    # DEGRADED + alerts enabled, but the target channel is disabled → the adapter
    # must NOT be called (best-effort no-op), and the run still exits 0.
    vault = _make_degraded_vault(tmp_path)
    cfg = _write_channels(vault, _ALERTS_TARGET_DISABLED_YAML)

    rc = ha.main(["--root", str(vault), "--config", str(cfg), "--today", "2026-06-19"])

    assert rc == 0
    assert _capture_send == []  # disabled channel → nothing sent
    assert "disabled" in capsys.readouterr().err.lower()


# --------------------------------------------------------------------------- #
# OK / UNKNOWN / UNCONFIGURED → adapter NOT called, exit 0
# --------------------------------------------------------------------------- #


def test_ok_does_not_alert(tmp_path, _token, _capture_send) -> None:
    vault = _make_ok_vault(tmp_path)
    cfg = _write_channels(vault, _ALERTS_ENABLED_YAML)
    rc = ha.main(["--root", str(vault), "--config", str(cfg), "--today", "2026-06-19"])
    assert rc == 0
    assert _capture_send == []  # OK is not actionable — no ping


def test_unknown_does_not_alert(tmp_path, _token, _capture_send) -> None:
    # Configured but never ran → UNKNOWN, not DEGRADED.
    vault = _vault(tmp_path)
    _write_sources(vault, _REAL_SOURCE_MD)
    h.record_event(vault, "collect", source="https://real.com/feed.xml", items=2)
    assert h.health_summary(vault, today=TODAY).status == h.Status.UNKNOWN
    cfg = _write_channels(vault, _ALERTS_ENABLED_YAML)
    rc = ha.main(["--root", str(vault), "--config", str(cfg), "--today", "2026-06-19"])
    assert rc == 0
    assert _capture_send == []


def test_unconfigured_does_not_alert(tmp_path, _token, _capture_send) -> None:
    # Fresh vault → UNCONFIGURED, never alerts.
    vault = _vault(tmp_path)
    assert h.health_summary(vault, today=TODAY).status == h.Status.UNCONFIGURED
    cfg = _write_channels(vault, _ALERTS_ENABLED_YAML)
    rc = ha.main(["--root", str(vault), "--config", str(cfg), "--today", "2026-06-19"])
    assert rc == 0
    assert _capture_send == []


# --------------------------------------------------------------------------- #
# Opt-in gating: DEGRADED but alerts NOT enabled → adapter NOT called
# --------------------------------------------------------------------------- #


def test_degraded_but_alerts_disabled_does_not_alert(
    tmp_path, _token, _capture_send, capsys
) -> None:
    vault = _make_degraded_vault(tmp_path)
    cfg = _write_channels(vault, _ALERTS_DISABLED_YAML)
    rc = ha.main(["--root", str(vault), "--config", str(cfg), "--today", "2026-06-19"])
    assert rc == 0
    assert _capture_send == []  # opt-in is OFF — no ping even though DEGRADED
    # It explains on stdout why nothing was sent (opt-in is the gate).
    assert "not enabled" in capsys.readouterr().out.lower()


def test_degraded_but_no_alerts_block_does_not_alert(
    tmp_path, _token, _capture_send, capsys
) -> None:
    # The shipped default has no alerts: block at all → behaves as OFF.
    vault = _make_degraded_vault(tmp_path)
    cfg = _write_channels(vault, _NO_ALERTS_BLOCK_YAML)
    rc = ha.main(["--root", str(vault), "--config", str(cfg), "--today", "2026-06-19"])
    assert rc == 0
    assert _capture_send == []


# --------------------------------------------------------------------------- #
# Best-effort: a send failure must NOT make the script exit non-zero
# --------------------------------------------------------------------------- #


def test_adapter_raises_still_exits_zero(tmp_path, _token, monkeypatch, capsys) -> None:
    vault = _make_degraded_vault(tmp_path)
    cfg = _write_channels(vault, _ALERTS_ENABLED_YAML)

    def _boom(*args, **kwargs):
        raise RuntimeError("transport exploded")

    monkeypatch.setattr(telegram_botapi, "send", _boom)
    rc = ha.main(["--root", str(vault), "--config", str(cfg), "--today", "2026-06-19"])
    assert rc == 0  # best-effort: an alert failure never fails a cron run
    captured = capsys.readouterr()
    # The error is surfaced (not swallowed silently) on stdout/stderr.
    assert "transport exploded" in (captured.out + captured.err)


def test_adapter_returns_false_still_exits_zero(
    tmp_path, _token, monkeypatch
) -> None:
    # A send that reports failure (returns False) is also best-effort → exit 0.
    vault = _make_degraded_vault(tmp_path)
    cfg = _write_channels(vault, _ALERTS_ENABLED_YAML)
    monkeypatch.setattr(telegram_botapi, "send", lambda *a, **k: False)
    rc = ha.main(["--root", str(vault), "--config", str(cfg), "--today", "2026-06-19"])
    assert rc == 0


# --------------------------------------------------------------------------- #
# --dry-run: prints the message it WOULD send, adapter NOT called
# --------------------------------------------------------------------------- #


def test_dry_run_prints_message_without_sending(
    tmp_path, _token, _capture_send, capsys
) -> None:
    vault = _make_degraded_vault(tmp_path)
    cfg = _write_channels(vault, _ALERTS_ENABLED_YAML)
    rc = ha.main(
        ["--root", str(vault), "--config", str(cfg), "--today", "2026-06-19", "--dry-run"]
    )
    assert rc == 0
    assert _capture_send == []  # dry-run sends nothing
    out = capsys.readouterr().out
    assert "DEGRADED" in out  # the message it WOULD send is printed
    assert "research-brain" in out


def test_dry_run_on_ok_reports_nothing_to_send(
    tmp_path, _token, _capture_send, capsys
) -> None:
    # On a healthy vault --dry-run says there is nothing to alert about.
    vault = _make_ok_vault(tmp_path)
    cfg = _write_channels(vault, _ALERTS_ENABLED_YAML)
    rc = ha.main(
        ["--root", str(vault), "--config", str(cfg), "--today", "2026-06-19", "--dry-run"]
    )
    assert rc == 0
    assert _capture_send == []
    assert "OK" in capsys.readouterr().out  # reports the (healthy) status


# --------------------------------------------------------------------------- #
# Dispatch fan-out: each non-telegram branch routes the PLAIN-TEXT alert to its
# own adapter (the "must be plain text" invariant holds for every sink, not just
# telegram), and the unknown/unconfigured channels stay best-effort (exit 0).
# --------------------------------------------------------------------------- #


def test_degraded_email_channel_sends_plain_text_body(
    tmp_path, _smtp_secret, _capture_email, capsys
) -> None:
    # DEGRADED + alerts enabled + channel: email → the email adapter is called
    # with the alert as a PLAIN-TEXT body and NO html alternative. This pins the
    # plain-text security invariant for the email sink (untrusted feed/topic names
    # must not reach a markdown/HTML renderer).
    vault = _make_degraded_vault(tmp_path)
    cfg = _write_channels(vault, _ALERTS_EMAIL_YAML)

    rc = ha.main(["--root", str(vault), "--config", str(cfg), "--today", "2026-06-19"])

    assert rc == 0
    assert len(_capture_email) == 1  # the email adapter was called exactly once
    call = _capture_email[0]
    expected = ha.alert_message(h.health_summary(vault, today=TODAY))
    # The alert is the plain-text body (positional, not an html kwarg)...
    assert call["body"] == expected
    assert "DEGRADED" in call["body"]
    # ...and NO HTML alternative was supplied — a crafted name can't inject HTML.
    assert call["kwargs"].get("html") is None
    assert "<" not in call["body"]  # no HTML markup leaked into the body


def test_degraded_rocketchat_channel_sends_message(
    tmp_path, _webhook_secret, _capture_rocketchat
) -> None:
    # DEGRADED + channel: rocketchat → the rocketchat adapter is called with the
    # one-line alert message (the third dispatch branch).
    vault = _make_degraded_vault(tmp_path)
    cfg = _write_channels(vault, _ALERTS_ROCKETCHAT_YAML)

    rc = ha.main(["--root", str(vault), "--config", str(cfg), "--today", "2026-06-19"])

    assert rc == 0
    assert len(_capture_rocketchat) == 1  # the rocketchat adapter was called once
    msg = _capture_rocketchat[0]["text"]
    assert "DEGRADED" in msg
    assert "research-brain" in msg


def test_degraded_unknown_channel_is_best_effort(
    tmp_path, _capture_send, capsys
) -> None:
    # DEGRADED + channel: bogus → _send_alert has no branch for it and raises
    # DeliveryError, which run() catches as best-effort: exit 0, nothing sent.
    # Pins the "an alert dispatch error never fails the run" claim.
    vault = _make_degraded_vault(tmp_path)
    cfg = _write_channels(vault, _ALERTS_UNKNOWN_CHANNEL_YAML)

    rc = ha.main(["--root", str(vault), "--config", str(cfg), "--today", "2026-06-19"])

    assert rc == 0  # best-effort: an unknown channel must not fail a cron run
    assert _capture_send == []  # no telegram (or any) send happened
    # The dispatch error is surfaced (not swallowed silently).
    captured = capsys.readouterr()
    assert "bogus" in (captured.out + captured.err)


# --------------------------------------------------------------------------- #
# Many reasons → still ONE line: the message names every reason but never wraps
# --------------------------------------------------------------------------- #


def _make_multi_reason_degraded_vault(tmp_path: Path) -> Path:
    """Build a DEGRADED vault with TWO distinct reasons: failed run AND overdue.

    The single `run` event is BOTH failed (status: failed) and old enough to be
    overdue (timestamped > EXPECTED_RUN_DAYS before TODAY), so the summary folds
    in two separate degraded reasons — letting us assert the one-line constraint
    holds when reasons are many.
    """
    vault = _vault(tmp_path)
    _write_sources(vault, _REAL_SOURCE_MD)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://real.com/feed.xml", items=3)
    # Old + failed run → both failed_run and run_overdue reasons (TODAY is 06-19,
    # EXPECTED_RUN_DAYS is 8, so 06-01 is comfortably overdue).
    h.record_event(
        vault, "run", status="failed", timestamp="2026-06-01T09:00:00+00:00"
    )
    summary = h.health_summary(vault, today=TODAY)
    assert summary.status == h.Status.DEGRADED
    # Sanity: this really is a multi-reason DEGRADED.
    assert summary.failed_run and summary.run_overdue
    return vault


def test_multi_reason_degraded_stays_one_line(tmp_path) -> None:
    vault = _make_multi_reason_degraded_vault(tmp_path)
    message = ha.alert_message(h.health_summary(vault, today=TODAY))
    # Both reasons are surfaced...
    assert "failed" in message.lower()
    assert "overdue" in message.lower()
    # ...yet the operator ping is still a single line (no embedded newline).
    assert "\n" not in message


# --------------------------------------------------------------------------- #
# alert_message — the one-line builder
# --------------------------------------------------------------------------- #


def test_alert_message_is_one_line_with_reasons(tmp_path) -> None:
    vault = _make_degraded_vault(tmp_path)
    summary = h.health_summary(vault, today=TODAY)
    message = ha.alert_message(summary)
    assert "\n" not in message
    assert message.startswith("⚠️")
    assert "DEGRADED" in message
    assert "research-brain" in message
