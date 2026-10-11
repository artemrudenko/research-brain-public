---
title: "Acceptance tests — research-audit"
type: acceptance-test
domain: research-methodology
status: active
created: 2026-05-03
last_updated: 2026-06-15
topic_tags: [acceptance, test, skill, research-audit, verify-phase]
related_skill: skills/research-audit/SKILL.md
generated_by: ai-then-human-edited
---

# Acceptance tests — research-audit

> Living spec for the Verify phase of the research lifecycle. Covers standard mode (3 levels 🟢🟡🔴), extended mode (4 levels + evidence-type), light mode (chat-answer downgrade), and failure modes.

## Scope

- **Skill:** `research-audit`
- **SKILL.md:** [`../SKILL.md`](../SKILL.md)
- **Position:** Verify in the research lifecycle
- **Coverage:** 7 scenarios — 2 happy paths (standard + extended) + 4 edge cases + 1 failure mode

---

## Scenarios

### Scenario 1: Happy path — standard mode, gate passed

**Given:**
- Draft `pipeline/3-synthesis/tool-comparison.md` exists with 12 verifiable claims (4 numeric, 6 vendor-claims, 2 factual)
- Brief `planning/research/2026-05-02_tool-comparison.md` with `format=document`, `audience=deliverable`, `recency_max=12mo`, `min_tier=T1+T2`, `grading_mode=standard`
- All sources registered in `sources/trusted-registry.md`

**When:**
- User: "Check the facts in tool-comparison.md before shipping"
- OR: research-build finished Synthesize and automatically handed off to research-audit

**Then:**
- Verification log created: `planning/research/2026-05-02_tool-comparison.verification-log.md`
- Frontmatter contains `type: audit-report`, `gate_status: passed`, `red_pct: ≤30%`
- 12 claims marked: ≥7× 🟢, ≤3× 🟡, ≤2× 🔴
- Brief updated: `verification_log` field + lifecycle checkbox `[x] **Verify**` + `last_updated: 2026-05-03`
- Hand-off to the research-build Critique pass (gate_status passed)

**Acceptance signal:**
- File exists at the expected path
- `grep "gate_status: passed"` in the verification log → 1 match
- `grep "🟢\|🟡\|🔴"` in the verification log → 12 markers (one per claim)

---

### Scenario 2: Happy path — extended mode

**Given:**
- Draft `pipeline/3-synthesis/decision-brief.md` with 18 claims
- Brief with `audience=leadership` → research-frame auto-set `grading_mode=extended`
- All sources registered; evidence-type definable per host

**When:**
- User: "Check the facts for the decision brief"

**Then:**
- Verification log created with extended frontmatter:
  - `grading_mode: extended`
  - `levels_distribution: {high: N, moderate: N, low: N, very_low: N}`
  - `evidence_type_distribution: {peer-reviewed: N, official-doc: N, ...}`
- Each claim has a 4-level marker (🟢 High / 🟢- Moderate / 🟡 Low / 🔴 Very-Low) + an `evidence_type` field
- The threshold gate uses `very_low_pct > 30%` (instead of `red_pct`)
- The standard 3-level mapping is NOT applied

**Acceptance signal:**
- `grep "grading_mode: extended"` in the verification log → 1 match
- `grep "evidence_type:"` in the verification log → ≥18 matches (one per claim)
- `grep "levels_distribution"` → 1 block with 4 keys

---

### Scenario 3: Edge case — chat-answer light mode

**Given:**
- Brief with `format: chat-answer` (Frame questionnaire)
- Draft = a chat response with 3 footnote URLs

**When:**
- research-audit activated with `MODE=auto` (reads `format` from the brief)

**Then:**
- Phases 2-6 skipped (per SKILL.md "Light mode")
- Inline summary in chat: "Tier audit: 3 links — 2× T1, 1× T3..." — short output
- Verification-log file **NOT created**
- Threshold gate disabled — never blocks

**Acceptance signal:**
- No file at `planning/research/{date}_{slug}.verification-log.md`
- Chat output contains the "Tier audit:" prefix
- No AskUserQuestion fired for unregistered hosts (light mode handles it inline)

---

### Scenario 4: Edge case — unregistered host triggers AskUserQuestion

**Given:**
- Draft contains 5 claims, 1 references a new host `someblog.dev` (not in `sources/trusted-registry.md`)

**When:**
- research-audit Phase 7d reached (after the log is written)

**Then:**
- AskUserQuestion fired: "New host `someblog.dev` appears in 1 claim. Tier?"
- Options: T1 / T2 / T3 / Skip
- On choosing T2 — `sources/trusted-registry.md` gets a new row
- Verification log updated: `unregistered_hosts_count: 0` after resolution

**Acceptance signal:**
- New row in `sources/trusted-registry.md` for `someblog.dev`
- `unregistered_hosts_count: 0` in the verification-log frontmatter

---

### Scenario 5: Edge case — contradiction between sources

**Given:**
- 2 sources with conflicting numeric values for the same claim:
  - Source A (analyst, T2): "value = $3/$15 per Mtok"
  - Source B (vendor news, T1): a different value for the same metric

**When:**
- Phase 5 cross-source check detects the mismatch

**Then:**
- The claim gets a 🔴 marker (extended: very-low) — a contradiction = unverified
- Verification-log section "Contradictions" contains an entry with both values
- AskUserQuestion: "Both versions explicit / Pick one + note / Drop the claim"

**Acceptance signal:**
- `grep "## Contradictions"` in the verification log → ≥1 match with both URLs
- The claim entry has `cross_source: contradiction`

---

### Scenario 6: Edge case — always-volatile keyword overrides recency

**Given:**
- Brief with `recency_max: 12mo`
- A claim about a "context window" (always-volatile per `sources/always-volatile-domains.md`)
- Source published 6 months ago

**When:**
- Phase 4 recency check

**Then:**
- Always-volatile override applies: threshold = 90 days (3mo) instead of 365 (12mo)
- The claim is flagged `recency_stale: true` (6 mo > 3 mo threshold)
- Marker downgraded: 🟢 → 🟡 (if it was T1) or 🟡 → 🔴

**Acceptance signal:**
- `grep "recency_stale: true"` in the claim entry → match
- The reason field contains "always-volatile override applied (6mo > 3mo)"

---

### Scenario 7: Failure mode — gate blocked (>30% 🔴)

**Given:**
- Draft with 15 claims; 6 🔴 unverified (40% > 30% threshold)

**When:**
- Phase 7b threshold gate evaluation

**Then:**
- `gate_status: blocked` in the frontmatter
- Verification log created in full (for the audit trail)
- The caller receives a return signal: "> 30% of claims unverified — formatting blocked. Returning to Gather. Weak claims: ..."
- Critique / formatting **do NOT run**
- Brief updated: lifecycle checkbox `[x] **Verify** — verification_log.md (BLOCKED)`

**Acceptance signal:**
- `grep "gate_status: blocked"` in the verification log → 1 match
- The draft was not finalized as a synthesized document (formatting did not run)
- Brief lifecycle: the `Verify` checkbox marked with `(BLOCKED)`

---

## Cross-references

- **SKILL.md:** [`../SKILL.md`](../SKILL.md)
- **Rules:** [`../rules/common.md`](../rules/common.md) (RED_THRESHOLD_PCT=30, claim patterns, evidence-type taxonomy)
- **Tier rules:** [`../references/tier-rules.md`](../references/tier-rules.md) (extended evidence-type rules)
- **Related skills:**
  - `research-build` (incoming Synthesize, outgoing Critique pass)
  - `source-archive` (supplementary fetches)
  - formatting step (downstream, only if the gate passed)

## Maintenance

- **Update triggers:** new mode added, changed RED_THRESHOLD_PCT, new evidence-type added
- **Coverage gaps known:** subagent dispatch (>20 claims) — add a scenario on the first production run; pre-existing log re-use (Phase 0 Step 1, light-mode-recent-log) — add a scenario

## Publisher diversity is not claim confirmation

Scenario: two explicitly synthetic publisher articles use different wording but both
attribute the same factual claim to one upstream announcement. Their domains differ and
lexical similarity is below the duplicate threshold. No second independent observation is
supplied. Evaluate in FULL and SOFT modes without fetching or inventing further evidence.

Expected:

- The publisher proxy may be `multi`; the legacy `independent_sources` field is explained
  as that proxy, not a verified independence count.
- Record shared upstream provenance (or `independence_review: unknown` when not established).
  Do not make the factual claim 🟢 from domain count or low text similarity alone.
- Keep a 🟡 limitation in FULL mode unless separate independent support is established.
  SOFT mode annotates the same limit and does not block ingest on coverage.
- The digest marker remains publisher diversity. A contradictory or unsupported passage
  still follows its own claim-level audit rule; counts cannot override it.

This is an acceptance scenario for the skill, not a recorded model-host run.
