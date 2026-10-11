"""Facade-compatible channel dispatch selection for delivery runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from .api import DeliveryApi
    from .model import SendResult


def dispatch_channel(
    channel: str,
    cfg: dict[str, object],
    *,
    text: str,
    digest_path: Path,
    api: DeliveryApi,
) -> SendResult:
    """Dispatch one enabled channel through monkeypatch-compatible facade names."""
    if channel == "email":
        return api._deliver_email(cfg, text, digest_path)
    if channel == "telegram":
        return api._deliver_telegram(cfg, text)
    return api._deliver_rocketchat(cfg, text)


__all__ = ["dispatch_channel"]
