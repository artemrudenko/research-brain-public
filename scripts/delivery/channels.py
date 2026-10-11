"""Headless channel dispatchers for digest delivery."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import email_html, email_smtp, rocketchat_webhook, telegram_botapi
from .constants import (
    EMAIL_HEADLESS_PROVIDER,
    EMAIL_MCP_PROVIDER,
    ROCKETCHAT_CHANNEL,
    STATUS_FAILED,
    STATUS_SENT,
    STATUS_SKIPPED,
    TELEGRAM_HEADLESS_TRANSPORT,
    TELEGRAM_MCP_TRANSPORT,
)


class ChannelError(Exception):
    """Raised for a channel config or secret problem."""


def email_subject(digest_path: Path) -> str:
    """Derive an email subject from the digest filename."""
    return f"Research digest — {digest_path.stem}"


def send_with_retry(send_fn: Callable[[], bool], *, attempts: int) -> bool:
    """Call a zero-arg send closure with a bounded retry."""
    for attempt in range(1, attempts + 1):
        if send_fn():
            return True
        if attempt < attempts:
            print(f"           retry {attempt}/{attempts - 1} (transient send failure)")
    return False


def deliver_email(
    cfg: dict[str, object],
    text: str,
    digest_path: Path,
    *,
    env_or_fail: Callable[[str, str], str],
    retry: Callable[[Callable[[], bool]], bool],
) -> tuple[str, str | None]:
    """Dispatch the email channel; returns (sent|failed|skipped, failure reason)."""
    provider = cfg.get("provider")
    if provider != EMAIL_HEADLESS_PROVIDER:
        if provider == EMAIL_MCP_PROVIDER:
            print(f"email     {STATUS_SKIPPED} (provider={provider} is MCP-only)")
            return "skipped", None
        raise ChannelError(
            f"[email] unknown provider {provider!r} "
            f"(expected {EMAIL_HEADLESS_PROVIDER!r} or {EMAIL_MCP_PROVIDER!r})"
        )
    recipients = cfg.get("to") or []
    if not isinstance(recipients, list) or not recipients:
        raise ChannelError("[email] provider smtp but 'to:' list is empty")
    smtp = cfg.get("smtp") or {}
    if not isinstance(smtp, dict):
        raise ChannelError("[email] missing 'smtp:' block")
    password = env_or_fail("email", str(smtp.get("password_env", "SMTP_PASSWORD")))
    host = str(smtp.get("host", ""))
    try:
        port = int(smtp.get("port", 587))
    except (TypeError, ValueError) as error:
        raise ChannelError(
            f"[email] smtp.port must be an integer, got {smtp.get('port')!r}"
        ) from error
    user = str(smtp.get("user", ""))
    to = [str(r) for r in recipients]
    try:
        html_body = email_html.render_email_html(text, title=email_subject(digest_path))
    except Exception:  # noqa: BLE001 — never let formatting break delivery
        html_body = None
    refused: list[str] = []
    # Out-box for the LAST attempt's failure reason (the retry wrapper only
    # passes a bool through, same trick as `refused` above).
    failure_reason: list[str | None] = [None]

    def _attempt() -> bool:
        result = email_smtp.send_detailed(
            email_subject(digest_path),
            text,
            to=to,
            host=host,
            port=port,
            user=user,
            password=password,
            html=html_body,
        )
        refused[:] = result.refused
        if result.reason:
            failure_reason[0] = result.reason
        return result.ok

    ok = retry(_attempt)
    target = ", ".join(map(str, recipients))
    if ok:
        line = f"email     {STATUS_SENT} (-> {target})"
        if refused:
            line += (
                f"  [WARNING: {len(refused)} recipient(s) refused, fix by hand: "
                f"{', '.join(refused)}]"
            )
        print(line)
        return "sent", None
    reason = failure_reason[0] or "SMTP send failed"
    print(f"email     {STATUS_FAILED} (-> {target}; {reason} via {host}:{port})")
    return "failed", reason


def deliver_telegram(
    cfg: dict[str, object],
    text: str,
    *,
    env_or_fail: Callable[[str, str], str],
) -> tuple[str, str | None]:
    """Dispatch the telegram channel; returns (sent|failed|skipped, failure reason)."""
    transport = cfg.get("transport")
    if transport != TELEGRAM_HEADLESS_TRANSPORT:
        if transport == TELEGRAM_MCP_TRANSPORT:
            print(f"telegram  {STATUS_SKIPPED} (transport={transport} is MCP-only)")
            return "skipped", None
        raise ChannelError(
            f"[telegram] unknown transport {transport!r} "
            f"(expected {TELEGRAM_HEADLESS_TRANSPORT!r} or {TELEGRAM_MCP_TRANSPORT!r})"
        )
    chat_id = str(cfg.get("chat_id", ""))
    if not chat_id:
        raise ChannelError("[telegram] transport bot-api but 'chat_id' is empty")
    token = env_or_fail("telegram", str(cfg.get("token_env", "TELEGRAM_BOT_TOKEN")))
    result = telegram_botapi.send_detailed(
        text, token=token, chat_id=chat_id, render_markdown=True
    )
    if result.ok:
        print(f"telegram  {STATUS_SENT} (-> {chat_id})")
        return "sent", None
    reason = result.reason or "Bot API send failed"
    print(f"telegram  {STATUS_FAILED} (-> {chat_id}; {reason})")
    return "failed", reason


def deliver_rocketchat(
    cfg: dict[str, object],
    text: str,
    *,
    env_or_fail: Callable[[str, str], str],
    retry: Callable[[Callable[[], bool]], bool],
) -> tuple[str, str | None]:
    """Dispatch the Rocket.Chat channel; returns (sent|failed, failure reason)."""
    webhook_url = env_or_fail(
        "rocketchat", str(cfg.get("webhook_url_env", "ROCKETCHAT_WEBHOOK_URL"))
    )
    if not rocketchat_webhook.is_safe_webhook_url(webhook_url):
        reason = "webhook URL rejected: not http(s) to a public host"
        print(
            f"rocketchat {STATUS_FAILED} ({reason} — check the "
            "ROCKETCHAT_WEBHOOK_URL value)"
        )
        return "failed", reason
    ok = retry(lambda: rocketchat_webhook.send(text, webhook_url=webhook_url))
    if ok:
        print(f"rocketchat {STATUS_SENT}")
        return "sent", None
    print(f"rocketchat {STATUS_FAILED} (webhook POST failed)")
    return "failed", "webhook POST failed"


def is_mcp_channel(channel: str, cfg: dict[str, object]) -> bool:
    """True when a channel is configured for the agent-side MCP transport.

    Used by the HEADLESS path (`deliver.py`) to skip channels the agent skill
    sends. Rocket.Chat is deliberately NOT here: it is a webhook the headless path
    sends itself, so it must not be skipped in cron mode.
    """
    if channel == "email":
        return cfg.get("provider") == EMAIL_MCP_PROVIDER
    if channel == "telegram":
        return cfg.get("transport") == TELEGRAM_MCP_TRANSPORT
    return False


def is_agent_delivered_channel(channel: str, cfg: dict[str, object]) -> bool:
    """True when the agent skill (MCP mode) sends this channel itself.

    That is every MCP-transport channel PLUS Rocket.Chat, whose webhook the skill
    POSTs directly in MCP mode. This — not `is_mcp_channel` — is the predicate the
    receipt commands (`record-mcp` / `mcp-status`) use to decide who owns the
    receipt: the skill must be able to stamp and consult Rocket.Chat so a re-run
    does not re-POST it. The headless send-skip keeps using `is_mcp_channel`, so
    cron still sends Rocket.Chat; the shared receipt stops the two double-sending.
    """
    return is_mcp_channel(channel, cfg) or channel == ROCKETCHAT_CHANNEL


__all__ = [
    "ChannelError",
    "deliver_email",
    "deliver_rocketchat",
    "deliver_telegram",
    "email_subject",
    "is_agent_delivered_channel",
    "is_mcp_channel",
    "send_with_retry",
]
