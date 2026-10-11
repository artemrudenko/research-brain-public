"""Final status calculation for delivery runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api import DeliveryApi


@dataclass
class DeliveryRunStatus:
    """Counters that determine runtime reporting and exit status."""

    any_enabled: bool = False
    enabled_count: int = 0
    mcp_skipped: int = 0
    mcp_skipped_channels: list[str] = field(default_factory=list)
    failures: int = 0
    receipt_persist_failed: bool = False

    def mark_enabled(self) -> None:
        """Count one enabled channel."""
        self.any_enabled = True
        self.enabled_count += 1

    def mark_mcp_skipped(self, channel: str = "") -> None:
        """Count one enabled channel skipped because it is MCP-only."""
        self.mcp_skipped += 1
        if channel:
            self.mcp_skipped_channels.append(channel)

    def mark_failure(self) -> None:
        """Count one failed enabled channel."""
        self.failures += 1


def report_final_status(
    status: DeliveryRunStatus,
    *,
    dry_run: bool,
    api: DeliveryApi,
) -> None:
    """Print final no-op/MCP-only summary lines; log the delivered-to-nobody case.

    An all-MCP-only headless run exits 0 (agent mode sends those channels), so
    without a health event this is the one failure mode with zero signal: cron
    stamps the heartbeat, the digest file exists, health stays OK while nobody
    receives anything. Append a per-channel failure-status event so /status
    flips DEGRADED and the daily watchdog pings."""
    if not status.any_enabled:
        print(api.NO_CHANNELS_MESSAGE)
    elif not dry_run and status.mcp_skipped == status.enabled_count:
        print(api.ALL_MCP_ONLY_MESSAGE)
        api._record_all_mcp_only_health(status.mcp_skipped_channels)


def exit_code(status: DeliveryRunStatus, *, dry_run: bool) -> int:
    """Return the deliver() process-style exit code."""
    if dry_run:
        return 0
    return 1 if (status.failures or status.receipt_persist_failed) else 0


__all__ = [
    "DeliveryRunStatus",
    "exit_code",
    "report_final_status",
]
