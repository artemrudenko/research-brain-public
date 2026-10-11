# ADR 0010 — Contributor guidance lives in DEVELOPING.md, out of the shipped contract

- **Status:** Accepted (backfilled 2026-06-24)
- **Tags:** docs, distribution, contributor

## Context
The shipped product contract — `AGENTS.md`, `CLAUDE.md`, `docs/` — is read by the recipient's agent
as authoritative runtime instructions. Contributor-only guidance (the `uv`/`make` toolchain, the
TDD/coverage gate, and local release routines) was mixed into
that contract, where an end user's agent could read dev instructions as if they were product rules.

## Decision
Move all developer/contributor guidance into **`DEVELOPING.md`**, marked `export-ignore` in
`.gitattributes` so `make dist` (= `git archive`) drops it from the shipped archive along with
`tests/`, `.github/`, and `.gitattributes`. The shipped `AGENTS.md` / `CLAUDE.md` keep only the
runtime/product contract and *link* to `DEVELOPING.md` for contributors; the always-on
runtime-stays-stdlib-only invariant stays in `AGENTS.md` because it is a product rule, not a dev one.

## Consequences
- An end user's agent never reads dev instructions as product contract — the original reason the
  file exists.
- One home for contributor concerns (toolchain, gate, sync, live-run safety); the shipped docs stay
  lean.
- The split must be maintained: a dev-only rule added to a shipped doc re-introduces the leak.

## Alternatives considered
Keeping contributor guidance inline in the shipped `AGENTS.md`/`CLAUDE.md` — rejected because the
recipient's agent would treat it as product contract; not recorded beyond that motivation.

## References
- `DEVELOPING.md` — contributor setup, public source checks, and end-user archive
  procedures.
- The original development-history commit IDs are intentionally absent from the
  clean public repository. The current contributor workflow is in `DEVELOPING.md`.
- `AGENTS.md` — Mandatory rules (stdlib-only note pointing to `DEVELOPING.md`).
