# research-grep — Acceptance Tests

Given/When/Then scenarios for regression coverage of research-grep's inventory-first router semantics.

This skill is a **read-only inventory router**: it greps the local corpus, shows what exists, and hands the decision to the user via AskUserQuestion. It MUST NOT WebFetch/WebSearch before the Phase 4 user choice, and it never auto-calls another skill.

---

## Test cases — Inventory-before-fetch invariant

### Test G-1.A — Never WebFetch before Phase 4

**Given:** a research query reaches research-grep AFTER wiki-query returned NO MATCH (`DEPTH=standard`, `MODE=auto`)
**When:** the skill runs Phases 1–4
**Then:**
- ✅ Phase 2 greps the local corpus first (`brain/INDEX.md` → `brain/` → `pipeline/2-curated/{topic}/index.md` → `pipeline/3-synthesis/`)
- ✅ Phase 3 compiles the inventory (a list with dates + coverage rating — NOT a content digest)
- ✅ Phase 4 shows the inventory and fires AskUserQuestion BEFORE any web access
- ❌ NO WebFetch / WebSearch is issued during Phases 1–4
- ✅ A web fetch happens only in Phase 5, and only after the user picks an option with a web component

**Anti-test:** a query that needs the web "anyway" still greps first — the inventory-first contract is not skipped because web seems inevitable.

### Test G-1.B — Handoff carries the inventory

**Given:** Phase 3 produced an inventory; in Phase 4 the user picks a web-research option
**When:** Phase 5 hands off to `research-build`
**Then:**
- ✅ `research-build` receives the local inventory + gaps as pre-loaded context
- ✅ research-grep does NOT call `research-build` automatically — the handoff follows the explicit Phase 4 choice

---

## Test cases — DOMAIN_FILTER handling (Phase 1.5)

### Test G-2.A — DOMAIN_FILTER rejection (unknown domain)

**Given:** `DOMAIN_FILTER=quantum` is forwarded, and `config/topics.yaml` exists but has no `quantum` topic
**When:** Phase 1.5a validation runs
**Then:**
- ✅ `quantum` is rejected (not among the `config/topics.yaml` domains)
- ✅ The skill suggests the closest matching domain and stops (no scan on an invalid facet)
- ❌ Phase 2 does NOT silently spread the grep across every domain (that would break the domain-constraint contract)

**Anti-test:** a valid `DOMAIN_FILTER=ai` (present in `config/topics.yaml`) passes validation and proceeds to build `CANDIDATE_FILES`.

### Test G-2.B — config/topics.yaml absent → soft-accept

**Given:** `DOMAIN_FILTER=ai` is forwarded but `config/topics.yaml` does NOT exist
**When:** Phase 1.5a validation runs
**Then:**
- ✅ Validation is SKIPPED with a soft warning (per `docs/CONVENTIONS.md` §10 — never halt on a missing config file)
- ✅ The `DOMAIN_FILTER` is accepted as-is and Phase 1.5b builds `CANDIDATE_FILES` for it
- ❌ The skill does NOT fail-fast or block on the missing config

---

## Test cases — MODE handling

### Test G-3.A — MODE=inventory-only skips Phase 4

**Given:** `MODE=inventory-only`
**When:** the skill completes Phase 3
**Then:**
- ✅ The inventory is shown and the skill finishes
- ❌ Phase 4 AskUserQuestion is NOT fired
- ❌ NO handoff to `research-build`, NO WebFetch
- ✅ The inventory-first invariant still holds (the user gets "what exists" with dates, nothing fetched)

---

## Test cases — Empty candidate set

### Test G-4.A — Empty CANDIDATE_FILES → graceful degrade

**Given:** `DOMAIN_FILTER=ai` is set and Phase 1.5b yields `len(CANDIDATE_FILES) == 0`
**When:** Phase 1.5c empty-handling runs
**Then:**
- ✅ The skill reports "NO MATCH domain=`ai`"
- ✅ Phase 4 offers degrade options: (a) drop the filter and re-run, (b) forward to web `research-build` WITH domain context, (c) stop empty
- ❌ The skill does NOT crash, and does NOT auto-fetch — it still asks before any web access
- ✅ On option (b), the domain context is forwarded so the degraded path keeps the facet

**Anti-test:** a non-empty `CANDIDATE_FILES` proceeds to Phase 2 scoped to those files — no degrade path triggered.

### Test G-4.B — Whole-corpus empty (no DOMAIN_FILTER)

**Given:** `brain/` is empty and the pipeline has no matching files; `DOMAIN_FILTER=none`
**When:** Phases 2–3 run
**Then:**
- ✅ Coverage rated "none"; the inventory says nothing local was found
- ✅ Phase 4 still fires AskUserQuestion (web research vs stop) — the inventory-first contract holds even on an empty corpus
- ✅ If Phase 2 exceeds the 30 s / >10-grep budget, it falls back to "none" and offers the web (stop condition)

---

## Acceptance criteria

- [x] Inventory-first invariant: AskUserQuestion (Phase 4) precedes any WebFetch/WebSearch
- [x] `DOMAIN_FILTER` validated against `config/topics.yaml` when present; soft-accepted when absent
- [x] `MODE=inventory-only` skips Phase 4 and never hands off / fetches
- [x] Empty candidate set degrades gracefully (NO MATCH + degrade options), never crashes or auto-fetches
- [x] No auto-call of `research-build` — handoff only after the explicit Phase 4 choice
- [ ] Dogfood test on a real cold-start research session (deferred)

---

## Test maintenance

- Update this file on a substantive change to Phase 1.5 (DOMAIN_FILTER), Phase 4 (decision/handoff), or the inventory-first hard rules.
- Re-check the trigger ownership boundary if AGENTS.md reassigns the cold-start "research X" trigger (currently owned by `research-frame`; research-grep runs post-wiki-query only).

## Sources

- [SKILL.md § Workflow + Hard rules](../SKILL.md)
- [rules/common.md](../rules/common.md) — search paths, thresholds, skip conditions
- [references/inventory-and-decision.md](../references/inventory-and-decision.md) — Phase 3/4/5 formats + decision tables
