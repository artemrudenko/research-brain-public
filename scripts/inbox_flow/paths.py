"""Path helpers for the inbox queue."""

from __future__ import annotations

import os
import re
from pathlib import Path

from scripts.inbox_flow.model import INBOX_TOPIC

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """A filesystem-safe, lowercase-hyphenated slug; 'untitled' when empty."""
    slug = _SLUG_STRIP.sub("-", text.strip().lower()).strip("-")
    return slug or "untitled"


def inbox_dir(incoming_root: Path) -> Path:
    """The `_inbox/` directory under a pipeline incoming root."""
    return incoming_root / INBOX_TOPIC


def default_registry(incoming_root: Path) -> Path:
    """`pipeline/registry.md`, the sibling of `pipeline/1-incoming/`."""
    return incoming_root.parent / "registry.md"


def unique_path(directory: Path, stem: str, suffix: str = ".md") -> Path:
    """`{stem}{suffix}` in `directory`, disambiguated with -2/-3/... on collision."""
    candidate = directory / f"{stem}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def safe_topic(topic: str) -> str:
    """Validate an agent-chosen topic as a single, contained path component."""
    stripped = topic.strip()
    if not stripped:
        raise ValueError("route topic must not be empty")
    if (
        stripped in (".", "..")
        or "/" in stripped
        or "\\" in stripped
        or "\x00" in stripped
        or os.path.isabs(stripped)
    ):
        raise ValueError(f"unsafe route topic (no separators / .. / absolute path): {topic!r}")
    if stripped == INBOX_TOPIC:
        # Routing INTO the queue itself is never meaningful — and would let the
        # route() adopt scan match the SOURCE article by its own URL and delete
        # the only copy.
        raise ValueError(f"route topic must be a real topic, not the {INBOX_TOPIC} queue itself")
    return stripped


def ensure_inbox_article(incoming_root: Path, article: Path) -> None:
    """Require `article` to live inside the inbox dir before route() touches it."""
    root = inbox_dir(incoming_root).resolve()
    resolved = article.resolve()
    if root not in resolved.parents:
        raise ValueError(
            f"route source must be inside {INBOX_TOPIC}/ (got {article!r})"
        )


__all__ = [
    "default_registry",
    "ensure_inbox_article",
    "inbox_dir",
    "safe_topic",
    "slugify",
    "unique_path",
]

