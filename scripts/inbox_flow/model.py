"""Shared inbox queue model constants."""

from __future__ import annotations

from dataclasses import dataclass, field

# The pseudo-topic that holds captured-but-unprocessed articles. Leading
# underscore keeps it out of the real topic space.
INBOX_TOPIC = "_inbox"

# How many queued articles trigger a batch by default.
DEFAULT_PROCESS_THRESHOLD = 5

# Transient values used to satisfy the strict pipeline frontmatter contract while
# the source-capture skill has not assigned real author/tags yet.
DEFAULT_CAPTURE_AUTHOR = "unknown"
DEFAULT_CAPTURE_TAG = "pending/uncategorized"


@dataclass(frozen=True)
class CaptureDefaults:
    """Normalized capture metadata used when writing a queued article."""

    author: str = DEFAULT_CAPTURE_AUTHOR
    tags: list[str] = field(default_factory=lambda: [DEFAULT_CAPTURE_TAG])


def capture_defaults(author: str = "", tags: list[str] | None = None) -> CaptureDefaults:
    """Return frontmatter-safe author/tags, filling strict-contract defaults."""
    clean_author = author.strip() or DEFAULT_CAPTURE_AUTHOR
    clean_tags = [tag.strip() for tag in (tags or []) if tag.strip()] or [DEFAULT_CAPTURE_TAG]
    return CaptureDefaults(author=clean_author, tags=clean_tags)


__all__ = [
    "DEFAULT_CAPTURE_AUTHOR",
    "DEFAULT_CAPTURE_TAG",
    "DEFAULT_PROCESS_THRESHOLD",
    "INBOX_TOPIC",
    "CaptureDefaults",
    "capture_defaults",
]

