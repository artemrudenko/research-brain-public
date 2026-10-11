# ADR 0012 — Reader-subagent fan-out (extract, don't dump) for context-bounded synthesis

- **Status:** Accepted (2026-06-26)
- **Tags:** subagents, research-build, context, synthesis

## Context
Users hit context-window exhaustion mid-research. The cause is structural: `research-build`
(standard deep-dives) and `weekly-synthesis` (the unattended internal-corpus loop) read many
**full article bodies** into the **main agent's** context before synthesising. The previous
subagent path only triggered at `depth: deep` AND `>10 sources`, and even then subagents returned
prose "mini-syntheses" while Phase 2b still wrote verbatim raw and Phase 3 re-read it — so the full
bodies reached the main window regardless. Fetching in parallel saved wall-clock but not the window.

## Decision
Adopt a single **reader-subagent contract** ([`skills/research-build/references/reader-contract.md`](../../skills/research-build/references/reader-contract.md))
shared by `research-build` and `weekly-synthesis`:

- **Trigger lowered** to **≥5 synthesis-bound sources, any `depth`** (one subagent per article;
  clusters of 2–4 when >~12, ≤~6 parallel).
- A reader subagent reads the full text and returns a **compact structured extract**
  (`key_claims` / verbatim `quotes` / `data_points` / `contradicts` flags / `dedup_key` /
  `raw_path`), writing the verbatim body to disk. **The main agent never loads full bodies.**
- Phase 2b assembles `raw_*.md` as an **index of fragment paths + extracts**; Phase 3 synthesis
  runs in the main agent on the bounded **extract set** — synthesis stays in the main agent because
  it needs a holistic view, but its input is now small.
- **Deterministic work stays out of the agents:** sanitize (`sanitize_incoming.py`, S1–S9) runs as
  a batch script *before* dispatch so a subagent only ever reads the `sanitized/` companion; URL
  dedup (`normalize_url.py` / `dedup.py`) stays a script.

## Consequences
- The main context window is protected — the actual failure users reported — so a multi-source
  research or a many-article weekly synthesis no longer exhausts it.
- **More total tokens** are spent (parallel subagents) in exchange for main-window survival; the
  trade is taken only at ≥5 sources, where the risk is real.
- Audit trail is per-subagent (fetched URL + `raw_path`, or a `manual-handoff` placeholder),
  preserving the Phase 2b "verifiable basis" rule without the bodies in context.
- The anti-injection guarantee is unchanged: no agent ingests raw untrusted text (CONVENTIONS §12).
- Some extraction nuance can be lost; mitigated by carrying **verbatim quotes** in the extract so a
  later claim never needs the body re-opened.
- A failed reader cluster is logged and skipped (not re-read inline) unless <5 sources remain.

## Alternatives considered
- **Keep sequential reading (status quo).** Rejected — it is the exact cause of context exhaustion.
- **Main agent summarises each source in place.** Rejected — it still loads every full body first.
- **Subagents return prose mini-syntheses (the old dispatch shape).** Rejected — prose is lossy on
  source granularity and the main agent's merge still carries the bulk; the structured-extract
  contract preserves attribution and stays compact.
- **Decouple synthesis into subagents too.** Rejected — synthesis needs a holistic cross-source view
  and cannot be partitioned without losing contradiction resolution.
- **Semantic dedup / security decisions as subagents.** Not adopted: deterministic
  scripts limit variance.

## References
- `skills/research-build/references/reader-contract.md` (the contract) + `references/gather-detail.md`.
- `skills/research-build/SKILL.md` (Phase 2/2b/3), `skills/research-build/AGENTS.md` (dispatch contract).
- `schedule/weekly-synthesis.md` Step 3 (unattended fan-out).
- `skills/research-build/tests/acceptance.md` Scenario 3.
- ADR 0003 (internal-corpus synthesis profile — the unattended path this bounds).
