# research-audit — Common Rules

Platform-agnostic rules for the skill. SKILL.md references this file in Phase 0.

---

## Paths

- **Input draft:** usually `pipeline/3-synthesis/{slug}.md` (md-first)
- **Input brief:** `planning/research/{YYYY-MM-DD}_{slug}.md`
- **Output verification log:** `planning/research/{YYYY-MM-DD}_{slug}.verification-log.md`
- **Trusted registry:** `sources/trusted-registry.md` (OPTIONAL — used for tier lookup in FULL mode if present; absence triggers SOFT mode, where tier-grading is skipped, NOT "everything T3". Per `docs/CONVENTIONS.md` §10)
- **Always-volatile domains:** `sources/always-volatile-domains.md` (OPTIONAL — recency override if present; absence → recency uses the brief/default window only)
- **Frontmatter spec:** `docs/CONVENTIONS.md` §5 / §5.1 (universal + type-specific extensions)
- **Source archives:** `materials/raw/*.md` (for the recency lookup via `published` / `fetched_at`)

All three files of one research cycle (`brief`, `verification-log`, `critique-log`) share the same `{date}_{slug}` prefix — for pair-linking.

---

## Threshold values (single point of change)

| Field | Value | Source |
|---|---|---|
| `RED_THRESHOLD_PCT` | 30 | starting value, tunable |
| `RECENCY_3MO_DAYS` | 90 | always-volatile + brief recency_max=3mo |
| `RECENCY_6MO_DAYS` | 180 | brief recency_max=6mo |
| `RECENCY_12MO_DAYS` | 365 | brief recency_max=12mo (default) |
| `RECENCY_24MO_DAYS` | 730 | brief recency_max=24mo |
| `LIGHT_MODE_RECENT_LOG_HOURS` | 24 | reuse an existing log if fresh |

Changing these values → edit only this file. SKILL.md and references/ reference this registry.

---

## Verifiable claim patterns

### Numeric

Triggers (regex, case-insensitive):

- Numbers with units: `\d+%`, `\d+\s?(million|billion|thousand|MB|GB|TB|tokens|requests)`
- Version numbers: `v?\d+\.\d+(\.\d+)?`
- Dates in numeric contexts: `Q[1-4]\s?20\d{2}`, `20\d{2}`
- Currency: `\$\d+`, `€\d+`, `\d+\s?(USD|EUR)`

### Vendor-claim

Triggers:

- Verb patterns: "X supports Y", "X has Y", "X integrates with Y", "X will introduce Y", "X released Y", "X launched Y"
- Pricing: "X costs", "X tier", "free tier", "context window"
- Compatibility: "works with", "compatible", "supports"
- Release: "shipped", "released", "launched"

### Factual statement

- "X did Y" / "Y was adopted by X"
- Attribution: "according to X", "per Y", "X reports"
- Quoted figures: a number + an explicit attribution to a source

### Non-verifiable (skip)

- Subjective: "better", "more convenient", "more mature", "more performant" (without specific benchmarks)
- Opinions: "this means", "probably", "one can expect"
- Recommendations: "better to pick X for team Y" (that's inference, not fact)
- General context: "the market is growing", "more and more teams" (without specifics)

---

## Tier inference for unregistered hosts (default treatment)

When a `host` is not found in `sources/trusted-registry.md`:

- **Default tier:** `T3` (treat as community/opinion)
- **Flag:** `unregistered: true` for AskUserQuestion after the log write
- **If the host is clearly vendor docs (`docs.{product}.com`):** suggested_tier=T1 in the AskUserQuestion (but the default stays T3 until confirmation)
- **If the host is clearly a community site (forum, aggregator):** already in the registry, tier T3 — not unregistered
- **Subdomain heuristic:** `blog.{host}` or `news.{host}` — usually T1/T2 if the parent is a T1 vendor

---

## Recency — formula

```python
def is_stale(claim, brief):
    # Always-volatile keyword check first
    if has_always_volatile_keyword(claim.text):
        threshold_days = 90  # 3mo override
    else:
        threshold_days = {
            "3mo": 90, "6mo": 180, "12mo": 365, "24mo": 730, "unlimited": None
        }[brief.recency_max]

    if threshold_days is None:
        return False

    source_date = claim.source.published or claim.source.fetched_at
    if source_date is None:
        return None  # unknown — flag separately, not auto-stale

    age_days = (today - source_date).days
    return age_days > threshold_days
```

**Edge cases:**

- `published` unknown, `fetched_at` < 30 days ago → assume fresh (just fetched — content current)
- `published` unknown, `fetched_at` > 90 days ago → flag as "recency-unknown" (treat as stale in strict mode, soft warning in default mode)
- `published` in the future (clock skew or typo) → log a warning, treat as today

---

## Cross-source thresholds

| Claim type | Min sources | Tier requirement | Default marker if met |
|---|---|---|---|
| numeric | 2 | ≥1 from {T1, T2} | 🟢 |
| numeric | 1 | T1 vendor docs OR T2 authoritative | 🟡 |
| numeric | 1 | T3 / unregistered | 🔴 (try a supplementary fetch first) |
| vendor-claim about own product | 1 | vendor's primary docs (T1) | 🟢 |
| vendor-claim about a competitor | 2 | ≥1 from {T1, T2} | 🟢 |
| vendor-claim about a competitor | 1 | T1 only | 🟡 |
| factual statement | 1 | T1 | 🟢 |
| factual statement | 1 | T2 | 🟡 |
| factual statement | 1 | T3 / unregistered | 🔴 |

**Vendor's own primary docs**: a claim about product X citing `docs.x.com` or `x.com` — vendor primary, a single source suffices.

**Vendor about a competitor**: a claim about a competitor's product citing the vendor's blog (where the vendor may benchmark dishonestly) — requires cross-source (a third party).

---

## Extended mode (opt-in)

Activated when `grading_mode: extended` in the brief. Auto-set when the brief marks a high-stakes / leadership audience.

### Extended mode levels (4-level scale)

| Marker | Label | Threshold logic |
|---|---|---|
| 🟢 High | high | ≥2 T1 sources, evidence-type ∈ {peer-reviewed, official-doc}, recency ≤6mo, cross-confirmed, no contradictions |
| 🟢- Moderate | moderate | ≥1 T1 OR ≥2 mixed T1+T2, recency OK, no contradictions, evidence-type ∈ {official-doc, vendor-blog, trade-press} |
| 🟡 Low | low | Single T2 OR ≥2 T2+T3, recency borderline, supplementary fetch attempted, evidence-type ∈ {trade-press, expert-opinion, forum-post} |
| 🔴 Very-Low | very_low | T3-only OR contradictions OR stale OR unregistered with no cross-source OR evidence-type: anon-source |

`RED_THRESHOLD_PCT` is reused as the `very_low_pct` threshold gate in extended mode (semantically — a bottom-tier threshold).

### Evidence-type taxonomy (always collected, both modes)

8 types with a tier baseline. Affects marker computation **only in extended** mode; in standard mode the tag is collected but does not change the existing 3-tier logic.

| Type | Tier baseline | Examples |
|---|---|---|
| `peer-reviewed` | T1 | Nature, Science, NeurIPS, ICLR, ACL, AAAI, reviewed standards |
| `official-doc` | T1 | `docs.{vendor}.com`, RFC, ISO/NIST/EU standards, regulator portals |
| `vendor-blog` | T1 | `{vendor}.com/news`, `{vendor}.com/blog`, vendor announcements |
| `vendor-marketing` | T2 | sales pages, product positioning, pricing pages, landing pages with claims but no data |
| `trade-press` | T2 | established technology / business news outlets |
| `expert-opinion` | T2-T3 | recognised practitioners with a track record |
| `forum-post` | T3 | discussion forums, Q&A accepted answers (signal, not fact) |
| `anon-source` | T3 | unattributed claims, leaked memos, anonymous threads |

The tier baseline is a starting point; it can be downgraded per the existing tier-rules edge cases (vendor about a competitor, marketing language without data, etc.). Full evidence-type → tier downgrade rules: `references/tier-rules.md` § "Evidence-type taxonomy — extended rules".

### Extended-mode frontmatter

Added to the verification-log frontmatter when `grading_mode == extended`:

```yaml
grading_mode: extended
levels_distribution:
  high: N
  moderate: N
  low: N
  very_low: N
evidence_type_distribution:
  peer-reviewed: N
  official-doc: N
  ...
```

Standard-mode frontmatter stays unchanged.

---

## Verification-log frontmatter — mandatory fields

Per `docs/CONVENTIONS.md` §5 / §5.1 (universal + type:log extensions):

```yaml
---
title: "Verification log — {slug}"
type: audit-report
status: active
created: {today}
last_updated: {today}
topic_tags: [{from the brief}]

# Verify-specific
brief_path: planning/research/{date}_{slug}.md
draft_path: {DRAFT_PATH}
verified_at: {today}
verifier: research-audit
gate_status: passed | blocked

total_claims: {n}
green_count: {n}
yellow_count: {n}
red_count: {n}
red_pct: {decimal}
threshold_pct: 30

contradictions_count: {n}
unregistered_hosts_count: {n}

generated_by: ai
---
```

If someone re-runs research-audit — `last_updated` updates; the original `verified_at` records the first verify timestamp (via `audit_history` on a rerun).

---

## AskUserQuestion templates

### Unregistered host detected

```
Phase: 7d
Header: "New host: {host}"
Body: "Host `{host}` appears in {n} claims in draft `{draft_short}`,
       not found in sources/trusted-registry.md. Which tier?"
Options:
  - T1 (vendor docs / NIST / peer-reviewed)
  - T2 (analyst / authoritative blog / trade press)
  - T3 (community / opinion)
  - Skip (leave unregistered, the claim stays 🔴)
```

### Threshold gate manual override (anti-pattern, requires explicit confirmation)

```
Phase: 7b
Header: "> 30% unverified — override?"
Body: "red_pct={red_pct}% > threshold 30%. The transition to formatting is blocked.
       We strongly recommend returning to Gather. Override is disabled by default;
       if strictly necessary (a deadline, etc.) it can be forced — but the decision
       is logged in the frontmatter override-history with a rationale."
Options:
  - Return to Gather (default, recommended)
  - Forced override — continue to formatting (a rationale is required)
```

A forced override is logged in the frontmatter:

```yaml
override:
  forced_at: {timestamp}
  reason: "{user-provided}"
  approved_by: user
```

### Contradiction detected

```
Header: "Contradiction: {topic}"
Body: "Source A ({url_a}, tier {tier_a}) → value X.
       Source B ({url_b}, tier {tier_b}) → value Y.
       This is a conflict; per the rules, do not pick the convenient version.
       How to record it in the final artifact?"
Options:
  - Both versions explicit (recommended, the claim stays 🔴)
  - Pick one + note (if there is a rationale: a T1 vs T2 disparity)
  - Drop the claim (if it is not critical to the artifact's thesis)
```

---

## Light mode (chat-answer)

Activated when `format == chat-answer` in the brief.

**Procedure:**

1. Skip Phases 2-6 entirely.
2. Extract URLs from the draft (regex `https?://...` + markdown links + footnotes).
3. For each URL → host lookup in the registry → tier.
4. Aggregate: count tiers, list T3+unregistered hosts.
5. Inline summary in chat (NOT writing a log file).
6. Threshold gate disabled — never block a chat answer.

Output template:

```
Tier audit: {n} links — {n_t1}× T1, {n_t2}× T2, {n_t3}× T3, {n_unreg}× unregistered.
Recency: {n_recent}× < {recency_max}, {n_stale}× stale.
{ list of stale + unregistered hosts if ≥1 }
Verdict: {OK | warning}.
```

---

## Anti-pattern guards

- **No silent skip** when the brief is missing — fail-fast with instructions (**FULL mode only**). In SOFT mode (internal-corpus / no-registry, per `docs/CONVENTIONS.md` §10) a missing brief is OPTIONAL: proceed with defaults + a confidence note, never fail-fast.
- **No auto-promote** 🔴 → 🟡 without an explicit AskUserQuestion override.
- **Do not use `last_updated`** for the recency check — only `published` / `fetched_at` (see the frontmatter schema § date semantics).
- **Do not overwrite the verification log** on a re-run without updating an `audit_history` entry.
- **Do not call WebFetch directly** — a supplementary fetch only via the `source-archive` skill.
- **Do not skip the registry update** when an unregistered host is confirmed → tier — the registry must reflect the new entry.
