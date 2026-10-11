# research-frame — Common Rules

Platform-agnostic rules for the skill. SKILL.md references this file in Phase 0.

---

## Trigger keywords

These words in the user's request mean **Frame mandatory** — never bypass:

- research
- investigate
- gather material on
- what do we have on
- deep dive
- discovery
- topic overview
- what do we know about

**Supporting triggers** (Frame mandatory + extra emphasis on determining params):

- "in detail" / "thoroughly" / "deeply" — depth → `deep` default
- "compare" / "which approach is better" — mandatory T1+T2 min_tier
- "justify" / "justification" — mandatory verify_log

---

## Bypass triggers — specific patterns

See also `references/bypass-heuristics.md` for extended examples.

### Pattern 1 — Specific entity + attribute lookup

The query contains a **specific entity name** (X) **and an attribute** (X.version, X.price, X.context-window, X.CEO, X.release-date).

Examples:
- "what's the latest version of tool X?"
- "when did product Y ship?"
- "how much does tool X Pro cost?"
- "who is CEO of company Z?"
- "what's the context window of model Y?"

### Pattern 2 — Resource existence / location

The query is about the **existence** or **location** of a resource.

Examples:
- "does tool X have MCP support?"
- "where to find the docs on hooks?"
- "give me a link to site Z"

### Pattern 3 — Yes/no factual

A query with an unambiguous yes/no answer.

Examples:
- "can you run Bash hooks in tool X?"
- "does tool Y work with the vendor API?"
- "does tool Z support MCP?"

### Pattern 4 — Short queries (< 15 words) without research triggers

If the query is short (≤ 15 words) AND does NOT contain trigger keywords — bypass.

If a short query contains a trigger — Frame mandatory (short ≠ simple).

---

## Default values for the Frame Questionnaire

Applied when the user picks "Use defaults" with one button:

| Field | Default value |
|---|---|
| depth | standard |
| audience | internal review |
| format | research-build (md) |
| sources_mode | hybrid |
| source_modality | mixed (auto-adjusted per always-volatile keywords — see below) |
| recency_max | ≤12mo |
| min_tier | T1+T2 |

`research_question` (Q9) — always requires input from the user, no default.

`audience` (Q2) — if the request is clearly externally-oriented ("for a client meeting", "for a team presentation") — pre-select the matching value.

---

## Always-volatile topic detection

Before applying defaults — **if `sources/always-volatile-domains.md` exists** — check the research_question against always-volatile topics (in `sources/always-volatile-domains.md`, created by copying the shipped [`sources/always-volatile-domains.example.md`](../../../sources/always-volatile-domains.example.md)). **The file is OPTIONAL (per `docs/CONVENTIONS.md` §10): if it is absent, skip this check entirely (soft warning, never a halt) and use the standard defaults below.** The keyword list that follows is also a usable inline fallback when the file is missing.

```
if sources/always-volatile-domains.md exists AND research_question contains its keywords:
    recency_max default = ≤3mo  # instead of 12
    sources_mode default = hybrid  # internal-only forbidden
    min_tier recommendation = T1   # vendor docs mandatory
    show note in Frame UI: "Topic is on the always-volatile list — defaults adapted for freshness"
```

**Always-volatile keywords (from the top-level headings of `sources/always-volatile-domains.md`):**

- model releases and release keywords
- AI API pricing
- features of coding assistants / IDE agents
- regulation (AI Act, NIST AI RMF, GPAI, EU AI Office)
- AI safety research / interpretability / red teaming / jailbreak
- MCP ecosystem (servers, spec, connectors)
- skill / agent ecosystems

---

## source_modality auto-detection rules

Before applying defaults — analyze the research_question against keyword groups:

| source_modality | Trigger keywords (substring match, case-insensitive) |
|---|---|
| `regulatory` | regulator / compliance / AI Act / GPAI / NIST / ISO / certification / accreditation / standard / law / EU AI Office |
| `research-tier` | academic / paper / journal / peer-reviewed / benchmark / arxiv / conference / proceedings |
| `social-pulse` | community / discord / twitter / reddit / forum / HN / hacker news / vibe / sentiment |
| `mixed` | DEFAULT (no matches above) |

**Rule:** apply first match wins (regulatory > research-tier > social-pulse > mixed).

**Combine with always-volatile:** if the query falls into always-volatile AND matches regulatory keywords → source_modality=regulatory + recency_max=3mo + min_tier=T1.

**Output behaviour:**
- `regulatory` → wiki-query / research-grep prioritise regulatory / policy materials
- `research-tier` → wiki-query prioritises notes in `brain/` with peer-reviewed-equivalent evidence-type tags + arxiv-fetched materials
- `social-pulse` → wiki-query prioritises `pipeline/2-curated/` with community-discussions tags + session-derived notes
- `mixed` → no priority shift (current default behaviour)

---

## Output paths

- Research brief: `planning/research/{YYYY-MM-DD}_{slug}.md`
- Verification log: `planning/research/{YYYY-MM-DD}_{slug}.verification-log.md` (created by `research-audit`)
- Critique log: `planning/research/{YYYY-MM-DD}_{slug}.critique-log.md` (created by the `research-build` Critique pass)

All three files of one research cycle share the same `{date}_{slug}` prefix — for pair-linking.

---

## Slug generation

Algorithm:

1. Extract `research_question` (Q9 answer)
2. Lowercase → strip punctuation → strip stopwords (the, a, and, or, how, what, etc.)
3. Take the first 3-5 most meaningful words
4. Convert to kebab-case
5. Truncate at 50 chars max

Examples:

| research_question | slug |
|---|---|
| "Where does tool B win over tool A in enterprise?" | `tool-b-vs-tool-a-enterprise` |
| "Which SDLC AI-tooling patterns suit a 200-person team?" | `sdlc-ai-tooling-team` |
| "What's new in the EU AI Act in the last 3 months?" | `eu-ai-act-recent-updates` |

Slug conflict (a file with the same `{date}_{slug}` already exists) → append a `-2`, `-3` suffix.

---

## Integration points

### Forward to wiki-query

After Phase 3 (brief written) — pass the following context:

```
{
  "brief_path": "planning/research/2026-05-02_tool-b-vs-tool-a-enterprise.md",
  "research_question": "...",
  "depth": "standard",
  "recency_max": "12mo",
  "min_tier": "T1+T2",
  "always_volatile": false,
  "frame_decision": "full" | "bypassed",
  "bypass_reason": "..." | null
}
```

`wiki-query` reads the brief frontmatter and applies recency/tier filters when scoring notes in `brain/`.

### Read from an existing brief

If the user returns to a research session hours / days later:
- Request like "continue research X" / "go back to brief Y" / explicit mention of the slug
- Skip Phase 1-2, read the existing brief from `planning/research/`, jump straight to Phase 4 (forward to the next stage depending on the Lifecycle status in the brief)

---

## Stop conditions detail

- **The user did not answer a question after 2 minutes** → fall back to defaults for unanswered questions + ask Q9 (focus) again separately
- **Bypass-evaluator confidence 60-40** → safety net: present the Phase 2 questionnaire (full) with pre-filled defaults; the user can skip via "Use defaults"
- **research_question too general** ("something about AI") → AskUserQuestion asking to narrow it before creating the brief

---

## Anti-pattern guards

- **Do not write the brief to `pipeline/3-synthesis/`** — the brief is a lifecycle artifact, not a synthesized document. Only `planning/research/`.
- **Do not reuse an existing slug** without a conflict check.
- **Do not apply Frame defaults blindly** — the always-volatile check must run BEFORE applying defaults.
