---
title: "Research-Audit — Optional Modes (revise, parallel)"
type: reference
domain: research-quality
created: 2026-05-23
last_updated: 2026-06-15
applies_when: "Modes declared in the SKILL.md frontmatter `modes:` block. Two opt-in modes."
---

# Research-Audit — Optional Modes

> Lazy-loaded from `SKILL.md`. SKILL.md holds a summary + a pointer.

## Mode `revise` (Reviewer-Revisor pattern)

**Trigger:** the verify gate returns a 🔴 ratio >30% (default block) AND the user explicitly requests a revise loop OR the brief frontmatter sets `enable_revise_mode: true`.

**Behavior:**
1. Read the failed verification-log.md (post-Phase 7)
2. **Reviewer pass:** for each 🔴 claim, generate a specific revision target (drop / soften / re-source / cross-confirm)
3. **Revisor hand-off:** create an amendment plan in `planning/research/{date}_{slug}.revise-plan.md`; signal `research-build` for a targeted re-Synthesize
4. **Re-verify:** automatic Phase 1-7 rerun on the revised draft
5. **Termination:** max 2 iterations (Reviewer→Revisor→Re-verify counts as 1). After 2 iterations still 🔴 >30% → escalate via AskUserQuestion (rerun manually / accept partial / abort)

**Anti-patterns:**
- ❌ Inline revise (overwriting failed claims without a plan) — bypasses the detect-only contract
- ❌ Recursion >2 iterations — hard-cap to prevent infinite loops (the Reviewer-Revisor loop inherits the same risk)

## Mode `parallel` (parallel investigators pattern)

**Trigger:** opt-in via the brief frontmatter `enable_parallel_audit: true` OR an explicit user request "run research-audit with parallel investigators".

**Behavior:**
1. Spawn N=3 sub-agents (use a cost-efficient model tier)
2. Each sub-agent independently searches for contradicting evidence on the top-5 claims (by audit prioritization)
3. Structured findings merge: a per-claim 3-row matrix (investigator-1 / investigator-2 / investigator-3) with consensus / dissent labels
4. Aggregate verdict: claim 🟢 if 3/3 confirmed, 🟡 if 2/3, 🔴 if ≤1/3 OR a contradiction surfaced

**Cost cap:** keep this bounded (3 investigators × 5 claims). Use a cost-efficient model tier for routine audits.

**Anti-patterns:**
- ❌ N>3 investigators — diminishing returns + cost spike; hard-cap at 3
- ❌ Use the most expensive model tier for routine audits — a mid tier suffices; reserve the top tier for escalation
