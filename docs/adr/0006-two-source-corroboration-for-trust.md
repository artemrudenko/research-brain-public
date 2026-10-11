# ADR 0006 — News/factual concepts need ≥2 independent sources for a 🟢 trust line

- **Status:** Accepted (backfilled 2026-06-24)
- **Tags:** fact-check, corroboration, digest

## Context
The primary audience is non-technical and cannot independently verify a factual/news claim. The
digest needs to show, per concept, whether a claim is confirmed by several **independent** sources —
without over-claiming when several "sources" are really one wire story reprinted.

## Decision
For news/factual claims, an **independent source** = a separate registrable domain (eTLD+1) among a
concept's `sources:`, **after** collapsing near-duplicate texts (syndication) via `scripts/dedup.py`
(10 reprints of one story = 1 source). A 🟢 trust line requires **≥2 independent sources**; the
digest renders a per-concept trust line from `corroborate.trust_line()`:
`🟢 Confirmed by N independent sources` (≥2 domains AND near-dup collapsed), `🔵 Reported by N sources`
(≥2 domains, syndication not ruled out), `🟡 Single-source — treat with caution` (exactly 1),
empty (0). The count is derived from `sources:`, never kept as a separate counter.

## Consequences
- The digest carries an honest, deterministic confidence signal per concept.
- 🟢 needs article bodies (to collapse near-dups), so the headless `build_digest.py` — which has no
  bodies — honestly emits at most 🔵; 🟢 is reachable only on the agent-authored path. Intentional,
  not a bug.
- In soft (unattended) mode the corroboration check is a light signal, never blocking.

## Alternatives considered
Keeping a separate corroboration counter was explicitly rejected ("do NOT keep a separate counter —
derive it"). Treating raw source count as trust (without collapsing syndication) is rejected by the
eTLD+1 + dedup definition; otherwise not recorded.

## References
- `docs/CONVENTIONS.md` §16 (Fact-check — multi-source corroboration).
- `scripts/corroborate.py` (`trust_line()`), `scripts/dedup.py`.
