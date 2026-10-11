---
title: "Research-Audit — Verify phases detail (claim extraction, tier lookup, recency, cross-source, markers)"
type: reference
domain: meta-process
last_updated: 2026-06-16
applies_when: "Phase 2 claim categories / Phase 3 tier lookup edge cases / Phase 4 recency math / Phase 5 cross-source pseudocode + subagent dispatch / Phase 6 marker rules"
---

# Verify phases detail

> Lazy-loaded from `SKILL.md`. SKILL.md keeps the phase summary; full procedures here.

## Phase 2 — Verifiable claim categories

**Verifiable:** Numeric (statistics, percentages, market share, benchmarks, deadlines, versions, prices, limits) · Vendor-claim (features, presence of a function, release date, support/compatibility) · Factual statement / news (unambiguously checkable: X did Y; a reported event) — `type: factual` or `type: news`; both routed through Phase 5b independence-counted corroboration · Quoted figure (a claim attributed to a source with a number).

**NOT verifiable:** Subjective ("better", "more convenient") · Opinion/interpretation · Context-only without specifics · Recommendation · Hypothesis/projection without attribution.

**Output:** `claims_list = [{id, text, type, source_ref, host}]` (ID incrementing `C1`, `C2`).

## Phase 3 — Tier lookup edge cases

```
if host in registry: tier = registry[host].tier  # T1 | T2 | T3
else: tier = "unregistered"  # T3 + flag for AskUserQuestion (Phase 7)
```

- Vendor sub-host (`docs.{vendor}.com` vs `{vendor}.com/news`) — separate rows, possibly different tiers (docs T1, news T1, marketing T2/T3)
- GitHub repos `github.com/{org}/{repo}` — vendor repos T1, community T3 (default T3, requires evaluation)
- Host not found AND the source is critical → `unregistered_critical` for a priority AskUserQuestion

## Phase 4 — Recency math

1. Read `published` from `materials/raw/{archive}.md`; fall back to `fetched_at`.
2. `age_days = today - published_or_fetched_date`.
3. Compare with `recency_max`: `3mo`→90 · `6mo`→180 · `12mo`→365 · `24mo`→730 · `unlimited`→skip.
4. `age_days > threshold` → flag `recency_stale = true`.

**Always-volatile override:** an always-volatile keyword in `research_question`/`claim.text` → threshold **3mo regardless of the brief `recency_max`**.

## Phase 5 — Cross-source corroboration (numeric + vendor-claim + factual/news)

### 5a — numeric + vendor-claim (tier-based, UNCHANGED)

```
for claim in claims_list:
    if claim.type not in ("numeric", "vendor-claim"): continue
    sources_for_claim = find_all_supporting_sources(claim)
    if len(sources_for_claim) >= 2 and any(s.tier in ("T1","T2") for s in sources_for_claim):
        claim.cross_source = "ok"
    elif len(sources_for_claim) == 1:
        if sources_for_claim[0].tier in ("T1","T2"):
            claim.cross_source = "single-authoritative"
        else:
            attempt_supplementary_fetch(claim)  # via source-archive (Phase 2 fetch chain)
    else:
        claim.cross_source = "unsupported"
```

A supplementary fetch is delegated to `source-archive` (never fetch directly). On success — update `claims_list[i].sources` and re-evaluate.

**Contradiction handling:** a supplementary source gives a different value → do not choose the convenient version; record both explicitly (the "Contradictions" section); marker → 🔴 unverified.

### 5b — factual / news: support and provenance — CONVENTIONS §16

1. Read the passages that support the exact claim; a relevant URL or topic is insufficient.
2. Derive the publisher-group proxy from source URLs, optionally grouping lexical
   near-duplicates. The `independent_sources` log field keeps its historical name but records
   this proxy only. Text similarity cannot establish evidentiary independence.
3. Trace whether the supporting passages share an upstream report, press release, dataset or
   original observation. Record `independence_review: unknown` when this is not established;
   otherwise record the actual assessment and its source evidence in prose.
4. At least two independently supporting sources, applicable recency and no contradiction
   are required for factual/news 🟢 eligibility. Unknown independence or one upstream source
   retains 🟡. No supporting evidence or a material contradiction follows the usual 🔴 rule.
   Soft mode annotates these limitations without blocking on the coverage signal.

The digest renders a publisher-diversity line from `sources:`. It does not turn this proxy
into factual confirmation, even when similar texts were collapsed. A claim-level review is
separate and cites the passages it actually inspected.

**Contradiction handling:** record incompatible supported claims explicitly; do not choose
whichever version is convenient. Marker → 🔴 unverified.

### Subagent dispatch

**Trigger:** > 20 verifiable claims. Group by category (vendor / numeric / regulatory / factual) → dispatch 2-4 parallel subagents. Each: tier lookup + recency + supplementary fetches (via source-archive) → returns (1) partial verification entries (🟢/🟡/🔴 per claim), (2) an explicit list of supplementary URLs + `materials/raw/...` paths (audit trail), (3) contradictions. The main agent merges them into the final verification log with aggregate stats. ≤20 claims — sequential.

## Phase 6 — Marker rules

| Marker | Conditions |
|---|---|
| 🟢 confirmed | ≥2 sources AND ≥1 source tier ∈ (T1, T2) AND recency OK AND no contradiction |
| 🟡 single-source | 1 source AND tier ∈ (T1, T2) AND recency OK |
| 🔴 unverified | T3 only OR unregistered only OR contradiction OR recency stale OR ≥2 sources but all T3 |

- **Numeric claim with 1×T1** → automatically 🟡 (numeric requires cross-source; a single T1 is not enough for 🟢, but not 🔴 either if the tier is high + recency OK).
- **Vendor-claim:** a vendor's own docs at T1 = 🟢 (primary source by definition); vendor blog T1 → 🟢; secondary trade press without vendor confirmation → 🟡.
- **Factual/news claim (per §16):** at least two independently supporting sources established by passage and upstream-provenance review, recency OK and no contradiction → 🟢 eligible. Domain counts and text deduplication alone are insufficient. Unknown independence or one upstream source → 🟡; no supporting evidence, material contradiction or stale recency → 🔴. Tier rules do not substitute for this support/provenance check.
- Extended edge cases: [tier-rules.md](tier-rules.md).
