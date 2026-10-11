#!/usr/bin/env python3
"""
promote_tags.py — the *real* tag auto-promoter (CONVENTIONS §11).

`validate_brain.py` is advisory: when a `pending:` tag recurs across enough
concepts it only WARNS ("promote this into the vocabulary"). This script does
the promotion. It scans `brain/concepts/` exactly the way validate_brain does
(normalized tag usage, distinct concepts per tag), and for every `pending:` tag
used by ≥ PENDING_PROMOTION_THRESHOLD concepts it moves the tag into `domains:`
and drops it from `pending:`.

Promotion shape (mirrors how the vocabulary is defined in config/tags.yaml):
  - a `domain/topic` pending tag (e.g. `ai/evals`) → its `topic` is appended
    under the existing `domain:` block (the domain is created if missing);
  - a bare pending tag (e.g. `robotics`) → becomes a new top-level domain key
    with an empty topic list (`robotics: []`).

Safety / idempotency:
  - never duplicates an existing domain key or topic;
  - never promotes a tag already present in `domains:`;
  - preserves every existing domain, topic, synonym and comment — the edit is a
    surgical text insertion, NOT a PyYAML round-trip, so the comment-rich
    machine-owned registry survives byte-for-byte except for the moved lines;
  - `--dry-run` reports what WOULD be promoted and writes nothing.

The counting/parsing is imported from validate_brain (DRY) so this script and
the advisory warning can never disagree about which tags qualify.

CLI:
    python3 scripts/promote_tags.py [--dry-run] [--root PATH]
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Make the `scripts` package importable when run directly as a script
# (`python3 scripts/promote_tags.py`), not only as a module (`-m scripts...`).
# This bootstrap must run BEFORE the sibling import below.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(_PROJECT_ROOT))

# Atomic same-path write so a crash mid-write can't truncate tags.yaml; the single
# source of truth lives in registry.py.
from scripts.registry import atomic_write_text  # noqa: E402

# Reuse validate_brain's parsing/counting and threshold so the advisory warning
# and this real promotion stay in lockstep (DRY — CONVENTIONS §11/§13).
from scripts.validate_brain import (  # noqa: E402 — sibling module import
    PENDING_PROMOTION_THRESHOLD,
    PROJECT_ROOT,
    _strip_inline_comment,
    _strip_quotes,
    domain_block_bounds,
    domains_insert_index,
    load_concepts,
    load_tag_registry,
    normalize_tag,
    pending_block_bounds,
)


@dataclass
class PromotionResult:
    """The outcome of one promotion pass, ready to print or assert on."""

    promoted: list[str] = field(default_factory=list)  # pending tags moved up
    stayed: list[str] = field(default_factory=list)  # pending tags left in place
    dry_run: bool = False


# --------------------------------------------------------------------------- #
# Counting which pending tags qualify (reuses validate_brain's view)
# --------------------------------------------------------------------------- #


def _concepts_per_pending_tag(root: Path) -> dict[str, int]:
    """Map each registered `pending:` tag → the count of concepts that use it.

    Uses the SAME normalized-usage approach as validate_brain.check_tags: every
    concept's tags are normalized through the registry, and a pending tag is
    matched against that normalized usage. Distinct concepts only (a set), so a
    tag repeated within one note still counts once.
    """
    concepts = load_concepts(root / "brain" / "concepts")
    registry = load_tag_registry(root / "config" / "tags.yaml")

    # Distinct concept stems per normalized tag (mirrors `normalized_usage`).
    normalized_usage: dict[str, set[str]] = {}
    for concept in concepts:
        for tag in concept.tags:
            normalized = normalize_tag(tag, registry)
            normalized_usage.setdefault(normalized, set()).add(concept.stem)

    counts: dict[str, int] = {}
    for pending_tag in registry.pending:
        normalized = normalize_tag(pending_tag, registry)
        counts[pending_tag] = len(normalized_usage.get(normalized, set()))
    return counts


# --------------------------------------------------------------------------- #
# Surgical edits to config/tags.yaml (comment-preserving)
# --------------------------------------------------------------------------- #


def _remove_pending_entry(lines: list[str], tag: str) -> None:
    """Delete the `  - <tag>` item line from the `pending:` block (in place).

    Matches a quoted item too (`- "ai/evals"`): the entry is compared after
    stripping the `- ` bullet, an inline comment, and surrounding quotes, so a
    quoted pending line is never left orphaned in `pending:` after promotion
    (BUG C3).

    The scan is scoped to the `pending:` block: a bare pending tag can share its
    name with a domain *topic* of the same name (e.g. pending `robotics` while
    `ai` already lists `robotics`), and that topic line sits ABOVE the pending
    block — an unscoped match would delete it by mistake.
    """
    bounds = pending_block_bounds(lines)
    if bounds is None:
        return
    start, end = bounds
    for i in range(start, end):
        stripped = _strip_inline_comment(lines[i]).strip()
        if not stripped.startswith("- "):
            continue
        if _strip_quotes(stripped[2:].strip()) == tag:
            del lines[i]
            return


def _apply_promotion(tags_text: str, tag: str) -> str | None:
    """Return tags_text with `tag` promoted from `pending:` into `domains:`.

    Returns None when the edit cannot be applied safely (no `domains:` block, or
    the tag is already present in domains) so the caller can skip it without
    corrupting the file. Handles both `domain/topic` and bare-domain shapes.
    """
    lines = tags_text.splitlines()
    domains_idx = next(
        (i for i, ln in enumerate(lines) if ln.rstrip() == "domains:"), None
    )
    if domains_idx is None:
        return None  # no domains: block -> respect the schema, change nothing

    if "/" in tag:
        domain, topic = tag.split("/", 1)
        bounds = domain_block_bounds(lines, domain)
        if bounds is None:
            # Domain missing: create it with this single topic at the block end.
            insert_at = domains_insert_index(lines, domains_idx)
            lines.insert(insert_at, f"  {domain}:")
            lines.insert(insert_at + 1, f"    - {topic}")
        else:
            header_idx, end = bounds
            # The domain's existing topic items (deeper-indented `- topic` lines).
            # Blank/comment lines in the span are NOT topics — a `  domain: []`
            # seeded by manage_sources may be followed by a blank + comment header
            # before the next block, yet still be EMPTY (BUG 2/3).
            topic_lines = [
                k
                for k in range(header_idx + 1, end)
                if lines[k].strip().startswith("- ")
            ]
            if not topic_lines:
                # EMPTY domain (`  domain: []` / bare `  domain:`): nest the topic
                # directly under it, normalizing the header to block form, so no
                # duplicate sibling key is ever appended (BUG 2).
                lines[header_idx] = f"  {domain}:"
                lines.insert(header_idx + 1, f"    - {topic}")
            else:
                # Compare against comment-stripped topic names: the shipped
                # registry annotates every topic (`- agents   # ...`), and a raw
                # comparison would never match, appending a duplicate (BUG C2).
                existing = {
                    _strip_inline_comment(lines[k]).strip()[2:].strip()
                    for k in topic_lines
                }
                if topic in existing:
                    # Already vocabulary -> just clean it out of pending.
                    _remove_pending_entry(lines, tag)
                    return "\n".join(lines) + "\n"
                # Append after the LAST topic line (not `end`, which may point at
                # a trailing blank/comment belonging to the next block).
                lines.insert(topic_lines[-1] + 1, f"    - {topic}")
    else:
        # Bare tag -> a new top-level domain key (skip if it already exists in
        # either block or inline-empty form, so no duplicate key is appended).
        if domain_block_bounds(lines, tag) is not None:
            _remove_pending_entry(lines, tag)
            return "\n".join(lines) + "\n"
        insert_at = domains_insert_index(lines, domains_idx)
        lines.insert(insert_at, f"  {tag}: []")

    _remove_pending_entry(lines, tag)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def promote_tags(root: Path = PROJECT_ROOT, *, dry_run: bool = False) -> PromotionResult:
    """Promote every qualifying `pending:` tag in `root` and return the result.

    A tag qualifies when it recurs across ≥ PENDING_PROMOTION_THRESHOLD distinct
    concepts. With `dry_run=True` the registry is left untouched but the result
    still reports what would have been promoted.
    """
    tags_path = root / "config" / "tags.yaml"
    counts = _concepts_per_pending_tag(root)
    registry = load_tag_registry(tags_path)

    result = PromotionResult(dry_run=dry_run)
    # Stable order: promote alphabetically so output and edits are deterministic.
    # Never promote a tag that is also a `synonyms:` alias — it already resolves
    # to a canonical tag, so promoting it would fork the vocabulary into a bogus
    # top-level domain that contradicts the synonyms map (BUG C4).
    qualifying = sorted(
        tag
        for tag, n in counts.items()
        if n >= PENDING_PROMOTION_THRESHOLD
        and normalize_tag(tag, registry) not in registry.synonyms
    )
    result.stayed = sorted(tag for tag in counts if tag not in qualifying)

    if not qualifying or not tags_path.exists():
        # Nothing reached threshold (or no registry) -> a clean, non-failing pass.
        result.promoted = []
        return result

    tags_text = tags_path.read_text(encoding="utf-8")
    for tag in qualifying:
        updated = _apply_promotion(tags_text, tag)
        if updated is None:
            # Could not safely promote (e.g. already in domains) -> keep it out
            # of `promoted` and treat it as stayed for an honest summary.
            result.stayed.append(tag)
            continue
        tags_text = updated
        result.promoted.append(tag)

    result.stayed = sorted(set(result.stayed))
    if result.promoted and not dry_run:
        atomic_write_text(tags_path, tags_text)
    return result


def _render_summary(result: PromotionResult) -> str:
    """A concise, human-readable one-shot summary of the pass."""
    prefix = "[dry-run] would promote" if result.dry_run else "promoted"
    if result.promoted:
        promoted = f"{prefix}: {', '.join(result.promoted)}"
    else:
        promoted = f"{prefix}: (none — no pending tag reached the threshold)"
    stayed = (
        f"still pending: {', '.join(result.stayed)}"
        if result.stayed
        else "still pending: (none)"
    )
    return f"{promoted}\n{stayed}"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: `promote_tags.py [--dry-run] [--root PATH]`."""
    parser = argparse.ArgumentParser(
        prog="promote_tags.py",
        description=(
            "Promote pending tags that recur across ≥ "
            f"{PENDING_PROMOTION_THRESHOLD} concepts into config/tags.yaml."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be promoted without writing.",
    )
    parser.add_argument(
        "--root",
        default=str(PROJECT_ROOT),
        help="Project root (default: the repo root inferred from this file).",
    )
    args = parser.parse_args(argv)

    result = promote_tags(Path(args.root), dry_run=args.dry_run)
    print(_render_summary(result))
    # A run that promotes nothing is NOT a failure (advisory cadence step).
    return 0


if __name__ == "__main__":
    sys.exit(main())
