---
title: "Research-Grep — Inventory format, coverage matrix, decision table, fetch strategy, example run"
type: reference
last_updated: 2026-06-15
applies_when: "Phase 3 inventory rendering / multi-topic coverage matrix / Phase 4 decision options / fetch fallback chain / worked example"
---

# Inventory, coverage matrix, decision & fetch detail

> Extracted from `SKILL.md`. SKILL.md keeps the phase summary; full formats here.

## Phase 3 — Inventory format

```
## Local knowledge — found on topic "{TOPIC}"

### Knowledge notes (brain/) — N
- [{path}] — {description} ({date})

### Curated sources (pipeline/2-curated/) — N
- [{path}] — {N articles/links}

### Synthesis drafts (pipeline/3-synthesis/) — N
- [{path}] — {short summary} ({date})

### Verbatim captures (pipeline/0-archive/, DEPTH=deep) — N
- [{path}] — {short summary} ({date})

**Overall coverage:** {none / partial / substantial / saturated}
```

Coverage thresholds (from `rules/common.md`): **none** = 0 notes · **partial** = 1-3 notes or only verbatim captures · **substantial** = synthesized note + curated/verbatim captures · **saturated** = several synthesized notes from different angles.

For each hit record: path, type (note/raw/curated/source), short description (first line / Markdown heading), date (from the filename or mtime).

### Coverage matrix (multi-topic, ≥5 distinct questions)

Trigger: a numbered list, bulleted sub-topics, phrases like "across N tasks". Build it before Phase 4:

```
| # | Question/task | brain/ | pipeline/2-curated/ | pipeline/3-synthesis/ | Coverage |
|---|---|:-:|:-:|:-:|---|
| 1 | ... | ✅ | ✅ | — | substantial |
| 2 | ... | ⚠️ | ✅ | — | partial |
| 3 | ... | ❌ | ❌ | — | none |
```

This gives an informed choice per sub-topic. For single-question requests — skip.

## Phase 4 — Decision table

| Coverage | Recommended option (first, "(Recommended)") | Description |
|---|---|---|
| **saturated** | Use local | "Local is enough — I'll answer from what we have" |
| **substantial** | Local + targeted web for an update | "I'll use local as the base and add fresh web findings" |
| **partial** | Local + a full web research pass | "Local is thin — needs web sources to round it out" |
| **none** | Web research from scratch | "No local material — going to the web; fetched sources are saved verbatim into `pipeline/0-archive/` by `source-archive`" |

Extra options (always): "Just show what exists" (= `inventory-only`) · "Ignore local, web from a clean slate" (escape hatch).

## Phase 5 — Execute table

| Choice | Action |
|---|---|
| Use local | Read the relevant files → synthesize → return the answer |
| Local + web (targeted) | Read local → identify gaps → WebFetch the gaps → `research-build` |
| Local + web (full) | `research-build` with the pre-loaded inventory |
| Web from scratch | `research-build` flagged "local checked, absent" |
| Just show | Finish, inventory in chat |
| Ignore local | `research-build` with an "ignore-local" flag |

## Fetch strategy (when Phase 5 forwards to research-build with web)

Fallback chain:
1. **WebFetch** — primary
2. On error / block / JS-redirect / empty response — **browser MCP** (`navigate` + `get_page_text`)
3. On login wall / SSO / CAPTCHA / paywall — **manual handoff:** placeholder `pipeline/0-archive/{YYYY-MM-DD}_{host}_MANUAL.md` (`status: pending`, `fetched_via: manual`)

**Web persistence:** any successful fetch is saved via `source-archive` (dedup, hash, audit history). In Cowork, hooks are not auto-run — the Phase 5 caller invokes the archive step itself; in Claude Code CLI it fires natively as a PostToolUse hook. **Forbidden:** bash/curl/wget/Python `requests` for fetching.

## Example run

**User:** "research MCP server security — what we need to know before adoption"

- **Phase 1 — keywords:** `MCP`, `Model Context Protocol`, `MCP server`, `security`, `adoption`
- **Phase 2 — local search:** `brain/INDEX.md` (points to a security MOC note) · `brain/` notes on supply-chain risk · `pipeline/0-archive/` (OWASP LLM Top 10, MITRE ATLAS verbatim, `DEPTH=deep`) · `pipeline/2-curated/security/index.md` (curated links) · `pipeline/3-synthesis/` (a prior synthesis draft)
- **Phase 3 — inventory:** Notes 2, Raw 2, Curated 1 index, Sources 1 → **Overall coverage: substantial**
- **Phase 4 — AskUserQuestion:** first option "Local + targeted web for an update (Recommended)" — "we have base security material; web is needed for fresh CVEs and vendor-specific MCP gotchas"
- **Phase 5 — Execute:** forward to `research-build` with the pre-loaded inventory + gaps
