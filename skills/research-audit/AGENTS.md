---
name: research-audit-agent-contract
tools_required: [Read, Write, Edit, Grep, Glob, Task]
tools_forbidden: [WebFetch]  # delegated to the source-archive skill
permissions:
  - read: skills/, docs/, brain/, materials/, planning/, pipeline/, sources/
  - write: planning/research/  # verification-log.md sibling of the brief
  - no_write: archive/, pipeline/
limits:
  max_files_per_run: 30
  max_subagents: 4  # Phase 5 dispatch (claim clusters) + parallel mode (N=3 investigators)
---

# Research-Audit — Agent Contract

Cross-platform contract for the `research-audit` skill (Verify step of the research lifecycle). Detect-only validator skill.

## Scope

Verifies factual claims in a draft research artifact against tier/recency from the research-brief. Output: `planning/research/{date}_{slug}.verification-log.md` with 🟢/🟡/🔴 markers and `gate_status` (passed/blocked). A hard block at `red_pct > 30%` returns control to the `research-build` Gather phase.

## Tool usage

- **Read** — draft md, research-brief, raw materials, trusted-registry, always-volatile-domains
- **Write** — verification-log.md (one file per run, canonical path)
- **Edit** — brief lifecycle checkbox + `verification_log:` field + `last_updated:` (post-write)
- **Grep/Glob** — claim extraction, sibling brief discovery
- **Task** — subagent dispatch for >20 claims (Phase 5) OR `--parallel` mode (N=3)
- **WebFetch FORBIDDEN** — all supplementary fetches delegated to the `source-archive` skill

## Permissions

- **Read everywhere** for context loading (sources/, brain/, materials/, planning/).
- **Write only** in `planning/research/` (sibling of the brief; one verification log per draft).
- **Edit only** in the brief frontmatter (lifecycle checkbox + 3 fields).
- **No write** in `archive/`, `pipeline/`.

## Limits

- Max 30 files per run (draft + brief + 10-20 supplementary checks + log).
- Max 4 subagents (Phase 5 dispatch: claim clusters by category, OR parallel mode: N=3 hypothesis investigators).

## Handoffs

- **Upstream:** `research-build` Synthesize phase (draft md complete).
- **Downstream:** `research-build` Critique pass (Phase 6.5) if `gate_status: passed`; back to Gather if `blocked`.
- **Validator pair:** self-contained — this IS a validator.

## Detect-only compliance

- Default `INTERACTIVE=false` → markdown-only output, no AskUserQuestion in the detect phase.
- AskUserQuestion allowed only in the fix phase (unregistered hosts) OR when `INTERACTIVE=true`.
- Output canonical path: `planning/research/{date}_{slug}.verification-log.md` (sibling of the brief).

## Cross-tool portability

- **Claude Code / Cowork:** supplementary fetches invoke the `source-archive` skill from the Phase 5 step.
- **Other agent tools (Copilot/Cursor/Codex):** read SKILL.md + this contract; manually invoke the source-archive equivalent.

See [`SKILL.md`](SKILL.md) for the full 7-phase workflow + Phase 6.5 inversion / 6.6 misinfo / 7.5 rigor passes (extended mode).
