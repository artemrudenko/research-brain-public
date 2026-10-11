---
title: "wiki-query — phases detail (topic pre-filter, optional staleness, peer expansion)"
type: reference
domain: meta-process
last_updated: 2026-06-15
applies_when: "Topic pre-filter (with multi-topic gate) / optional freshness check / category-peer expansion via backlinks"
---

# wiki-query phases detail

> Extracted from `SKILL.md`. SKILL.md keeps the step summary; full procedures here.

## Topic pre-filter

Pre-match filter — narrows the candidate set BEFORE keyword matching. Reduces false positives (cross-topic keyword overlap) and speeds up search. Optional: skipped entirely when no topic is supplied.

### Step a — Resolve topic
1. **From DOMAIN_FILTER** (explicit, highest priority): the query contains 'topic=X' / 'on topic X' / 'in the area of X' → extract X.
2. **From RESEARCH_BRIEF_PATH.topic** (default): read the brief's frontmatter `topic:` field (set by research-frame).
3. **No filter** (fallback): no brief + nothing explicit → match without a topic restriction (emit a soft note 'no topic filter applied — running through research-frame is recommended').

### Step b — Pre-filter the MOC
If `target_topic` is resolved: read `brain/INDEX.md` (the MOC lists concepts grouped by topic cluster, each with a topic tag); for any concept not tagged in the MOC, open its individual frontmatter to read the topic tag. **Build the candidate set:** concepts whose topic matches `target_topic` → input for the Match step.

### Step c — Multi-topic disambiguation gate
After keyword matching — bucket matched concepts by topic. The gate **fires** when both:
1. **≥2 different topics** among matched concepts
2. **`top2_cluster_size / top1_cluster_size ≥ 0.4`** — the secondary cluster is substantial

Otherwise skip; primary = `top1`.

- **INTERACTIVE=true** → AskUserQuestion with 3 options: (a) `{top1_topic}` ({N1}) / (b) `{top2_topic}` ({N2}) / (c) both (the top concept from each, combined). Default: brief.topic if present, otherwise (a).
- **INTERACTIVE=false (subagent)** → emit a structured flag:
  ```yaml
  multi_topic_ambiguity:
    detected: true
    candidate_topics:
      - {top1_topic}: {N1}
      - {top2_topic}: {N2}
    primary_used: brief.topic | top1
    ratio_top2_top1: {0.0-1.0}
  ```
  Primary = `brief.topic` (if present) OR `top1_topic`.

### Step d — Empty result handling
`target_topic` is set but the candidate set is empty:
- **Do NOT degrade to other topics** — that would be a false signal; the topic filter was explicit.
- Match → `NO MATCH (topic-constrained)`.
- Forward to `research-grep` with the topic filter parameter.

## Category-peer expansion (via backlinks)

Closes the adjacency blind spot where a matched concept has a sibling note in the same MOC cluster that is also relevant.

**Trigger:** only `MATCH high` / `MATCH partial` (skip `NO MATCH` — pointless without an anchor).

**Steps:** (1) locate the matched concept's cluster in `brain/INDEX.md` § topic clusters; (2) collect sibling concepts from the same cluster by following the matched note's `[[wikilinks]]`/backlinks; (3) score peers by topic-tag overlap + confidence level; (4) surface the top 2 peers (limit: 1 anchor + ≤2 peers = max 3 concepts).

**Output:** `MATCH high` + ≥1 high-confidence peer → read anchor + 1 strongest peer · `MATCH high` + 2+ peers → AskUserQuestion (a only / b anchor+top peer / c all 3; default by depth) · `MATCH partial` → peer expansion may upgrade to `MATCH high` if the top peer covers the gap.

**Anti-patterns:** peer expansion beyond a single cluster (breaks the max-3 invariant) · recursive peer-of-peer (strict 1 hop; deeper → research-grep).

## Freshness check (optional, soft)

**Only on `MATCH high` / `MATCH partial`, and only as a soft note** — freshness never hard-blocks an answer here (there is no audit dependency). Read `last_verified` and `ttl_days` when present. `last_updated` records an edit; it is not source re-verification:

```
if last_verified is missing:
    -> state "freshness unknown"; do not infer that the note is wrong
elif ttl_days is present and (today - last_verified) > ttl_days:
    -> state "review due"; do not infer that the note is wrong
elif ttl_days is missing:
    -> state "unassessed"; no age threshold is recorded
else:
    -> state "within recorded TTL"; still check that the note covers the request

For unknown / review-due freshness, on a forwarded research request hand the note and its
sources/gaps to research-grep. On a vault-only request, answer with the caveat and offer a
separate research step.
```

**Always-volatile check:** if the query keywords fall into an always-volatile topic (fast-moving areas listed in `rules/common.md` — e.g. model/API pricing, tool features, regulation), recommend current-source research regardless of `last_verified`.

When supplementing, forward to `research-grep` with the brain context + a `freshness_required` flag. Search the configured local corpus first; its inventory and user-choice gate still control any external research.
