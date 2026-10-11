---
title: "research-frame — WDM templates (source-selection + thread-selection)"
type: skill-reference
parent_skill: research-frame
created: 2026-06-15
last_updated: 2026-06-15
applies_when: "research-frame Phase 2 sources_mode == hybrid OR web from scratch; research-audit Phase 5 cross-source check claim-selection (cross-skill use)"
---

# WDM templates — Weighted Decision Matrix

> WDM = a generic Pareto-frontier multi-criteria evaluation. The criteria + weights below are sensible defaults; tune them to your workflow.

## Template 1 — Source-selection WDM

> Applied in `research-frame` Phase 2 after the Frame Questionnaire — to shortlist sources before the Gather phase. Applied when `sources_mode == hybrid` or `web from scratch` (where there is a choice between ≥2 candidate sources).

### Criteria + weights

| Criterion | Weight | Score 0-5 rubric |
|---|:-:|---|
| **Authority** | 5 | 5 = vendor primary docs / peer-reviewed; 4 = major trade press; 3 = secondary trade press; 2 = forums (Reddit / HN top thread); 1 = blog without attribution; 0 = anonymous source |
| **Relevance** | 5 | 5 = direct match to research_question; 4 = covers ≥80% scope; 3 = covers ≥50% scope; 2 = tangential but useful; 1 = mentioned only; 0 = off-topic |
| **Accessibility** | 3 | 5 = open access without registration; 4 = open access with registration; 3 = paywall with available digest; 2 = paywall full only; 1 = restricted (vendor confidential); 0 = inaccessible |
| **Recency** | 2 | 5 = within 1mo; 4 = within 3mo; 3 = within 6mo; 2 = within 12mo; 1 = within 24mo; 0 = older than 24mo (or always-volatile + >3mo) |
| **COI (no conflict-of-interest)** | 3 | 5 = fully independent; 4 = mild incentive (sponsor disclosed); 3 = vendor-aligned (vendor's own pub); 2 = sponsored content disclosed; 1 = paid placement disclosed; 0 = COI undisclosed |

**Total weight:** 5+5+3+2+3 = 18.

### Score computation

```
weighted_sum = sum(weight × score_per_criterion)
normalized_score = weighted_sum / total_weight  # 0-5 scale

shortlist_threshold:
  - standard depth: shortlist top-N where normalized_score ≥ 3.5 (~70th percentile)
  - deep dive: shortlist top-N where normalized_score ≥ 3.0 (~60th percentile)
  - quick scan: top-N highest-scoring without threshold (capacity-bound)
```

### Worked example — "AI coding assistant landscape 2026"

Candidate sources (5 evaluated, top-3 selected):

| Source | Authority | Relevance | Access | Recency | COI | Weighted | Norm | Selected? |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| vendor A docs | 5 | 5 | 5 | 5 | 3 | 73 | **4.06** | ✅ |
| vendor B docs | 5 | 5 | 5 | 5 | 3 | 73 | **4.06** | ✅ |
| trade-press analysis 2026-04 | 4 | 4 | 5 | 4 | 5 | 64 | **3.56** | ✅ |
| Reddit megathread | 2 | 4 | 5 | 5 | 4 | 56 | 3.11 | ❌ (below 3.5) |
| sponsored vendor blog post | 5 | 5 | 5 | 4 | 1 | 56 | 3.11 | ❌ (low COI) |

> Top-3 selected for hybrid mode. Reddit drops out on accessibility/COI net cost. Sponsored content drops out on COI even with an otherwise high score — this is **anti-anchoring discipline**.

---

## Template 2 — Thread-selection WDM

> Applied when the research question yields ≥2 distinct "threads" (parallel angles), and you need to decide which threads to investigate deeply vs shallow. Used in research-build Phase 2 (Gather) after the source shortlist is ready.

### Criteria + weights

| Criterion | Weight | Score 0-5 rubric |
|---|:-:|---|
| **Coverage** | 4 | 5 = thread answers ≥80% of research_question; 4 = ≥50%; 3 = ≥30%; 2 = peripheral; 1 = single fact; 0 = unrelated |
| **Diversity** | 3 | 5 = unique angle uncovered by other threads; 4 = mostly unique with overlap ≤30%; 3 = ≥50% unique content; 2 = mostly redundant; 1 = duplicate of another thread |
| **Accessibility** | 3 | 5 = sources for the thread already shortlisted; 4 = sources easily found; 3 = sources require a web search; 2 = paywalled major sources; 1 = unclear if sources exist |
| **Relevance** | 4 | 5 = directly answers research_question; 4 = answers the most important sub-question; 3 = answers a secondary sub-question; 2 = tangential; 1 = informational background only |

**Total weight:** 4+3+3+4 = 14.

### Score computation

```
weighted_sum = sum(weight × score)
normalized_score = weighted_sum / total_weight  # 0-5

prioritization:
  - threads with norm score ≥ 4.0 → DEEP investigate (≥3 sources, full claim extract)
  - threads with norm score 3.0-4.0 → STANDARD (1-2 sources, summary)
  - threads with norm score < 3.0 → SHALLOW (mention only) or DROP
```

### Worked example — "Multi-agent orchestration patterns"

5 threads identified, ranked:

| Thread | Coverage | Diversity | Access | Relevance | Weighted | Norm | Tier |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Native sub-agents (task dispatch) | 5 | 5 | 5 | 5 | 70 | **5.00** | DEEP |
| Preset team library | 4 | 4 | 4 | 4 | 56 | **4.00** | DEEP |
| Deep-research multi-agent team | 4 | 4 | 4 | 4 | 56 | **4.00** | DEEP |
| Council / multi-voice pattern | 4 | 4 | 3 | 3 | 49 | **3.50** | STANDARD |
| Hypothetical custom internal pattern | 3 | 5 | 1 | 3 | 43 | 3.07 | SHALLOW (no concrete sources) |

> Top-3 DEEP investigate. 4th gets standard treatment. 5th dropped due to accessibility=1 (no concrete sources to evaluate).

---

## Cross-skill use — `research-audit` claim-selection

When there are >50 claims in a draft (a large research artifact), `research-audit` Phase 5 (Cross-source check) applies a simplified WDM for claim prioritization (which claims to verify first, which can be batched for a secondary cycle):

### Lightweight claim-selection WDM

| Criterion | Weight | Rubric |
|---|:-:|---|
| **Strategic centrality** | 5 | Thesis claim vs supporting numeric vs context |
| **Risk of falsity** | 3 | High if numeric / vendor / always-volatile; low if a widely-cited common fact |
| **Cost to verify** | 2 | Inverse — if cheap (1 cross-source pass) score high; if expensive score low |

Top-priority claims are verified first; subsequent batches are lower priority. Total weight: 10.

---

## Anti-patterns

- ❌ **A pure number with no reasoning behind it** — WDM scoring without filled criteria = false rigor. Always document the score-per-criterion with a brief rationale.
- ❌ **Manipulating weights to fit a predetermined choice.** Weights must be set BEFORE scoring candidates, not tuned post-hoc.
- ❌ **WDM as a substitute for thinking.** WDM = decision support, not a decision mechanism. Tied scores → human judgment call with explicit reasoning logged.
- ❌ **Applying it to < 3 candidates.** If the choice is 1-2 sources — direct comparison is stronger. WDM ROI kicks in starting at ~3-5 candidates.
- ❌ **Skipping the COI criterion for "objectivity".** The COI weight (3) is intentional — independence matters more than raw authority in multi-perspective research.

## Sources

- WDM concept: generic Pareto-frontier multi-criteria evaluation (decision theory)
- [research-frame SKILL.md § Phase 2 WDM](../SKILL.md) — invocation point
