---
name: source-archive-agent-contract
tools_required: [Read, Write, Edit, Glob, Bash, WebFetch]
tools_forbidden: []
permissions:
  - read: pipeline/, sources/, brain/, skills/, docs/, config/
  - write: pipeline/0-archive/, pipeline/0-archive/sanitized/, pipeline/registry.md
limits:
  max_files_per_run: 50
  max_subagents: 0
---

# source-archive — Agent Contract

Cross-platform agent contract for the `source-archive` skill (web content persistence).

The archive root is config-derived (default `pipeline/0-archive/`); written as `{{ARCHIVE_ROOT}}` below.

**Behaviour summary** (full spec -> [`SKILL.md`](SKILL.md)):

- Phase 0 — load `rules/common.md` (dedup window 7d, sha256, filename convention, archive-root resolution)
- Phase 1 — pre-fetch dedup check: in-session memo -> filesystem glob -> freshness gate
- Phase 2 — fetch fallback chain: WebFetch -> browser-fetch -> manual placeholder
- Phase 2.5 (optional) — instruction stripping (MODE=instruction-stripping)
- Phase 3 — compute hash + tier lookup + write `{{ARCHIVE_ROOT}}/{date}_{host}_{slug}.md`
- Phase 4 — STALE CACHE re-fetch with hash drift handling (append to `audit_history`)

**Tool constraints:**
- WebFetch (primary) or a browser-automation tool that navigates and extracts page text (fallback)
- Bash for sha256: `shasum -a 256`
- Never writes outside `{{ARCHIVE_ROOT}}`
- Idempotent: a repeated call with the same URL <7d returns the existing path (cache hit)

**Cross-tool portability:** runtimes without native hook support call the archive step manually after each fetch; runtimes with PostToolUse hooks can fire it automatically (both optional). Other agent tools read this AGENTS.md by convention.
