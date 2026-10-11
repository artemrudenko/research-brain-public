"""Receipt idempotency and persistence flow for delivery runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api import DeliveryApi
    from .model import SendOutcome


@dataclass
class ReceiptFlow:
    """In-memory receipt state plus persistence helpers for one delivery run."""

    path: Path
    receipt: dict[str, dict[str, str]]
    changed: bool = False

    def already_delivered(
        self,
        channel: str,
        *,
        digest_hash: str,
        force: bool,
        api: DeliveryApi,
    ) -> bool:
        """Return True and print the idempotent skip line when a channel is sent.

        A receipt with no content hash (written before content hashing) still
        counts as a match, deliberately: receipts are keyed PER DIGEST FILE
        (`receipt_path` -> `{stem}.json`), so such an entry can only mean "this
        very digest was delivered" — a new digest has a different stem and its
        own, empty receipt. Refusing to match would re-deliver every legacy
        digest once, to real channels, to guard the one narrow case a hash-less
        entry genuinely cannot detect: a same-name REBUILD with changed content.
        That case is surfaced in the skip line instead of being paid for with
        duplicate sends. (External review 2026-07-25 P2 argued the opposite;
        per-digest keying is why the original call stands.)
        """
        prior = self.receipt.get(channel, {})
        prior_hash = prior.get(api.RECEIPT_CONTENT_HASH)
        content_matches = prior_hash is None or prior_hash == digest_hash
        if (
            not force
            and prior.get("status") == api.RECEIPT_SENT
            and content_matches
        ):
            unverified = "" if prior_hash is not None else " — legacy receipt, content unverified"
            print(
                f"{channel:<10} {api.STATUS_SKIPPED} "
                f"(already delivered {prior.get('timestamp', '')}{unverified})"
            )
            return True
        return False

    def record_status(
        self,
        channel: str,
        status: str,
        *,
        digest_hash: str,
        reason: str | None = None,
        api: DeliveryApi,
    ) -> None:
        """Record and best-effort flush one channel status (+ failure reason)."""
        api._record(
            self.receipt, channel, status, digest_hash=digest_hash, reason=reason
        )
        self.changed = True
        self.flush_best_effort(api=api)

    def record_outcome(
        self,
        channel: str,
        outcome: SendOutcome,
        *,
        digest_hash: str,
        reason: str | None = None,
        api: DeliveryApi,
    ) -> None:
        """Persist SENT/FAILED outcomes; SKIPPED outcomes are intentionally omitted."""
        status = (
            api.RECEIPT_SENT
            if outcome is api.SendOutcome.SENT
            else api.RECEIPT_FAILED
        )
        self.record_status(
            channel, status, digest_hash=digest_hash, reason=reason, api=api
        )

    def flush_best_effort(self, *, api: DeliveryApi) -> None:
        """Persist the receipt without affecting channel processing."""
        try:
            api.write_receipt(self.path, self.receipt)
        except OSError:
            pass

    def finalize(self, *, dry_run: bool, api: DeliveryApi) -> bool:
        """Flush changed receipts at run end; return True when persistence failed."""
        if dry_run or not self.changed:
            return False
        try:
            api.write_receipt(self.path, self.receipt)
        except OSError as error:
            print(f"receipt write failed — delivery may re-send next run: {error}")
            return True
        return False


def start_receipt_flow(
    digest_path: Path,
    receipt_dir: Path,
    *,
    dry_run: bool,
    api: DeliveryApi,
) -> ReceiptFlow:
    """Build the receipt flow, avoiding receipt reads during dry-runs."""
    rcpt_path = api.receipt_path(digest_path, receipt_dir)
    receipt = {} if dry_run else api.load_receipt(rcpt_path)
    return ReceiptFlow(rcpt_path, receipt)


__all__ = [
    "ReceiptFlow",
    "start_receipt_flow",
]
