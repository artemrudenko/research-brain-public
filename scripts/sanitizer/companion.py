"""Sanitized companion file construction and integrity checks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from scripts._yaml import optional_yaml
from scripts.sanitizer.frontmatter import _sanitize_frontmatter, _split_frontmatter
from scripts.sanitizer.model import SanitizeResult

# PyYAML is a project dependency; None only on a mis-bootstrapped interpreter.
yaml = optional_yaml()

COMPANION_DIRNAME = "sanitized"
# Bumped 1 -> 2 when S9 was reordered to run first and its char class was widened to
# cover Trojan-Source bidi isolates (U+2066-U+2069) and U+061C. The bump invalidates
# every existing companion so previously "clean" bodies are re-sanitized under the
# stronger ruleset. (See scripts/sanitizer/rules.py; security review 2026-07-08.)
SANITIZER_VERSION = "2"


def source_digest(text: str) -> str:
    """sha256 of the full source file content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# The placeholder the integrity hash field holds while the file is being hashed.
_HASH_PLACEHOLDER = "__PENDING__"


def companion_digest(text: str) -> str:
    """sha256 of the whole companion with its own hash field neutralized."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sanitized_path(article: Path) -> Path:
    return article.parent / COMPANION_DIRNAME / article.name


def _iso(now: datetime | None) -> str:
    now = now or datetime.now(UTC)
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _companion_text(
    src_frontmatter: str,
    clean_body: str,
    result: SanitizeResult,
    source_hash: str,
    now: datetime | None,
    *,
    sanitizer_version: str = SANITIZER_VERSION,
) -> str:
    """Build the companion file: sanitized source frontmatter + audit + body."""
    body = clean_body.lstrip("\n")
    # Sanitize untrusted frontmatter values before appending trusted audit fields,
    # so a malicious title/source cannot pass the gate as clean.
    fm = _sanitize_frontmatter(src_frontmatter.rstrip("\n"), result)
    audit_before = [
        "instruction_stripped: true",
        f"stripped_at: {_iso(now)}",
        f"sanitizer_version: {sanitizer_version}",
        f"source_hash: {source_hash}",
    ]
    audit_after = [
        f"stripped_classes: [{', '.join(sorted(result.stripped_classes))}]",
        f"stripping_severity: {result.severity}",
    ]
    # Splice the hash positionally. A source containing the literal placeholder
    # must not hijack a first-occurrence replacement and create a gate DoS.
    head = "---\n" + (fm + "\n" if fm else "") + "\n".join(audit_before) + "\nsanitized_hash: "
    tail = "\n" + "\n".join(audit_after) + f"\n---\n\n{body}"
    draft = head + _HASH_PLACEHOLDER + tail
    return head + companion_digest(draft) + tail


@dataclass(frozen=True)
class _CompanionAudit:
    """The integrity fields read back from a companion's frontmatter."""

    source_hash: str | None
    sanitized_hash: str | None
    sanitizer_version: str | None = None


_AUDIT_KEYS = ("source_hash", "sanitized_hash", "sanitizer_version")


def _parse_companion_audit_lines(fm: str) -> _CompanionAudit:
    """Recover flat audit fields without PyYAML for the headless cron path."""
    found: dict[str, str] = {}
    for line in fm.split("\n"):
        key, sep, value = line.partition(":")
        if sep and key.strip() in _AUDIT_KEYS:
            found[key.strip()] = value.strip()
    return _CompanionAudit(
        source_hash=found.get("source_hash"),
        sanitized_hash=found.get("sanitized_hash"),
        sanitizer_version=found.get("sanitizer_version"),
    )


def _read_companion_audit(companion: Path) -> _CompanionAudit:
    """Read source_hash, sanitized_hash, and sanitizer_version from a companion.

    Unreadable for ANY reason — missing, permission-denied, or not valid UTF-8 —
    yields the empty audit, which the gate treats as "no usable companion". A
    `UnicodeDecodeError` is a ValueError, so it must be named explicitly; letting
    it escape would crash the gate on malformed bytes, i.e. let anyone who can
    write a companion file disable the check by writing garbage into it.
    """
    try:
        fm, _ = _split_frontmatter(companion.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return _CompanionAudit(None, None)

    if yaml is None:
        return _parse_companion_audit_lines(fm)
    try:
        data = yaml.safe_load(fm) or {}
    except yaml.YAMLError:
        return _CompanionAudit(None, None)

    def _str_or_none(value: object) -> str | None:
        return str(value) if value is not None else None

    return _CompanionAudit(
        source_hash=_str_or_none(data.get("source_hash")),
        sanitized_hash=_str_or_none(data.get("sanitized_hash")),
        sanitizer_version=_str_or_none(data.get("sanitizer_version")),
    )


def _companion_is_intact(companion: Path, recorded_hash: str | None) -> bool:
    """Return whether companion bytes match the recorded sanitized_hash.

    Fails closed on any read problem, undecodable bytes included — a companion we
    cannot read is a companion we cannot vouch for (see `_read_companion_audit`).
    """
    if recorded_hash is None:
        return False
    try:
        text = companion.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    placeholder_form = text.replace(
        f"sanitized_hash: {recorded_hash}", f"sanitized_hash: {_HASH_PLACEHOLDER}", 1
    )
    return companion_digest(placeholder_form) == recorded_hash


__all__ = [
    "COMPANION_DIRNAME",
    "SANITIZER_VERSION",
    "_AUDIT_KEYS",
    "_CompanionAudit",
    "_HASH_PLACEHOLDER",
    "_companion_is_intact",
    "_companion_text",
    "_iso",
    "_parse_companion_audit_lines",
    "_read_companion_audit",
    "companion_digest",
    "sanitized_path",
    "source_digest",
]
