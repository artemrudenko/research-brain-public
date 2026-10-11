# ADR 0004 — Distribute as an unpacked archive, not a published plugin marketplace

- **Status:** Accepted (backfilled 2026-06-24)
- **Tags:** distribution, packaging

## Context
The project needs a delivery channel to its (primarily non-technical) recipients. A
`.claude-plugin/plugin.json` exists in the repo, which could be mistaken for an active marketplace
listing / release channel.

## Decision
Ship the repo as an **unpacked archive** the recipient sets up locally — **not** published to a
plugin marketplace. `.claude-plugin/plugin.json` is retained **only** for in-place plugin / Cowork
loading, not as a release channel. Cutting an archive goes through `make dist` (wraps `git archive`,
honoring `.gitattributes` `export-ignore`), which writes `dist/research-brain-<version>.zip` and drops
contributor-only paths (`DEVELOPING.md`, `tests/`, `.github/`, `.gitattributes`).

## Consequences
- Recipient owns a local copy with their own `config/.env`; no marketplace publishing pipeline.
- `make dist` archives only committed state, so live run data and `config/.env` never leak.
- Contributor-only files are excluded so the recipient's agent never reads dev instructions as
  product contract.
- Cost: no automatic update channel — recipients re-take an archive to update. The **assisted**
  update path that makes re-taking an archive safe (overlay code, preserve data, backup first) is
  [ADR 0019](0019-assisted-in-place-update.md) / `update.sh`.

## Alternatives considered
A published plugin marketplace listing — explicitly rejected ("it is *not* published to a plugin
marketplace"; "don't mistake it for an active marketplace listing").

## References
- `DEVELOPING.md` — "Distribution = zip handoff, not marketplace".
- `CLAUDE.md` — "Distribution = zip handoff, not marketplace".
