"""Best-effort delivery health logging."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def record_delivery_health(
    digest_path: Path,
    *,
    channels: set[str] | None,
    project_root: Path,
    receipt_dir: Path,
    load_receipt: Callable[[Path], dict[str, dict[str, str]]],
    receipt_path: Callable[[Path, Path | None], Path],
) -> None:
    """Append one health event per attempted delivery channel."""
    try:
        from scripts import health  # noqa: PLC0415 — optional, lazy

        receipt = load_receipt(receipt_path(digest_path, receipt_dir))
        for channel, info in receipt.items():
            if channels is not None and channel not in channels:
                continue
            # Carry the receipt's failure reason into the event, so /status
            # forensics can distinguish a 401 from a timeout without a rerun.
            reason = info.get("reason")
            health.record_event(
                project_root,
                "deliver",
                status=info.get("status", "unknown"),
                channel=channel,
                details={"reason": reason} if reason else None,
            )
    except Exception:  # noqa: BLE001 — health logging must never break delivery  # nosec B110
        pass


def record_channel_statuses(
    channels: list[str], *, status: str, project_root: Path
) -> None:
    """Append one health event per channel with the given status.

    For skips/failures that never reach a receipt (e.g. the all-MCP-only
    headless run). Best-effort: never raises."""
    try:
        from scripts import health  # noqa: PLC0415 — optional, lazy

        for channel in channels:
            health.record_event(project_root, "deliver", status=status, channel=channel)
    except Exception:  # noqa: BLE001 — health logging must never break delivery  # nosec B110
        pass


__all__ = ["record_channel_statuses", "record_delivery_health"]
