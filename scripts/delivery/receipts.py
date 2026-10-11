"""Delivery receipt persistence helpers."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

RECEIPT_CONTENT_HASH = "content_hash"


def receipt_path(digest_path: Path, receipt_dir: Path) -> Path:
    """Return the receipt JSON path for a digest."""
    return receipt_dir / f"{digest_path.stem}.json"


def load_receipt(path: Path) -> dict[str, dict[str, str]]:
    """Load a delivery receipt; return {} when absent or unreadable."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def write_receipt(path: Path, receipt: dict[str, dict[str, str]]) -> None:
    """Persist `receipt` as pretty JSON via same-dir atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    suffix = f".{os.getpid()}.{os.urandom(6).hex()}.tmp"
    tmp = path.with_name(path.name + suffix)
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def content_hash(text: str) -> str:
    """Stable short hash of a digest body."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def record(
    receipt: dict[str, dict[str, str]],
    channel: str,
    status: str,
    *,
    digest_hash: str,
    reason: str | None = None,
    chunks_sent: int | None = None,
) -> None:
    """Stamp one channel status in an in-memory receipt.

    `reason` (failures only) persists the WHY next to the "failed" status, so
    `cat .delivered/<digest>.json` diagnoses a dead cron send without a rerun.
    `chunks_sent` (in-progress chunked sends only) records how many messages of a
    split body already reached the user, so an interrupted send resumes instead
    of re-delivering the parts they have.

    The whole channel entry is replaced, so a later success drops a stale reason
    AND stale chunk progress — a completed send has no resume point.
    """
    entry = {
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        RECEIPT_CONTENT_HASH: digest_hash,
    }
    if reason:
        entry["reason"] = reason
    if chunks_sent is not None:
        # Stored as a string: receipt entries are `dict[str, str]` end to end, and
        # widening that for one field would ripple through every reader. Parse it
        # back with `chunk_progress`.
        entry["chunks_sent"] = str(chunks_sent)
    receipt[channel] = entry


def chunk_progress(entry: dict[str, str]) -> int:
    """How many chunks of a split body already reached the user (0 if unknown).

    Tolerant by design: a missing, empty, or non-numeric value means "no proven
    progress", which restarts the send rather than skipping messages the user
    never received.
    """
    try:
        return max(0, int(entry.get("chunks_sent", "0")))
    except ValueError:
        return 0


__all__ = [
    "RECEIPT_CONTENT_HASH",
    "chunk_progress",
    "content_hash",
    "load_receipt",
    "receipt_path",
    "record",
    "write_receipt",
]
