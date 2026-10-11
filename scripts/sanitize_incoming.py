#!/usr/bin/env python3
"""
sanitize_incoming.py — the auto-ingest sanitization gate for the unattended path.

Why: the unattended synthesis path (`research-build` PROFILE=internal-corpus, run
by `weekly-synthesis`) reads RSS-collected articles from `pipeline/1-incoming/`
*directly*. Those articles are collected verbatim and never pass through
`source-archive`'s web-fetch instruction-stripping, so an indirect prompt
injection in an article body could reach the synthesis prompt. Until now
"instruction-stripping is mandatory" was prose in a SKILL.md with no code behind
it (see CONVENTIONS §12). This module makes it real:

  - `sanitize_tree` writes a sanitized companion per incoming article under
    `pipeline/1-incoming/{topic}/sanitized/{file}.md`, applying the documented
    S1–S9 strip classes;
  - `gate_tree` refuses (exit 1) when any article lacks an up-to-date companion,
    so the synthesis step can hard-stop instead of ingesting raw untrusted text.

The strip ruleset is the deterministic subset of
`skills/source-archive/references/instruction-stripping-patterns.md`:
critical classes (S1,S2,S3,S5,S6,S9) are stripped; medium/informational classes
(S4,S7,S8) are flagged in the audit but not stripped (documented false-positive
risk). This is defense-in-depth, NOT a guarantee — the gate's value is that
synthesis can never silently consume an un-sanitized article.

stdlib + PyYAML (already a project dep), best-effort, deterministic.

CLI (wired into weekly-run between curate and synthesis):
    python3 scripts/sanitize_incoming.py sanitize             # write/update companions
    python3 scripts/sanitize_incoming.py gate                 # exit 1 if missing/stale/corrupt
    python3 scripts/sanitize_incoming.py gate --topic ai      # scope to one topic (repeatable)

The gate fails on three conditions: a missing companion, a drifted source_hash
(source changed since sanitization), or a corrupt companion body (its bytes no
longer hash to the recorded sanitized_hash — truncation/tampering, or an old
companion predating sanitized_hash, which must be re-sanitized).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scripts.sanitizer.api import SanitizerApi

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Make `scripts` importable when run directly (`python3 scripts/sanitize_incoming.py`).
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.sanitizer import cli as sanitizer_cli  # noqa: E402
from scripts.sanitizer import companion as sanitizer_companion  # noqa: E402
from scripts.sanitizer import frontmatter as sanitizer_frontmatter  # noqa: E402
from scripts.sanitizer import model as sanitizer_model  # noqa: E402
from scripts.sanitizer import operations as sanitizer_operations  # noqa: E402
from scripts.sanitizer import rules as sanitizer_rules  # noqa: E402

Finding = sanitizer_model.Finding
SanitizeResult = sanitizer_model.SanitizeResult
FileOutcome = sanitizer_model.FileOutcome
GateResult = sanitizer_model.GateResult
_Rule = sanitizer_rules.Rule
_RULES = sanitizer_rules.RULES
sanitize_text = sanitizer_rules.sanitize_text
_FM_BLOCK_SCALAR = sanitizer_frontmatter._FM_BLOCK_SCALAR
_FM_KEY_VALUE = sanitizer_frontmatter._FM_KEY_VALUE
_FM_LIST_ITEM = sanitizer_frontmatter._FM_LIST_ITEM
_sanitize_flow_sequence = sanitizer_frontmatter._sanitize_flow_sequence
_sanitize_frontmatter = sanitizer_frontmatter._sanitize_frontmatter
_split_flow_items = sanitizer_frontmatter._split_flow_items
_split_frontmatter = sanitizer_frontmatter._split_frontmatter
_unquote_flow_scalar = sanitizer_frontmatter._unquote_flow_scalar
_yaml_safe_scalar = sanitizer_frontmatter._yaml_safe_scalar
COMPANION_DIRNAME = sanitizer_companion.COMPANION_DIRNAME
SANITIZER_VERSION = sanitizer_companion.SANITIZER_VERSION
_AUDIT_KEYS = sanitizer_companion._AUDIT_KEYS
_CompanionAudit = sanitizer_companion._CompanionAudit
_HASH_PLACEHOLDER = sanitizer_companion._HASH_PLACEHOLDER
_companion_is_intact = sanitizer_companion._companion_is_intact
_iso = sanitizer_companion._iso
_parse_companion_audit_lines = sanitizer_companion._parse_companion_audit_lines
companion_digest = sanitizer_companion.companion_digest
sanitized_path = sanitizer_companion.sanitized_path
source_digest = sanitizer_companion.source_digest
yaml = sanitizer_companion.yaml

DEFAULT_INCOMING = _PROJECT_ROOT / "pipeline" / "1-incoming"

# Identity of the S1–S9 ruleset. Bump whenever sanitization logic changes
# meaningfully: it is recorded in every companion (so skip-if-current re-sanitizes
# ruleset-stale companions) and folded into the synthesis freshness hash (so a
# bump forces re-synthesis of every topic). `synthesis_freshness` imports it from
# this stable facade; the concrete value lives with the companion internals.


def _companion_text(
    src_frontmatter: str,
    clean_body: str,
    result: SanitizeResult,
    source_hash: str,
    now: datetime | None,
) -> str:
    """Compatibility wrapper that respects monkeypatched SANITIZER_VERSION."""
    return sanitizer_companion._companion_text(
        src_frontmatter,
        clean_body,
        result,
        source_hash,
        now,
        sanitizer_version=SANITIZER_VERSION,
    )


def _read_companion_audit(companion: Path) -> _CompanionAudit:
    """Compatibility wrapper that respects monkeypatched yaml availability."""
    return sanitizer_operations._read_audit_with_yaml(companion, yaml)


def sanitize_file(src: Path, *, now: datetime | None = None) -> FileOutcome:
    """Compatibility wrapper that respects monkeypatched facade settings."""
    return sanitizer_operations.sanitize_file(
        src,
        now=now,
        sanitizer_version=SANITIZER_VERSION,
        yaml_module=yaml,
    )


def _articles(
    incoming_root: Path, topics: list[str] | None = None
) -> list[Path]:
    return sanitizer_operations.articles(incoming_root, topics)


def sanitize_tree(
    incoming_root: Path = DEFAULT_INCOMING,
    *,
    topics: list[str] | None = None,
    now: datetime | None = None,
) -> list[FileOutcome]:
    """Write/refresh a companion for every incoming article (optionally topic-scoped)."""
    return sanitizer_operations.sanitize_tree(
        incoming_root,
        topics=topics,
        now=now,
        sanitizer_version=SANITIZER_VERSION,
        yaml_module=yaml,
    )


def gate_tree(
    incoming_root: Path = DEFAULT_INCOMING, topics: list[str] | None = None
) -> GateResult:
    """Compatibility wrapper that respects monkeypatched facade settings."""
    return sanitizer_operations.gate_tree(
        incoming_root,
        topics,
        sanitizer_version=SANITIZER_VERSION,
        yaml_module=yaml,
    )


# ── CLI ──────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    return sanitizer_cli.build_parser(DEFAULT_INCOMING)


def main(argv: list[str] | None = None) -> int:
    # This module is the api seam — attribute reads happen at call time, so
    # monkeypatched facade names are honored; the TYPE_CHECKING conformance
    # assignment below keeps the cast honest.
    return sanitizer_cli.main(argv, api=cast("SanitizerApi", sys.modules[__name__]))


if TYPE_CHECKING:
    # Static conformance check: mypy verifies this module satisfies SanitizerApi,
    # so the cast in main() can never hide facade drift. Zero runtime cost.
    import scripts.sanitize_incoming as _facade_for_typecheck

    _API_CONFORMANCE: SanitizerApi = _facade_for_typecheck


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
