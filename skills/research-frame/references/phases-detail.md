---
title: "Research-Frame — Workflow Phases Detail"
type: reference
created: 2026-06-15
last_updated: 2026-06-15
applies_when: "Phase 0.5 pre-flight resolution (3 sub-steps) + Phase 2 questionnaire schema + Phase 2.5 topic-aware recency profile"
---

# Workflow Phases Detail

> SKILL.md contains the summary; the complete detail is here.

---

## Phase 0.5 — Pre-flight resolution

> **Goal:** before the bypass-evaluator (Phase 1) — catch ambiguous / keyword-trapped queries that look like a factual lookup but carry research depth. 3 sub-steps: keyword-trap pre-check (0.45) → entity resolution (0.5) → confidence scoring + clarification gate (0.55). The output of this phase informs the Phase 1 bypass decision.

### Step 0.45 — Keyword-trap pre-check

Detect 4 classes of "keyword traps" — query patterns that look simple on the surface but carry hidden depth:

| Class | Pattern | Trap signal | Example |
|---|---|---|---|
| **K1 Comparative-disguised-as-lookup** | "X versus Y" / "X or Y" / "X compared to Y" in a short query | Surface looks Y/N but requires multi-source compare | "tool A or tool B", "X vs Y" |
| **K2 Stateful-disguised-as-static** | Mentions stat / version / price / quota / SLA / availability | Likely volatile (TTL <90 days), needs a recency check | "API price", "enterprise tier" |
| **K3 Strategic-disguised-as-tactical** | Asks a specific decision ("should we adopt X?") | Lookup form but requires context, ROI, alternatives | "should we use tool X in production?" |
| **K4 Topic-explosive-disguised-as-narrow** | Single-noun query touching a big domain ("multi-agent", "MCP", "hooks") | One word can spawn 10+ sub-questions | "multi-agent", "SDK hooks", "MCP" |

**Action on match:** flag the query as "keyword-trapped" — the bypass-evaluator (Phase 1) immediately downgrades to Frame mandatory regardless of length. Confidence score (Step 0.55) penalty: -0.15 per matched class.

**See acceptance test:** `tests/acceptance.md` § "Keyword-trap classes K1-K4".

### Step 0.5 — Entity resolution

Detect named entities in the query and resolve perceived ambiguity:

| Entity type | Pattern | Resolution |
|---|---|---|
| **Handles** | `@user` or `user/repo` or upper-case CamelCase before nouns | Identify as repo / org / person; if unknown → flag for clarification |
| **Repos** | mentioned repo without org prefix | Try to qualify the org from context; if ambiguous → flag |
| **Communities** | `r/{name}` / `discord.gg/{name}` / known forum names | Identify the channel; clarify topic-channel match |
| **Named tools** | Mentioned product name | Match against `brain/` — if a known tool, no clarification; if new, flag |

**Action on ambiguity (≥1 unresolved entity):** flag for the Phase 0.55 clarification gate. Confidence score penalty: -0.10 per unresolved entity.

### Step 0.55 — Confidence scoring + clarification gate

Aggregate confidence score:

```
base_confidence = 1.0  # start at full confidence

apply Step 0.45 penalties: -0.15 per matched keyword-trap class (max -0.60)
apply Step 0.5 penalties: -0.10 per unresolved entity (max -0.40)
apply other heuristics:
  - query <15 words: +0.10 boost (likely factual lookup)
  - query has an explicit research trigger word: -0.20 (treat as research-mandatory regardless)

final_confidence = clamp(base_confidence + adjustments, 0.0, 1.0)
```

**3 routing decisions:**

| Final confidence | Action | Behavior |
|---|---|---|
| **≥ 0.8** | Proceed | Forward to Phase 1 (bypass-evaluator) with current routing |
| **0.6 - 0.8** | Refine | Use defaults (no clarification, but Frame mandatory regardless of bypass) |
| **< 0.6** | Clarify | AskUserQuestion ONE clarification question before Phase 1; e.g., "Just to clarify — is this {factual lookup ABOUT_X} or {strategic comparison X_vs_Y}?". **Maximum 1 clarification** — then proceed regardless. |

**Anti-pattern:** do not ask ≥2 clarification questions — it scatters focus. A single targeted clarification beats a multi-step questionnaire.

**3 worked examples:** see [`bypass-heuristics.md`](bypass-heuristics.md) § "Phase 0.5 worked examples".

---

## Phase 2 — Frame Questionnaire Detail

AskUserQuestion with 9 questions (multi-step UI flow):

| # | Question (header / max 12 chars) | Options | Default (single-key shortcut) |
|---|---|---|---|
| 1 | **Depth** | quick scan (1-2h, 3-5 sources) · standard (half-day, 8-12) · deep dive (a day+, 15+) | standard |
| 2 | **Audience** | internal review · external deliverable · strategic / leadership | internal review |
| 3 | **Output format** | chat answer · research-build (md) | research-build (md) |
| 4 | **Sources** | internal only (wiki+materials) · hybrid (internal + web mandatory) · web from scratch | hybrid |
| 5 | **Freshness** | ≤3mo · ≤6mo · ≤12mo · ≤24mo · no limit | ≤12mo |
| 6 | **Tiering** | T1 only · T1+T2 · T1+T2+T3 | T1+T2 |
| 7 | **Source modality** | mixed · research-tier · social-pulse · regulatory | mixed (auto-adjusted, see below) |
| 8 | **Topic** | one tag from `config/topics.yaml` | (auto-suggested, see below) |
| 9 | **Focus** | free field — the research question in one sentence | (input required) |

**"Use defaults" option** — one button = standard depth · hybrid sources · mixed modality · ≤12mo · T1+T2 · research-build md (questions 1, 3, 4, 5, 6, 7 → defaults; questions 2 audience, 8 topic and 9 focus are still asked).

### Topic auto-suggest logic (Q8)

When possible, suggest a candidate `topic:` value based on keyword detection in research_question + topic_tags + always-volatile zones. The set of available topics is defined in `config/topics.yaml` — adapt the keyword map below to whatever topics that file declares.

**⚠️ Row order matters** — first-match-wins. Order rows specificity-first: narrow topics before broader ones. Within a row, list multi-word specific phrases before generic singles. The mapping below is an illustrative default; tune it to `config/topics.yaml`.

| Trigger keywords / signals (specific phrases first) | Suggested `topic:` |
|---|---|
| prompt-injection / OWASP / threat-intel / CVE / vulnerability / guardrails / security | `security` |
| EU AI Act / ISO 42001 / NIST / IEEE / compliance / governance / policy / regulator | `governance-policy` |
| MCP / plugin / hooks / agent / SDK / coding assistant | `agent-tooling` |
| e-learning / curriculum / LMS / edtech / student / course | `edtech` |
| CI/CD / SDLC / code review / dev practices / testing framework | `sdlc-dev` |
| knowledge graph / frontmatter / wiki / KB / index / notes | `kb-architecture` |
| source modality / research-audit / research methodology / tier | `research-methodology` |
| fine-tuning / context window / RAG / agentic / prompting / LLM | `ai-craft` |
| audit framework / quality metrics / validator / verification / monitoring | `quality` |
| ROI / pitch / competitor / pricing / sales / market | `sales-marketing` |
| session continuity / workflow / lessons / process / meta | `meta-process` |

The suggested value is offered to the user as the first option; the user can override by picking another value from `config/topics.yaml`. Keeping topics to a known set keeps the topic axis disciplined (anti-drift).

### Source modality semantics

- `mixed` (default) — a combination of academic / vendor docs / community signal — typical for broad topics
- `research-tier` — academic / peer-reviewed / formal benchmarks priority — for evidence-heavy methodology research
- `social-pulse` — community signals priority (Discord/Twitter/Reddit/HN/forums) — for emerging tech / vibe checks
- `regulatory` — official regulatory documents priority (laws, standards, accreditation bodies) — for compliance research

### Always-volatile topic check

See `sources/always-volatile-domains.md`. If the research_question falls into an always-volatile topic (models, AI API pricing, agent-tooling features, regulation, AI safety research, MCP ecosystem):
- recency_max default → 3mo (instead of 12)
- sources_mode default → hybrid (internal-only not allowed)
- min_tier recommendation → T1
- **source_modality auto-adjust:**
  - keywords "regulator/compliance/AI Act/GPAI/NIST/ISO/certification" → `regulatory`
  - keywords "academic/paper/journal/peer-reviewed/benchmark" → `research-tier`
  - keywords "community/discord/twitter/reddit/forum/HN" → `social-pulse`
  - otherwise → `mixed`

### WDM source-selection step

> WDM = a generic Pareto-frontier multi-criteria evaluation. The criteria + weights below are defaults; tune them to your workflow.

If `sources_mode == hybrid` or `web from scratch` — after the questionnaire, apply a **Weighted Decision Matrix** to shortlist candidate sources (≤8 sources by default for standard depth, ≤15 for deep dive):

**Source-selection WDM template:**

| Criterion | Weight (1-5) | Description |
|---|---|---|
| Authority | 5 | Vendor primary docs > peer-reviewed > trade press > forums |
| Relevance | 5 | Direct match to research_question vs tangential |
| Accessibility | 3 | Open-access > paywall > restricted (impacts ROI) |
| Recency | 2 | Per recency_max + always-volatile override |
| COI (no conflict-of-interest) | 3 | Independent > vendor-aligned > sponsored content |

**Score computation:** for each candidate source — score = sum(weight × score_per_criterion(0-5)) / sum(weights). Top-N candidates per shortlist.

**Output:** a `wdm_source_shortlist` section in the research-brief frontmatter (optional, recommended for deep dive depth):

```yaml
wdm_source_shortlist:
  - {url}: {score: 4.2, criteria: {authority: 5, relevance: 5, accessibility: 3, recency: 4, coi: 4}}
  - ...
```

**See extended templates** (source-selection + thread-selection): [`wdm-templates.md`](wdm-templates.md).

**Anti-pattern:** do not propagate WDM scoring without filling the criteria — a pure number with no reasoning behind it = false rigor.

---

## Phase 2.5 — Topic-aware recency profile

> Per-topic freshness windows instead of a generic `recency_max: 12mo` default.

**Why:** different topics change at different rates. The AI tools landscape — 12 months is a hard ceiling (vendors ship features quarterly). Standards (ISO/IEEE) — 36 months acceptable (standards amend slowly). Security threats — 6 months (CVEs / threats evolve). A generic `recency_max: 12mo` leads to (a) false-fresh for standards and (b) false-stale for security.

### Topic → default recency_max mapping

| Topic tag pattern | Default `recency_max` | Rationale |
|---|---|---|
| `security`, `cve`, `vulnerability`, `threat-intel` | **6mo** | Security landscape evolves fast; CVEs deprecate; threat-actor TTPs shift |
| `ai-tools`, `llm-tooling`, `coding-assistants`, `agents` | **12mo** | AI tooling ships quarterly; tools rename / pivot frequently |
| `agent-tooling`, `mcp`, `claude-code`, `sdk` | **6mo** | Agent primitives ship faster than yearly; recent matters most |
| `general-tech`, `devops`, `architecture`, `patterns` | **24mo** | Tech patterns settle over 1-2 years; foundational material remains valid |
| `iso`, `ieee`, `nist`, `regulatory`, `governance` | **36mo** | Standards amend slowly; a 3-year-old paper is often a canonical reference |
| `academic`, `peer-reviewed`, `whitepaper` | **48mo** | Academic literature is long-tail valid; foundational papers remain authoritative |
| (no matched topic) | **12mo** | Default fallback |

### Application

1. During Phase 2 (Frame Questionnaire) — collect the `topic` / `topic_tags` field in the research brief.
2. During Phase 2.5 (this step) — match the topic tags against the table → derive the default `recency_max`.
3. The user can override via an explicit AskUserQuestion: "Detected topic: {X}. Default recency: {Y}. Override? (a) accept default (b) tighter Nmo (c) looser Nmo".
4. **Always-volatile override:** keywords from `sources/always-volatile-domains.md` (e.g., news, market-prices) override any topic default → `recency_max: 1mo` or less.

### Edge cases

- **Multi-topic queries** (e.g., security + AI tools) — pick the tighter window (security 6mo wins over AI tools 12mo).
- **Conflicting tags** (e.g., `iso` + `cve`) — surface to the user via AskUserQuestion instead of auto-resolving.
- **No topic tags** (legacy briefs) — fall back to 12mo.

**Anti-pattern:** do not over-engineer — keep the topic taxonomy flat (a small set + fallback), not a tree. Expand the topic set only when ≥2 research sessions need a new tag.
