# research-audit — verification-log template

> **Lazy-load reference.** Phase 7c (Generate verification log) uses this template to write `planning/research/{date}_{slug}.verification-log.md`. SKILL.md holds only the pointer.

---

## Path

`planning/research/{date}_{slug}.verification-log.md` (where `{date}_{slug}` matches the brief).

---

## Frontmatter (mandatory)

```yaml
---
type: audit-report
skill: research-audit
mode: audit
created: {YYYY-MM-DD}
target: {path/to/draft}
severity_summary:
  high: {N — 🔴 unverified claims}
  medium: {N — 🟡 single-source}
  low: {N — 🟢 high-confidence}
gate_status: pass | fail (>30% 🔴 → fail → return to Gather)
---
```

Additional fields (for lifecycle tracking; per the universal markdown frontmatter schema):

```yaml
title: "Verification log — {slug}"
status: active
last_updated: {today}
topic_tags: [{from the brief}]

# Verify-specific
brief_path: planning/research/{date}_{slug}.md
draft_path: {DRAFT_PATH}
verified_at: {today}
verifier: research-audit

# Aggregate granular counts (mirror severity_summary)
total_claims: {total}
green_count: {green}
yellow_count: {yellow}
red_count: {red}
red_pct: {red_pct}
threshold_pct: 30

# Extended mode only — added when grading_mode: extended
grading_mode: standard | extended
levels_distribution:        # only when extended
  high: {n}
  moderate: {n}
  low: {n}
  very_low: {n}
evidence_type_distribution: # always collected, useful audit trail
  peer-reviewed: {n}
  official-doc: {n}
  vendor-blog: {n}
  vendor-marketing: {n}
  trade-press: {n}
  expert-opinion: {n}
  forum-post: {n}
  anon-source: {n}

generated_by: ai
```

---

## Body

```markdown
# Verification log — {slug}

**Draft:** {DRAFT_PATH}
**Brief:** {BRIEF_PATH}
**Gate:** {🟢 PASSED | 🔴 BLOCKED — return to Gather}

## Summary

| Marker | Count | % |
|---|---|---|
| 🟢 confirmed | {green} | {pct}% |
| 🟡 single-source | {yellow} | {pct}% |
| 🔴 unverified | {red} | {pct}% |

## Claim-by-claim

### C1 — {claim text}

- **Type:** numeric / vendor-claim / factual / news
- **Source(s):** {url} (host: {host}, tier: {tier}, age: {days}d)
- **Recency:** {OK | STALE — {days}d old, threshold {threshold}d}
- **Cross-source:** {ok | single-authoritative | unsupported | contradiction}
- **Corroboration (factual/news only):** {independent_sources: N} → {multi (≥2) | single} — distinct registrable domains after same-story collapse (§16). Surfaced downstream (concept `sources:` + digest trust line).
- **Marker:** 🟢 / 🟡 / 🔴
- **Reason:** {short rationale — for factual/news: single-source → capped at 🟡}

[... C2, C3, ...]

## Contradictions

(if any)

### Contradiction #1 — {topic}

- **Source A:** {url} → value X
- **Source B:** {url} → value Y
- **Resolution:** both versions recorded in the final artifact; the claim is marked 🔴

## Unregistered hosts

(if any)

| host | claims_count | proposed_tier | action |
|---|---|---|---|
| {host} | {n} | {AskUserQuestion} | pending |

## Recommended confidence tags

For inline confidence badges in the final artifact (the formatting step can render these as `high`/`medium`/`low` confidence labels):

| Claim ID | Marker | Confidence tag |
|---|---|---|
| C1 | 🟢 | High |
| C2 | 🟡 | Medium |
| C3 | 🔴 | Low |

## Recommendations (for the Gather return, if the gate is blocked)

1. {claim ID} — needs an additional T1/T2 source
2. {claim ID} — recency stale, find a fresher source
3. ...
```
