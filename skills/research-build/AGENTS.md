---
name: research-build-agent-contract
tools_required: [Read, Write, Edit, Grep, Glob, WebFetch, Bash, Task]
tools_forbidden: []  # WebFetch allowed, but always via source-archive
permissions:
  - read: skills/, docs/, brain/, pipeline/, config/
  - write: pipeline/3-synthesis/
  - no_write: pipeline/0-archive/, pipeline/1-incoming/, brain/
limits:
  max_files_per_run: 60
  max_subagents: 6  # Phase 2 reader fan-out: 1 per article (5–~12 sources) or per cluster (>~12)
---

# Research-Build — Agent Contract

Cross-platform contract for the `research-build` skill (Phase 2–4 Gather + Synthesize of the
research lifecycle). Worker skill (not a validator). Has `tests/acceptance.md`.

## Scope

Compiles multi-source research into a structured Markdown research document under
`pipeline/3-synthesis/`. Phase 7 `wiki-ingest` suggestion is mandatory when ≥5 sources were used.

## Tool usage

- **Read** — the research-brief (mandatory pre-load), `brain/concepts/`, raw materials, prior corpus
- **Write** — `pipeline/3-synthesis/{topic}/{slug}.md` + the Phase 2b raw file `raw_{date}.md`
- **Edit** — brief lifecycle checkboxes + `last_updated` + research-log fields
- **Grep/Glob** — `research-grep` inventory + claim attribution discovery
- **WebFetch** — via the `source-archive` skill ONLY (Phase 2 fetch chain: WebFetch → Chrome MCP → manual handoff)
- **Bash** — invoking the `source-archive` hook
- **Task** — Phase 2 reader fan-out (≥5 synthesis-bound sources, any depth): 1 subagent per article, or per cluster when >~12; subagents return extracts, not full bodies

## Permissions

- **Read** everywhere for context loading.
- **Write** to `pipeline/3-synthesis/` (the synthesized document, the raw file, and the critique-log).
- **No write** to `pipeline/0-archive/`, `pipeline/1-incoming/`, or `brain/` (the vault is updated only through `wiki-ingest`).

## Limits

- Max 60 files per run (10–20 raw materials + draft + brief + critique-log + verification-log handoff).
- Max 6 subagents (Phase 2 reader fan-out — 1 per article or per cluster, audit trail mandatory).

## Handoffs

- **Upstream:** `research-grep` (Phase 1 inventory pre-loaded), preceded by `wiki-query`.
- **Downstream (recommended):** `research-audit` (Verify, gate at the 30% red threshold).
- **Downstream (after Verify):** `wiki-ingest` (Archive — Phase 7 suggestion).
- **Validator pair:** `research-audit` (covers claims verification + the 30% threshold gate).

## Subagent dispatch contract — reader fan-out

Full contract: [`references/reader-contract.md`](references/reader-contract.md). When **≥5
synthesis-bound sources** (any `depth` — the count is the trigger, not `depth: deep`):
1. Dispatch **1 `general-purpose` subagent per article** (5–~12 sources), or group into clusters of 2–4 (vendor docs / analyst / community / regulatory) with one per cluster when >~12 — all in one Agent message, ≤ ~6 parallel.
2. Each subagent returns a **compact structured extract** (`source_meta` / `key_claims` / verbatim `quotes` / `data_points` / `contradicts` / `dedup_key` / `raw_path`) and writes its verbatim body to `pipeline/3-synthesis/{topic}/raw/`. It does **not** return a prose body — **the main agent never loads full article bodies** (the context-exhaustion fix).
3. Audit trail mandatory: fetched URLs + raw paths, or `manual-handoff` placeholders.
4. Synthesize (Phase 3) runs sequentially in the main agent on the bounded **extract set** — it cannot be decoupled (it needs a holistic view).
5. Sanitize (S1–S9) and URL dedup stay deterministic scripts, run before/after dispatch — never inside a subagent.

See [`SKILL.md`](SKILL.md) for the full 7-phase workflow + Phase 5.5 Anti-AI Audit + Phase 6.5 Critique + Phase 7 wiki-ingest suggestion.
