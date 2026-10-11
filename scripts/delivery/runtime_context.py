"""Runtime context helpers for headless delivery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api import DeliveryApi


@dataclass(frozen=True)
class ChannelConfig:
    """One configured delivery channel for a runtime pass."""

    name: str
    config: dict[str, object] | None

    @property
    def enabled(self) -> bool:
        """Whether this channel has an enabled mapping in channels.yaml."""
        return self.config is not None and bool(self.config.get("enabled"))


@dataclass(frozen=True)
class DeliveryRunLock:
    """The optional lock held for a live delivery run."""

    path: Path
    token: str | None


class DeliveryInProgress(Exception):
    """Raised when another live delivery already holds the delivery lock."""


def collect_channel_configs(
    delivery: dict[str, object], channel_names: tuple[str, ...]
) -> list[ChannelConfig]:
    """Return channel configs in delivery order, preserving disabled entries."""
    configs: list[ChannelConfig] = []
    for channel in channel_names:
        cfg = delivery.get(channel)
        configs.append(ChannelConfig(channel, cfg if isinstance(cfg, dict) else None))
    return configs


def has_enabled_channel(configs: list[ChannelConfig]) -> bool:
    """True when at least one configured channel is enabled."""
    return any(config.enabled for config in configs)


def acquire_delivery_lock(
    receipt_dir: Path,
    *,
    dry_run: bool,
    needs_lock: bool,
    api: DeliveryApi,
) -> DeliveryRunLock:
    """Acquire the live delivery lock when this run can send real messages."""
    delivery_lock = receipt_dir / api.DELIVERY_LOCK_NAME
    if dry_run or not needs_lock:
        return DeliveryRunLock(delivery_lock, None)

    acquired = api._lock_acquire(
        delivery_lock,
        stale_after=api.DELIVERY_LOCK_LEASE,
        steal_dead=True,
        note="delivery",
    )
    if not acquired.acquired:
        raise DeliveryInProgress
    return DeliveryRunLock(delivery_lock, acquired.token)


def release_delivery_lock(lock: DeliveryRunLock, *, api: DeliveryApi) -> None:
    """Release a lock acquired by `acquire_delivery_lock`."""
    if lock.token is not None:
        api._lock_release(lock.path, token=lock.token)


__all__ = [
    "ChannelConfig",
    "DeliveryInProgress",
    "DeliveryRunLock",
    "acquire_delivery_lock",
    "collect_channel_configs",
    "has_enabled_channel",
    "release_delivery_lock",
]
