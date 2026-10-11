"""Shared constants for the delivery package."""

from __future__ import annotations

# Status tokens for the per-channel report line.
STATUS_SENT = "SENT"
STATUS_SKIPPED = "SKIPPED"
STATUS_FAILED = "FAILED"

# Receipt status values (lower-case, persisted in JSON).
RECEIPT_SENT = "sent"
RECEIPT_FAILED = "failed"
# Claimed by an agent that is about to send but has not finished. Written BEFORE
# the external side effect so a second sender is refused rather than duplicating it.
RECEIPT_SENDING = "sending"

# How long a `sending` reservation is honoured before it is treated as abandoned.
# An external send is not transactional, so this is a deliberate trade-off: too
# short and a slow multi-chunk send gets duplicated; too long and an agent that
# died mid-send blocks the channel. Sized like DELIVERY_LOCK_LEASE — comfortably
# past a worst-case send — because a stuck channel is recoverable (wait, or clear
# the receipt) while a duplicate delivery is not.
RESERVATION_LEASE = 3600.0
RESERVATION_IN_FLIGHT_MESSAGE = (
    "delivery: another sender has this channel in flight — not sending (it will "
    "be retryable if that sender fails)"
)
RESERVATION_ALREADY_DELIVERED_MESSAGE = (
    "delivery: this channel is already delivered for this digest content — not sending"
)

# Delivery concurrency guard. The lock is taken with steal_dead=True, so a crashed
# holder is reclaimed instantly (dead pid) regardless of the lease — the lease only
# bounds when a LIVE holder may be stolen. A slow large multi-channel send (email +
# telegram chunks + rocketchat, each ~30s with a retry) can run for many minutes; a
# short lease would let a second run steal the lock mid-send and re-deliver the digest.
# One hour comfortably exceeds the worst-case send budget without delaying crash recovery.
DELIVERY_LOCK_NAME = ".delivery.lock"
DELIVERY_LOCK_LEASE = 3600.0
DELIVERY_IN_PROGRESS_MESSAGE = (
    "delivery: another delivery is already in progress — skipping to avoid a "
    "double send (retry once it finishes)"
)

# The known headless vs. agent-side channel modes.
EMAIL_HEADLESS_PROVIDER = "smtp"
EMAIL_MCP_PROVIDER = "gmail-mcp"
TELEGRAM_HEADLESS_TRANSPORT = "bot-api"
TELEGRAM_MCP_TRANSPORT = "mcp"

# Bounded retry on transient transport errors (one extra attempt — no new deps).
MAX_SEND_ATTEMPTS = 2

NO_CHANNELS_MESSAGE = "no enabled channels — nothing to deliver"
ALL_MCP_ONLY_MESSAGE = (
    "note: every enabled channel is MCP-only, so this headless run delivered "
    "nothing. In agent/MCP mode that is expected — the digest-deliver skill sends "
    "those. For cron/headless delivery switch email to provider: smtp and telegram "
    "to transport: bot-api in config/channels.yaml."
)
QUIET_SKIP_MESSAGE = "quiet week — nothing new; skipping delivery (--skip-quiet)"

SAMPLE_MESSAGE = (
    "# research-brain — test message\n\n"
    "This is a delivery test. If you can read this, the channel is wired up.\n"
)

CHANNELS = ("email", "telegram", "rocketchat")

# Rocket.Chat is webhook-only, but in MCP mode the agent skill POSTs the webhook
# itself, so it — not the headless deliver path — owns the receipt on that run.
ROCKETCHAT_CHANNEL = "rocketchat"


__all__ = [
    "ALL_MCP_ONLY_MESSAGE",
    "CHANNELS",
    "ROCKETCHAT_CHANNEL",
    "DELIVERY_IN_PROGRESS_MESSAGE",
    "DELIVERY_LOCK_LEASE",
    "DELIVERY_LOCK_NAME",
    "EMAIL_HEADLESS_PROVIDER",
    "EMAIL_MCP_PROVIDER",
    "MAX_SEND_ATTEMPTS",
    "NO_CHANNELS_MESSAGE",
    "QUIET_SKIP_MESSAGE",
    "RECEIPT_FAILED",
    "RECEIPT_SENDING",
    "RECEIPT_SENT",
    "RESERVATION_ALREADY_DELIVERED_MESSAGE",
    "RESERVATION_IN_FLIGHT_MESSAGE",
    "RESERVATION_LEASE",
    "SAMPLE_MESSAGE",
    "STATUS_FAILED",
    "STATUS_SENT",
    "STATUS_SKIPPED",
    "TELEGRAM_HEADLESS_TRANSPORT",
    "TELEGRAM_MCP_TRANSPORT",
]
