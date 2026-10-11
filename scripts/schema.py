#!/usr/bin/env python3
"""schema.py — the frontmatter/config schema-version contract.

Future-proofing for migrations. Every frontmatter-bearing artifact (concept,
lesson, playbook, pipeline article) and the YAML configs carry a single FLAT top-level
`schema_version:` integer. This is the enabler a future migrator reads to decide
what to transform — without it, a migrator would have to guess a file's shape.

Two design rules make it safe to add now:

1. **Flat, not nested.** The stamp is a column-0 `schema_version: N` line, never a
   sub-key of a `meta:` block. Several readers on the headless (no-PyYAML) path are
   line-based (`build_digest._split_frontmatter`, the audit reader in
   `sanitize_incoming`, the tag reader in `validate_brain`); a nested stamp would be
   invisible or misread by them. A flat key is read correctly by every parser.

2. **Missing == baseline.** Every file already deployed predates the stamp, so an
   absent `schema_version` means the BASELINE (1), never "unknown / needs
   migration". Introducing the stamp is therefore a no-op for existing installs.

When a breaking schema change ships, bump `CURRENT[kind]`, stamp the templates/
writers with the new number, and add a migration `(kind, N) -> N+1`. Additive
changes (a new OPTIONAL key with a code default) do NOT need a bump — see the
additive-only rule in CONVENTIONS §5.5.

stdlib-only.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from types import ModuleType

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not __package__:  # direct script run (zip-run, no install — incl. bare /usr/bin/python3)
    sys.path.insert(0, str(_PROJECT_ROOT))

# The baseline every unstamped (pre-contract) file is treated as.
BASELINE = 1

# Current schema version per artifact class — the single source of truth. Bump the
# relevant entry (and ship a migration) only on a BREAKING change to that shape.
CURRENT: dict[str, int] = {
    "concept": 1,   # brain/concepts/*.md frontmatter (CONVENTIONS §5.1)
    "lesson": 1,    # brain/lessons/*.md frontmatter (§5.2)
    "playbook": 1,  # brain/playbooks/*.md frontmatter (§5.3)
    "author": 1,    # brain/authors/*.md frontmatter (Stage 9 — author nodes)
    "article": 1,   # pipeline/1-incoming/**/*.md frontmatter (§5)
    "config": 1,    # the fixed-schema YAML configs channels/schedule (§2.1/§2.2)
    "sources": 2,   # config/sources.*: 1 = legacy .md pipe tables, 2 = sources.yaml (§2.3)
    "topics": 2,    # config/topics.*:  1 = legacy .md sections,   2 = topics.yaml (§2.3)
}

# A column-0 (top-level) `schema_version:` line only. A leading space means the key
# is nested under some block and is NOT the artifact stamp — it must be ignored.
_STAMP_RE = re.compile(r'^schema_version:[ \t]*"?(\d+)"?[ \t]*(#.*)?$', re.MULTILINE)

# ── migration machinery ───────────────────────────────────────────────────────
#
# One step per (kind, from_version): a pure text -> text transform lifting the
# artifact to from_version + 1. `migrate_text` chains steps up to CURRENT[kind]
# and owns the restamping, so a transform only changes CONTENT, never the stamp.
# The whole chain stays rehearsed in tests via an injected synthetic step; the
# shipped entries below are the FIRST real migration (guarded by a test so
# nothing else can accrete here unnoticed).
Migration = Callable[[str], str]


def _import_store() -> ModuleType:
    """Import scripts.sources.store lazily (the schema-only path stays light).

    The package root is importable in every supported flow: the installed venv,
    or the module-level prelude on a zero-install `python3 scripts/schema.py …`
    run (the documented migrate-config command, bare /usr/bin/python3 included).
    """
    from scripts.sources import store  # noqa: PLC0415 — the lazy import IS the seam

    return store


def _sources_md_to_yaml(text: str) -> str:
    """(sources, 1) -> 2: the legacy sources.md pipe tables become sources.yaml.

    Reads the old table via the shared store parser (its last duty for this
    format) and emits the canonical YAML twin. Shipped EXAMPLE placeholder
    sections are template furniture, not config — they are dropped, so a pristine
    template migrates to an empty (but valid) `categories: []`.
    """
    store = _import_store()
    return store.dump_sources_yaml(store.parse_categories_md(text, skip_examples=True))


def _topics_md_to_yaml(text: str) -> str:
    """(topics, 1) -> 2: the legacy topics.md sections become topics.yaml."""
    store = _import_store()
    return store.dump_topics_yaml(store.parse_topics_md(text, skip_examples=True))


MIGRATIONS: dict[tuple[str, int], Migration] = {
    ("sources", 1): _sources_md_to_yaml,
    ("topics", 1): _topics_md_to_yaml,
}

# Kinds whose migration is a FORMAT change: the migrated text lands in a NEW
# sibling file (`{stem}<suffix>`) and the original is never rewritten or deleted
# — it stays as a read-only fallback for one minor version (BACKLOG plan step 2).
MIGRATION_SIDECAR_SUFFIX: dict[str, str] = {"sources": ".yaml", "topics": ".yaml"}


class MigrationPathMissing(RuntimeError):
    """Raised when CURRENT[kind] is ahead of a file but a step is unregistered."""


def _frontmatter_scope(text: str) -> str:
    """The leading `---`-fenced frontmatter block, else the whole text.

    A config YAML has no fences (its whole body is the scope); a markdown note does,
    and we must read ONLY its frontmatter — a col-0 `schema_version:` line in the
    BODY (e.g. inside a fenced code block discussing schemas) must not be read as
    the stamp."""
    if not text.startswith("---"):
        return text
    lines = text.split("\n")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index])
    return text  # unclosed fence -> treat as no frontmatter boundary


def read_schema_version(text: str) -> int:
    """Return the flat top-level `schema_version` of a file's frontmatter, or BASELINE.

    Scoped to the leading frontmatter block (or the whole text for a fence-less
    config), then matched line-based so it works with or without PyYAML and never
    trips over nested frontmatter. A missing or malformed stamp returns BASELINE
    (an unstamped file is the baseline, not an error)."""
    match = _STAMP_RE.search(_frontmatter_scope(text))
    if match is None:
        return BASELINE
    try:
        return int(match.group(1))
    except ValueError:  # pragma: no cover - the regex already guarantees digits
        return BASELINE


def drift_warning(kind: str, version: int) -> str | None:
    """Return an advisory string if `version` is NEWER than this code understands.

    A file stamped ahead of `CURRENT[kind]` was written by a newer release; older
    code reading it may silently misinterpret fields — the one direction worth a
    warning. An older/baseline version is fine (a migrator will lift it when one
    exists). Raises KeyError for an unknown artifact kind (a programming error)."""
    current = CURRENT[kind]
    if version > current:
        return (
            f"{kind}: schema_version {version} is NEWER than this code supports "
            f"({current}) — update research-brain; some fields may be misread."
        )
    return None


def stamp_schema_version(text: str, version: int) -> str:
    """Return `text` carrying exactly one flat top-level `schema_version: N`.

    An existing stamp is replaced in place. Otherwise the stamp is inserted as the
    first line of the leading `---` frontmatter block (fenced markdown note), or
    prepended as line 1 for a fence-less config YAML — always column 0, per the
    flat-stamp rule (design rule 1 above)."""
    stamp = f"schema_version: {version}"
    scope = _frontmatter_scope(text)
    if _STAMP_RE.search(scope):
        # Replace within the frontmatter scope only, so a col-0 lookalike in the
        # body (e.g. a fenced code block discussing schemas) is never rewritten.
        new_scope = _STAMP_RE.sub(stamp, scope, count=1)
        return text.replace(scope, new_scope, 1)
    if text.startswith("---"):
        head, sep, rest = text.partition("\n")
        return f"{head}{sep}{stamp}\n{rest}"
    return f"{stamp}\n{text}"


def migrate_text(text: str, kind: str) -> tuple[str, int, int]:
    """Lift `text` to CURRENT[kind] through the registered steps.

    Returns `(new_text, from_version, to_version)`. Already-current text is
    returned unchanged; text stamped NEWER than this code is also returned
    unchanged (that is `drift_warning`'s message to deliver, not ours to mangle).
    Raises :class:`MigrationPathMissing` when a needed step is unregistered —
    refusing loudly beats guessing at user data."""
    target = CURRENT[kind]
    version = read_schema_version(text)
    if version >= target:
        return text, version, version
    from_version = version
    while version < target:
        step = MIGRATIONS.get((kind, version))
        if step is None:
            raise MigrationPathMissing(
                f"no migration registered for ({kind}, {version}) — cannot lift "
                f"{kind} from {from_version} to {target}"
            )
        text = step(text)
        version += 1
    return stamp_schema_version(text, target), from_version, target


def _write_atomic(path: Path, text: str) -> None:
    """Atomic same-path write — a crash mid-write never leaves a half-migrated note.

    Thin indirection over the pipeline-wide `registry.atomic_write_text` (the single
    source of truth for this idiom); lazy so importing `schema` stays dependency-light."""
    from scripts.registry import atomic_write_text  # noqa: PLC0415

    atomic_write_text(path, text)


def migrate_file(path: Path, kind: str, *, dry_run: bool = False, force: bool = False) -> bool:
    """Migrate one file (atomically). Returns True if anything changed / would.

    For ordinary kinds the file is rewritten in place. For sidecar kinds
    (`MIGRATION_SIDECAR_SUFFIX` — the sources/topics format change) the migrated
    text is written to the sibling `{stem}<suffix>` file and the ORIGINAL is left
    untouched (read-only fallback); an existing sidecar is never overwritten
    unless `force=True`. `dry_run` computes the result without writing."""
    sidecar = MIGRATION_SIDECAR_SUFFIX.get(kind)
    original = path.read_text(encoding="utf-8")
    new_text, from_version, to_version = migrate_text(original, kind)
    if sidecar is not None:
        target = path.with_suffix(sidecar)
        if target == path or (target.exists() and not force):
            return False  # already migrated (or the path IS the new format)
        if from_version == to_version:
            return False  # already current / newer — nothing to write
        if not dry_run:
            _write_atomic(target, new_text)
        return True
    if new_text == original:
        return False
    if not dry_run:
        _write_atomic(path, new_text)
    return True


def _migrate_one_for_cli(path: Path, kind: str, *, dry_run: bool) -> str:
    """Migrate one file for the CLI and return its report line.

    One read, one transform, one write — the reported versions are exactly what
    lands on disk (no re-read between report and write). Sidecar kinds report
    the twin they write and never touch the original."""
    original = path.read_text(encoding="utf-8")
    new_text, from_version, to_version = migrate_text(original, kind)
    sidecar = MIGRATION_SIDECAR_SUFFIX.get(kind)
    if sidecar is not None:
        target = path.with_suffix(sidecar)
        if target == path or target.exists():
            return f"{path}: already migrated ({target.name} exists)"
        if from_version == to_version:
            return f"{path}: already current (schema_version {to_version})"
        if dry_run:
            return f"{path}: would migrate {from_version} -> {to_version} (writing {target})"
        _write_atomic(target, new_text)
        return (
            f"{path}: migrated {from_version} -> {to_version} -> wrote {target} "
            f"(the original is kept as a read-only fallback)"
        )
    if new_text == original:
        return f"{path}: already current (schema_version {to_version})"
    if dry_run:
        return f"{path}: would migrate {from_version} -> {to_version}"
    _write_atomic(path, new_text)
    return f"{path}: migrated {from_version} -> {to_version}"


# The config files the `migrate-config` convenience command lifts, in order.
_CONFIG_MIGRATION_FILES: tuple[tuple[str, str], ...] = (
    ("sources.md", "sources"),
    ("topics.md", "topics"),
)


def migrate_config_dir(
    config_dir: Path, *, dry_run: bool = False, force: bool = False
) -> tuple[list[str], int]:
    """Migrate config/sources.md + config/topics.md to their YAML twins.

    Returns `(report_lines, failures)`. The .md files are never modified or
    deleted — they stay as the read-only fallback for one minor version. An
    existing YAML twin is kept (re-running is a safe no-op) unless `force=True`
    (e.g. after copying a fresh starter pack over the .md files)."""
    lines: list[str] = []
    failures = 0
    migrated_any = False
    for name, kind in _CONFIG_MIGRATION_FILES:
        md = config_dir / name
        twin = md.with_suffix(MIGRATION_SIDECAR_SUFFIX[kind])
        if not md.exists():
            state = f"already the active config ({name} absent)" if twin.exists() else "not found"
            lines.append(f"{name}: {state} — nothing to migrate")
            continue
        if twin.exists() and not force:
            lines.append(
                f"{twin.name}: already exists — skipped "
                f"({name} left untouched; --force regenerates from it)"
            )
            continue
        try:
            changed = migrate_file(md, kind, dry_run=dry_run, force=force)
        except (OSError, MigrationPathMissing) as exc:
            lines.append(f"error: {md}: {exc}")
            failures += 1
            continue
        if not changed:  # pragma: no cover - md present + twin absent always changes
            lines.append(f"{name}: nothing to migrate")
            continue
        migrated_any = True
        verb = "would write" if dry_run else "wrote"
        lines.append(f"{name}: migrated 1 -> 2 — {verb} {twin.name}")
    if migrated_any and not dry_run:
        lines.append(
            "note: the YAML files are now the active config; the .md files are kept "
            "untouched as a read-only fallback (readers ignore them while the YAML exists)."
        )
    return lines, failures


def main(argv: list[str] | None = None) -> int:
    """CLI: `python3 scripts/schema.py migrate <kind> <path...> [--dry-run]`, or
    `python3 scripts/schema.py migrate-config [--config-dir DIR] [--dry-run] [--force]`."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    mig = sub.add_parser("migrate", help="lift files to CURRENT[kind]")
    mig.add_argument("kind", help=f"artifact kind: one of {', '.join(sorted(CURRENT))}")
    mig.add_argument("paths", nargs="+", type=Path, help="files to migrate")
    mig.add_argument("--dry-run", action="store_true", help="report, write nothing")
    cfg = sub.add_parser(
        "migrate-config",
        help="migrate config/sources.md + config/topics.md to their YAML twins "
        "(the .md files are kept as a read-only fallback)",
    )
    cfg.add_argument(
        "--config-dir",
        type=Path,
        default=_PROJECT_ROOT / "config",
        help="config directory (default: project config/)",
    )
    cfg.add_argument("--dry-run", action="store_true", help="report, write nothing")
    cfg.add_argument(
        "--force",
        action="store_true",
        help="regenerate the YAML twins even when they already exist",
    )
    args = parser.parse_args(argv)

    if args.command == "migrate-config":
        lines, failures = migrate_config_dir(
            Path(args.config_dir), dry_run=args.dry_run, force=args.force
        )
        for line in lines:
            print(line, file=sys.stderr if line.startswith("error:") else sys.stdout)
        return 1 if failures else 0

    if args.kind not in CURRENT:
        print(
            f"error: unknown kind {args.kind!r} (expected one of "
            f"{', '.join(sorted(CURRENT))})",
            file=sys.stderr,
        )
        return 2

    failures = 0
    for path in args.paths:
        # Write errors get the same per-file report-and-continue treatment as
        # read errors — never a traceback, never aborting the remaining files.
        try:
            print(_migrate_one_for_cli(path, args.kind, dry_run=args.dry_run))
        except (OSError, MigrationPathMissing) as exc:
            print(f"error: {path}: {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


def scan_paths_for_drift(paths: Iterable[Path], kind: str) -> list[str]:
    """Return an advisory `<name>: <warning>` line for every file in `paths` stamped
    NEWER than `CURRENT[kind]`. Unreadable files are skipped (a separate concern).

    The single shared drift scanner both validators call — so the advisory wording
    and the "missing == baseline, only newer warns" rule live in exactly one place."""
    out: list[str] = []
    for path in paths:
        try:
            version = read_schema_version(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        warning = drift_warning(kind, version)
        if warning:
            out.append(f"{path.name}: {warning}")
    return out

if __name__ == "__main__":
    raise SystemExit(main())
