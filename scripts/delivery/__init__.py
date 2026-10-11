"""
scripts.delivery — headless transport for the weekly digest.

Pure-stdlib adapters (urllib / smtplib / email) plus a config-driven dispatcher.
Used by cron / no-agent runs; the agent-driven path lives in the
`digest-deliver` skill. Each adapter exposes a single `send(...) -> bool` so
network calls stay isolated and testable (monkeypatch-friendly).
"""

from . import email_smtp, rocketchat_webhook, telegram_botapi

__all__ = ["email_smtp", "rocketchat_webhook", "telegram_botapi"]
