"""Facade-backed MCP receipt commands for delivery."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api import DeliveryApi


def mcp_status(
    digest_path: Path,
    config_path: Path,
    *,
    receipt_dir: Path | None,
    api: DeliveryApi,
) -> int:
    """Report each enabled MCP channel's receipt state for `digest_path`."""
    return api.mcp_receipts.mcp_status(
        digest_path,
        config_path,
        receipt_dir=receipt_dir or api._default_receipt_dir(),
        channel_names=api._CHANNELS,
        load_config=api.load_config,
        load_receipt=api.load_receipt,
        receipt_path=api.receipt_path,
        content_hash=api.content_hash,
        is_agent_channel=api._is_agent_delivered_channel,
        chunk_progress=api.chunk_progress,
        receipt_sent=api.RECEIPT_SENT,
        receipt_sending=api.RECEIPT_SENDING,
        reservation_lease=api.RESERVATION_LEASE,
        receipt_content_hash=api.RECEIPT_CONTENT_HASH,
    )


def reserve_mcp(
    digest_path: Path,
    channel: str,
    config_path: Path,
    *,
    receipt_dir: Path | None,
    api: DeliveryApi,
) -> int:
    """Claim one MCP channel in the shared receipt before the external send."""
    return api.mcp_receipts.reserve_mcp(
        digest_path,
        channel,
        config_path,
        receipt_dir=receipt_dir or api._default_receipt_dir(),
        channel_names=api._CHANNELS,
        load_config=api.load_config,
        receipt_path=api.receipt_path,
        load_receipt=api.load_receipt,
        write_receipt=api.write_receipt,
        content_hash=api.content_hash,
        is_agent_channel=api._is_agent_delivered_channel,
        record=api._record,
        receipt_sent=api.RECEIPT_SENT,
        receipt_sending=api.RECEIPT_SENDING,
        reservation_lease=api.RESERVATION_LEASE,
        receipt_content_hash=api.RECEIPT_CONTENT_HASH,
        delivery_lock_name=api.DELIVERY_LOCK_NAME,
        delivery_lock_lease=api.DELIVERY_LOCK_LEASE,
        delivery_in_progress_message=api.DELIVERY_IN_PROGRESS_MESSAGE,
        in_flight_message=api.RESERVATION_IN_FLIGHT_MESSAGE,
        already_delivered_message=api.RESERVATION_ALREADY_DELIVERED_MESSAGE,
        lock_acquire=api._lock_acquire,
        lock_release=api._lock_release,
    )


def record_mcp(
    digest_path: Path,
    channel: str,
    config_path: Path,
    *,
    receipt_dir: Path | None,
    api: DeliveryApi,
    chunks_sent: int | None = None,
) -> int:
    """Stamp one MCP channel as delivered — or record partial chunk progress."""
    return api.mcp_receipts.record_mcp(
        digest_path,
        channel,
        config_path,
        receipt_dir=receipt_dir or api._default_receipt_dir(),
        channel_names=api._CHANNELS,
        load_config=api.load_config,
        receipt_path=api.receipt_path,
        load_receipt=api.load_receipt,
        write_receipt=api.write_receipt,
        content_hash=api.content_hash,
        is_agent_channel=api._is_agent_delivered_channel,
        record=api._record,
        receipt_sent=api.RECEIPT_SENT,
        receipt_sending=api.RECEIPT_SENDING,
        chunks_sent=chunks_sent,
        delivery_lock_name=api.DELIVERY_LOCK_NAME,
        delivery_lock_lease=api.DELIVERY_LOCK_LEASE,
        delivery_in_progress_message=api.DELIVERY_IN_PROGRESS_MESSAGE,
        lock_acquire=api._lock_acquire,
        lock_release=api._lock_release,
    )


__all__ = [
    "mcp_status",
    "record_mcp",
    "reserve_mcp",
]
