"""Shared delivery model types."""

from __future__ import annotations

import enum


class SendOutcome(enum.Enum):
    """Outcome of dispatching one channel in a headless run."""

    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class DeliveryError(Exception):
    """Raised for an unrecoverable config/secret problem on an enabled channel."""


# The single-channel dispatch contract: (outcome, failure reason when FAILED).
# One alias so the adapters, the dispatch seam, and the DeliveryApi protocol
# can never drift apart on this shape.
SendResult = tuple[SendOutcome, str | None]


__all__ = [
    "DeliveryError",
    "SendOutcome",
    "SendResult",
]
