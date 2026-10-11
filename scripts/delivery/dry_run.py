"""Dry-run reporting for delivery channels."""

from __future__ import annotations

from collections.abc import Callable

from .constants import (
    EMAIL_HEADLESS_PROVIDER,
    EMAIL_MCP_PROVIDER,
    STATUS_SKIPPED,
    TELEGRAM_HEADLESS_TRANSPORT,
    TELEGRAM_MCP_TRANSPORT,
)


def dry_run_channel(
    channel: str,
    cfg: dict[str, object],
    *,
    secret_state: Callable[[str], str],
) -> None:
    """Print what an enabled channel would send without resolving secrets."""
    if channel == "email":
        provider = cfg.get("provider")
        if provider != EMAIL_HEADLESS_PROVIDER:
            if provider == EMAIL_MCP_PROVIDER:
                print(f"email     {STATUS_SKIPPED} (provider={provider} is MCP-only)")
            else:
                print(f"email     CONFIG ERROR (unknown provider={provider!r})")
            return
        raw_smtp = cfg.get("smtp")
        smtp: dict[str, object] = raw_smtp if isinstance(raw_smtp, dict) else {}
        env_var = str(smtp.get("password_env", "SMTP_PASSWORD"))
        raw_to = cfg.get("to")
        to_list: list[object] = raw_to if isinstance(raw_to, list) else []
        recipients = ", ".join(map(str, to_list)) or "(none)"
        print(
            f"email     WOULD SEND (transport=smtp -> {recipients}; "
            f"secret {env_var}={secret_state(env_var)})"
        )
    elif channel == "telegram":
        transport = cfg.get("transport")
        if transport != TELEGRAM_HEADLESS_TRANSPORT:
            if transport == TELEGRAM_MCP_TRANSPORT:
                print(f"telegram  {STATUS_SKIPPED} (transport={transport} is MCP-only)")
            else:
                print(f"telegram  CONFIG ERROR (unknown transport={transport!r})")
            return
        env_var = str(cfg.get("token_env", "TELEGRAM_BOT_TOKEN"))
        chat_id = str(cfg.get("chat_id", "")) or "(none)"
        print(
            f"telegram  WOULD SEND (transport=bot-api -> chat {chat_id}; "
            f"secret {env_var}={secret_state(env_var)})"
        )
    else:
        env_var = str(cfg.get("webhook_url_env", "ROCKETCHAT_WEBHOOK_URL"))
        print(
            f"rocketchat WOULD SEND (transport=webhook; "
            f"secret {env_var}={secret_state(env_var)})"
        )


__all__ = ["dry_run_channel"]
