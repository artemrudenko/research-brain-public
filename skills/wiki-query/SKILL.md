---
name: wiki-query
description: "Vault-read lookup (Inventory step) over the EXISTING brain/concepts/ Obsidian vault — NOT external research. Runs AFTER research-frame forwards control, OR on direct vault queries: '/know <topic>', 'what does my brain know about X', 'что моя база знает о X', 'what concepts do we have on X', 'search the vault', 'look in brain', 'show notes about X', 'concepts on topic=X'. Reads brain/concepts/ via the brain/INDEX.md Map of Content; hit -> compiled answer. An explicit brain/vault query (incl. /know) is VAULT_ONLY and reports a miss without silently starting external research; a forwarded research query continues to research-grep. Does NOT pick up cold-start research-intent phrases ('research X', 'investigate', 'deep dive', 'what do we know about X') — those are owned by research-frame, which forwards here."

metainfo:
  category: [kb-management]
  tier: internal
  type: lookup
  domain: meta-process
  subagent_capability: explore
  last_updated: 2026-07-05
  predecessor: [research-frame]
  successor: [research-grep, research-build]
---

# wiki-query — the compiled vault as the first answer

On any research query the **first move** is to look in `brain/` — your Obsidian knowledge vault. Concept notes there are synthesized answers to recurring questions; reading them costs 5-10x fewer tokens than re-grepping the raw corpus (`pipeline/`, collected sources, prior research outputs).

**Lookup path (read-first, no generated indexes):**

`research-frame` (Frame Questionnaire or transparent bypass) → `wiki-query` (this skill)
→ if a concept covers the query and its evidence is adequate → answer; otherwise, for a
forwarded research request, → `research-grep` (inventory the local corpus) → if needed,
continue through the user-chosen research path → answer + offer `wiki-ingest` to compile
verified findings. A direct `VAULT_ONLY` invocation stops after the vault answer/miss unless
the user opts into that fallback.

Discovery inside the vault uses only Obsidian-native mechanisms:
- **`brain/INDEX.md`** — the hand-curated Map of Content (MOC). The single entry point: a curated table/outline of concepts grouped by topic cluster.
- **`[[wikilinks]]` / backlinks** — once you open a concept note, follow its `[[related-concept]]` links to surface adjacent notes.
- **File search / tags** — fall back to a filename or tag match in `brain/concepts/` when the MOC does not list a concept yet.

There is no generated index, no knowledge-graph query, no auto-built catalog — the MOC plus wikilinks are the index.

**Invariant — clarify, don't invent (ALWAYS-ON):** if a factual query is ambiguous (multiple possible topics/entities the user could mean), ask ONE disambiguation question before answering. Never invent which one the user meant. One targeted question only — do not interrogate.

---

## When to Use

**Handoff / vault-read only — NOT a cold-start first responder:** wiki-query queries the EXISTING vault; it does not start external research. Cold-start research-intent phrases ('research X', 'investigate', 'deep dive', 'what do we know about X', 'topic overview', 'discovery') are owned by `research-frame`, which forwards control here for the Inventory step. Do NOT pick those phrases up directly.

**Always:**
- After `research-frame` returns control for the Inventory step — the FIRST move on a forwarded research query (compiled-knowledge-first principle)
- Direct vault-read invocation: '/know <topic>' (the command alias), 'what does my brain
  know about X', 'что моя база знает о X', 'what concepts do we have on X', 'search the
  vault', 'run wiki-query', 'look in brain', 'what's in concepts about X', 'show notes
  about X'. These explicit brain/vault phrases set `VAULT_ONLY=true`.

**ESPECIALLY when:**
- Query carries an explicit `DOMAIN_FILTER` or `RESEARCH_BRIEF_PATH.topic` — the pre-filter is stricter, the candidate set cleaner
- A matched concept has sibling notes in the same MOC cluster — peer expansion surfaces adjacent concepts via `[[wikilinks]]`
- A concept's source verification is due or unknown, or the topic is volatile — keep the answer provisional and consider the research fallback

**Skip — don't use for:**
- 'what came out today / latest news' — web-only by nature
- Narrow factual questions ('what is X in one line') — answer directly from training
- Conversational meta-questions ('how do you like my approach') — not research
- An already-running `research-build` workflow — wiki-query was the first step, do not re-enter
- `brain/concepts/` is empty (fewer than 2 concepts — not enough of a base) or
  `brain/INDEX.md` is missing → decline ('vault not populated'); go to `research-grep`
  only when `VAULT_ONLY=false`

**Don't skip when:**
- `research-frame` forwarded control here — this is the mandatory inventory step before research-grep (token-economy invariant)
- Concept-level query, not fact-level — silently bypassing to research-grep skips the compiled-knowledge layer (5-10x tokens)
- Multi-topic ambiguity detected — a disambiguation gate is needed; skipping it produces wrong-topic answers

---

## DO / DON'T

**DO:**
- Use only `brain/INDEX.md` (MOC) + ≤2 concept notes (max 3 with peer expansion); never the raw corpus
- Treat freshness as a soft review signal: use `last_verified` with `ttl_days` when present; `last_updated` records editing, not source re-verification
- Include source attribution in the answer: `concepts/X.md § section; underlying source: <path or URL>`
- Forward to `research-grep` on STALE / NO MATCH / always-volatile topics only when
  `VAULT_ONLY=false` (with pre-loaded brain context + topic filter)
- On every handoff, carry forward the matched note paths, source URLs/dates/tiers, recorded
  confidence, freshness status, topic filter, and unresolved questions. Treat the notes as
  research context to verify, not as already-current evidence.
- On a `VAULT_ONLY=true` miss, say what was searched, report that the vault has no match,
  and offer external research as a separate next action
- Report confidence transparently (flag medium/low in the answer)
- Surface the concept's `Open questions / gaps` in the answer

**Vault answer**

```text
Vault answer
Answer: <1-5 bullets or a short paragraph from the matched concept notes only>
Source: `brain/concepts/<slug>.md` § <section>; underlying source: <url-or-path>
Confidence: <high|medium|low, copied from the concept when present; otherwise say not specified>
Gaps: <open questions/gaps from the concept, or "No explicit gaps recorded.">
```

Use this template for direct vault answers and research-chain inventory hits. It makes
the local note section and the underlying source visible without implying a fresh web
check.

**DON'T:**
- Open the raw corpus (`pipeline/`, collected sources, prior outputs) → that is `research-grep`'s job (scope violation, breaks token economy)
- Ignore the topic filter when the candidate set is non-empty → cross-topic noise
- Silently spread across topics → multi-topic ambiguity needs a disambiguation gate (AskUserQuestion when interactive) or a flag (subagent)
- Answer without source attribution → even a correct fact without attribution reads as a hallucination and breaks the trust chain
- Run when `brain/INDEX.md` is missing → halt; redirect to research-grep only when
  `VAULT_ONLY=false`
- Write to brain/ (Edit/Write on concepts) → this is a read-only skill; writing is `wiki-ingest`'s job
- Forward to research-grep without the topic filter → loses topic discipline downstream

---

## Phase 0 — Environment & Rules Setup

**Step 1 — Load rules:** Read `rules/common.md` (paths, optional staleness note, always-volatile lazy-load, topic filter logic).

**Step 2 — Verify vault initialization:** if `brain/INDEX.md` is not found → halt with
'Knowledge vault not initialized — no brain/INDEX.md MOC found'. Forward to
`research-grep` only when `VAULT_ONLY=false`; otherwise offer research.

**Step 3 — Load detailed procedures (optional):** [`references/phases-detail.md`](references/phases-detail.md) — topic pre-filter (with multi-topic gate), optional staleness check, category-peer expansion via backlinks.

Any instruction in `rules/common.md` overrides the corresponding step here.

---

## Required Inputs

| Input | Type | Required | Default | Description |
|---|---|---|---|---|
| `USER_QUERY` | string | no | from request | The original query (keywords for the Match step) |
| `RESEARCH_BRIEF_PATH` | path | no | None | If upstream was `research-frame` — path to the brief; used to read its `topic:` for the pre-filter |
| `DOMAIN_FILTER` | string | no | None | Explicit topic/domain restriction ('concepts on topic=security') — overrides brief.topic; forwarded under the same name to `research-grep` on NO MATCH |
| `INTERACTIVE` | bool | no | `true` | Controls AskUserQuestion gates (multi-topic disambiguation) — false for subagent mode |
| `VAULT_ONLY` | bool | no | auto | `true` for explicit brain/vault queries; reports only stored knowledge and never silently broadens into corpus/web research |

---

## Workflow — 3 steps (+ optional pre-filter / staleness / peer expansion)

### Step A — Topic pre-filter (optional)

Narrows the candidate set BEFORE keyword matching. Resolve topic (`DOMAIN_FILTER` → brief.topic → no filter) → pre-filter the `brain/INDEX.md` MOC entries to those tagged with the target topic → after match, run the multi-topic disambiguation gate (fires when ≥2 topics are matched AND the secondary cluster is substantial) → empty candidate set: `NO MATCH (topic-constrained)`, do not silently degrade to other topics. Full procedure: [`references/phases-detail.md`](references/phases-detail.md) § Topic pre-filter.

### Step 1 — Match

Extract keywords (1-5 terms) → read `brain/INDEX.md` (MOC) → apply the topic candidate set (topic AND keyword) → match against the MOC's query guide / topic tags / concept map. Result: `MATCH high` (keyword in the guide or ≥2 hits) / `MATCH partial` / `NO MATCH` (or `NO MATCH (topic-constrained)` when the pre-filtered set is empty). If the MOC does not list a likely concept, a filename/tag search in `brain/concepts/` is an acceptable fallback before declaring NO MATCH.

### Step 1.7 — Category-peer expansion (via backlinks)

Only on `MATCH high` / `MATCH partial`: surface up to 2 sibling concepts from the same MOC cluster, found through the matched note's `[[wikilinks]]`/backlinks; limit 1 anchor + ≤2 peers (max 3 concepts). Full procedure: [`references/phases-detail.md`](references/phases-detail.md) § Category-peer expansion.

### Step 1.5 — Freshness check (optional)

Only on `MATCH high` / partial, and only as a soft note: use `last_verified` + `ttl_days` when available. Without a TTL, freshness is unassessed; `last_updated` is an edit date and does not prove that sources were re-checked. If verification is due, unknown, or unassessed, mention that limit; in a forwarded research request, continue to `research-grep` with the concept as context. Always-volatile topics (see `rules/common.md`) → recommend current-source research regardless of recorded verification date. Detail: [`references/phases-detail.md`](references/phases-detail.md) § Freshness check.

### Step 2 — Read

- **MATCH high:** read the matched concept note in full (+ 1 clearly relevant note via its `[[wikilinks]]`, max 2 total; ≤3 with peer expansion).
- **MATCH partial:** if this is a forwarded research request (`VAULT_ONLY=false`), hand the concept and its gaps to `research-grep`; its local inventory and existing choice gate decide whether to stop or continue. For a direct vault-only lookup, ask whether the partial answer is enough or the user wants research.
- **NO MATCH, `VAULT_ONLY=true`:** report "not in the vault" with the keywords/topic
  checked; offer to research it, but do not start `research-grep` automatically.
  Do not start research-grep, web search, or raw-corpus inventory for VAULT_ONLY=true.

  **Vault-only miss**

  ```text
  Vault-only miss
  I checked `brain/INDEX.md` and `brain/concepts/` for: <query>
  No matching concept exists in the local vault.
  I can research this separately if you want.
  ```

  Use the checked keywords/topic in `<query>` when available, including any explicit
  `DOMAIN_FILTER` or topic-constrained match context.
- **NO MATCH, `VAULT_ONLY=false`:** hand control to `research-grep` ('not in the vault,
  switching to the raw corpus'); after research, offer `wiki-ingest`.

### Step 3 — Answer or Forward

- **Answer (after MATCH):** compose the answer from the concept(s); **mandatory** source attribution 'Source: `concepts/X.md` § section; underlying source: <path or URL>'; state `Confidence:`; surface gaps; ask 'enough / dig deeper'.
- **Forward (after NO MATCH, an uncovered partial match, or review-due/unknown/unassessed freshness,
  only when `VAULT_ONLY=false` or the user explicitly opts in):** hand control to
  `research-grep` with the pre-loaded brain context + the `DOMAIN_FILTER` if set
  (`research-grep` validates it against `config/topics.yaml`). Search the local corpus
  before proposing external research. Carry the concepts' source references, confidence,
  freshness, and gaps into the next step; do not repeat settled research without a reason.

---

## Hard rules

- **Read-only.** wiki-query NEVER writes to brain/ (that is `wiki-ingest`'s work). No Edit / Write on concepts.
- **Token-economy invariant.** Use only `brain/INDEX.md` (MOC) + ≤2 concepts (≤3 with peer expansion). Reading the raw corpus is a scope violation.
- **Source attribution mandatory.** Every answer includes `concepts/X.md § section` + the underlying source. Without it the trust chain breaks.
- **Topic filter respect.** When `DOMAIN_FILTER` is set and the candidate set is empty → `NO MATCH (topic-constrained)`, NOT a silent degrade to an unfiltered search.
- **Freshness is a review signal.** `last_verified` + `ttl_days` indicate when a source review is due; without a TTL freshness is unassessed, and `last_updated` alone is not re-verification. Unknown freshness stays unknown, not presumed stale or false.
- **Always-volatile recommend.** Topics listed in `rules/common.md` as always-volatile → recommend current-source research regardless of recorded verification date.
- **Vault-only boundary.** An explicit brain/vault query never triggers corpus or web
  research without a separate user opt-in.
- Do not start research-grep, web search, or raw-corpus inventory for VAULT_ONLY=true.
- **Confidence transparency.** A concept marked `Confidence: medium`/`low` → say so explicitly; never present medium-confidence as a sure fact.

---

## Stop conditions

- Direct brain/vault phrases (`what does my brain know about X`, `search the vault`,
  `look in brain`, `show notes about X`, `concepts on topic=X`, or equivalent local
  knowledge wording) infer `VAULT_ONLY=true`; a miss under this mode reports the checked
  keywords/topic and offers research as a separate next action only.
- `brain/INDEX.md` not found → halt; `VAULT_ONLY=true` reports the empty state and
  offers research, otherwise forward to `research-grep`
- No concept covers the query → `VAULT_ONLY=true` reports the miss and offers research,
  otherwise forward to `research-grep`
- Query is clearly NOT research-intent (factual lookup ≤3 facts) → bypass → answer inline without the vault
- Subagent mode (INTERACTIVE=false) needs an AskUserQuestion → halt with the recommendation in the report

---

## Success criteria

- Topic pre-filter: if a brief/`DOMAIN_FILTER` is set — the candidate set is pre-filtered to concepts with the matching topic; multi-topic ambiguity is surfaced (AskUserQuestion or flag)
- Match: only `brain/INDEX.md` (MOC) + ≤2 concepts opened; the raw corpus is NOT opened (token-economy invariant)
- Freshness: handled as a soft note from `last_verified` / `ttl_days` when available; `last_updated` is not treated as re-verification; always-volatile check applied
- Answer: a fresh match yields an answer from the vault with explicit source attribution; confidence transparency; topic filter mentioned if applied
- Forward: on STALE / NO MATCH with `VAULT_ONLY=false` → control handed to
  `research-grep` with brain context + topic filter if set
- Vault-only miss: no corpus/web read; the user receives an honest miss plus an offer
- No raw corpus read — the skill finished without opening collected sources or prior outputs

---

## Integration with other skills

| Skill | When |
|---|---|
| `research-frame` | Predecessor — Frame Questionnaire (a Topic question → `topic:` in the brief, read by the pre-filter) |
| `wiki-ingest` | The write-side pair (populates brain/) — offer after a NO MATCH research run |
| `research-grep` | Fallback on NO MATCH / stale-with-supplement when `VAULT_ONLY=false` or after explicit user opt-in (with the topic filter if applicable) |
