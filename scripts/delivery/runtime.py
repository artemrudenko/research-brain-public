"""Runtime delivery orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .dispatch import dispatch_channel
from .receipt_flow import start_receipt_flow
from .runtime_context import (
    DeliveryInProgress,
    acquire_delivery_lock,
    collect_channel_configs,
    has_enabled_channel,
    release_delivery_lock,
)
from .runtime_status import DeliveryRunStatus, exit_code, report_final_status

if TYPE_CHECKING:
    from .api import DeliveryApi


def deliver(
    digest_path: Path,
    config_path: Path,
    *,
    dry_run: bool,
    force: bool,
    skip_quiet: bool,
    receipt_dir: Path | None,
    attempted: set[str] | None,
    api: DeliveryApi,
) -> int:
    """Deliver `digest_path` using the stable deliver.py facade as compatibility API."""
    receipt_dir = receipt_dir or api._default_receipt_dir()

    text = digest_path.read_text(encoding="utf-8")

    if skip_quiet and not dry_run and api.is_quiet_digest(text):
        print(api.QUIET_SKIP_MESSAGE)
        return 0

    delivery = api.load_config(config_path)
    channel_configs = collect_channel_configs(delivery, api._CHANNELS)
    try:
        delivery_lock = acquire_delivery_lock(
            receipt_dir,
            dry_run=dry_run,
            needs_lock=has_enabled_channel(channel_configs),
            api=api,
        )
    except DeliveryInProgress:
        print(api.DELIVERY_IN_PROGRESS_MESSAGE)
        return 1

    receipt_flow = start_receipt_flow(digest_path, receipt_dir, dry_run=dry_run, api=api)
    digest_hash = api.content_hash(text)
    status = DeliveryRunStatus()
    try:
        for channel_config in channel_configs:
            channel = channel_config.name
            cfg = channel_config.config
            if cfg is None or not channel_config.enabled:
                print(f"{channel:<10} {api.STATUS_SKIPPED} (disabled)")
                continue
            status.mark_enabled()
            if dry_run:
                api._dry_run_channel(channel, cfg)
                continue

            if receipt_flow.already_delivered(
                channel, digest_hash=digest_hash, force=force, api=api
            ):
                continue

            if attempted is not None:
                attempted.add(channel)
            try:
                outcome, failure_reason = dispatch_channel(
                    channel, cfg, text=text, digest_path=digest_path, api=api
                )
            except api.DeliveryError as error:
                print(f"{channel:<10} {api.STATUS_FAILED} — {error}")
                receipt_flow.record_status(
                    channel,
                    api.RECEIPT_FAILED,
                    digest_hash=digest_hash,
                    reason=str(error),
                    api=api,
                )
                status.mark_failure()
                continue
            except Exception as error:  # noqa: BLE001
                print(f"{channel:<10} {api.STATUS_FAILED} — unexpected error: {error}")
                receipt_flow.record_status(
                    channel,
                    api.RECEIPT_FAILED,
                    digest_hash=digest_hash,
                    reason=f"unexpected error: {error}",
                    api=api,
                )
                status.mark_failure()
                continue

            if outcome is api.SendOutcome.SKIPPED:
                status.mark_mcp_skipped(channel)
                continue
            receipt_flow.record_outcome(
                channel,
                outcome,
                digest_hash=digest_hash,
                reason=failure_reason,
                api=api,
            )
            if outcome is api.SendOutcome.FAILED:
                status.mark_failure()
    finally:
        status.receipt_persist_failed = receipt_flow.finalize(dry_run=dry_run, api=api)
        release_delivery_lock(delivery_lock, api=api)

    report_final_status(status, dry_run=dry_run, api=api)
    return exit_code(status, dry_run=dry_run)


__all__ = [
    "deliver",
]
