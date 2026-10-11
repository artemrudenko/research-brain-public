# ADR 0017 — Weekly trends report from durable, dated sources

- **Status:** Accepted (2026-07-01)
- **Tags:** trends, digest, analytics, scheduling

## Context
The weekly digest answers "what happened this week?" but not "how is this
changing over time?". A user asked for an **extended weekly trends analysis**
covering four signals: (a) **volume by topic** this week vs prior, (b)
**emerging tags/terms** over recent weeks, (c) **activity/health** over time, and
(d) **concept growth & linking**.

Trend analysis needs a durable, dated time-series. A survey of the data found:

- **`pipeline/registry.md`** — append-only local state, one row per article
  ever collected: `collected` (ISO date) · `category` (topic) · `status`
  (blank/`processed`/`rejected`) · `url` · `title`. Rows survive after the article
  leaves `1-incoming`. This is the single fully-durable dated series.
- **`brain/concepts/*.md`** — local vault notes, with `created`, `last_updated`,
  `tags` (controlled vocabulary from `config/tags.yaml`), and `related_concept`
  wikilinks. Durable snapshot with dated frontmatter.
- **`pipeline/.health/events.jsonl`** — durable local state (gitignored);
  inflow/run/delivery outcomes. **Backlog count** lives only in the gitignored
  `synthesis-run_*.md` `Totals` block and has no parser.

## Decision
Add a **deterministic** (no-LLM) trends builder, `scripts/trends.py`, that reads
only the two **durable local** sources — the registry and concepts — and
writes `pipeline/3-synthesis/trends_YYYY-MM-DD.md`. Windows are **rolling 7-day
periods** anchored on `today` (period 0 = `[today-6, today]`, period 1 =
`[today-13, today-7]`, …), matching the digest's calendar-day lookback style.

Each signal maps to a durable source:

- **(a) Volume by topic** — registry rows bucketed by period on `collected`,
  grouped by `category`: current vs prior count, delta, plus **new** topics
  (present this period, absent last) and **fading** topics (vice-versa).
- **(b) Emerging tags** — computed from **concept** `tags` (not article tags,
  which default to just the category and are lossy), bucketed by the concept's
  `last_updated` period: tags rising in frequency this period vs prior.
- **(c) Activity** — registry inflow per period and the status mix
  (collected/processed/rejected) as a local backlog proxy.
- **(d) Concept growth & linking** — concepts **created** per period (growth) and
  the most-linked concepts now (link degree from `related_concept` + inline
  `[[concepts/…]]` wikilinks), a durable current-state ranking.

Cadence: an **optional** `weekly_trends` block in `config/schedule.yaml`
(cron + `weeks` lookback), validated like `daily_digest` (ADR 0016) and default-
absent. `build_trends.py` (or `trends.py --weeks N`) builds it; delivery reuses
the existing `deliver.py` path over the `trends_*.md` file.

## Consequences
- **Durable & reproducible.** Given the same local registry and vault notes,
  the builder reproduces the same trends. These data stay out of the public repo.
- **Honest limits, stated in the report.** True week-over-week **tag** and
  **link** deltas rely on the concept snapshot's `last_updated`/`created` stamps,
  not a per-change event log — so a tag that stopped being touched simply drops
  out of the recent window. Backlog-over-time and per-source inflow (from
  `events.jsonl`/synthesis `Totals`) are **out of scope for v1** (gitignored,
  no parser); the registry status mix is the durable activity proxy instead.
- **Composes with the digest.** Trends is a separate report/cadence, not a digest
  section, so the weekly digest is unchanged; a future step could embed a
  one-line trends headline into the digest.
- Adds one optional schedule block (absent → no trends report; backward compatible).

## Alternatives considered
- **Parse `synthesis-run_*.md` Totals / `events.jsonl` for backlog & inflow.**
  Deferred — both are gitignored runtime-only, so a fresh checkout can't reproduce
  them and they aren't backed up. The registry gives a durable proxy for v1.
- **Emerging tags from article frontmatter.** Rejected — collected articles set
  `tags: [category]` only and their files are unlinked after rejection, so article
  tags carry no durable vocabulary trend; concept tags do.
- **Embed trends inside the weekly digest.** Rejected for v1 — keeps the digest
  stable and lets trends run on its own cadence; revisit once the report settles.
