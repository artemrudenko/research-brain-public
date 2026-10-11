# ADR 0005 — Controlled-vocabulary tagging from config/tags.yaml

- **Status:** Accepted (backfilled 2026-06-24)
- **Tags:** tagging, vocabulary, knowledge-store

## Context
Tags are the secondary filter over the vault and feed the graph. An LLM left to invent tags freely
produces synonym sprawl and inconsistent casing/plurality, which degrades navigation — and the
target user does no manual gardening.

## Decision
Concept tags are a **controlled vocabulary**: nested `domain/topic` form, chosen **closed-book**
from `config/tags.yaml` only (2–5 per note, ≥1 domain-level tag). The super-tag is the nested
parent (`#ai` aggregates `#ai/*` natively — no separate super-tag feature). When nothing fits,
propose **≤1** new tag in `domain/topic` form into the `pending:` quarantine — never straight into
the live vocabulary. `validate_brain.py` (advisory) normalizes, merges synonyms, and *recommends*
promoting a pending tag once it recurs across ≥3 notes; `scripts/promote_tags.py` *applies* that
promotion in the weekly brain-hygiene step. `source-manage` (add-topic) seeds a new topic's tag
immediately so it does not get stuck in quarantine.

## Consequences
- Tag space stays small and consistent without per-note human review.
- New vocabulary is earned (recurrence-gated), not minted ad hoc.
- Frontmatter `tags:` only (not inline `#tag`); tags live on concepts, articles carry seed tags
  from RSS `<category>` normalized through the registry.
- Cost: a genuinely novel topic waits in `pending:` until it recurs (unless seeded by add-topic).

## Alternatives considered
Not recorded as explicit rejected options; the documented rationale is the positive design
(closed-book picks + quarantine + recurrence-gated promotion).

## References
- `docs/CONVENTIONS.md` §11 (Tagging — controlled vocabulary).
- `AGENTS.md` — Mandatory rules ("Tags are a controlled vocabulary").
