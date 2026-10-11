---
title: "Research-Audit — Extended Mode Phases (6.5, 6.6, 7.5)"
type: reference
domain: research-quality
created: 2026-05-23
last_updated: 2026-06-15
applies_when: "grading_mode == extended (auto-set when the brief marks a high-stakes / leadership audience) OR explicit manual activation for the adversarial / misinfo / rigor passes"
---

# Research-Audit — Extended Mode Phases

> Lazy-loaded from `SKILL.md`. Contains: the 6-level taxonomy, Phase 6.5 inversion, Phase 6.6 misinfo classifier, Phase 7.5 rigor review. SKILL.md keeps a 3-5 line summary + a pointer to this file.

---

## 6-Level Taxonomy (Phase 6 extended branch)

If `grading_mode == extended` (auto-set when the brief marks a high-stakes / leadership audience, or by manual override) — this **6-level** taxonomy replaces the standard 3-level table:

| Marker | Label | Conditions |
|---|---|---|
| 🟢🟢 **Definitive** | Definitive | ≥3 sources, **ALL T1**, ≥1 peer-reviewed, recency ≤6 mo, cross-confirmed on ≥2 facets, **0 contradictions**. Used for the highest-stakes financial/regulatory/legal claims. |
| 🟢 **High** | High confidence | ≥2 T1 sources, evidence-type ∈ {peer-reviewed, official-doc}, recency strict (≤6 mo), cross-confirmed, no contradictions |
| 🟢- **Moderate** | Moderate confidence | ≥1 T1 source OR ≥2 mixed T1+T2, recency OK, cross-confirmed with no contradictions, evidence-type ∈ {official-doc, vendor-blog, trade-press} |
| 🟡 **Low** | Low confidence | Single T2 OR ≥2 sources T2+T3, recency borderline, supplementary fetch attempted, evidence-type ∈ {trade-press, expert-opinion, forum-post} |
| 🔴 **Very-Low** | Very-low confidence | T3-only OR contradictions OR recency stale OR unregistered with no cross-source OR evidence-type: anon-source |
| ⚫ **Insufficient** | Insufficient | **0 sources** OR claim unverifiable in the current scope (placeholder, manual hand-off pending, scope explicitly excludes verification). NOT the same as Very-Low (which has weak evidence). Used for an honest "we don't know" rather than over-claiming. |

In extended mode the evidence-type is recorded per claim, mandatory (see `rules/common.md` § "Evidence-type taxonomy" for the full list of 8 types and their tier baselines).

**Promotion rules:**
- 🟢 → 🟢🟢 (Definitive): manual upgrade only when ≥3 T1 + peer-reviewed + cross-confirmed; never auto-assigned
- 🔴 → ⚫ (Insufficient): downgrade on detecting "no source attempted" (vs Very-Low "source attempted but failed")

**Standard mode stays unchanged** when `grading_mode != extended` — the 3-level table in SKILL.md Phase 6 is used (regression-safe).

---

## Phase 6.5 — Inversion adversarial pass (extended mode only)

> **Concept:** inversion as a universal cognitive primitive — instead of "how should X work?", ask "what must happen for X to fail?".

### When it activates

- **Auto-activate:** `grading_mode == extended` (auto-set when the brief marks a high-stakes / leadership audience).
- **Manual activate:** an explicit user trigger "run an inversion pass" / "adversarial pass on this research" — even in standard mode.
- **Skip:** `grading_mode != extended` AND no manual trigger — pass straight to Phase 7.

### Procedure

Inversion = "instead of 'how should X work?', ask 'what would have to happen for X to fail?'". The adversarial reframe surfaces hidden assumptions, overconfidence, and gaps in the reasoning chain that standard verify (tier/recency/cross-source) does not catch.

**Step 1 — Identify thesis claims** (1 prompt):
Find the top-3 "thesis claims" in the draft — the central conclusions / recommendations / strategic positions. Not numerics (that's Phase 5), but **synthetic statements** of the form "we should adopt X", "the competitor analysis shows Y is winning", "the market trajectory implies Z".

**Step 2 — Generate inversions** (1 prompt per thesis):
For each thesis claim, generate ≥3 inversion questions:

```
Thesis: "Multi-agent orchestration is the right next step for our research workflow."

Inversion questions:
1. What evidence would convince us multi-agent orchestration is wrong for our scale?
2. What past attempts at multi-agent paradigms in adjacent domains failed, and why?
3. What single-agent pattern, if shown to scale to our needs, would obsolete this thesis?
4. Who has a stake in promoting multi-agent? (COI check on the reasoning chain)
```

**Step 3 — Test thesis robustness:**
For each inversion, a quick check: "is there evidence in our draft material for this inversion?". 4 outcomes:

| Outcome | Marker | Action |
|---|---|---|
| Inversion has no supporting evidence in the draft AND fails common sense | 🟢 robust | thesis withstands inversion — log + proceed |
| Inversion has weak supporting evidence | 🟢- borderline | log specifics, recommend stronger framing in Critique |
| Inversion has moderate supporting evidence — gap visible | 🟡 hedge-required | thesis needs hedge wording / scope limit; recommend in Critique |
| Inversion has strong supporting evidence — thesis falls | 🔴 thesis-broken | **block the transition to formatting**; return to the `research-build` Synthesize phase with instructions to revise the thesis |

**Step 4 — Append to the verification log:**
Add a `## Inversion Pass` section with the structure:

```markdown
## Inversion Pass (extended mode)

### Thesis claims identified

1. {thesis 1 — verbatim quote from the draft}
2. ...

### Inversion findings

| Thesis | Inversion strength | Marker | Recommendation |
|---|---|---|---|
| 1 | weak | 🟢 robust | Proceed; minor framing tighten optional |
| 2 | strong | 🔴 thesis-broken | BLOCK formatting; rewrite thesis after re-Synthesize |

### Detailed inversions per thesis

(per thesis, 2-4 paragraphs with inversion questions + evidence-from-draft + verdict)
```

**Step 5 — Gate decision:**
- ≥1 thesis with a 🔴 thesis-broken marker → **block formatting**, return to Synthesize with specific feedback (consistent with the Phase 7 threshold gate). This overrides the usual 30% rule — **a single broken thesis = block** (thesis-level breaks outrank claim-level statistical thresholds).
- All theses 🟢 / 🟡 → proceed to Phase 7. Yellow recommendations carry forward into the Critique pass.

### Cost & timing

Phase 6.5 runs roughly 5-10 min for 3 theses × 3-4 inversions each (~12 LLM rounds typical). These are strategic reasoning ops — use a capable model. Keep the pass bounded; it is only for extended mode.

### Anti-patterns

- ❌ **Run the inversion pass on standard-mode artifacts.** False positives — drafts for a technical audience do not need strategic adversarial framing; Phase 6.5 is only for extended mode.
- ❌ **Generate inversions without referencing the draft material.** Abstract inversion questions are not adversarial review — they're hypothetical-list generation. Each inversion must be testable against the draft evidence.
- ❌ **Treat 🟡 hedge-required as 🔴 block.** 🟡 = the thesis is valid but needs a scope hedge — the Critique pass catches the framing issue without blocking the production cycle.
- ❌ **Skip Step 4 documentation.** Without a verification-log section, future readers cannot verify the inversion pass was actually run vs claimed-but-not-done.

### Worked example

See [`examples.md`](examples.md) § Example 5 "Inversion adversarial pass".

---

## Phase 6.6 — 4-category misinformation classifier (extended mode only)

### When it activates

- **Auto-activate:** `grading_mode == extended` (auto-set when the brief marks a high-stakes / leadership audience)
- **Manual activate:** an explicit user trigger "run the misinfo classifier" / "check for false claims"
- **Skip:** standard mode AND no manual trigger

### Procedure

Phase 6 markers catch **evidence quality** (is there confirmation?). Phase 6.6 catches **claim integrity** (does the claim correctly represent the source?). These are orthogonal — an evidence-quality 🟢 does not guarantee the absence of misinfo (correct source, mis-quoted claim).

**Step 1 — Per-claim misinfo classification** (1 prompt):

For each 🟢🟢/🟢/🟢-/🟡 claim, check against the 4 misinfo categories:

| Category | Marker | Definition | Detection signal |
|---|---|---|---|
| 🚨 **Fabrication** | F | Claim invented — no correspondence to the source. Hallucinated stat / quote / event. | Source URL does not contain the phrase/number; quote attribution wrong; event date does not match the source |
| ⚠️ **Distortion** | D | Source exists and says something related, but the claim mis-quotes — numbers altered, context stripped, scope changed | Source says "X grew 12% YoY", claim says "X doubled"; scope mismatch (source: "in the EU", claim: "globally") |
| 📅 **Outdated** | O | Claim was true historically, now stale | Standard deprecated, product retired, statistic from >5y ago without a "historical" framing, regulation superseded |
| 🔀 **Conflation** | C | Multiple distinct concepts merged | Different studies fused; vendor + product mixed; concept conflated with a related-but-distinct one |

**Step 2 — Append to the verification log:**

In extended mode the verification log gets a `## Misinfo Classification (Phase 6.6)` section:

```markdown
## Misinfo Classification (Phase 6.6, extended mode)

### Per-claim audit

| Claim # | Marker (P6) | Misinfo? | Category | Detection rationale |
|---|---|---|---|---|
| 12 | 🟢 High | YES | 📅 Outdated | Cites a standard's audit cycle as "12-month" — was true for v1.0, now "18-month" per the v1.1 amendment |
| 17 | 🟢- Moderate | YES | 🔀 Conflation | Conflates two distinct product ecosystems on adjacent domains |
| other claims | — | NO | — | clean |

### Distribution

- 🚨 Fabrication: 0
- ⚠️ Distortion: 0
- 📅 Outdated: 1
- 🔀 Conflation: 1
- Total flagged: 2 / 23 claims (8.7%)
```

**Step 3 — Gate decision:**

- **Hard rule:** ≥1 🚨 Fabrication = **block the transition to formatting**. Fabrication = a trust breach, requiring a source fix or claim removal before production.
- **Soft rule:** ≥3 total misinfo flags (any category) = recommend a Critique-pass review for a structural issue (likely a systemic problem, not an isolated incident).
- **Otherwise:** proceed to Phase 7. Misinfo flags carry forward into Critique for wording fixes.

### Cost & timing

Phase 6.6 runs roughly 3-5 min for 20-30 claims (1 batch prompt with structured output). This is a fast op — a lightweight model suffices.

### Anti-patterns

- ❌ **Treat a misinfo flag as an evidence-quality issue.** Phase 6 catches quality (got the source); Phase 6.6 catches integrity (correct quote). Different orthogonal concerns.
- ❌ **Skip 🟡 Low claims in Phase 6.6.** Distortion is often prevalent in low-confidence claims — secondary citations cite the primary incorrectly.
- ❌ **Flag without a specific detection rationale.** Without a rationale, future readers cannot verify or contest the flag.
- ❌ **Auto-block on the soft rule (3+ flags).** The soft rule is a recommendation for Critique; only Fabrication is auto-block.

---

## Phase 7.5 — 6-dim rigor reviewer (extended mode only)

> **Concept:** an artifact-level rigor review adapting the GRADE methodology to six dimensions.

### When it activates

- **Auto-activate:** `grading_mode == extended` (auto-set when the brief marks a high-stakes / leadership audience)
- **Manual activate:** an explicit user trigger "run a rigor review" / "6-dim audit"
- **Skip:** standard mode AND no manual trigger — pass straight to Critique

### Purpose vs other phases

| Phase | What it checks | Granularity |
|---|---|---|
| Phase 6 | **Evidence quality** per claim (tier/recency/cross-source) | per-claim |
| Phase 6.5 | **Thesis robustness** (inversion) | per-thesis |
| Phase 6.6 | **Claim integrity** (misinfo categories) | per-claim |
| **Phase 7.5** | **Artifact-level rigor** (6 dimensions) | whole-document |

Phase 7.5 is a meta-pass. It uses the verification-log metadata (Phase 7 output) for a structured assessment of the whole artifact across 6 rigor dimensions.

### Procedure

**Step 1 — Score 6 dimensions (1 prompt):**

For the draft artifact (full read) + the verification log (per-claim outcomes), score each dimension on a 4-level scale (1-4). Output: a structured rubric with a rationale per dimension.

| # | Dimension | What we check | 4-level scale |
|---|---|---|---|
| **D1** | **Clarity** | Claims unambiguous · terminology defined · jargon controlled · structure navigable | 1=ambiguous-everywhere / 2=mixed / 3=mostly-clear / 4=consistently-clear |
| **D2** | **Accuracy** | Phase 6 markers + Phase 6.6 misinfo flags aggregated | 1=>30% Very-Low / 2=15-30% / 3=5-15% / 4=<5% |
| **D3** | **Completeness** | All relevant aspects covered · scope gaps documented · counter-evidence acknowledged | 1=major-gaps / 2=some-gaps / 3=mostly-complete / 4=comprehensive |
| **D4** | **Objectivity** | POV-balanced · not leading-thesis-then-justify · counter-arguments addressed (inversion residue) | 1=advocacy-piece / 2=biased-but-evidenced / 3=mostly-balanced / 4=fully-balanced |
| **D5** | **Actionability** | Decisions can be made on this · specific deliverables / next steps · ambiguity in recommendations | 1=non-actionable / 2=vague-recs / 3=mostly-actionable / 4=specific-actionable |
| **D6** | **Source-quality** | Phase 6 evidence-type distribution · diversity (not single-source-heavy) · recency · authoritativeness | 1=>50% T3 or anon / 2=mostly-T2 / 3=balanced-T1+T2 / 4=≥60% T1 + diverse |

**Step 2 — Compute the aggregate rigor score:**

```
rigor_score = sum(D1-D6) / 24 * 100   # percentage 0-100
```

| Score range | Verdict | Action |
|---|---|---|
| ≥85% | 🟢 Strong rigor | Proceed to Critique without mandatory revisions |
| 70-84% | 🟡 Adequate rigor | Critique pass mandatory; 1-2 dimensions targeted |
| 55-69% | 🟠 Marginal rigor | Mandatory revision pass: address the ≥2 weakest dimensions before formatting |
| <55% | 🔴 Insufficient rigor | **Block the transition to formatting** — return to Synthesize with specific dimension-level feedback |

**Step 3 — Append to the verification log:**

In extended mode the verification log gets a `## Rigor Review (Phase 7.5)` section:

```markdown
## Rigor Review (Phase 7.5, extended mode)

### 6-dimension scores

| Dim | Score | Rationale |
|---|---|---|
| D1 Clarity | 4/4 | Claims unambiguous; key terms defined in the summary; structure follows the expected brief schema |
| D2 Accuracy | 3/4 | Phase 6: 23 claims, 0 Very-Low, 2 misinfo flags (1 Outdated, 1 Conflation, P6.6) |
| D3 Completeness | 3/4 | Major gap: a related framework not addressed (acknowledged in Open Questions) |
| D4 Objectivity | 4/4 | Counter-arguments addressed (Anti-patterns section); no leading thesis |
| D5 Actionability | 4/4 | 4 fixed deliverables · 7 discovery questions · clear scope per layer |
| D6 Source-quality | 4/4 | 12 sources: 8× T1 (standards / deep dives), 0 T3, evidence-type diverse |

### Aggregate

- **Rigor score: 22/24 = 92%** 🟢 Strong rigor
- **Verdict:** Proceed to Critique without mandatory revisions; minor framing tighten in D3 optional
```

**Step 4 — Update the verification-log frontmatter:**

```yaml
rigor_review:
  enabled: true
  score: 22/24
  pct: 92
  verdict: strong  # strong | adequate | marginal | insufficient
  weakest_dim: D3
  scores:
    d1_clarity: 4
    d2_accuracy: 3
    d3_completeness: 3
    d4_objectivity: 4
    d5_actionability: 4
    d6_source_quality: 4
```

### Cost & timing

Phase 7.5 runs roughly 5-8 min for a full artifact read + verification-log read + 6-dim scoring (1 batch prompt). This is a strategic op — use a capable model.

### Anti-patterns

- ❌ **Score without reading the verification log.** D2 + D6 scores derive from the Phase 6/6.6 data — without it, scoring is speculative
- ❌ **Treat marginal (55-69%) as acceptable.** Marginal = a mandatory revision pass; not "good enough"
- ❌ **Score the artifact without a full read.** D3 (completeness) cannot be scored from a skim — a full read is needed to detect scope gaps
- ❌ **Skip the rationale.** A single number without a rationale is not auditable; future reviewers cannot verify or contest it
