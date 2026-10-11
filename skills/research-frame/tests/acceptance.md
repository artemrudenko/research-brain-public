# research-frame — Acceptance Tests

Given/When/Then scenarios for regression coverage of research-frame's gateway semantics.

---

## Test cases — Trigger ownership

### Test C-1.A — research-frame wins on "research X"

**Given:** cold session, no prior conversation
**When:** user input = "research the MCP vs CLI token economics topic"
**Then:**
- ✅ research-frame activates first (creates research-brief.md in planning/research/)
- ❌ research-build does NOT activate before handoff

### Test C-1.B — research-frame wins on "deep dive on X"

**Given:** cold session
**When:** "deep dive on the EU AI Act timeline"
**Then:** research-frame activates first.

### Test C-1.C — research → build chain

**Given:** cold session
**When:** "research the EU AI Act timeline and write it up"
**Then:**
- Phase 1: research-frame → wiki-query → … → research-build
- research-build renders the markdown artifact after the chain completes
- Do NOT pre-empt research-build in Phase 1

### Test C-1.D — bypass-evaluator skip on factual

**Given:** cold session
**When:** "when was company X founded?"
**Then:** research-frame bypass-evaluator skips → factual lookup without a research-brief.

---

## Phase 0.5 — Pre-flight resolution

### Test K1 — Comparative-disguised-as-lookup

**Given:** user query = "tool A or tool B for our project"
**When:** research-frame Phase 0.5 Step 0.45 runs
**Then:**
- ✅ Match detected: K1 (Comparative-disguised-as-lookup)
- ✅ K3 also detected (Strategic — "for our project")
- ✅ Confidence adjustment: -0.30 (2 classes × -0.15)
- ✅ Routing (entity resolution clean): "Refine" → Frame mandatory + defaults

**Anti-test:** "tool A v0.42 release date" — should NOT match K1.

### Test K2 — Stateful-disguised-as-static

**Given:** "how much does the API cost"
**When:** Phase 0.5 Step 0.45 runs
**Then:**
- ✅ K2 match (pricing volatile)
- ✅ Confidence -0.15
- ✅ Phase 0.5 propagates the volatility flag to downstream Phase 1
- ✅ If bypass = OK → wiki-query inherits the flag → forces a fresh fetch

**Anti-test:** "what is the API" (concept) — should NOT match K2.

### Test K3 — Strategic-disguised-as-tactical

**Given:** "should we adopt MCP in production?"
**When:** Phase 0.5 Step 0.45 runs
**Then:**
- ✅ K3 + K4 match
- ✅ Confidence -0.30
- ✅ Routing: Refine, Frame mandatory; audience defaults to strategic-leadership

**Anti-test:** "is MCP supported in the API" — yes/no factual, no "should we" — should NOT match K3.

### Test K4 — Topic-explosive-disguised-as-narrow

**Given:** "hooks" (single noun)
**When:** Phase 0.5 Step 0.45 runs
**Then:**
- ✅ K4 match (topic-explosive)
- ✅ Step 0.5 entity resolution flags "hooks" as ambiguous
- ✅ Combined: K4 + unresolved entity = Clarify routing

**Anti-test:** "what are pre-commit hooks" — full context, may not match K4.

---

## Phase 0.5 — Entity resolution (Step 0.5)

### Test E1 — Known entity (no clarification)

**Given:** "tell me about tool X"
**When:** Step 0.5 runs
**Then:** "tool X" matched to a note in brain/; no penalty.

### Test E2 — Unknown handle (clarification needed)

**Given:** "research @some_handle's methodology for decks"
**When:** Step 0.5 runs
**Then:** "@some_handle" detected as a handle, not matched in brain/, unresolved entity flag → -0.10.

### Test E3 — Repo without org (auto-resolve)

**Given:** "research the patterns in some-repo"
**When:** Step 0.5 runs
**Then:** "some-repo" resolved to its org via context references; no penalty.

---

## Phase 0.5 — Confidence routing (Step 0.55)

### Test C1 — High confidence proceed

**Given:** "when did model X 4.6 ship"
**Then:** confidence = 1.0 + 0.10 (short query) = clamp 1.0 → ≥0.80 → Proceed; Phase 1 likely bypasses.

### Test C2 — Mid confidence proceed (boundary)

**Given:** "AI coding assistants 2026"
**Then:** confidence = 1.0 - 0.15 (K4) + 0.10 (short) = 0.95 → Proceed (just above 0.80).

### Test C3 — Low confidence clarify

**Given:** "research pricing" (incomplete)
**Then:** confidence = 1.0 - 0.15 (K2) - 0.10 (unresolved vendor) + 0.10 (short) - 0.20 (explicit "research" trigger) = 0.65 → Clarify routing → AskUserQuestion (single).

---

## Phase 2 — WDM source-selection

### Test W1 — Source shortlist generation

**Given:** brief with `sources_mode: hybrid`, `depth: standard`, 5 candidate sources identified
**When:** Phase 2 WDM source-selection runs
**Then:**
- ✅ 5 candidates scored across 5 criteria (Authority / Relevance / Accessibility / Recency / COI)
- ✅ Total weight = 18 confirmed
- ✅ Normalized scores 0-5 computed
- ✅ Top-N with norm ≥3.5 selected (standard depth threshold)
- ✅ Output saved in the brief frontmatter `wdm_source_shortlist:`
- ✅ Per-criterion rationale logged (not just numbers)

**Anti-test:** scoring without filled criteria = false rigor → halt with a warning.

---

## Test maintenance

- Update this file when there is a substantive change in Phase 0.5 / Phase 1 / Phase 2 / Phase 3
- Regression run: on the first 3-5 actual research sessions with Phase 0.5 — log mismatches between predicted vs actual routing → update scenarios
- Re-evaluate thresholds (0.6 / 0.8) if actual behavior consistently mis-classifies queries

## Sources

- [SKILL.md § Phase 0.5 + Phase 2 WDM](../SKILL.md)
- [references/bypass-heuristics.md § Phase 0.5 worked examples](../references/bypass-heuristics.md) — 3 worked examples
- [references/wdm-templates.md](../references/wdm-templates.md) — WDM templates spec
