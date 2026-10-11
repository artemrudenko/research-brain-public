# ADR 0007 — RSS-first, multi-stage collection (gather wide → rank → read best)

- **Status:** Accepted (backfilled 2026-06-24)
- **Tags:** collection, rss, ranking

## Context
Each topic must be collected from heterogeneous places (feeds, official pages, aggregator
platforms) on a cadence, cheaply and reliably, without a browser becoming the default fetch path.

## Decision
Collection is **multi-stage and RSS-first**. Per topic, gather candidates in parallel from three
**source roles** — **RSS** feeds, **Official** news/docs pages, and **Search** platforms
(Medium/dev.to/Habr tags) — into a wide pool (`collect.candidate_pool_per_topic`, default 25), rank
by **relevance × recency × tier**, then read the best (`collect.max_articles_per_topic`, default 10)
in full. Within each role climb a cheap→expensive ladder (RSS body → WebFetch top-up → static fetch
→ browser only per a per-source allow-list). The persistent cross-run dedup key is the canonical URL
(`scripts/normalize_url.py`); the RSS `<guid>`/`<id>` is used only for in-run feed-item dedup;
near-dup syndication is collapsed by `scripts/dedup.py`. Seed tags come from RSS `<category>`,
normalized through `config/tags.yaml`.

## Consequences
- Cheapest/most-reliable sources are tried first; the browser is the exception, not the rule.
- A wide gather then a narrow read bounds expensive full reads while keeping recall.
- Untrusted RSS bodies feed synthesis only through the sanitize gate (see anti-injection, §12).
- Cost: ranking + two caps to tune per topic; dedup correctness depends on URL normalization.

## Alternatives considered
Browser-first / fetch-everything is implicitly rejected (the ladder makes the browser opt-in per
allow-list, and the pool→rank→read-best design exists to avoid reading every candidate in full).
Other alternatives not recorded at decision time.

## References
- `docs/CONVENTIONS.md` §12 (Collection — multi-stage, RSS-first).
- `AGENTS.md` — Mandatory rules ("Collection is multi-stage and RSS-first").
