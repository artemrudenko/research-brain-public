# ADR 0003 — Internal-corpus synthesis profile for the unattended weekly loop

- **Status:** Accepted (backfilled 2026-06-24)
- **Tags:** synthesis, unattended, soft-mode

## Context
The weekly loop runs unattended, with no operator to answer a blocking gate. The full manual
research chain (frame → grep → build → audit) assumes a research brief, an external `sources/`
tier registry, and a fail-fast ">30% 🔴" audit gate — all of which need a human in the loop and
would stall the unattended run if mandatory.

## Decision
The auto cycle (`weekly-synthesis`) runs an **internal-corpus synthesis profile**: `research-build`
synthesizes from the already-gathered local corpus (`2-curated/` + `1-incoming/`) **without** a
mandatory research brief, **without** an external `sources/`-tier registry, and **without** the
fail-fast/">30% 🔴" gate. The dedup defaults and the citation guard stay. The full strict chain
remains available for **manual** deep-dives, where `sources/` and `planning/research/` are
optional/soft (absence → warning, not halt).

## Consequences
- The unattended digest never blocks: a missing registry is not treated as "everything T3".
- A missing tier registry on a default install puts `research-audit` in soft mode automatically.
- Trades strict tier-grading at synthesis time for liveness; the citation guard and §16
  corroboration still provide a trust signal in the digest.
- Two profiles to keep coherent: soft unattended synthesis and strict manual research.

## Alternatives considered
The strict manual full-chain profile with a mandatory brief/registry/30%-red gate — rejected for the
unattended loop because it requires an operator and would stall the weekly run; it is retained as
the opt-in manual path rather than discarded.

## References
- `docs/CONVENTIONS.md` §10 (Auto modes — Internal-corpus synthesis profile).
- `AGENTS.md` — "Source tier-grading is opt-in / advanced"; soft vs FULL mode.
