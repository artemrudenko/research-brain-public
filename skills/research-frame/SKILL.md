---
name: research-frame
description: "GATEWAY — use FIRST on research-intent triggers ('research X' / 'investigate' / 'deep dive' / 'topic overview' / 'what do we know about X'). Owns these phrases; research-build does NOT pick them up. Bypass-evaluator skips factual lookups; everything else forwards to wiki-query."

metainfo:
  category: [research]
  type: gateway
  subagent_capability: plan
  last_updated: 2026-06-16
  predecessor: []
  successor: [wiki-query]
---

# Research Frame — Phase 1 (Frame) of the Research Lifecycle

**Purpose:** lock down the **input contract** for a research session before any searching starts. Without an explicit frame, research drifts — the Frame Questionnaire captures scope / depth / audience / freshness in one place and hands it to every downstream stage.

**Position in the research chain:** `research-frame → wiki-query → research-grep → research-build → research-audit (Verify) → research-build (Critique) → wiki-ingest (Archive)`. On bypass — forward directly to `wiki-query`.

---

## Invariant — clarify, don't invent intent (ALWAYS-ON)

**If the user's intent, scope, or the referenced entity/topic is ambiguous or under-specified, ask ONE targeted clarifying question BEFORE producing any research output. Never infer or invent the intended topic/entity/scope. Prefer one good clarifying question over a confident guess.**

This is unconditional — it holds regardless of the confidence score below. The confidence-scoring and bypass machinery (Phase 0.5 / Phase 1) is the *implementation* of this invariant, not a threshold that can override it: a confidently-misread query, or a short ambiguous one, must still trigger a single clarifying question rather than a guess. Ask exactly **one** question (never 2+) — a non-technical user must not be interrogated.

---

## When to Use

**Always:**
- Any research / knowledge-gathering request with triggers: "research", "investigate", "gather material on", "what do we have on", "deep dive", "discovery", "topic overview", "what do we know about"
- Comparison / analysis / decision-justification requests
- Requests with an explicit depth signal ("in detail", "thoroughly", "deeply")

**ESPECIALLY when:**
- Complex multi-faceted topic (several questions in one request)
- Strategic content for decision-makers
- Topic in an always-volatile domain (models, AI API pricing, regulation — strict defaults needed)

**Skip — Don't use for (bypass / forward directly):**
- Specific entity + attribute lookup ("which version of X", "when did Y ship", "who is CEO of Z")
- Yes/no factual questions without depth signals
- Resource existence / location ("is there", "where to find", "give me a link")
- Short queries (< 15 words) without research-trigger keywords
- An already-running `research-build` workflow / conversational meta-questions / an action request rather than a knowledge request / a pre-loaded raw file → `research-build`

**Don't skip when:**
- The request contains an explicit research keyword even if short
- Compliance / regulatory / safety implications
- Comparison / contrast request (needs cross-source verification)

"It's just a quick lookup"? If it contains a trigger — Frame is mandatory. Bypass only for obviously factual queries.

---

## DO / DON'T

**DO:**
- ✅ On ANY ambiguous intent / scope / entity → ask ONE targeted clarifying question BEFORE producing output (the always-on invariant above) — never infer or invent the topic
- ✅ Bypass-evaluator FIRST — BEFORE any AskUserQuestion (Phase 1)
- ✅ Phase 0.5 pre-flight resolution (keyword-trap + entity resolution + confidence) for ambiguous queries
- ✅ AskUserQuestion with the Frame questions in Phase 2 for non-bypass
- ✅ Auto-set `grading_mode: extended` if `audience: strategic-leadership`
- ✅ Always-volatile check before AskUserQuestion (recency_max default → 3mo for volatile keywords)
- ✅ Write `planning/research/{date}_{slug}.md` brief with all mandatory frontmatter fields
- ✅ Open the search-trail for the session (`planning/research/{date}_{slug}.search-trail.jsonl`, beside the brief) and pass its dir to `research-build` (CONVENTIONS §15b)
- ✅ Forward to `wiki-query` with the pre-loaded brief path in Phase 4

**DON'T:**
- ❌ Bypass (answer directly) when intent is unclear → Bypass ONLY when both the entity AND the attribute asked about are unambiguous; on any unresolved entity or vague scope, ask first
- ❌ Invent or guess the intended topic/entity/scope to avoid asking → a confident guess on an ambiguous query is the failure this invariant prevents
- ❌ Ask 2+ clarifying questions → one targeted question only; a non-technical user must not be interrogated
- ❌ AskUserQuestion for an obviously factual request → friction without value
- ❌ Skip Frame on research triggers because "it's all clear anyway" → research drift, rework
- ❌ Brief without `topic:` → non-conformant frontmatter
- ❌ Forward directly to `research-grep` bypassing `wiki-query` → breaks the chain
- ❌ Dispatch via subagent → Frame is UI-driven (AskUserQuestion), single-agent only

---

## Phase 0 — Environment & Rules Setup

**Step 1 (if present):** Read [`docs/research-workflow.md`]({{VAULT_ROOT}}/docs/research-workflow.md) when it exists (it is optional and may be absent on a de-branded / fresh install — then skip this step, it is not a halt). Its rules (local-knowledge-first, fetch fallback chain, web persistence, markdown-first artifact pattern, `last_updated` mandatory) apply to the whole downstream research chain.

**Step 2 — Load rules:** Read `rules/common.md` in this directory. It defines: triggers, bypass heuristics, default values for AskUserQuestion, output paths for the research brief, and integration points with downstream skills.

**Step 3 — Load detailed procedures (optional):** [`references/phases-detail.md`](references/phases-detail.md) (Phase 0.5 / 2 / 2.5 full procedures), [`references/bypass-heuristics.md`](references/bypass-heuristics.md) (extended bypass examples + edge cases), [`references/wdm-templates.md`](references/wdm-templates.md) (Weighted Decision Matrix).

Any instruction from `rules/common.md` overrides the corresponding step of this skill.

---

## Required Inputs

All optional — extracted automatically from the request text.

| Input | Type | Required | Default | Description |
|---|---|---|---|---|
| `USER_QUERY` | string | no | from request | The user's original request |
| `MODE` | enum: `auto` / `force-frame` / `force-bypass` | no | `auto` | `auto` = bypass-evaluator decides; `force-frame` = always full questionnaire; `force-bypass` = always forward directly |

---

## Workflow — 3 phases (+ Phase 0.5 pre-flight resolution)

### Phase 0.5 — Pre-flight resolution

Before the bypass-evaluator (Phase 1) — catch ambiguous / keyword-trapped queries that look like a factual lookup but carry research depth. 3 sub-steps:

- **Step 0.45 — Keyword-trap pre-check:** detect 4 trap classes (K1 comparative-disguised, K2 stateful-disguised, K3 strategic-disguised, K4 topic-explosive). Match → -0.15 confidence penalty per class.
- **Step 0.5 — Entity resolution:** detect handles / repos / communities / named tools; flag unresolved entities. -0.10 confidence penalty per unresolved.
- **Step 0.55 — Confidence scoring + clarification gate:** aggregate score → 3 routing decisions (≥0.8 Proceed / 0.6-0.8 Refine / <0.6 single Clarify question). Anti-pattern: ≥2 clarification questions — a single targeted clarification beats a multi-step one.

**Output of this phase informs the Phase 1 bypass decision.** Full procedure (trap-class table / entity patterns / confidence formula / routing thresholds / 3 worked examples): [`references/phases-detail.md`](references/phases-detail.md) § Phase 0.5.

### Phase 1 — Bypass-evaluator (FIRST step, transparent)

The query passes through a local bypass-evaluator before any AskUserQuestion. If the query is clearly factual, Frame self-bypasses and forwards directly to `wiki-query` without a UI trigger.

**Bypass triggers** (extended examples — [`references/bypass-heuristics.md`](references/bypass-heuristics.md)):

1. **Specific entity + attribute lookup** — "what license does X use", "latest version of Y", "when did Z ship", "who is CEO of Y"
2. **Resource existence / location** — "is there", "where to find", "give me a link to the Z docs"
3. **Yes/no factual questions** — "can you run hooks in this tool?"
4. **Short queries (< 15 words)** WITHOUT research trigger words

**Frame mandatory (do NOT skip)** for: research triggers; comparison / analysis / justification requests; requests with an explicit depth signal.

**Bypass gate (unconditional):** Bypass (answer directly) ONLY when **both the entity AND the attribute** asked about are unambiguous. On any unresolved entity or vague scope → do NOT bypass and do NOT guess; ask ONE targeted clarifying question first (per the always-on invariant). The confidence score is how this is operationalized, not a license to guess below threshold.

### Phase 2 — Frame Questionnaire (if not bypass)

AskUserQuestion with the Frame questions (multi-step UI flow): Depth (1) · Audience (2) · Format (3) · Sources (4) · Freshness (5) · Tiering (6) · Source modality (7) · Topic (8) · Focus (9). "Use defaults" = standard · hybrid · mixed · ≤12mo · T1+T2 · md (questions 2/8/9 are still asked).

- **Source modality** (Q7): `mixed` / `research-tier` / `social-pulse` / `regulatory`. Auto-adjusted on always-volatile keywords.
- **Always-volatile check (OPTIONAL source):** if `sources/always-volatile-domains.md` exists, keywords from it override defaults — recency_max → 3mo, sources_mode → hybrid, min_tier → T1. **If the file is absent → skip this check (a soft warning, not a halt)**; the standard recency defaults apply.
- **WDM source-selection** (optional for deep dive): Weighted Decision Matrix shortlist (≤8 standard, ≤15 deep) across 5 criteria.

Full procedure (question table / topic mapping / modality semantics / WDM template / always-volatile logic): [`references/phases-detail.md`](references/phases-detail.md) § Phase 2.

### Phase 2.5 — Topic-aware recency profile

Per-topic freshness windows instead of a generic `recency_max: 12mo` (6 mappings: security 6mo / ai-tools 12mo / agent-tooling 6mo / general-tech 24mo / standards 36mo / academic 48mo + 12mo fallback). Multi-topic — pick the tighter window; always-volatile keywords trump topic defaults. Full procedure: [`references/phases-detail.md`](references/phases-detail.md) § Phase 2.5.

### Phase 3 — Generate research-brief

After collecting all answers — auto-set `grading_mode`: `extended` if `audience == "strategic-leadership"`, otherwise `standard`. Manual override by editing the brief frontmatter.

Then Write `planning/research/{YYYY-MM-DD}_{slug}.md` (**create the `planning/research/` directory if it does not exist** — its absence is never a halt). Output skeleton + validator detail: see [assets/brief-template.md](assets/brief-template.md).

> **Note (auto path):** `research-frame` is the manual-entry gateway. The unattended `weekly-synthesis` loop does NOT run it — it calls `research-build` with `PROFILE=internal-corpus`, which does not require this brief (per `docs/CONVENTIONS.md` §10). The brief written here remains useful for manual deep-dives, but downstream skills must not REQUIRE it in internal-corpus mode.

**"Chat answer" downgrade rule:** if `format: chat-answer` (Q3) — downstream is downgraded: Verify light (only tier-check citations) · Critique optional · Format inline in chat · Archive only if it contains web fetches. Saves friction for moderately complex requests.

### Phase 4 — Forward to wiki-query

After the brief is created — hand off to `wiki-query` with pre-loaded context: brief path (`planning/research/{date}_{slug}.md`), key fields (`research_question`, `depth`, `recency_max`, `min_tier`), decision context. `wiki-query` reads the brief and applies recency/tier filters when scoring notes in `brain/`.

**Open the search-trail for the session (provenance, CONVENTIONS §15b).** The trail is the auditable-grounding companion of the verification-log — a durable JSONL record of *what was searched* across the whole session — and it must live BESIDE the brief, sharing its `{date}_{slug}` prefix: `planning/research/{date}_{slug}.search-trail.jsonl`. Pass its directory down to `research-build` so every later search self-records into the same file. Set it once, here, from the brief path:

```bash
# trail target = the brief's directory; all searches this session append to one file
export RESEARCH_TRAIL_DIR="$(dirname planning/research/{date}_{slug}.md)"
```

API-provider searches via `scripts/search/search.py` / `cross_check.py` then auto-append. The agent's OWN `claude-websearch` results don't flow through those scripts, so append them yourself with one line per search (`research-build` does this in Phase 2):

```bash
python3 -c "from scripts.search.search_trail import trail_path_for_brief, append_search_entry; \
import pathlib; t=trail_path_for_brief(pathlib.Path('planning/research/{date}_{slug}.md')); \
append_search_entry(t, query='<the query>', provider='claude-websearch', n_results=<N>, urls=['<url1>','<url2>'])"
```

If `RESEARCH_TRAIL_DIR` is unset the feature is OFF (nothing is written) and a trail-write failure is soft-skipped — it never aborts the search.

---

## Hard rules

- **Bypass-evaluator FIRST.** Never ask AskUserQuestion if the query is clearly factual.
- **Frame is NOT skipped on research triggers.** Even a short request with "research" / "overview" / "deep dive" → full questionnaire.
- **research-brief.md is ALWAYS created on non-bypass — in this (manual) gateway path.** Without a brief, downstream FULL-mode stages have no input contract. This does NOT apply to the unattended auto path: `weekly-synthesis` never invokes `research-frame` and `research-build PROFILE=internal-corpus` does not require a brief (per `docs/CONVENTIONS.md` §10). Create `planning/research/` if missing.
- **Always-volatile check** is run before AskUserQuestion when `sources/always-volatile-domains.md` exists (applies to defaults). The file is OPTIONAL: absence → skip the check (soft warning), use standard defaults.
- **Never auto-call wiki-query before the brief is written.** Forward only after Phase 3.
- **Never dispatch via subagent.** Frame is UI-driven and cannot be decoupled from the main session.

---

## Stop conditions

- The user explicitly said "no brief", "straight to wiki" → skip the skill.
- The user did not answer the questionnaire after two attempts → fall back to "Use defaults", then Phase 3.
- The bypass-evaluator is unsure (60-40 split) → present the Phase 2 questionnaire as a safety net.
- Pre-loaded research context (raw file + "make a guide") → that's `research-build`, not Frame.

---

## Success criteria

- ✅ Bypass heuristic applied BEFORE any AskUserQuestion
- ✅ If non-bypass: research-brief.md created at `planning/research/{date}_{slug}.md` with valid frontmatter (type: brief)
- ✅ wiki-query received the brief path in pre-loaded context
- ✅ Always-volatile check applied to defaults (if the topic is volatile)
- ✅ Time from request to brief written — < 90 seconds

---

## Example run

**Bypass case** — "what's the context window of the current model release?": Phase 1 detects specific entity + attribute + short query → bypass trigger #1; Phases 2-3 skipped; Phase 4 forward to `wiki-query` flagged "bypassed: factual lookup".

**Full Frame case** — "research how best to adopt SDLC AI tooling for a 200-person team": Phase 1 contains "research" → mandatory Frame; Phase 2 AskUserQuestion (user picks deep dive / internal-review / markdown / hybrid / ≤6mo / T1+T2 / mixed / `sdlc-dev`); Phase 3 writes `planning/research/2026-05-02_sdlc-ai-tooling.md`; Phase 4 forward to `wiki-query`.

---

## Integration with other skills

| Skill | When to hand off |
|---|---|
| `wiki-query` | Always after Phase 4 (or immediately on bypass) |
| `research-grep` | Never directly — only via wiki-query (Phase B fallback) |
| `research-build` | Never directly — only via the chain |
