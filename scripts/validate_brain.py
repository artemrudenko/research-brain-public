#!/usr/bin/env python3
"""
validate_brain.py — the single brain-hygiene pass (CONVENTIONS §13).

A vault for non-technical users must stay healthy without manual gardening.
This one advisory scan reads `brain/concepts/*.md` and reports problems; it
NEVER auto-deletes or auto-edits notes. It surfaces:

  - orphan       — a concept with NO `related_concept:` and NO inbound/outbound
                   `[[concepts/X]]` link (tags are NOT graph edges in Obsidian,
                   so a shared tag does not rescue it from orphanhood).
  - weakly-linked — a softer note: a concept with no graph links but at least one
                   tag shared with another concept (reachable only via the tag
                   pane, not the graph view).
  - broken link  — a `[[concepts/X]]` reference (in `related_concept:` or body)
                   whose target file `brain/concepts/X.md` does not exist.
  - missing src  — a `type: concept` note with no non-empty `sources:`.
  - uncited fact — a bullet under `## Key facts` with no inline `Source:`,
                   wikilink, or URL tying that fact back to provenance.
  - tag hygiene  — tags that need normalization (lowercase / singular / hyphen),
                   synonym→canonical merges (via config/tags.yaml), off-vocabulary
                   tags absent from the registry AND its `pending:` quarantine,
                   `pending:` tags that now recur across ≥3 concepts ("promote"),
                   and one-off tags used by a single note ("fold to domain").
  - missing-from-INDEX — a concept absent from the `brain/INDEX.md` MOC fallback
                   (which is hand-maintained and can drift behind the vault).
  - stale        — a concept whose `last_verified + ttl_days` is in the past
                   ("needs re-verification").

SEED / EXAMPLE notes (CONVENTIONS §5.1) are skipped — they ship with the vault
to demonstrate the format and are not real knowledge to garden.

Layout: this file is the CLI + stable import surface. The implementation lives
in the `scripts/hygiene/` package — `model` (result types), `load` (frontmatter
+ concept loading), `tags` (the tags.yaml registry + normalization), `checks`
(every hygiene check, the write-time gate, the quarantine mover), and `report`
(rendering + the durable report) — and every name is re-exported here, so
`from scripts.validate_brain import …` keeps working unchanged.

It prints a short human summary plus a machine-readable one-line headline the
digest builder matches by its exact `Health:` prefix:

    Health: N concepts · X orphans · Y broken links · Z missing-sources · U uncited-facts · W stale

(a longer human "brain health: ..." line is also printed for readability) and
writes both to `pipeline/3-synthesis/brain-health_YYYY-MM-DD.md` so the digest
builder can surface the headline line. Exit code is always 0 (advisory) unless
`--strict`: bare `--strict` exits 1 when the full-vault scan raised any warning,
while `--strict --paths FILE...` is the WRITE-TIME gate — it exits non-zero only
when one of the named (just-written) concept files breaks the tagging/citation
contract (missing/empty `sources:`, or an off-vocabulary LIVE tag; `pending:`
tags are allowed). The default — no `--strict` — is unchanged: always exit 0.

PyYAML is imported lazily and optionally; a minimal stdlib frontmatter reader
covers the list-bearing keys (`tags`, `related_concept`, `sources`) when it is
absent, so the scan never hard-depends on it.

CLI:
    python3 scripts/validate_brain.py [--json] [--strict [--paths FILE...]]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# Resolve the project root from this file's location (scripts/ -> root) so the
# scan works regardless of the current working directory (CONVENTIONS §1).
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Make `scripts` importable when run directly (`python3 scripts/validate_brain.py`).
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import schema  # noqa: E402
from scripts.hygiene.checks import (  # noqa: E402
    _INDEX_WIKILINK_RE,
    _is_off_vocabulary,
    _is_verifiable_url,
    _key_fact_bullets,
    _normalized_pending,
    _outbound_targets,
    _source_has_url,
    check_broken_links,
    check_contributor_links,
    check_index_completeness,
    check_keyfacts_citation,
    check_lesson_navigation,
    check_missing_sources,
    check_orphan,
    check_pending_cap,
    check_playbook_navigation,
    check_stale,
    check_tags,
    gate_concepts,
    quarantine_failing_concepts,
)
from scripts.hygiene.load import (  # noqa: E402
    _as_str_list,
    _is_seed_or_example,
    _parse_frontmatter,
    _parse_frontmatter_fallback,
    _parse_inline_list,
    _parse_int,
    _parse_iso_date,
    _split_frontmatter,
    _strip_quotes,
    load_author,
    load_authors,
    load_concept,
    load_concepts,
    load_notes_by_type,
)
from scripts.hygiene.model import Author, BrainHealth, Concept, Warning  # noqa: E402
from scripts.hygiene.report import (  # noqa: E402
    default_report_path,
    health_to_dict,
    render_summary,
    write_report,
)
from scripts.hygiene.tags import (  # noqa: E402
    PENDING_PROMOTION_THRESHOLD,
    TagRegistry,
    _build_registry,
    _fold_tag,
    _parse_flow_list,
    _parse_tag_registry_lines,
    _singularize,
    _strip_inline_comment,
    domain_block_bounds,
    domains_insert_index,
    load_tag_registry,
    normalize_tag,
    pending_block_bounds,
)
from scripts.registry import atomic_write_text  # noqa: E402

# The compatibility surface: everything the pre-split module defined at top
# level and other modules / tests import from here. Keeping the private helpers
# listed keeps `from scripts.validate_brain import _split_frontmatter`
# (concept_manage.py, promote_tags.py) and the tests' `vb._…` accesses working.
__all__ = [
    "PENDING_PROMOTION_THRESHOLD",
    "PROJECT_ROOT",
    "Author",
    "BrainHealth",
    "Concept",
    "TagRegistry",
    "Warning",
    "_INDEX_WIKILINK_RE",
    "_as_str_list",
    "_build_registry",
    "_fold_tag",
    "_is_off_vocabulary",
    "_is_seed_or_example",
    "_is_verifiable_url",
    "_key_fact_bullets",
    "_normalized_pending",
    "_outbound_targets",
    "_parse_flow_list",
    "_parse_frontmatter",
    "_parse_frontmatter_fallback",
    "_parse_inline_list",
    "_parse_int",
    "_parse_iso_date",
    "_parse_tag_registry_lines",
    "_singularize",
    "_source_has_url",
    "_split_frontmatter",
    "_strip_inline_comment",
    "_strip_quotes",
    "atomic_write_text",
    "check_broken_links",
    "check_contributor_links",
    "check_index_completeness",
    "check_keyfacts_citation",
    "check_lesson_navigation",
    "check_missing_sources",
    "check_orphan",
    "check_playbook_navigation",
    "check_pending_cap",
    "check_stale",
    "check_tags",
    "default_report_path",
    "domain_block_bounds",
    "domains_insert_index",
    "gate_concepts",
    "health_to_dict",
    "load_author",
    "load_authors",
    "load_concept",
    "load_concepts",
    "load_notes_by_type",
    "load_tag_registry",
    "main",
    "normalize_tag",
    "pending_block_bounds",
    "quarantine_failing_concepts",
    "render_summary",
    "validate_brain",
    "write_report",
]


def validate_brain(root: Path = PROJECT_ROOT, *, today: date | None = None) -> BrainHealth:
    """Run every hygiene check against `root` and return the assembled result."""
    if today is None:
        today = date.today()
    concepts = load_concepts(root / "brain" / "concepts")
    lessons = load_notes_by_type(root / "brain" / "lessons", "lesson")
    playbooks = load_notes_by_type(root / "brain" / "playbooks", "playbook")
    # Author nodes (Stage 9): backlink-only entities. Loaded for the broken-link
    # check on their bodies, but NEVER run through check_orphan — an author with
    # no outbound link is reachable via Obsidian backlinks by design, not debt.
    authors = load_notes_by_type(root / "brain" / "authors", "author")
    registry = load_tag_registry(root / "config" / "tags.yaml")

    existing_stems = {c.stem for c in concepts}
    author_stems = {a.stem for a in authors}
    tag_to_concepts: dict[str, set[str]] = {}
    for concept in concepts:
        for tag in concept.tags:
            tag_to_concepts.setdefault(normalize_tag(tag, registry), set()).add(
                concept.stem
            )

    # Build the set of stems touched by a real graph edge (an existing-target
    # [[link]]). Both ends of every edge are connected — Obsidian backlinks make
    # the edge bidirectional. Tags are NOT edges (W3), so they're excluded here.
    linked_stems: set[str] = set()
    for concept in concepts:
        for target in _outbound_targets(concept):
            if target in existing_stems:
                linked_stems.add(concept.stem)
                linked_stems.add(target)

    # Cold-start exception: a single root note in an otherwise-empty vault is the
    # legitimate seed of a cluster, not orphan debt — don't spam an orphan/weak
    # warning for it (CONVENTIONS §10 cold-start crosslink relaxation).
    cold_start = len(concepts) == 1

    warnings: list[Warning] = []
    for concept in concepts:
        if not cold_start:
            orphan = check_orphan(concept, linked_stems, tag_to_concepts, registry)
            if orphan:
                warnings.append(orphan)
        warnings.extend(check_broken_links(concept, existing_stems))
        warnings.extend(check_contributor_links(concept, author_stems))
        missing = check_missing_sources(concept)
        if missing:
            warnings.append(missing)
        warnings.extend(check_keyfacts_citation(concept))
        stale = check_stale(concept, today=today)
        if stale:
            warnings.append(stale)

    warnings.extend(check_tags(concepts, registry))
    warnings.extend(check_index_completeness(concepts, root / "brain" / "INDEX.md"))
    for lesson in lessons:
        orphan = check_lesson_navigation(lesson)
        if orphan:
            warnings.append(orphan)
    for playbook in playbooks:
        orphan = check_playbook_navigation(playbook)
        if orphan:
            warnings.append(orphan)
    # Author-node body links must trace to a real concept — a dangling
    # [[concepts/X]] in an author's prose is still a broken-link finding.
    for author in authors:
        warnings.extend(check_broken_links(author, existing_stems))

    return BrainHealth(concept_count=len(concepts), warnings=warnings)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: `validate_brain.py [--json] [--strict]`."""
    parser = argparse.ArgumentParser(
        prog="validate_brain.py",
        description="Advisory brain-hygiene scan over brain/concepts/ (CONVENTIONS §13).",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit the result as JSON instead of prose."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on a contract violation (default: always exit 0).",
    )
    parser.add_argument(
        "--paths",
        nargs="+",
        metavar="FILE",
        help=(
            "Scope --strict to these concept files (the write-time gate over "
            "just-written notes): fail only on a missing/empty sources: field or "
            "an off-vocabulary live tag in one of FILE. Without --paths, --strict "
            "fails when the full-vault advisory scan raises any warning."
        ),
    )
    parser.add_argument(
        "--quarantine",
        metavar="DIR",
        help=(
            "With --strict --paths: move any in-scope concept that FAILS the gate "
            "out of brain/concepts/ into DIR, so an invalid (e.g. unsourced) note "
            "can't later be surfaced by build_digest. Exit code is unchanged."
        ),
    )
    parser.add_argument(
        "--restore-from",
        metavar="DIR",
        help=(
            "With --quarantine: a pre-write backup dir. When a FAILING concept has a "
            "backup here (it was valid before this run), roll the live note back to "
            "that last-known-good version instead of leaving the vault without it — "
            "so a corrupting UPDATE never deletes a previously-valid concept."
        ),
    )
    args = parser.parse_args(argv)

    today = date.today()

    if args.paths:
        # Lightweight write-time gate: evaluate ONLY the contract invariants over
        # the scoped, just-written files. Skip the full-vault scan and the report
        # write so a per-topic gate check during synthesis never masquerades as a
        # scheduled hygiene pass (which would clobber the brain-health report that
        # build_digest.latest_brain_health() surfaces). The gate is meaningful
        # only with --strict; without it, stay advisory (exit 0) and do nothing.
        if not args.strict:
            return 0
        registry = load_tag_registry(PROJECT_ROOT / "config" / "tags.yaml")
        paths = [Path(p) for p in args.paths]
        # A missing in-scope file (a concept that was supposed to be written but
        # isn't there) is a gate FAILURE — never an unhandled traceback.
        missing_paths = [p for p in paths if not p.is_file()]
        for path in missing_paths:
            print(
                f"strict: {path.stem}: file not found — expected a written "
                f"concept at {path}",
                file=sys.stderr,
            )
        violations = gate_concepts([p for p in paths if p.is_file()], registry)
        for violation in violations:
            print(f"strict: {violation.concept}: {violation.message}", file=sys.stderr)
        # Defense-in-depth: evict the failing notes from the vault so a later digest
        # can't surface an invalid concept (the finding's root cause: no quarantine).
        if args.quarantine and violations:
            moved = quarantine_failing_concepts(
                [p for p in paths if p.is_file()], violations, Path(args.quarantine),
                restore_from=Path(args.restore_from) if args.restore_from else None,
            )
            for path in moved:
                print(f"strict: quarantined {path.name} -> {path.parent}", file=sys.stderr)
        return 1 if (missing_paths or violations) else 0

    health = validate_brain(PROJECT_ROOT, today=today)
    report_path = write_report(health, root=PROJECT_ROOT, today=today)

    if args.json:
        print(json.dumps(health_to_dict(health), indent=2))
    else:
        print(render_summary(health, today=today), end="")
        try:
            rel = report_path.relative_to(PROJECT_ROOT)
        except ValueError:
            rel = report_path
        print(f"\n(report written to {rel})")

    # Schema-version drift (advisory, never changes exit): a note stamped NEWER
    # than this code understands means the vault was updated but this checkout was
    # not — some frontmatter may be misread. Missing/baseline is fine.
    for kind, subdir in (
        ("concept", "concepts"),
        ("lesson", "lessons"),
        ("playbook", "playbooks"),
        ("author", "authors"),
    ):
        note_dir = PROJECT_ROOT / "brain" / subdir
        if not note_dir.exists():
            continue
        for drift in schema.scan_paths_for_drift(sorted(note_dir.glob("*.md")), kind):
            print(f"warning: {drift}", file=sys.stderr)

    if not args.strict:
        return 0  # advisory default — unchanged

    # Unscoped --strict keeps its original meaning: any advisory warning fails.
    return 1 if health.warnings else 0


if __name__ == "__main__":
    sys.exit(main())
