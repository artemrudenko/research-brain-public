---
name: wiki-query-agent-contract
tools_required: [Read, Glob, Grep]
tools_forbidden: [Write, Edit, WebFetch, Bash]
permissions:
  - read: brain/, config/, planning/research/, docs/
  - write: (none — read-only skill)
  - no_write: brain/, pipeline/, archive/
limits:
  max_files_per_run: 5
  max_subagents: 0
---

# wiki-query — Agent Contract

Cross-platform agent contract for the `wiki-query` lookup skill (read-only by contract).

**Behaviour summary** (full spec → [`SKILL.md`](SKILL.md)):

- Step 0 — load `rules/common.md` + verify `brain/INDEX.md` (the MOC) exists
- Step A — topic pre-filter: narrow MOC candidates by topic; multi-topic disambiguation gate
- Step 1 — match: keyword search over the pre-filtered candidate set (or the full MOC if no filter)
- Step 1.5 — optional freshness note (`last_verified` + `ttl_days`; `last_updated` is edit-only) + always-volatile check
- Step 1.7 — category-peer expansion via `[[wikilinks]]`/backlinks: max 1 anchor + ≤2 peers = 3 concepts total
- Step 2 — read matched concept(s) (≤2 standard, ≤3 with peer expansion)
- Step 3 — answer (fresh match), report a vault-only miss, OR forward to
  `research-grep` (NO MATCH / stale / always-volatile when `VAULT_ONLY=false`)

**Tool constraints:**
- Read `brain/INDEX.md` (MOC) + ≤2-3 concept notes; follow `[[wikilinks]]` between them
- NEVER read the raw corpus (collected sources / prior outputs) — token-economy invariant
- NEVER write — that is `wiki-ingest`'s work
- When forwarded a research request, pass matched note paths, citations, confidence, freshness,
  and gaps into `research-grep`; local corpus search precedes any user-chosen external research
- AskUserQuestion when INTERACTIVE=true for the multi-topic ambiguity gate

**Compiled-knowledge-first:** the brain/ vault is the single source of truth, not the raw corpus. Discovery uses the hand-curated `brain/INDEX.md` MOC plus Obsidian `[[wikilinks]]` and file/tag search — no generated index, no knowledge-graph query.

**Subagent capability:** `explore` (read-only lookup, safe for parallel dispatch). In subagent context (INTERACTIVE=false) — emit a `multi_topic_ambiguity` flag instead of AskUserQuestion.

**Cross-tool portability:** works in any agent runtime exposing Read/Glob/Grep (broad compatibility).
