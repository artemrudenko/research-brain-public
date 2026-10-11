"""End-to-end delivery rehearsal helper."""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path


def rehearse(
    config_path: Path,
    *,
    allow_unsanitized: bool,
    project_root: Path,
    deliver_func: Callable[..., int],
) -> int:
    """Build today's digest into a temp file, then dry-run-deliver it."""
    from scripts import build_digest  # noqa: PLC0415 — lazy: rehearsal-only seam

    fd, name = tempfile.mkstemp(suffix=".md", prefix="rehearse-digest-")
    os.close(fd)
    digest_path = Path(name)
    try:
        try:
            data = build_digest.build_digest(
                digest_path,
                root=project_root,
                require_sanitized=not allow_unsanitized,
            )
        except build_digest.IncomingNotSanitized as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 4
        sources = data.new_source_count
        concepts = len(data.concepts)
        print(
            f"rehearsal — would deliver a digest with {sources} source(s) / "
            f"{concepts} concept(s) to these channels:"
        )
        return deliver_func(digest_path, config_path, dry_run=True)
    finally:
        digest_path.unlink(missing_ok=True)


__all__ = ["rehearse"]
