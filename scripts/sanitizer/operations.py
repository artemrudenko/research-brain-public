"""Tree-level sanitize and gate operations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.registry import atomic_write_text
from scripts.sanitizer import companion as sanitizer_companion
from scripts.sanitizer.companion import (
    COMPANION_DIRNAME,
    SANITIZER_VERSION,
    _companion_is_intact,
    _companion_text,
    _CompanionAudit,
    _read_companion_audit,
    sanitized_path,
    source_digest,
)
from scripts.sanitizer.frontmatter import _split_frontmatter
from scripts.sanitizer.model import FileOutcome, GateResult
from scripts.sanitizer.rules import sanitize_text


def _read_audit_with_yaml(companion: Path, yaml_module: Any) -> _CompanionAudit:
    previous = sanitizer_companion.yaml
    sanitizer_companion.yaml = yaml_module
    try:
        return _read_companion_audit(companion)
    finally:
        sanitizer_companion.yaml = previous


def sanitize_file(
    src: Path,
    *,
    now: datetime | None = None,
    sanitizer_version: str = SANITIZER_VERSION,
    yaml_module: Any = sanitizer_companion.yaml,
) -> FileOutcome:
    """Sanitize one article into its sanitized/ companion. Never touches the source."""
    raw = src.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(raw)
    result = sanitize_text(body)
    dest = sanitized_path(src)
    if dest.exists():
        audit = _read_audit_with_yaml(dest, yaml_module)
        if (
            audit.sanitizer_version == sanitizer_version
            and audit.source_hash == source_digest(raw)
            and _companion_is_intact(dest, audit.sanitized_hash)
        ):
            return FileOutcome(source=src, companion=dest, result=result)
    atomic_write_text(
        dest,
        _companion_text(
            fm,
            result.clean_text,
            result,
            source_digest(raw),
            now,
            sanitizer_version=sanitizer_version,
        ),
    )
    return FileOutcome(source=src, companion=dest, result=result)


def articles(incoming_root: Path, topics: list[str] | None = None) -> list[Path]:
    """Every article under the incoming tree, excluding sanitized/ companion dirs."""
    wanted = set(topics) if topics is not None else None
    out: list[Path] = []
    for path in sorted(incoming_root.rglob("*.md")):
        if COMPANION_DIRNAME in path.parts:
            continue
        rel_parts = path.relative_to(incoming_root).parts
        topic = rel_parts[0] if len(rel_parts) > 1 else None
        if wanted is not None and topic not in wanted:
            continue
        out.append(path)
    return out


def sanitize_tree(
    incoming_root: Path,
    *,
    topics: list[str] | None = None,
    now: datetime | None = None,
    sanitizer_version: str = SANITIZER_VERSION,
    yaml_module: Any = sanitizer_companion.yaml,
) -> list[FileOutcome]:
    """Write/refresh a companion for every incoming article."""
    return [
        sanitize_file(
            art,
            now=now,
            sanitizer_version=sanitizer_version,
            yaml_module=yaml_module,
        )
        for art in articles(incoming_root, topics)
    ]


def gate_tree(
    incoming_root: Path,
    topics: list[str] | None = None,
    *,
    sanitizer_version: str = SANITIZER_VERSION,
    yaml_module: Any = sanitizer_companion.yaml,
) -> GateResult:
    """Verify every in-scope article has a current, intact companion."""
    missing: list[Path] = []
    stale: list[Path] = []
    corrupt: list[Path] = []
    unreadable: list[Path] = []
    outdated: list[Path] = []
    for art in articles(incoming_root, topics):
        companion = sanitized_path(art)
        if not companion.exists():
            missing.append(art)
            continue
        audit = _read_audit_with_yaml(companion, yaml_module)
        try:
            current_digest = source_digest(art.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            # Undecodable bytes are `unreadable`, not a crash. Article bodies come
            # from external web content, so this input is attacker-influenced —
            # a gate that raises here is a gate that can be turned off.
            unreadable.append(art)
            continue
        # Ruleset supersession is checked before content staleness: a companion
        # from an older ruleset must be rebuilt regardless of whether the source
        # drifted, so it belongs in `outdated`, not `stale`.
        if audit.sanitizer_version != sanitizer_version:
            outdated.append(art)
            continue
        if audit.source_hash != current_digest:
            stale.append(art)
            continue
        if not _companion_is_intact(companion, audit.sanitized_hash):
            corrupt.append(art)
    return GateResult(
        ok=not missing and not stale and not corrupt and not unreadable and not outdated,
        missing=missing,
        stale=stale,
        corrupt=corrupt,
        unreadable=unreadable,
        outdated=outdated,
    )


__all__ = [
    "articles",
    "gate_tree",
    "sanitize_file",
    "sanitize_tree",
]
