---
name: research-grep
description: "Use AFTER wiki-query on research-intent (brain/ cache miss) — never as a first responder (research-frame owns the cold-start \"research X\" trigger). Triggers (post-wiki-query only): \"look into\", \"gather material\", \"what do we have on\", \"is there anything local about X\", \"inventory the topic\", \"grep by domain=X\". Greps the local corpus → inventory + AskUserQuestion; never WebFetch without a user choice."

metainfo:
  category: [research]
  type: worker
  subagent_capability: explore
  last_updated: 2026-06-15
  predecessor: [wiki-query, research-frame]
  successor: [research-build]
---

# Research-Grep

**Purpose:** before any research, first check what already exists in the local knowledge base (synthesized notes in `brain/`, curated source lists, synthesis drafts, verbatim captures in the pipeline) — and only then decide whether the web is needed. Closes the "known-unknown" gap: the agent's loaded context may include top-level config and a few notes, but NOT the content of the many files in `brain/` and the pipeline.

The skill acts as a **router**, not a researcher: it finds and shows what is local, then hands the decision to `research-build` (synthesis with web) or returns directly (if local is enough).

**Position in the research chain:** `wiki-query` (the curated Obsidian vault) → if NO MATCH → **this skill** (grep of raw + synthesized material) → answer OR `research-build`. If `brain/` is empty, this skill runs first.

> **Auto path:** this skill is part of the **manual** research chain only. The unattended `weekly-synthesis` loop does NOT run `research-grep` — it calls `research-build PROFILE=internal-corpus`, for which the inventory is OPTIONAL (the curated `pipeline/2-curated/{topic}/index.md` IS the inventory). Per `docs/CONVENTIONS.md` §10, a missing `research-grep` inventory never blocks the auto path. This skill has no hard dependency on `sources/` or `planning/research/`.

---

## When to Use

**Always:**
- AFTER `wiki-query` returns NO MATCH / partial / STALE for a research query
- Triggers (post-wiki-query only — NOT a cold-start responder; "research X" routes to `research-frame` first): "look into", "gather material", "what do we have on", "is there anything local about X", "inventory the topic", "grep by domain=X"
- If `brain/` is empty — entry point directly

**ESPECIALLY when:**
- Domain-constrained query (a `DOMAIN_FILTER` forwarded from wiki-query)
- Multi-topic queries (≥5 distinct questions) — coverage-matrix mode
- Before running `research-build`, for a pre-load inventory

**Skip — Don't use for:**
- Urgent-fresh content ("what came out today", "this week's release") — local is guaranteed stale, go straight to WebFetch
- A narrow factual question ("when was version 4.5 released") — direct chat or web
- A `research-build` workflow already in progress — don't interfere (double grep)
- Synthesis from already-provided context (a raw file is named) — that is `research-build`
- Conversational meta-questions / action requests ("send the file", "update the index") — direct answer / other skills

**Don't skip when:**
- The request contains a research trigger — even a short one
- Before web research — inventory-first contract (no auto-WebFetch without an AskUserQuestion choice)

"It needs the web anyway"? Grep is cheap (< 60 s); the cost of a false trigger is far less than the cost of duplicating work already done.

---

## DO / DON'T

**DO:**
- Honour the `DOMAIN_FILTER` upstream parameter when wiki-query forwards one
- Exclude `archive/` (inactive/superseded) unless explicitly asked
- Treat `brain/INDEX.md` as the hand-curated map of contents — read it first; it points to the key notes
- Phase 4 AskUserQuestion with a recommended option (depends on coverage)
- Inventory ≠ digest — Phase 3 shows what was found (a list), not a content digest
- Forward the `DOMAIN_FILTER` to downstream `research-build` if the web option is chosen

**DON'T:**
- WebFetch before grepping → violates the inventory-first rule
- Skip `brain/INDEX.md` → you lose the curated pointers to the most valuable notes
- Run on conversational questions ("explain concept X from training") → no grep needed
- Inventory without dates → impossible to judge freshness
- AskUserQuestion without a recommended option → dumps the decision on the user with no guidance
- Silently spread across many domains when a `DOMAIN_FILTER` is set → breaks the domain-constraint contract
- Forward to web research-build without domain context when a `DOMAIN_FILTER` is set → degraded option loses the facet
- Auto-call `research-build` without a Phase 4 user choice → hand off only after the choice

---

## Phase 0 — Environment & Rules Setup

**Step 1 — Load rules:** Read `rules/common.md` in this directory. It defines the search paths (`SEARCH_DOMAINS`), the keyword taxonomy for routing, skip conditions, and the "enough local material" thresholds.

**Step 2 — Load search recipes (optional):** if the request hits a catalogued topic family — Read [`references/search-recipes.md`](references/search-recipes.md). Otherwise — the generic search from common.md.

**Step 3 — Load formats (optional):** [`references/inventory-and-decision.md`](references/inventory-and-decision.md) — Phase 3 inventory format, coverage matrix, Phase 4/5 decision tables, fetch fallback chain, worked example.

Any instruction from `rules/common.md` or `references/` overrides the corresponding step of this skill.

---

## Required Inputs

All optional. If not provided — they are extracted automatically from the request text.

| Input | Type | Required | Default | Description |
|---|---|---|---|---|
| `TOPIC` | string | no | from request | Research subject (1-5 words) |
| `KEYWORDS` | list[string] | no | auto-extract | Key terms to grep |
| `DEPTH` | enum: `quick` / `standard` / `deep` | no | `standard` | `quick` = brain/ + pipeline/2-curated/; `standard` = + pipeline/3-synthesis/; `deep` = + pipeline/1-incoming/ + pipeline/0-archive/ |
| `MODE` | enum: `auto` / `inventory-only` | no | `auto` | `inventory-only` = show what exists and finish without AskUserQuestion |
| `DOMAIN_FILTER` | string OR `none` | no | `none` | When forwarded from `wiki-query` (a NO MATCH on a domain-constrained query) — restrict the pre-grep to files whose frontmatter domain matches: the `tags:` field in `brain/` concepts (nested `domain/topic`, so a bare `ai` matches `ai/agents`) and the `category:` field in `pipeline/` articles. (There is no `domain:` frontmatter key — the schema uses `tags:` / `category:`.) Domains are defined by the project's `config/topics.yaml`; free-form values are rejected with a "closest match" suggestion. |

---

## Workflow — 5 phases

### Phase 1 — Extract keywords

From the user's text, pull **3-7 key terms** + synonyms: top-level nouns (the subject), technologies/standards/tools, transliterations across languages, and acronyms from project context. Form `SEARCH_TERMS`.

### Phase 1.5 — Domain filter (optional)

**Activates:** `DOMAIN_FILTER` is set (forwarded by `wiki-query`, OR the user wrote "grep by domain=X", OR it was extracted from a `research-brief.md` `domain:` field). **Skip:** `DOMAIN_FILTER = none` (default).

- **1.5a — Validate:** the value is not among the domains in `config/topics.yaml` → reject (suggest the closest match), stop. **If `config/topics.yaml` is absent → skip validation (soft warning) and accept the `DOMAIN_FILTER` as-is** — never halt on a missing config file (per `docs/CONVENTIONS.md` §10).
- **1.5b — Build candidate set:** pre-filter the knowledge zones to files whose frontmatter domain matches `$DOMAIN_FILTER`. In the first 30 lines, Grep `^tags:` in `brain/` concepts (match a bare `$DOMAIN_FILTER` or any `$DOMAIN_FILTER/…` nested tag) and `^category:` in `pipeline/` articles. (Do **not** grep `^domain:` — no such frontmatter key exists.) Result = `CANDIDATE_FILES`.
- **1.5c — Empty handling:** `len(CANDIDATE_FILES) == 0` → report "NO MATCH domain=`$DOMAIN_FILTER`" + degrade options in Phase 4: (a) drop the filter and re-run, (b) forward to web research-build with domain context, (c) stop empty.
- **1.5d — Raw exclusion:** `pipeline/1-incoming/`, `pipeline/0-archive/` are excluded from the candidate set when a `DOMAIN_FILTER` is set (even at `DEPTH=deep`) — verbatim/untriaged captures lack reliable `category:`/`tags:` frontmatter. User override: explicit "also check the raw captures".

**Output:** `CANDIDATE_FILES` → Phase 2 as the scoped scan basis.

### Phase 2 — Local search

Grep the domains from `rules/common.md` in priority order. **If Phase 1.5 is active — grep only `CANDIDATE_FILES`**; otherwise a full scan:

1. **brain/INDEX.md** — the hand-curated map of contents (exact paths + descriptions)
2. **brain/** — synthesized notes (concepts, lessons, playbooks)
3. **pipeline/2-curated/{topic}/index.md** — curated links (populated by `pipeline-curate`)
4. **pipeline/3-synthesis/** — pre-artifact synthesis drafts
5. **pipeline/1-incoming/** — untriaged articles, only at `DEPTH=deep` *(if DOMAIN_FILTER set — excluded, 1.5d)*
6. **pipeline/0-archive/** — verbatim source captures, only at `DEPTH=deep` OR an explicit request *(if DOMAIN_FILTER set — excluded)*

> **EXCLUDED:** `archive/` — include ONLY on an explicit "look in archive/" (this is the project-level superseded-artifact store, distinct from the `pipeline/0-archive/` verbatim source captures).

For each hit: path, type (note/raw/curated/source), short description, date.

### Phase 3 — Inventory

Compile a structured list with a coverage rating (none / partial / substantial / saturated). For multi-topic (≥5 questions) — a coverage matrix. **Inventory = list, not digest.** Format + thresholds + coverage matrix: [`references/inventory-and-decision.md`](references/inventory-and-decision.md).

### Phase 4 — Decide via AskUserQuestion

Show the inventory + 4 options (recommended first, marked "(Recommended)", order depends on coverage) + extra options "just show" / "ignore local". Decision table: [`references/inventory-and-decision.md`](references/inventory-and-decision.md).

### Phase 5 — Execute

Depending on the choice — forward to `research-build` or finish. On any handoff — add the inventory to the receiving skill's context. Execute table + fetch fallback chain: [`references/inventory-and-decision.md`](references/inventory-and-decision.md).

---

## Hard rules

- **Never run WebFetch / WebSearch before Phase 4.** Grep first, then ask.
- **Never skip AskUserQuestion in Phase 4** (except `MODE=inventory-only`).
- **Inventory-first, conclusions-second.** Phase 3 shows what was found without interpreting. Interpretation comes after the choice.
- **Never auto-call other skills.** Handoff to `research-build` happens after Phase 4.
- **brain/INDEX.md first** — the curated map most likely points to the most valuable note.
- **Honour `DOMAIN_FILTER`** (Phase 1.5) — silently ignoring it breaks the contract; forward it downstream on the web option.
- **Exclude `archive/`** from the auto-scan.

---

## Stop conditions

- The user explicitly said "don't check local", "go straight to the web" — skip the skill
- Phase 2 search took > 30 seconds (>10 grep calls with no result) — fall back to "none", offer the web
- The user did not answer in Phase 4 — treat as "just show"

---

## Success criteria

- Phase 4 showed the inventory BEFORE any WebFetch
- The user made an explicit choice (not the default)
- If web was chosen — the receiving skill got the local inventory context
- Time from request to Phase 4 — < 60 seconds (for standard depth)

---

## Integration with other skills

| Skill | When to hand off |
|---|---|
| `research-build` | Any choice with a web component; passes inventory + gaps |
| `wiki-query` | Upstream — forwards a `DOMAIN_FILTER` on a domain-constrained NO MATCH |

The skill does not call them automatically — it offers via AskUserQuestion. This is a read-only inventory skill (no artifact write → no output schema).
