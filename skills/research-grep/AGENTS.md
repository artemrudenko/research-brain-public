---
name: research-grep-agent-contract
tools_required: [Read, Grep, Glob, AskUserQuestion, Bash]
tools_forbidden: [WebFetch, Write, Edit]  # read-only inventory; no mutations
permissions:
  - read: skills/, brain/, pipeline/
  - write: []  # read-only by design
limits:
  max_files_per_run: 200  # grep scans can be large
  max_subagents: 0  # sequential within session
---

# Research-Grep — Agent Contract

Cross-platform contract for the `research-grep` skill (the grep fallback after a `brain/` cache miss). Worker skill, **read-only inventory** — no artifact write.

## Scope

Greps the locally available knowledge corpus (`brain/` and the `pipeline/` stages: `2-curated/`, `3-synthesis/`, `1-incoming/`, `0-archive/`) and produces an inventory + AskUserQuestion for the next step (use local / local+web / web from scratch). NEVER auto-runs WebFetch — the user choice gates downstream actions.

## Tool usage

- **Read** — `brain/INDEX.md`, `brain/` notes, candidate files based on grep hits
- **Grep** — search target zones by KEYWORDS / DOMAIN_FILTER (matched against `^tags:` in `brain/` concepts and `^category:` in `pipeline/` articles — there is no `domain:` frontmatter key; see SKILL.md §1.5b)
- **Glob** — discover files in target zones (`brain/**`, `pipeline/2-curated/**`, `pipeline/0-archive/**`)
- **AskUserQuestion** — Phase 4 routing decision (use local / local+web / web from scratch / inventory-only)
- **Bash** — optional: invoke `scripts/grep-patterns.sh` for batch search recipes
- **WebFetch FORBIDDEN** — Phase 5 forwards to `research-build`, always via source-archive

## Permissions

- **Read everywhere** for inventory compilation.
- **NO WRITE** — this is a read-only inventory skill. Output is an inline chat message, no file artifact.
- **No Edit** — no mutations to the knowledge corpus.

## Limits

- Max 200 file reads per run (large scans at deep depth).
- Max 0 subagents (sequential within the main session; multi-topic queries handled via the coverage matrix, not dispatch).

## Handoffs

- **Upstream:** `wiki-query` (may forward a `DOMAIN_FILTER`) OR `research-frame` (if `brain/` is empty).
- **Downstream:** `research-build` (if Phase 4 user choice = web option) OR terminal (if `inventory-only` MODE).

## Hard rules

- **NEVER WebFetch / WebSearch before Phase 4** — inventory-first contract.
- **NEVER skip AskUserQuestion in Phase 4** (except `MODE=inventory-only`).
- **brain/INDEX.md first** — the curated map points to the key notes.
- **archive/ excluded by default.**
- **DOMAIN_FILTER must match a domain in `config/topics.yaml`**; reject free-form values.

## Cross-tool portability

- **Cowork / Claude Code CLI:** native Grep + Glob + AskUserQuestion.
- **Other chat-based tools:** workspace search; manual user choice (no AskUserQuestion equivalent).

See [`SKILL.md`](SKILL.md) for the full 5-phase workflow + Phase 1.5 DOMAIN_FILTER handling.
