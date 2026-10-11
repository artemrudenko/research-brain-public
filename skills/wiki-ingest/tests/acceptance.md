---
title: "Acceptance tests — wiki-ingest"
type: acceptance-test
domain: knowledge-management
status: active
created: 2026-05-03
last_updated: 2026-06-15
topic_tags: [acceptance, test, skill, wiki-ingest, brain-management]
related_skill: skills/wiki-ingest/SKILL.md
generated_by: ai-then-human-edited
---

# Acceptance tests — wiki-ingest

> Living spec for the ingest step of the research lifecycle (writes into the Obsidian vault under `brain/`). Covers 4 decisions (UPDATE/CREATE/BACKLOG/IGNORE), the source-link hard rule, the bidirectional lesson↔concept link, and failure modes.

## Scope

- **Skill:** `wiki-ingest`
- **SKILL.md:** [`../SKILL.md`](../SKILL.md)
- **Position:** final (ingest) step of the research lifecycle — writes to the vault
- **Coverage:** 7 scenarios — 1 happy path + 4 edge cases + 1 failure mode + 1 automatic (unattended) mode

---

## Scenarios

### Scenario 1: Happy path — CREATE new concept

**Given:**
- research-build finished: draft md in `pipeline/3-synthesis/some-topic.md` covering ≥3 distinct topics
- research-audit passed (gate_status: passed)
- Critique pass complete
- The vault has no concept for this topic
- The Backlog in `brain/INDEX.md` shows ≥3 mentions of this topic in the last 4 weeks

**When:**
- User: "update the vault" or auto-handoff after Format

**Then:**
- Phase 1 diff: artifact vs brain/concepts/ → no match found
- Phase 2 AskUserQuestion: "Create concept `some-topic.md` in `brain/concepts/`?" → user confirms CREATE
- Phase 3 Apply:
  - New file `brain/concepts/some-topic.md` created
  - Frontmatter: `type: concept`, `ttl_days`, `last_verified: today`, `sources: [{url, pipeline/0-archive/...}]`
  - Double link for every web source (URL + pipeline/0-archive path)
  - At least one `[[wikilink]]` to a related note (so it is not an orphan)
- Phase 4 Sync: `brain/INDEX.md` MOC updated by hand, mention removed from Backlog (consumed)

**Acceptance signal:**
- `brain/concepts/some-topic.md` exists with frontmatter `type: concept`
- `grep "sources:" brain/concepts/some-topic.md` → ≥1 source with a double link
- `brain/INDEX.md` has a new MOC row for this concept

---

### Scenario 2: Edge case — UPDATE existing concept (merge)

**Given:**
- The vault already contains `brain/concepts/some-topic.md` (created 60 days ago, last_verified: 60 days ago)
- New artifact contains 2 fresh facts not yet in the concept

**When:**
- wiki-ingest Phase 1 diff finds a match (existing concept)

**Then:**
- AskUserQuestion: "Existing concept matches. UPDATE with merge / CREATE separate / SKIP?" → user confirms UPDATE
- Phase 3 Apply: Edit the existing concept file:
  - 2 new facts added in the appropriate section
  - `sources` array extends with 2 new entries (double link)
  - `last_verified: today`, `last_updated: today`
- Phase 4 Sync: `brain/INDEX.md` MOC row remains, `last_updated` field updated

**Acceptance signal:**
- The existing concept file has updated `last_verified: <today>`
- `grep -c "^- " brain/concepts/some-topic.md` (sources count) increased by 2

---

### Scenario 3: Edge case — BACKLOG (mention < 3, not CREATE)

**Given:**
- Artifact mentions topic "X" for the first time
- The Backlog in `brain/INDEX.md` has no entry for X
- The theme appears once, no other artifacts reference X

**When:**
- wiki-ingest Phase 1 evaluation against the BACKLOG threshold

**Then:**
- Decision: BACKLOG (per the "≥3 mentions" rule)
- New entry added to `brain/INDEX.md` Backlog section: "X — mentioned 2026-05-03 in some-topic.md"
- NO concept file created (insufficient material yet)
- AskUserQuestion NOT fired (BACKLOG = automatic decision, no user input needed)

**Acceptance signal:**
- `grep "X — mentioned 2026-05-03"` in brain/INDEX.md → 1 match
- No file at `brain/concepts/x.md`

---

### Scenario 4: Edge case — IGNORE (an existing artifact already covers it 1:1)

**Given:**
- Artifact contains the fact: "Tool Pro = $20/mo"
- The guide `pipeline/3-synthesis/tool-comparison.md` already contains this exact fact with a link

**When:**
- wiki-ingest Phase 1 evaluation

**Then:**
- Decision: IGNORE (an existing artifact already covers it 1:1)
- The vault is not modified in any way
- `brain/INDEX.md` Backlog optionally gets a note: "X covered by pipeline/3-synthesis/tool-comparison.md (link)"

**Acceptance signal:**
- No file changes in `brain/concepts/` or `brain/lessons/`
- If a note is added — `grep "covered by pipeline/3-synthesis/"` in brain/INDEX.md → ≥1 match

---

### Scenario 5: Edge case — bidirectional lesson↔concept link

**Given:**
- `brain/lessons/2026-05-03_some-fact.md` exists
- While processing the artifact, related knowledge is found for an existing `brain/concepts/some-topic.md`
- The lesson holds a specific fact that is now integrated into the concept

**When:**
- Phase 3 Apply: UPDATE the concept

**Then:**
- The concept's `Sources` section gets a back-reference to the lesson: `- brain/lessons/2026-05-03_some-fact.md`
- The lesson's `integrated_into` frontmatter field: `concept: brain/concepts/some-topic.md`
- The lesson moves to RETIRE_LESSON status: kept as an archive trail, but `status: integrated`
- The bidirectional link connects them in the Obsidian graph view

**Acceptance signal:**
- The lesson frontmatter has an `integrated_into:` field
- The concept's Sources section contains a link to the lesson
- `grep "status: integrated"` in the lesson → 1 match

---

### Scenario 6: Failure mode — source without a URL (source-link mandatory violation)

**Given:**
- Artifact contains a claim "In our experience, X yields Y" with no attributable source
- User asks: "update the vault with this fact"

**When:**
- wiki-ingest Phase 2 AskUserQuestion CREATE

**Then:**
- AskUserQuestion: "A source-link is mandatory. Provide a URL OR mark `unsourced: true` (the concept will be flagged low-confidence) OR cancel?"
- If the user cancels → no changes, abort
- If the user provides a URL → source-archive runs → concept created with a double link
- If the user marks `unsourced: true` → concept created with frontmatter flags `confidence: low` AND `unsourced: true` (rare; for internal lessons)

**Acceptance signal:**
- On cancel: no file changes
- On URL provided: `grep "pipeline/0-archive/" brain/concepts/X.md` → 1 match (double link)
- On unsourced: `grep "unsourced: true"` in the concept → 1 match AND `confidence: low`

---

### Scenario 7: Automatic (unattended) mode — scheduled weekly-synthesis, no human present

**Given:**
- The scheduled `weekly-synthesis` run invokes wiki-ingest with `INTERACTIVE=false`
- research-build produced a finalized artifact in `pipeline/3-synthesis/` (closure signal present)
- The artifact contains ≥3 fresh facts for a topic with no existing concept
- Every fact carries a source-link (URL + `pipeline/0-archive/...`) and a provenance tag

**When:**
- wiki-ingest runs Phase 1 (diff) → CREATE verdict, then Phase 2 in automatic mode

**Then:**
- NO AskUserQuestion is fired (no human present)
- Phase 2 applies the recommended-default verdict (CREATE) per the same decision rules
- Phase 3 writes `brain/concepts/{slug}.md` with mandatory source-link + provenance + ≥1 crosslink
- ORPHAN_RISK_HOLD, if it arose, auto-resolved (assigned `related_concept:` by best match, else BACKLOG) — never silently orphaned
- All hard rules enforced: a missing source-link / provenance / crosslink or all-🔴 confidence would have halted-and-logged instead of writing

**Acceptance signal:**
- The concept file exists with a double link (`grep "pipeline/0-archive/" brain/concepts/{slug}.md` → ≥1) and ≥1 `[[wikilink]]`
- No prompt was surfaced during the run (automatic mode)
- On an injected hard-rule violation (e.g. an unsourced fact): no write, a halt/log entry is produced

---

### Scenario 8: Anti-sprawl — dedup search downgrades CREATE to UPDATE

**Given:**
- The vault already contains `brain/concepts/multi-agent-orchestration.md` (`tags: [ai-agents, orchestration]`)
- The artifact would otherwise CREATE a new concept titled "AI agent orchestration" (`tags: [ai-agents, orchestration]`)

**When:**
- wiki-ingest Phase 1.6 dedup search runs before the CREATE: normalized titles
  (`multi agent orchestration` vs `ai agent orchestration`) share `agent`/`orchestration`,
  and the two notes share ≥1 tag

**Then:**
- The verdict is downgraded from CREATE to UPDATE of `multi-agent-orchestration.md`
- No near-duplicate `brain/concepts/ai-agent-orchestration.md` is created
- The existing concept is stamped `last_updated: today` (and `last_verified: today` if re-confirmed)

**Acceptance signal:**
- No file at `brain/concepts/ai-agent-orchestration.md`
- `brain/concepts/multi-agent-orchestration.md` has a new Change-history row

---

### Scenario 9: Anti-sprawl — ambiguous match CREATEs but logs a possible-duplicate line

**Given:**
- A CREATE candidate whose normalized title shares some tokens with an existing concept but
  shares **no** tags (ambiguous — not a clear match)

**When:**
- Phase 1.6 dedup search runs

**Then:**
- The verdict stays CREATE (ambiguity does not block the run)
- A line `possible duplicate of [[<closest-existing-concept>]]` is written into the
  synthesis-run log (`pipeline/3-synthesis/synthesis-run_*.md`) for later manual merge

**Acceptance signal:**
- The new concept file is created
- `grep "possible duplicate of" pipeline/3-synthesis/synthesis-run_*.md` → ≥1 match

---

## Cross-references

- **SKILL.md:** [`../SKILL.md`](../SKILL.md)
- **Rules:** [`../rules/common.md`](../rules/common.md) (paths, naming conventions, confidence levels, domain tags)
- **Enforcement detail:** [`../references/ingest-rules.md`](../references/ingest-rules.md)
- **Related skills:**
  - `research-build` (predecessor — produces a draft with claims)
  - `wiki-query` (downstream consumer — reads concepts during research)

## Maintenance

- **Update triggers:** changed BACKLOG threshold (currently "≥3 mentions"), a new decision option (currently 4: UPDATE/CREATE/BACKLOG/IGNORE), a source-link policy change, a change to the interactive/automatic mode switch (`INTERACTIVE`), a change to the Phase 1.6 dedup heuristic (normalized title + tag overlap) or the TTL `last_verified` discipline
- **Known coverage gaps:** mass ingest from a large artifact (>10 new concepts) — add a scenario when first encountered; concept split (>300 lines → split into playbooks/) — edge case
