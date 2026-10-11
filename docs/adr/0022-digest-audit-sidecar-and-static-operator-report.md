# ADR 0022 — Digest audit sidecar and static operator report

- **Status:** Accepted
- **Tags:** digest, observability, artifacts

## Context

The weekly digest is intentionally a curated read, not a full archive. Per-topic source
groups show only the top few items by credibility and fold the rest into a `+N more` line.
That keeps Telegram and email readable, but operators still need a durable explanation of
what was shown, what was hidden, and which exact digest content was reviewed.

The project must keep its core deployment shape: no database, no server, no SPA requirement,
and no second source of truth beside the Markdown pipeline and Obsidian vault.

## Decision

Every deterministic `scripts/build_digest.py` run writes a JSON audit sidecar next to the
Markdown digest: `digest_YYYY-MM-DD.audit.json` (or `digest_daily_YYYY-MM-DD.audit.json`).
The sidecar is derived from the same `DigestData` and curation rule used by the Markdown
renderer. Schema version `digest_audit.v1` records the digest hash, quiet/daily flags,
summary totals, and per-topic source decisions with `included`, `rank`, and `reason`.

`build_digest.py --report` writes a static browser-grade operator report,
`digest_YYYY-MM-DD.report.html`, that links to the audit sidecar and displays the same
digest with stats/glossary/concept snapshots. The report is a local file, not a web app or
delivery channel.

## Consequences

- Operators can inspect digest selection without re-running collection or reading raw
  incoming folders by hand.
- Tests can assert selection behavior through a structured artifact instead of scraping
  presentation text.
- Old digests without sidecars remain valid; the sidecar is additive provenance.
- Delivery idempotency remains owned by `.delivered/*.json`; the audit sidecar does not
  replace delivery receipts or health events.
- The implementation stays inside the stdlib-only runtime boundary.

## Alternatives considered

- **Full dashboard / SPA.** Rejected for the core product because it would add server or
  frontend operational weight to a Markdown/Obsidian system.
- **Only improve the Markdown digest.** Rejected because the digest should stay concise for
  readers; operator provenance belongs beside it, not inside it.
- **Reuse the health event log.** Rejected because health events describe runs and delivery,
  while the audit sidecar describes one specific digest artifact.

## References

- ADR 0001 — Obsidian vault instead of generated indices
- ADR 0002 — Runtime scripts import only stdlib + pyyaml
- ADR 0009 — One gated weekly-run orchestrator
- ADR 0017 — Weekly trends report from durable, dated sources
- ADR 0021 — Stable script facades over domain packages
