---
title: "Acceptance tests — research-build"
type: acceptance-test
status: active
created: 2026-05-03
last_updated: 2026-06-15
topic_tags: [acceptance, test, skill, research-build, gather, synthesize, critique]
related_skill: skills/research-build/SKILL.md
---

# Acceptance tests — research-build

> Living spec for the Gather + Synthesize + Critique phases of the research lifecycle. Covers the pre-loaded context flow, subagent dispatch, and the Critique pass.

## Scope

- **Skill:** `research-build`
- **SKILL.md:** [`../SKILL.md`](../SKILL.md)
- **Position:** Gather + Synthesize (Phases 3–4) + Critique pass (Phase 6.5)
- **Coverage:** 6 scenarios — 1 happy path + 4 edge cases + 1 failure mode

---

## Scenarios

### Scenario 1: Happy path — pre-loaded context from research-grep

**Given:**
- A brief `pipeline/3-synthesis/topic/2026-05-15_topic.brief.md` created by research-frame
- wiki-query done: 2 concepts in `brain/concepts/` matched (≥0.7 fresh)
- research-grep done: 4 files found in `pipeline/` + `brain/`
- The pre-loaded context is passed into the research-build handoff

**When:**
- research-build is activated with inputs: brief path + pre-loaded summary

**Then:**
- Phase 0–2 (Gather) — fetch done via `source-archive` for additional T1/T2 sources; minimum 5 sources total
- Phase 3–4 (Synthesize) — the draft md is created in `pipeline/3-synthesis/{topic}/{slug}.md` per output-routing.md
- Frontmatter contains `materials_used: [...]`, `last_updated: today` (the fields the skill actually writes — there is no canonical draft `type` defined in SKILL.md / output-routing.md, so do not assert one)
- Phase 6.5 (Critique pass) — red-team / critical-hat applied
- Handoff to research-audit (auto-trigger when `format != chat-answer`)

**Acceptance signal:**
- The draft md is created in the expected `pipeline/3-synthesis/` location per output-routing
- `materials_used` array ≥5 elements
- Brief lifecycle checkboxes `[x] **Gather**` + `[x] **Synthesize**` + `[x] **Critique**` marked

---

### Scenario 2: Edge case — pre-loaded context empty (no local matches)

**Given:**
- The brief exists
- wiki-query: NO MATCH in `brain/concepts/`
- research-grep: 0 files found in `pipeline/` + `brain/`
- The pre-loaded summary indicates "empty inventory"

**When:**
- research-build is activated

**Then:**
- Phase 0–2 continues in web-from-scratch mode (if `sources_mode != internal-only`)
- If `sources_mode = internal-only` AND the inventory is empty → AskUserQuestion: "Internal corpus empty for this topic. Fall back to hybrid mode?"
- On confirmation — continues with web fetches; otherwise — aborts with a notice
- The draft is created with an explicit mention in the notes section: "Inventory empty, full web-from-scratch synthesis"

**Acceptance signal:**
- Draft created OR abort notice issued
- On abort: brief lifecycle checkbox `[ ] **Gather**` (unchecked, so a re-attempt is possible)

---

### Scenario 3: Edge case — reader fan-out trigger (extract, don't dump)

**Given:**
- A build with **≥5 synthesis-bound sources** (any `depth` — the trigger is the source count, not `depth: deep`; per [`../references/reader-contract.md`](../references/reader-contract.md))

**When:**
- Phase 2 Collect runs over those sources

**Then:**
- Reader subagents dispatched in **one Agent message with multiple subagent calls** — one per article (5–~12 sources), or per cluster of 2–4 when >~12
- Each subagent returns a **compact structured extract** (`source_meta` / `key_claims` / verbatim `quotes` / `data_points` / `contradicts` / `dedup_key` / `raw_path`) and writes its verbatim body to `pipeline/3-synthesis/{topic}/raw/{n}_{host}.md` — it does **NOT** return a prose body or a "mini-synthesis", and the **main agent never loads a full article body into its context**
- Phase 2b `raw_{date}.md` is assembled as an **index of fragment paths + extracts**, not by re-reading the bodies
- Synthesis (Phase 3) runs in the main agent on the bounded extract set
- Audit trail in the notes: "Reader fan-out: N subagents, X sources, 0 bodies loaded into main context"

**Acceptance signal:**
- `grep "Reader fan-out:"` in the notes section → 1 match
- `materials_used` references every dispatched source/cluster
- No full article body text appears in the synthesised draft outside the `quotes` carried in the extracts (extract-only boundary held)

---

### Scenario 4: Edge case — JSON-twin emitted

**Given:**
- A brief with `emit_json_twin: true`, `audience: leadership`

**When:**
- research-build finishes the Synthesize phase

**Then:**
- The draft md is created **first**
- Handoff to research-audit (with extended grading mode auto-set)
- After the research-audit pass + Critique pass → a `{slug}.json` twin is written alongside the md
- The JSON-twin references the same sources and claims as the md (referential integrity)

**Acceptance signal:**
- Both `pipeline/3-synthesis/{topic}/{slug}.md` AND `{slug}.json` exist
- Every `claims[*].sources[*]` ID resolves to a `sources[*].id` entry

---

### Scenario 5: Edge case — Critique pass surfaces a counter-argument

**Given:**
- A draft md with 4 main thesis statements
- research-audit passed (gate_status: passed)

**When:**
- Phase 6.5 Critique pass: red-team applies the critical hat

**Then:**
- 1–2 thesis statements get a counter-argument addendum in the draft md
- The notes section contains "Critique pass: 2 counter-arguments added (red-team)"
- A `critique-log` file is written

**Acceptance signal:**
- `grep -c "Counter-argument"` in the draft md → ≥1
- Brief lifecycle `[x] **Critique**` marked

---

### Scenario 6: Failure mode — no research-brief, fail-fast

**Given:**
- User: "Run research-build on X"
- No brief in `pipeline/3-synthesis/{topic}/`

**When:**
- research-build Phase 0 input validation

**Then:**
- The skill fails fast with the instruction: "research-build cannot run without a brief — there is no input contract (recency_max, min_tier, audience). Run `research-frame` for a retroactive brief or pass BRIEF_PATH explicitly."
- No files created (no draft, no raw-materials modifications)
- AskUserQuestion is NOT fired (fail-fast = explicit abort, no silent recovery)

**Acceptance signal:**
- No file changes in `pipeline/3-synthesis/`
- Chat output contains "research-frame for a retroactive brief"

---

## Cross-references

- **SKILL.md:** [`../SKILL.md`](../SKILL.md)
- **References:**
  - [`../references/raw-template.md`](../references/raw-template.md) — Phase 2b raw materials template
  - [`../references/output-routing.md`](../references/output-routing.md) — output location
- **Related skills:**
  - `research-frame` (predecessor — creates the brief)
  - `wiki-query`, `research-grep` (inventory predecessors)
  - `source-archive` (web persistence)
  - `research-audit` (next phase)
  - `wiki-ingest` (downstream Archive)

## Maintenance

- **Update triggers:** new format added to the brief, subagent dispatch refinement, a new output location in output-routing.
