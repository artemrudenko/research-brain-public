---
name: research-frame-agent-contract
tools_required: [Read, Write, Edit, AskUserQuestion]
tools_forbidden: [WebFetch, Task]  # gateway is UI-driven, no subagent dispatch
permissions:
  - read: skills/, docs/, brain/, sources/, planning/
  - write: planning/research/  # research-brief output only
  - no_write: archive/, pipeline/3-synthesis/, materials/
limits:
  max_files_per_run: 5
  max_subagents: 0  # Frame is UI-driven, never dispatch
---

# Research-Frame — Agent Contract

Cross-platform contract for the `research-frame` skill (Phase 1 Frame of the research lifecycle). **Gateway skill** — the single entry-point on research-intent triggers.

## Scope

Captures the input contract for a research session (scope / depth / audience / freshness / sources / topic) via AskUserQuestion. Writes `planning/research/{date}_{slug}.md` brief and forwards to `wiki-query` with pre-loaded context. Bypass-evaluator (Phase 1) + Phase 0.5 pre-flight resolution skip factual queries.

## Tool usage

- **Read** — `docs/research-workflow.md` (Phase 0, if present), `brain/` for entity resolution, `sources/always-volatile-domains.md` for recency override
- **Write** — `planning/research/{date}_{slug}.md` brief (one file per session)
- **Edit** — N/A (Frame writes a new brief; updates are done by research-build / research-audit downstream)
- **AskUserQuestion** — Phase 2 Frame Questionnaire (one multi-step call); Phase 0.55 clarification gate (max 1)

## Permissions

- **Read** in skills/, docs/, brain/, sources/, planning/.
- **Write only** in `planning/research/` (one brief per session).
- **No write** in `archive/`, `pipeline/3-synthesis/`, `materials/` (Frame does not modify research artifacts).

## Limits

- Max 5 files per run (brief + 2-3 reads).
- **Max 0 subagents** — gateway skill is UI-driven, never dispatch. Sequential single-agent ONLY.

## Handoffs

- **Upstream:** NONE (gateway entry-point on research-intent triggers).
- **Downstream:** `wiki-query` ALWAYS (Phase 4 forward). Alternative: `research-grep` if `brain/` is empty.

## Hard rules (per Frame contract)

- **Bypass-evaluator FIRST** — never AskUserQuestion if the query is clearly factual.
- **Frame is NOT skipped on research triggers** even for short queries.
- **research-brief.md is ALWAYS created on non-bypass** — without a brief downstream has no input contract.
- **Always-volatile check** is mandatory before AskUserQuestion (applies to defaults).
- **Never auto-call wiki-query before the brief is written** — forward only after Phase 3 Write.
- **Never dispatch via subagent** — Frame is UI-driven.

## Cross-tool portability

- **Cowork / Claude Code CLI:** native AskUserQuestion via system tool.
- **Other agents:** chat-based question flow (no programmatic AskUserQuestion equivalent — fall back to a single chat prompt with numbered options).

See [`SKILL.md`](SKILL.md) for the full Phase 0.5 + 1 + 2 + 2.5 + 3 + 4 workflow.
