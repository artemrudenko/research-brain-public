# Changelog

This file records releases made from the **public repository**. Its first release
will be `0.1.0`; the release tag will be created in that repository after the
final verification and pilot review. The current source is a release candidate.

## [Unreleased]

### Added

- Validated problem-solution concept records, explicit language/problem-type MCP filters,
  and private exact-digest project proposals with interactive owner approval, stale-base
  checks, retained evidence, atomic readback and resumable interrupted saves. MCP stays
  read-only; profile problems appear in vault health reports.

### Included in the 0.1.0 candidate

- Topic and source configuration, RSS-first collection, sanitization, curation,
  cited concept notes in an Obsidian vault, and weekly digest delivery.
- A deterministic RSS Digest Lite path for installations without the full agent
  workflow. The two paths have different capabilities; see `README.md`.
- Source and author management, capture inbox, health diagnostics, update tools,
  and local scheduling helpers.
- New `search` author follows are unavailable because that variant never
  collected work. Existing rows remain readable and removable.
- The doctor reports warnings as needing attention. The Codex scheduler wrapper
  provides network access for collection and records the CLI path in cron entries.
- An optional local read-only MCP adapter supplies source-backed concept context
  to project agents. Lexical search is bounded; research and approved saving remain
  host workflows. The pinned SDK is isolated from the core runtime.
- A cross-project pilot protocol and a disposable stdio replay example document
  evidence boundaries. The local gate and CI also check the isolated adapter.

- Publisher-diversity labels no longer claim factual confirmation after lexical
  text deduplication. Audit instructions require separate claim/provenance review.
- The Claude plugin manifest uses the supported author object; an unverified
  homepage is omitted until a public destination exists.

### First-run and upgrade notes

- `install.sh` installs dependencies by default; its interactive configuration
  interview is selected with `--configure`.
- The runtime reads `config/sources.yaml` and `config/topics.yaml`. An older
  installation with only the retired Markdown tables can import them with
  `python3 scripts/schema.py migrate-config` after a backup.
- The public `0.1.0` line is for a clean installation. Use the normal updater
  for future releases on this line.

A successful test suite establishes the deterministic code checks. The full
unattended workflow still needs the two-cycle evidence described in
`docs/PILOT.md` before claiming validated recurring value.
