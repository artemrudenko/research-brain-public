"""Shared receipt helpers for the agent-side MCP delivery path.

Three commands, one shared `.delivered/{stem}.json` receipt and one
`.delivery.lock`, forming the agent's send sequence:

    --mcp-status   what still needs sending (PENDING / IN-FLIGHT / DELIVERED)
    --reserve-mcp  claim a channel BEFORE the external send   <- refuses a racer
    --record-mcp   promote the claim to delivered AFTER it succeeds

The reservation exists because an external send cannot be undone: without it two
agents both read PENDING, both send, and only then serialise on the receipt
write. Claiming first turns that silent double-send into a refusal.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def mcp_status(
    digest_path: Path,
    config_path: Path,
    *,
    receipt_dir: Path,
    channel_names: tuple[str, ...],
    load_config: Callable[[Path], dict[str, object]],
    load_receipt: Callable[[Path], dict[str, dict[str, str]]],
    receipt_path: Callable[[Path, Path | None], Path],
    content_hash: Callable[[str], str],
    is_agent_channel: Callable[[str, dict[str, Any]], bool],
    chunk_progress: Callable[[dict[str, str]], int],
    receipt_sent: str,
    receipt_sending: str,
    reservation_lease: float,
    receipt_content_hash: str,
) -> int:
    """Report each enabled agent-delivered channel's receipt state for `digest_path`."""
    digest_hash = content_hash(digest_path.read_text(encoding="utf-8"))
    delivery = load_config(config_path)
    receipt = load_receipt(receipt_path(digest_path, receipt_dir))
    any_mcp = False
    for channel in channel_names:
        cfg = delivery.get(channel)
        if not isinstance(cfg, dict) or not cfg.get("enabled"):
            continue
        if not is_agent_channel(channel, cfg):
            continue
        any_mcp = True
        prior = receipt.get(channel, {})
        prior_hash = prior.get(receipt_content_hash)
        # A hash-less (pre-content-hash) entry still counts as delivered: receipts
        # are keyed per digest FILE, so it can only refer to this digest. What it
        # cannot detect is a same-name rebuild, so that ambiguity is printed rather
        # than resolved by re-sending. Same rule as the headless path's
        # `ReceiptFlow.already_delivered` — the two must not disagree.
        content_matches = prior_hash is None or prior_hash == digest_hash
        status = prior.get("status")
        if status == receipt_sent and prior_hash is None:
            print(
                f"{channel:<10} DELIVERED {prior.get('timestamp', '')} "
                "(legacy receipt — no content hash, so a same-name rebuild "
                "cannot be detected; re-send explicitly if the content changed)"
            )
        elif status == receipt_sent and content_matches:
            print(f"{channel:<10} DELIVERED {prior.get('timestamp', '')}")
        elif status == receipt_sent:
            print(f"{channel:<10} PENDING (content changed since last send — send again)")
        elif status == receipt_sending and content_matches and _reservation_is_live(
            prior, reservation_lease
        ):
            # Someone else claimed it and has not finished. Reporting this as
            # PENDING would send the skill straight into the race the
            # reservation exists to stop.
            done = chunk_progress(prior)
            resume = f"; {done} chunk(s) already delivered" if done else ""
            print(
                f"{channel:<10} IN-FLIGHT (another sender claimed it — "
                f"do not send{resume})"
            )
        else:
            print(f"{channel:<10} PENDING")
    if not any_mcp:
        print("no enabled MCP channels in config — nothing for the MCP path to send")
    return 0


def _reservation_is_live(entry: dict[str, str], reservation_lease: float) -> bool:
    """True when a `sending` entry is recent enough to still own the channel.

    A reservation whose owner died mid-send would otherwise block the channel
    forever, so it expires.

    An unparseable/absent timestamp reads as EXPIRED, not live. Treating it as
    live looks like the fail-safe choice, but a `sending` entry is only ever
    cleared by a successful send: refuse every sender and nothing can clear it,
    so the channel goes silently dead with no recovery short of deleting the
    receipt by hand. Expiring is recoverable and cannot resurrect a real
    delivery, because a channel that actually went out is recorded `sent`.
    """
    stamped = entry.get("timestamp", "")
    try:
        claimed_at = datetime.fromisoformat(stamped)
    except ValueError:
        return False
    if claimed_at.tzinfo is None:
        claimed_at = claimed_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - claimed_at).total_seconds() < reservation_lease


def _reject_unusable_channel(
    channel: str,
    cfg: object,
    *,
    command: str,
    channel_names: tuple[str, ...],
    is_agent_channel: Callable[[str, dict[str, Any]], bool],
) -> int | None:
    """Return an exit code when `channel` may not be stamped by the agent path.

    Shared by reserve/record so the two commands can never disagree about which
    channels the agent owns — a channel the headless adapters deliver must never
    have its receipt written by an agent that did not send it.
    """
    if channel not in channel_names or not isinstance(cfg, dict):
        print(
            f"{command}: unknown channel {channel!r} "
            f"(expected one of: {', '.join(channel_names)})",
            file=sys.stderr,
        )
        return 2
    if not is_agent_channel(channel, cfg):
        print(
            f"{command}: channel {channel!r} is not agent-delivered in this "
            "config — the headless deliver path owns its receipt",
            file=sys.stderr,
        )
        return 2
    return None


def reserve_mcp(
    digest_path: Path,
    channel: str,
    config_path: Path,
    *,
    receipt_dir: Path,
    channel_names: tuple[str, ...],
    load_config: Callable[[Path], dict[str, object]],
    receipt_path: Callable[[Path, Path | None], Path],
    load_receipt: Callable[[Path], dict[str, dict[str, str]]],
    write_receipt: Callable[[Path, dict[str, dict[str, str]]], None],
    content_hash: Callable[[str], str],
    is_agent_channel: Callable[[str, dict[str, Any]], bool],
    record: Callable[..., None],
    receipt_sent: str,
    receipt_sending: str,
    reservation_lease: float,
    receipt_content_hash: str,
    delivery_lock_name: str,
    delivery_lock_lease: float,
    delivery_in_progress_message: str,
    in_flight_message: str,
    already_delivered_message: str,
    lock_acquire: Callable[..., Any],
    lock_release: Callable[..., Any],
) -> int:
    """Claim `channel` for `digest_path` before sending. 0 means "you may send".

    ANY non-zero exit means do NOT send: either another sender holds the channel,
    it is already delivered, or the delivery lock is busy. The check and the claim
    happen under the same `.delivery.lock` as the receipt write, so two agents
    cannot both come away believing they own the channel.

    This bounds — it cannot eliminate — duplicate delivery: an external send is
    not transactional, so a reservation abandoned past `reservation_lease` is
    reclaimable and a pathologically slow send could still be duplicated.
    """
    delivery = load_config(config_path)
    rejection = _reject_unusable_channel(
        channel,
        delivery.get(channel),
        command="reserve-mcp",
        channel_names=channel_names,
        is_agent_channel=is_agent_channel,
    )
    if rejection is not None:
        return rejection

    digest_hash = content_hash(digest_path.read_text(encoding="utf-8"))
    delivery_lock = receipt_dir / delivery_lock_name
    acquired = lock_acquire(
        delivery_lock, stale_after=delivery_lock_lease, steal_dead=True, note="reserve-mcp"
    )
    if not acquired.acquired:
        print(delivery_in_progress_message)
        return 1
    try:
        rcpt_path = receipt_path(digest_path, receipt_dir)
        receipt = load_receipt(rcpt_path)
        prior = receipt.get(channel, {})
        prior_hash = prior.get(receipt_content_hash)
        # Same match rule as `mcp_status` and the headless `already_delivered`:
        # a hash-less entry counts, because receipts are per digest file. If the
        # three disagreed, the status check and the reservation would contradict
        # each other and the skill could never make a consistent decision.
        content_matches = prior_hash is None or prior_hash == digest_hash
        if prior.get("status") == receipt_sent and content_matches:
            print(already_delivered_message)
            return 3
        if (
            prior.get("status") == receipt_sending
            and content_matches
            and _reservation_is_live(prior, reservation_lease)
        ):
            print(in_flight_message)
            return 4
        record(receipt, channel, receipt_sending, digest_hash=digest_hash)
        write_receipt(rcpt_path, receipt)
    finally:
        lock_release(delivery_lock, token=acquired.token)
    print(f"{channel:<10} reserved (MCP) for {digest_path.name} — send now, then --record-mcp")
    return 0


def record_mcp(
    digest_path: Path,
    channel: str,
    config_path: Path,
    *,
    receipt_dir: Path,
    channel_names: tuple[str, ...],
    load_config: Callable[[Path], dict[str, object]],
    receipt_path: Callable[[Path, Path | None], Path],
    load_receipt: Callable[[Path], dict[str, dict[str, str]]],
    write_receipt: Callable[[Path, dict[str, dict[str, str]]], None],
    content_hash: Callable[[str], str],
    is_agent_channel: Callable[[str, dict[str, Any]], bool],
    record: Callable[..., None],
    receipt_sent: str,
    delivery_lock_name: str,
    delivery_lock_lease: float,
    delivery_in_progress_message: str,
    lock_acquire: Callable[..., Any],
    lock_release: Callable[..., Any],
    receipt_sending: str,
    chunks_sent: int | None = None,
) -> int:
    """Stamp an MCP channel as delivered for `digest_path` in the shared receipt.

    Promotes a `reserve_mcp` claim to `sent`; also works without a prior
    reservation, so an older skill revision (or a manual stamp) still behaves.

    With `chunks_sent` it instead records PARTIAL progress on a split body: the
    entry stays `sending` (nothing was fully delivered yet) but remembers how many
    messages the user already has, so an interrupted send resumes rather than
    re-delivering them. It also refreshes the reservation timestamp, which keeps a
    slow multi-chunk send from outliving its own claim.
    """
    delivery = load_config(config_path)
    rejection = _reject_unusable_channel(
        channel,
        delivery.get(channel),
        command="record-mcp",
        channel_names=channel_names,
        is_agent_channel=is_agent_channel,
    )
    if rejection is not None:
        return rejection
    digest_hash = content_hash(digest_path.read_text(encoding="utf-8"))
    delivery_lock = receipt_dir / delivery_lock_name
    acquired = lock_acquire(
        delivery_lock, stale_after=delivery_lock_lease, steal_dead=True, note="record-mcp"
    )
    if not acquired.acquired:
        print(delivery_in_progress_message)
        return 1
    partial = chunks_sent is not None
    try:
        rcpt_path = receipt_path(digest_path, receipt_dir)
        receipt = load_receipt(rcpt_path)
        record(
            receipt,
            channel,
            receipt_sending if partial else receipt_sent,
            digest_hash=digest_hash,
            chunks_sent=chunks_sent,
        )
        write_receipt(rcpt_path, receipt)
    finally:
        lock_release(delivery_lock, token=acquired.token)
    if partial:
        print(f"{channel:<10} progress recorded: {chunks_sent} chunk(s) delivered")
    else:
        print(f"{channel:<10} recorded as delivered (MCP) for {digest_path.name}")
    return 0


__all__ = ["mcp_status", "record_mcp", "reserve_mcp"]
