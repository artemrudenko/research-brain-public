---
title: "research-audit — worked examples reference"
type: skill-reference
domain: meta-process
parent_skill: research-audit
created: 2026-05-02
last_updated: 2026-06-15
---

# research-audit — example runs

> **Lazy-load reference.** 5 worked examples (full-mode pass, blocked, chat-answer light, extended mode, inversion adversarial pass). SKILL.md holds the pointer.

---

## Example run — full mode

**User:** "Check the facts in `pipeline/3-synthesis/tool-comparison.md` before shipping"

**Phase 1:**
- Read draft → 12 claims extracted (4 numeric, 6 vendor-claims, 2 factual statements)
- Read brief `planning/research/2026-05-02_tool-comparison.md` → format=document, recency_max=12mo, min_tier=T1+T2

**Phase 2-6:**
- 8 claims supported by vendor primary docs (T1) — 6× 🟢 (cross-source with trade press), 2× 🟡 (single T1, no secondary)
- 2 numeric claims from an analyst report (T2) — 1× 🟢 (with T1 cross-confirmation), 1× 🟡 (single T2)
- 1 vendor-claim from a forum thread (T3) — supplementary fetch succeeded (vendor docs confirmed) → 🟢
- 1 vendor-claim from a blog with no registry record → unregistered → flagged for AskUserQuestion

**Phase 7:**
- aggregate: 8× 🟢, 3× 🟡, 1× 🔴 (unregistered) → red_pct=8.3%, gate_status=passed
- Write `planning/research/2026-05-02_tool-comparison.verification-log.md`
- AskUserQuestion: "New host `someblog.dev` — tier?" → user picks T2 → registry updated
- Update brief `verification_log` field + lifecycle checkbox

**Result:** the caller (the `research-build` Critique pass) receives the signal `gate=passed, red_pct=8.3%` and continues to Critique.

---

## Example run — blocked

**User:** "Check the draft `pipeline/3-synthesis/market-trends.md`"

**Phase 1-6:**
- 15 claims extracted
- 4× 🟢, 5× 🟡, 6× 🔴 (5 stale, 1 contradiction) → red_pct=40%

**Phase 7:**
- gate_status=blocked, log written, brief updated with lifecycle checkbox `- [x] **Verify** — verification_log.md (BLOCKED)`
- Return to the caller: "> 30% of claims unverified (40%). Returning to Gather. Weak claims:
  - C3: stale (24 mo old, threshold 12 mo) — needs a fresh source
  - C5: contradiction between two analyst sources — pick one + explicit note
  - ...
  Recommendation: re-fetch C3, C7, C9 with updated dates; resolve the C5 contradiction; add a T1 source for C12, C14."

Critique / formatting do not run.

---

## Example run — chat-answer light

**User:** "What's the latest version of tool X? Quick answer." (Frame → format=chat-answer)

**Phase 1:**
- Brief format=chat-answer → Light mode
- Draft = a chat response with 1 link to the vendor docs (T1)

**Phase 7 (light):**
- Tier audit: 1× T1, 0× T3 → clean
- Recency: the cited release date matches recency
- Inline summary in chat: "Tier OK (1× T1). Safe to answer."
- No verification-log file written.

---

## Example run — extended mode

**User:** "Check the facts in `pipeline/3-synthesis/decision-brief.md` — for a leadership deck"

**Phase 1:**
- Read draft → 18 claims extracted (8 numeric, 6 vendor-claims, 4 factual statements)
- Read brief `planning/research/2026-05-15_decision-brief.md` → format=presentation, audience=leadership, recency_max=6mo, min_tier=T1+T2, **grading_mode=extended** (auto-set by audience)

**Phase 2-5:** standard cycle, plus an evidence-type tag per claim (peer-reviewed / official-doc / vendor-blog / etc.)

**Phase 6 (extended branch):**
- 6 claims: 2 T1 sources (peer-reviewed research + official vendor docs), recency 3mo, cross-confirmed → 🟢 **High**
- 5 claims: 1 T1 vendor blog, recency 4mo, no cross-source needed (vendor primary) → 🟢- **Moderate**
- 4 claims: T2 trade press (two outlets combined), recency 5mo → 🟡 **Low**
- 3 claims: T3 forum post + 1 contradiction + 1 stale 24mo → 🔴 **Very-Low**

**Phase 7:**
- Aggregate: high=6, moderate=5, low=4, very_low=3 → very_low_pct=16.7%, gate_status=passed
- Write `planning/research/2026-05-15_decision-brief.verification-log.md` with extended frontmatter (`grading_mode: extended`, `levels_distribution`, `evidence_type_distribution`)
- Update brief `verification_log` field + lifecycle checkbox

**Result:** the leadership deck gets 18 claims with distinct labels (high/moderate/low/very-low) + an evidence-type per claim — granularity sufficient for decision-grade scrutiny. Standard mode does not produce this granularity by default.

---

## Example 5 — Inversion adversarial pass

> **Concept:** inversion as a universal cognitive primitive — instead of asking "how should X succeed?", ask "what would have to happen for X to fail?".
>
> **Why it adds value:** the example below comes from a research session where Phase 1-6 baseline Verify passed cleanly (claim-level red rate ~0.6%), yet the extended-mode inversion pass surfaced two broken theses.

### Setup

- **Draft:** `pipeline/3-synthesis/strategy-analysis.md` (initial state, before the critique log)
- **research-brief:** `planning/research/2026-05-09_strategy-analysis.md`
- **`audience: leadership`** → `grading_mode: extended` auto-set → Phase 6.5 auto-activates
- **Phase 1-6 already passed:** verification log shows 0.6% red — claim-level Verify clean

### Step 1 — Identify thesis claims

Top-3 thesis claims from the draft:

1. **Thesis A:** "Adopt all 30 roadmap items — it's a portfolio cherry-pick, and each has its own triggered activation."
2. **Thesis B:** "The 48-item → 30-item reduction via conflict resolution dropped non-essential overlaps at no cost."
3. **Thesis C:** "The Wave 3 patterns (multi-agent orchestration) extend the operating model without operational drift."

### Step 2 — Generate inversions

**Thesis A inversions:**

1. What if the "portfolio cherry-pick" framing rationalizes adopting too many patterns regardless of fit?
2. What past decisions to add 5+ items in a quarter showed regression in discoverability / cognitive load?
3. Who profits from a 30-item adoption rate? (COI: the researcher and the LLM session are both incentivized toward large-surface adoption)
4. If we adopted only the top-5 highest-value patterns, what would we lose?

**Thesis B inversions:**

1. What if "conflict resolution" reduced 18 items not because they were redundant, but because we mis-classified them as overlapping?
2. Did the merged group (5 items → 1 deliverable, claimed savings) actually save effort, or did the merge hide complexity?
3. What if some "conflicts" were genuinely complementary patterns mis-judged as redundant?

**Thesis C inversions:**

1. What does the system look like in 6 months if 30 items are implemented? (Is it still "lean", or has it become a platform?)
2. Does the multi-agent paradigm fit the actual workflows, or are we adopting it because the pattern is impressive in research synthesis?
3. What if the edge comes precisely from the single-agent paradigm, and multi-agent adoption erodes the differentiator?

### Step 3 — Test thesis robustness

| Thesis | Inversion strength | Marker | Reasoning |
|---|---|---|---|
| **A** Adopt all 30 | strong | 🔴 thesis-broken | Inversions 1+3 well-supported: the research session itself was biased (12 high-star repos selected, no lean-methodology repo); COI obvious. |
| **B** 48→30 reduction without cost | moderate | 🟡 hedge-required | Inversion 2 partially evidenced: the merged group claimed combined effort but isolated items summed differently. |
| **C** Wave 3 extends without operational drift | strong | 🔴 thesis-broken | Inversion 1 specifically calls out: 30 items + multi-agent + new governance overhead = a medium-weight platform, not a lean system. |

### Step 4 — Verification-log section appended

```markdown
## Inversion Pass (extended mode)

### Inversion findings

| Thesis | Inversion strength | Marker | Recommendation |
|---|---|---|---|
| A | strong | 🔴 thesis-broken | BLOCK formatting. Re-Synthesize: lean cherry-pick (Wave 0+1 only); Wave 2/3 → deferred backlog. |
| B | moderate | 🟡 hedge-required | Hedge the wording. Bump the merged-group effort estimate. |
| C | strong | 🔴 thesis-broken | BLOCK formatting. Document the explicit single-agent paradigm; gate Wave 3 multi-agent behind a trigger only. |
```

### Step 5 — Gate decision

**2 thesis-broken markers (A + C)** → block the transition to formatting. Return to the `research-build` Synthesize phase.

### Why the inversion pass added value (over baseline Verify)

Phase 1-6 baseline Verify passed with 0.6% red (claim-level). Without Phase 6.5, the synthesis would have gone to formatting with two thesis-broken positions. The inversion pass surfaced strategic-level gaps that claim-level research-audit does not catch:

- Selection bias in the repo set (Phase 0 selection bias is not fact-checkable)
- COI (the researcher's incentive to expand the adoption rate)
- Operating-model drift (operational consequences of architectural choices)
- Negative arbitrage (the merge increased effort, not reduced it)

### Cost of the inversion pass

- Step 1 (3 thesis identification): 1 prompt
- Step 2 (9-12 inversions generation): 3 prompts referencing the draft
- Step 3 (robustness testing): 1 aggregation prompt
- Step 4 (append log section): 1 write

Roughly 6 LLM rounds total. Acceptable for high-stakes deliverables — a few prompts can prevent weeks of misaligned implementation work.
