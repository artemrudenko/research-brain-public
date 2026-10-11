from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Status = Literal["invalid", "unsupported", "already_existing", "ready", "added", "failed"]

STATUSES: tuple[Status, ...] = (
    "invalid",
    "unsupported",
    "already_existing",
    "ready",
    "added",
    "failed",
)


class OpmlError(ValueError):
    """Unsafe or malformed OPML input."""


class UsageError(ValueError):
    """Invalid CLI selection or assignment."""


@dataclass(frozen=True)
class OpmlEntry:
    """One candidate subscription-like OPML outline."""

    id: str
    title: str
    xml_url: str
    outline_type: str
    folder_label: str | None
    sequence: int

