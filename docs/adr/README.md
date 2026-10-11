# Architecture Decision Records (ADR)

An ADR captures **one architectural decision** for research-brain — its context, the decision, its
consequences, and the alternatives considered — so the *why* survives the people who made it. These
were **backfilled** from the existing contract; each one cites its source prose rather than restating
it (keep docs lean, link don't restate).

Some records describe implementation steps before the first public `0.1.0`.
Their older version numbers are historical development labels, not tags in the
public Git history. The current behavior is defined by the code and
`docs/CONVENTIONS.md`; amendments in each ADR identify superseded details.

## Template

MADR-lite. Each ADR file uses this exact shape:

```
# ADR NNNN — <Title>

- **Status:** <Accepted | Superseded by NNNN | Deprecated>
- **Tags:** <2-4 keywords>

## Context
## Decision
## Consequences
## Alternatives considered
## References
```

## Status convention

- **Accepted** — in force. Backfilled ADRs read `Accepted (backfilled 2026-06-24)`.
- **Superseded by NNNN** — replaced; point at the ADR that replaces it.
- **Deprecated** — no longer in force, not replaced.

New decisions get the next free number; never renumber an existing ADR.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-obsidian-vault-over-leiden-autoindex.md) | Obsidian vault instead of Leiden/AUTO_INDEX/kb indices | Accepted |
| [0002](0002-stdlib-only-runtime.md) | Runtime scripts/ import only stdlib + pyyaml | Accepted |
| [0003](0003-internal-corpus-synthesis-profile.md) | Internal-corpus synthesis profile for the unattended loop | Accepted |
| [0004](0004-zip-handoff-not-marketplace.md) | Distribute as an unpacked archive, not a marketplace | Accepted |
| [0005](0005-controlled-vocabulary-tagging.md) | Controlled-vocabulary tagging from config/tags.yaml | Accepted |
| [0006](0006-two-source-corroboration-for-trust.md) | ≥2 independent sources for a 🟢 trust line | Accepted |
| [0007](0007-rss-first-multistage-collection.md) | RSS-first, multi-stage collection | Accepted |
| [0008](0008-english-baseline-with-parallel-translations.md) | English baseline; RU docs are parallel translations | Accepted |
| [0009](0009-single-gated-orchestrator-over-timers.md) | One gated weekly-run orchestrator over four timers | Accepted |
| [0010](0010-contributor-docs-out-of-shipped-contract.md) | Contributor docs in DEVELOPING.md, out of the shipped contract | Accepted |
| [0011](0011-native-windows-via-cross-platform-primitives.md) | Native Windows via cross-platform concurrency primitives | Accepted |
| [0012](0012-reader-subagent-fanout-for-context-bounding.md) | Reader-subagent fan-out (extract, don't dump) for context-bounded synthesis | Accepted |
| [0013](0013-technical-level-render-time-knob.md) | `technical_level` render-time presentation knob, not stored variants | Accepted |
| [0014](0014-concept-lifecycle-soft-delete-and-monitored-entity.md) | Concepts soft-deleted (archive + restore), never hard-deleted; user concept = monitored entity | Accepted |
| [0015](0015-least-privilege-role-subagents.md) | Least-privilege role subagents for model tiering and capability isolation | Accepted |
| [0016](0016-daily-inflow-digest-second-cadence.md) | A daily "inflow" digest as an opt-in second cadence | Accepted |
| [0017](0017-weekly-trends-report.md) | Weekly trends report from durable, dated sources | Accepted |
| [0018](0018-claim-level-dedup.md) | Deterministic claim-level dedup helper | Accepted |
| [0019](0019-assisted-in-place-update.md) | Assisted in-place update (`update.sh`), not a re-unpack | Accepted |
| [0020](0020-frontmatter-schema-versioning.md) | Flat `schema_version` stamp + additive-only rule for painless migrations | Accepted |
| [0021](0021-stable-script-facades-over-domain-packages.md) | Stable script facades over domain packages | Accepted |
| [0022](0022-digest-audit-sidecar-and-static-operator-report.md) | Digest audit sidecar and static operator report | Accepted |
| [0023](0023-scripts-installed-package-with-zip-run-prelude.md) | `scripts` installs as a real package; zip-run survives via one canonical prelude | Accepted |
