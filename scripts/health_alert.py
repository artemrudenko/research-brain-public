#!/usr/bin/env python3
"""
health_alert.py — opt-in PUSH alert when the system health verdict is DEGRADED.

The `/status` health verdict (see `health.py`) is PULL-only: an operator has to
go look. This script flips the **actionable bad state** into a PUSH ping — when
`health_summary(...).status` is DEGRADED, it sends a single one-line alert through
the SAME delivery adapter the digest uses (no new transport), so a silently-stopped
or degraded unattended run finds the operator instead of waiting to be noticed.

It is **opt-in (default OFF)**, so existing users are never suddenly messaged. The
switch is a tiny `alerts:` block under `delivery:` in `config/channels.yaml`:

    delivery:
      alerts:
        enabled: true        # default OFF — omit the block or set false to disable
        channel: telegram    # which already-configured channel to alert through
      telegram:
        enabled: true
        transport: bot-api
        chat_id: "..."
        token_env: TELEGRAM_BOT_TOKEN

Only DEGRADED triggers an alert: OK / UNKNOWN / UNCONFIGURED do nothing and exit 0.
If alerts are not configured/enabled, it does nothing and exits 0 (saying so).

Best-effort: a send failure (or any error) is printed but NEVER raises a non-zero
exit — it is an alert, not the pipeline, so it must not fail a cron run.

CLI:
    python3 scripts/health_alert.py            # alert if DEGRADED and opted in
    python3 scripts/health_alert.py --dry-run  # print the message it WOULD send
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

# Make `scripts` importable when run directly (`python3 scripts/health_alert.py`).
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.delivery import (  # noqa: E402
    deliver,  # noqa: E402 — reuse config + .env + adapters
    email_smtp,
    rocketchat_webhook,
    telegram_botapi,
)
from scripts.health import HealthSummary, Status, health_summary  # noqa: E402

# The default channels config (same file deliver.py reads).
DEFAULT_CHANNELS_CONFIG = _PROJECT_ROOT / "config" / "channels.yaml"

# Printed (and the run no-ops) when the opt-in is absent/OFF, so a cron log shows
# why nothing was sent.
NOT_ENABLED_MESSAGE = "health alert: not enabled (set delivery.alerts.enabled: true to opt in) — nothing to send"
# Printed when health is fine — no actionable state, nothing to alert about.
NOT_DEGRADED_MESSAGE = "health alert: status is {status} (only DEGRADED alerts) — nothing to send"


def alert_message(summary: HealthSummary) -> str:
    """Build the one-line operator ping from a DEGRADED health summary.

    Short by design — an operator ping, not a digest: a leading marker, the
    project name + DEGRADED verdict, then the concrete degraded reasons joined on
    one line (e.g. "⚠️ research-brain health DEGRADED: dead feed: ai; run overdue").
    """
    reasons = _degraded_reasons(summary)
    suffix = f": {'; '.join(reasons)}" if reasons else ""
    return f"⚠️ research-brain health DEGRADED{suffix}"


def _degraded_reasons(summary: HealthSummary) -> list[str]:
    """Distinct, short reasons the verdict is DEGRADED, in a stable order.

    Mirrors the failure signals `health._classify` folds into DEGRADED, kept terse
    for a one-line ping. Each axis contributes at most one short phrase.
    """
    reasons: list[str] = []
    if summary.failed_run:
        reasons.append("last weekly run failed")
    if summary.run_overdue:
        reasons.append("run overdue (no recent run)")
    for feed in summary.dead_feeds:
        reasons.append(f"source unreachable: {feed.source}")
    # `stale_feeds` (a quiet registry) is informational, not a DEGRADED cause, so it
    # is deliberately NOT an alert reason — see health.health_summary.
    for topic in summary.gate_skipped:
        reasons.append(f"topic gate-skipped: {topic}")
    if summary.digest_stale:
        reasons.append("digest stale")
    for channel, status in sorted(summary.delivery.items()):
        if status in ("failed", "error"):
            reasons.append(f"delivery failed: {channel}")
    return reasons


def _alerts_config(delivery_cfg: dict[str, object]) -> tuple[bool, str | None]:
    """Read the opt-in `alerts:` block: (enabled, channel name or None).

    Absent block, a non-mapping block, or `enabled` falsey → (False, None): the
    default-OFF behaviour, so existing users are never messaged.
    """
    raw = delivery_cfg.get("alerts")
    if not isinstance(raw, dict) or not raw.get("enabled"):
        return False, None
    channel = raw.get("channel")
    return True, str(channel) if channel else None


def _send_alert(channel: str, cfg: dict[str, object], message: str) -> bool:
    """Send `message` through the chosen channel's EXISTING adapter (best-effort).

    Reuses deliver.py's secret-resolution (`_env_or_fail`) and the per-channel
    adapter send functions, so there is no second transport to maintain. Returns
    the adapter's success bool; the caller treats any False/raise as best-effort.

    SECURITY: `message` carries UNTRUSTED feed/topic names (a feed URL, an
    agent-chosen topic from registry.md). It MUST be sent as PLAIN TEXT — Telegram
    with `render_markdown=False`, email as a plain MIMEText body — so a crafted
    name can't inject markdown/HTML/links into the operator's channel. Do NOT switch
    this to a markdown/HTML sink without first escaping those content-derived strings.
    """
    if channel == "telegram":
        chat_id = str(cfg.get("chat_id", ""))
        token = deliver._env_or_fail("telegram", str(cfg.get("token_env", "TELEGRAM_BOT_TOKEN")))
        return telegram_botapi.send(message, token=token, chat_id=chat_id, render_markdown=False)
    if channel == "email":
        recipients = cfg.get("to") or []
        to = [str(r) for r in recipients] if isinstance(recipients, list) else []
        smtp_raw = cfg.get("smtp")
        # Narrow a single bound value so mypy can prove `.get()` is safe (calling
        # cfg.get("smtp") twice leaves the assigned value typed as `object`).
        smtp: dict[object, object] = smtp_raw if isinstance(smtp_raw, dict) else {}
        password = deliver._env_or_fail("email", str(smtp.get("password_env", "SMTP_PASSWORD")))
        return email_smtp.send(
            "research-brain health alert", message,
            to=to, host=str(smtp.get("host", "")),
            port=int(str(smtp.get("port", 587))), user=str(smtp.get("user", "")),
            password=password,
        )
    if channel == "rocketchat":
        webhook_url = deliver._env_or_fail(
            "rocketchat", str(cfg.get("webhook_url_env", "ROCKETCHAT_WEBHOOK_URL"))
        )
        return rocketchat_webhook.send(message, webhook_url=webhook_url)
    raise deliver.DeliveryError(f"unknown alert channel {channel!r}")


def run(
    root: Path,
    config_path: Path = DEFAULT_CHANNELS_CONFIG,
    *,
    today: date | None = None,
    dry_run: bool = False,
) -> int:
    """Send a one-line health alert iff the verdict is DEGRADED and opt-in is on.

    Always returns 0 (best-effort): a non-DEGRADED verdict, a missing opt-in, or a
    send failure are all reported on stdout/stderr but never fail the run.
    """
    summary = health_summary(root, today=today)

    # Only DEGRADED — the actionable bad state — alerts. OK/UNKNOWN/UNCONFIGURED
    # are no-ops (a fresh or healthy system must not ping anyone).
    if summary.status is not Status.DEGRADED:
        print(NOT_DEGRADED_MESSAGE.format(status=summary.status.value))
        return 0

    message = alert_message(summary)

    # --dry-run: print what WOULD be sent and stop (handy for rehearsal/docs).
    if dry_run:
        print(f"health alert (dry-run) would send: {message}")
        return 0

    # Opt-in gate: only send when explicitly enabled. Reuse deliver's config
    # loader (and the .env auto-load) so there is no second config path.
    deliver.load_dotenv()
    try:
        delivery_cfg = deliver.load_config(config_path)
    except deliver.DeliveryError as error:
        print(f"health alert: cannot read channels config — {error}", file=sys.stderr)
        return 0  # best-effort — a bad config must not fail the run
    enabled, channel = _alerts_config(delivery_cfg)
    if not enabled:
        print(NOT_ENABLED_MESSAGE)
        return 0
    if not channel:
        print("health alert: alerts enabled but no 'channel' set — nothing to send")
        return 0

    cfg = delivery_cfg.get(channel)
    if not isinstance(cfg, dict):
        print(
            f"health alert: alert channel {channel!r} is not configured under delivery — "
            "nothing to send",
            file=sys.stderr,
        )
        return 0

    # Defence in depth (validate_config also rejects this): never alert through a
    # channel the user has disabled — its adapter is not meant to be used.
    if cfg.get("enabled") is not True:
        print(
            f"health alert: channel {channel!r} is disabled (delivery.{channel}.enabled "
            "is not true) — nothing to send",
            file=sys.stderr,
        )
        return 0

    # Best-effort send: any failure (missing secret, transport error, adapter bug)
    # is surfaced but never makes this exit non-zero — it is an alert, not the run.
    try:
        ok = _send_alert(channel, cfg, message)
    except Exception as error:  # noqa: BLE001 — an alert must never fail the run
        print(f"health alert: send failed — {error}", file=sys.stderr)
        return 0
    if ok:
        print(f"health alert sent via {channel}: {message}")
    else:
        print(f"health alert: send via {channel} reported failure (best-effort)", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry: compute health, and PUSH a one-line alert iff DEGRADED + opted in."""
    parser = argparse.ArgumentParser(
        prog="health_alert.py",
        description="Opt-in PUSH alert when the system health verdict is DEGRADED.",
    )
    parser.add_argument(
        "--root", default=str(_PROJECT_ROOT), help="Project root (default: repo root)."
    )
    parser.add_argument(
        "--config", default=str(DEFAULT_CHANNELS_CONFIG),
        help="channels.yaml path (default: config/channels.yaml).",
    )
    parser.add_argument(
        "--today", help="Override today's date (YYYY-MM-DD) — for tests/rehearsal."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the alert message that WOULD be sent, without sending it.",
    )
    args = parser.parse_args(argv)

    today: date | None = None
    if args.today:
        try:
            today = date.fromisoformat(args.today)
        except ValueError:
            print(f"--today must be YYYY-MM-DD, got {args.today!r}", file=sys.stderr)
            return 2

    return run(
        Path(args.root), Path(args.config), today=today, dry_run=args.dry_run
    )


if __name__ == "__main__":
    sys.exit(main())
