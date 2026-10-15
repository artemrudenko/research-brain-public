---
name: wiki-ingest-agent-contract
tools_required: [Read, Write, Edit, Glob, Grep]
tools_forbidden: [WebFetch]
permissions:
  - read: pipeline/, brain/, templates/, docs/
  - write: brain/concepts/, brain/lessons/ (status updates only), brain/INDEX.md
  - write: pipeline/.learning/ (private candidates and approval receipts)
  - write: pipeline/0-archive/, pipeline/3-synthesis/ (only declared evidence in an exact owner-approved problem_solution.py package)
  - no_write: archive/, other pipeline files (read-only)
limits:
  max_files_per_run: 20
  max_subagents: 0
---

# wiki-ingest — Agent Contract

Cross-platform agent contract for the `wiki-ingest` worker skill (has `tests/acceptance.md`).

**Behaviour summary** (full spec → [`SKILL.md`](SKILL.md)):

- Phase 0 — load `rules/common.md` + verify upstream closure signal
- Phase 1 — diff: read new artifact / lesson + `brain/INDEX.md` (MOC), extract entities, match to existing concepts
- Phase 1.5 — cross-link presence check (orphan prevention — an orphan note has no backlinks; **cold-start exception:** the first concept in an empty/near-empty cluster, with no real non-SEED/EXAMPLE sibling, is written as a self-standing root note without an outbound `[[wikilink]]` per `docs/CONVENTIONS.md` §10)
- Phase 2 — verdict UPDATE / CREATE / BACKLOG / IGNORE / RETIRE_LESSON / ORPHAN_RISK_HOLD: via AskUserQuestion in interactive mode (`INTERACTIVE=true`), or the recommended-default verdict in automatic mode (`INTERACTIVE=false`, scheduled `weekly-synthesis`)
- Phase 3 — apply (Edit / Write) with mandatory source-link + provenance tag verification, and a mandatory frontmatter stamp: `last_updated: <today>` on every write, `created: <today>` additionally on CREATE (per `docs/CONVENTIONS.md` §5.1 — the digest reads `last_updated`, not mtime)
- Phase 4 — sync `brain/INDEX.md` (hand-curated MOC) + add `[[wikilinks]]` (skipped for a cold-start root note) + summary to user

**Tool constraints:**
- Read for the new artifact (`pipeline/3-synthesis/...md` or `brain/lessons/...md`)
- Read `brain/INDEX.md` + `brain/concept-template.md` mandatory
- Edit for UPDATE of an existing concept; Write for CREATE of a new one
- AskUserQuestion before every write in interactive mode (no-silent-edits invariant); in automatic mode (`INTERACTIVE=false`) apply the recommended-default verdict — hard rules still enforced, a violation halts and logs
- WebFetch FORBIDDEN — wiki-ingest works only with already-archived sources (`pipeline/0-archive/`)

**Activation timing (hard rule):**
- POST-TASK only — after a completed upstream skill (research-build, or a finalized manual note)
- Required closure signal: research-build verification-log `gate_status` ∈ {`passed`, `soft-pass`}, or a finalized note. `soft-pass` is the unattended / internal-corpus verdict (research-audit `SOFT_MODE=true`): the >30% threshold gate is disabled *by design*, so `soft-pass` is a valid closure, NOT a block. Only `gate_status: blocked` (or an absent closure signal) stops ingest.
- NEVER mid-session, NEVER parallel-running

**Subagent capability:** `general`. In a subagent context without AskUserQuestion, run in automatic mode (`INTERACTIVE=false`): apply the recommended-default verdict per the decision rules — this is how the scheduled `weekly-synthesis` drives it unattended. Hard rules remain enforced; a hard-rule violation halts and logs.

**Portability note:** interactive mode requires AskUserQuestion gates for writes. In a CLI / subagent / scheduled context without AskUserQuestion — use automatic mode (apply recommended-default verdicts) or, if write-suppression is desired, run read-only diff mode (Phase 1) and emit a recommendation report instead of writes.
