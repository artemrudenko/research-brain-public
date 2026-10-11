---
name: brain-review
description: "Adversarial, multi-agent CONTENT-TRUST audit of the standing knowledge vault — re-verify existing brain/concepts/ against their own sources: to catch hallucinations, the single-source illusion, staleness, contradictions, overconfidence and tag drift. NOT mechanical hygiene (that is validate_brain.py), NOT operational health (that is brain-ask), NOT fresh-draft fact-check (that is research-audit). Agent-runtime only; degrades to validate_brain.py headless. Triggers: \"review the brain\", \"audit the knowledge base\", \"is the vault accurate\", \"re-verify concepts\", \"check the brain for hallucinations\", \"trust audit\", \"проверь базу знаний\", \"аудит достоверности\", \"перепроверь концепты\", \"нет ли выдумок в базе\", \"проверь базу на галлюцинации\"."
metainfo:
  type: validator
  domain: meta-process
  subagent_capability: general
  last_updated: 2026-06-23
  relation: "Deeper, adversarial complement to validate_brain.py (mechanical hygiene) and brain-ask (operational health). Reuses research-audit's verify discipline, but applied to the STANDING vault instead of a fresh draft. Routes content changes to wiki-ingest; never edits the vault silently."
---

# brain-review — adversarial content-trust audit of the vault

`validate_brain.py` checks the **graph is intact**; `brain-review` checks the **knowledge is
true**. It re-verifies standing `brain/concepts/` against their *own* cited `sources:` and flags
the failures a deterministic script cannot judge: hallucinations, the **single-source illusion**
(one domain dressed up as "confirmed"), staleness, internal contradictions, overconfidence, and
semantic tag drift. It is multi-agent by nature and runs **only in the agent runtime**.

## Boundary — read this first

| Question | Skill | Layer |
|---|---|---|
| Is the system running (feeds alive, delivery, digest fresh)? | **brain-ask** / `health.py` | operational |
| Is the vault graph intact (orphans, broken links, missing `sources:`, tags, ttl-stale)? | **validate_brain.py** | mechanical hygiene |
| Are the facts in *this fresh draft* sound? | **research-audit** | draft fact-check |
| **Is the accumulated knowledge actually accurate and well-grounded?** | **brain-review** (this) | content trust |

## When to Use
- "review the brain", "audit the knowledge base", "is the vault accurate", "re-verify concepts",
  "check the brain for hallucinations / single-source", "trust audit",
  "проверь базу знаний", "аудит достоверности", "перепроверь концепты", "нет ли выдумок в базе".
- A periodic (e.g. **monthly**) trust sweep; after a large synthesis burst; or when
  `validate_brain` flags many `stale` notes (brain-review is what *resolves* a stale flag — by
  actually re-verifying — and stamps `last_verified:`).

## Skip / don't use for
- Mechanical integrity only → **validate_brain.py**. "Is it running / did the digest go out" →
  **brain-ask**. Fact-checking a NEW draft in the research chain → **research-audit**.
- **Changing vault content** → that goes through **wiki-ingest** with its approval gate.
  brain-review *proposes and routes*; it never silently rewrites a concept.

## Runtime modes
- **Agent runtime** (Cowork / Claude Code / cloud `/schedule`): the full multi-agent audit below.
  Keyless — uses the agent's own sub-agents, no API keys.
- **Headless / cron** (no agent): **degrade** — run `python3 scripts/validate_brain.py` (mechanical
  pass) and report plainly: *"content-trust audit needs the agent runtime; ran mechanical hygiene
  only."* (Same MCP-only pattern as inbound Telegram.)

## Procedure (agent runtime)

**Phase 0 — Scope the batch.** Run `validate_brain.py` first (cheap mechanical pre-pass; fold its
orphan / broken-link / missing-source / stale flags into the report — don't re-do them). Then pick
the audit batch: default = concepts that are **ttl-stale** (`last_verified + ttl_days` past),
**never-verified**, or **changed since the last `brain-review_*.md` report**; or a user-named
topic/cluster; or **all** on explicit request. **Cap** the batch per run and **`log` what was
deferred** — never silently truncate.

**Phase 1 — Verify (fan out, one agent per concept).** Each verifier reads the concept **and every
entry in its `sources:`**, then adversarially checks:
- **(a) Grounding / citation guard** — every key fact traces to a `sources:` entry, and that source
  actually supports it (hallucination / fabricated-quote guard; reuse `research-audit`'s Phase 5.5
  discipline).
- **(b) Corroboration honesty** — count **distinct independent registrable domains** in `sources:`
  vs the concept's trust claim; flag the **single-source illusion** (one domain or syndication
  collapsed-but-counted-as-many) per CONVENTIONS §16.
- **(c) Recency** — facts whose sources predate a known newer development, or past
  `last_verified + ttl_days` → stale.
- **(d) Contradiction** — claims that conflict with a linked `related_concept:` note.
- **(e) Overconfidence** — categorical claims thinner than their evidence.
- **(f) Tag sanity** — tags semantically fit (closed-book vs `config/tags.yaml`), not merely valid.

Verdict per concept: `VERIFIED-OK` / `STALE` / `NEEDS-RESYNTHESIS` / `DOWNGRADE-TRUST` /
`HALLUCINATION-RISK` / `TAG-FIX`, each with the evidence that justifies it.

**Phase 2 — Refute (adversarial second pass).** For every **non-OK** verdict, a second agent tries
to **refute** the finding (default to "not a real problem" unless the evidence holds). Keep only
findings that survive — so no concept is condemned on a single agent's read.

**Phase 3 — Report.** Synthesize a graded report and write
`pipeline/3-synthesis/brain-review_YYYY-MM-DD.md`: counts by verdict, the per-concept evidence, a
**worklist** (concepts → re-synthesize via `research-build` → `wiki-ingest`, or → re-collect a
corroborating source), and a one-line headline the digest can surface:
`Trust: N concepts · X stale · Y resynth · Z hallucination-risk`.

**Phase 4 — Apply (gated).**
- **Interactive (default):** PROPOSE. On approval, stamp `last_verified: <today>` on `VERIFIED-OK`
  concepts (an allowed hygiene-metadata write) and route every **content** change to **wiki-ingest**.
- **Unattended (`INTERACTIVE=false`):** may stamp `last_verified:` on clean concepts (low-risk
  metadata), but **never** auto-rewrites content — every content change goes to the worklist for a
  human / `wiki-ingest`. A mass-failure (most of the batch flagged) → **halt and report**, do not
  mass-mutate.

## Stop conditions
- Read-only by default; **no content rewrite without `wiki-ingest` + approval**; never mass-edit
  the vault (respects the `brain/` "don't touch" rule and the no-silent-edit invariant).
- Headless → degrade to `validate_brain.py`. Honor the batch cap and `log` deferrals.

## Output
- `pipeline/3-synthesis/brain-review_YYYY-MM-DD.md` (graded report + headline + worklist).
- A plain-language summary. Nothing fetched; no vault content silently changed.

## Verification
- Batch selection is correct (stale + never-verified + changed-since-last; cap honored, deferrals
  logged). Each verdict cites evidence. A planted single-source illusion is caught. Every non-OK
  finding survives the Phase-2 refute pass. The report headline matches the digest's expected
  prefix. The headless degrade path runs `validate_brain` and says so. No silent vault edit occurs.

## Examples
1. **"audit the knowledge base for accuracy"** → Phase 0 scopes stale + changed concepts (logs the
   rest deferred); verifiers find one concept whose three "sources" are the same domain
   re-syndicated (single-source illusion) → `DOWNGRADE-TRUST`; report + worklist; offers to stamp
   `last_verified` on the `VERIFIED-OK` ones and route the flagged one to `wiki-ingest`.
2. **headless cron** → "content-trust audit needs the agent runtime; ran `validate_brain` only —
   N concepts, X orphans, Y stale."
3. **"перепроверь концепты по теме X"** → audits only that topic cluster.

## Cadence
Token-costly and judgment-heavy → **on demand**, or a **separate** (e.g. monthly) `/schedule`
routine. Deliberately **not** wired into the weekly `weekly-run.md` loop, which stays lean.
