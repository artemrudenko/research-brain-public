"""Quiet-digest detection for the delivery dispatcher."""

from __future__ import annotations

# Importable both as part of `scripts.delivery` and when deliver.py is executed
# directly from scripts/delivery/.
from ..fm import split_frontmatter as _fm_split_frontmatter

# A quiet digest opens its body with one of these markers (weekly / daily — see
# ADR 0016). Detection is line-prefix on the stripped body, so either cadence's
# "nothing new" build is recognized by --skip-quiet.
QUIET_DIGEST_MARKERS = ("Quiet week —", "Quiet day —")

# Structural marker rendered by scripts.digest.model.QUIET_DIGEST_HTML_MARKER.
# Kept as a local copy to avoid a delivery -> digest package dependency.
QUIET_DIGEST_HTML_MARKER = "<!-- research-brain: quiet-digest -->"


def strip_frontmatter(text: str) -> str:
    """Return `text` with a leading YAML frontmatter block removed."""
    return _fm_split_frontmatter(text)[1]


def is_quiet_digest(text: str) -> bool:
    """True when `text` is a quiet weekly or daily digest."""
    body = strip_frontmatter(text)
    return any(
        line.strip() == QUIET_DIGEST_HTML_MARKER
        or line.lstrip().startswith(QUIET_DIGEST_MARKERS)
        for line in body.splitlines()
    )


__all__ = [
    "QUIET_DIGEST_HTML_MARKER",
    "QUIET_DIGEST_MARKERS",
    "is_quiet_digest",
    "strip_frontmatter",
]
