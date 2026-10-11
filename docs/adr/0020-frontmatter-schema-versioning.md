# ADR 0020 — Flat `schema_version` stamp + additive-only rule for painless migrations

- **Status:** Accepted (2026-07-02)
- **Tags:** schema, migrations, frontmatter, config

## Context
The distribution model ships without an auto-migrator ([ADR 0019](0019-assisted-in-place-update.md)):
an update overlays code and preserves the user's `brain/`, `pipeline/`, and `config/` as-is. That is
safe today, but the moment a release changes a frontmatter or config *shape*, a deployed install
carries files in the old shape with no marker saying so — a future migrator would have to *guess*
each file's version from its structure. We need to lay the groundwork now, cheaply, without breaking
the flat parsers already in the pipeline.

Two constraints shaped the decision:
- **Flat parsers exist by design.** The headless (no-PyYAML) cron path reads frontmatter line-based:
  `build_digest._split_frontmatter`, the audit reader in `sanitize_incoming`, and the fallback
  frontmatter reader in `validate_brain`. A **nested** `meta.schema_version` would be invisible to
  them (or, worse, `build_digest`'s indent-blind `partition(":")` would misread an indented key as a
  top-level one). So a version marker they must read has to be a **flat top-level** key.
- **Existing installs must not churn.** Every deployed file predates any stamp; introducing one must
  be a no-op for them.

## Decision
1. **Additive-only is the default schema-change rule.** A change ADDS an OPTIONAL key with a safe
   code default, never makes a key required and never repurposes an existing key. Readers already
   tolerate absence (`*.get(k, default)`). Such a change needs **no** version bump and **no**
   migration — the path most changes should take.
2. **A flat `schema_version: N` stamp** marks the shape of each frontmatter-bearing artifact
   (concept, lesson, playbook, article) and the fixed-schema configs. It is a **column-0 key**, never nested.
   Newly written files carry it (concept/lesson/playbook templates; `collect.py`/`inbox.py` for articles;
   shipped `channels.yaml`/`schedule.yaml`); **a missing stamp reads as the baseline `1`**, so
   existing installs are unaffected.
3. **One source of truth**: `scripts/schema.py` holds `CURRENT[kind]`, a flat-safe
   `read_schema_version` (scoped to the frontmatter block), a `drift_warning`, and the shared
   `scan_paths_for_drift` both validators call. `validate_config` and `validate_brain` emit an
   **advisory** warning (exit unchanged) when a file is stamped NEWER than the running code — the one
   risky direction (old code silently misreading a new-schema file).
4. **On a breaking change:** bump `CURRENT[kind]`, restamp the template/writer, and add a migration
   `(kind, N) -> N+1` when the migrator ships.

## Consequences
- A future migrator has a deterministic per-file version to key on; the additive-only rule keeps the
  number of changes that ever need it small.
- The stamp is inert until a bump: no behavior change today, advisory-only drift signalling.
- Nested metadata blocks remain usable for information only full-YAML readers touch — but anything a
  line-based reader or the migrator must see stays flat.
- The migrator MACHINERY now ships (2026-07-03): `scripts/schema.py` carries
  `MIGRATIONS[(kind, from)] -> transform`, `migrate_text` (chains steps, owns restamping),
  `migrate_file` (atomic in-place), and a `schema.py migrate <kind> <paths> [--dry-run]` CLI —
  rehearsed end-to-end in tests with a synthetic `(concept, 1) -> 2` step, so the first real
  breaking change registers a transform into battle-tested wiring instead of exercising it for
  the first time on user data. The shipped registry stays EMPTY (guarded by a test) until a
  real breaking change lands. What remains deferred is only each concrete transform.
- Historical note (superseded by the above): the migrator itself was deferred (ADR 0019); this ADR was the groundwork that makes it a small
  addition rather than a retrofit.

## Alternatives considered
- **Nested `meta:` block** (the intuitive shape). Rejected for the migration-critical stamp: the
  flat headless readers can't see it. Fine for full-YAML-only metadata, not for this.
- **No stamp, infer version from structure.** Rejected: brittle and ambiguous; the whole point is to
  avoid guessing.
- **Bump on every change.** Rejected: most changes are additive and need neither a bump nor a
  migration; reserving the bump for breaking changes keeps the version meaningful.

## References
- `scripts/schema.py`, `docs/CONVENTIONS.md` §5.5, `DEVELOPING.md` (release/schema section).
- [ADR 0019](0019-assisted-in-place-update.md) — the update path whose deferred migrator this enables.
