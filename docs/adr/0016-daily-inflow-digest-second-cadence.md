# ADR 0016 — A daily "inflow" digest as an opt-in second cadence

- **Status:** Accepted (2026-06-30)
- **Tags:** scheduling, digest, cadence, delivery

## Context
The product ships **one** digest cadence: a weekly, synthesis-grade digest
(`digest.cron`, `lookback_days: 7`) built by `build_digest.py` / the RICH
`weekly-digest` path. A user asked for a **daily** digest *in addition to* the
weekly one — a quick "what came in today" scan, not a second deep synthesis.

The trigger timing is already data-driven (cron is just a value the scheduler
reads), but a *second parallel cadence* was modeled nowhere, and "weekly" is
baked into several seams: the digest filename `digest_YYYY-MM-DD.md` (a daily and
weekly build on the same date would collide on one file), the quiet-digest
detection (`deliver.is_quiet_digest` matches the literal `"Quiet week —"`), the
schedule schema (declared *fixed*), and the `brain_status` block list.

Two facts shape the design: collection runs every ~3 days and **synthesis runs
weekly**, so "updated concepts" / "synthesis this week" rarely change day-to-day.
A daily digest that re-rendered those sections would mostly be empty noise.

## Decision
Add a **daily "inflow" digest** as an **opt-in, lighter render mode** of the same
deterministic builder — not a second orchestration stack.

- **Schema:** one new **optional** block in `config/schedule.yaml`:
  ```yaml
  daily_digest:
    cron: "0 8 * * *"     # every day 08:00
    lookback_days: 1
  ```
  Absent → the daily digest simply does not exist (backward compatible). The weekly
  `digest:` block is unchanged.
- **Content (light):** the daily digest renders **only** the inflow-centric
  sections — `📰 New sources` (in the daily window) and `📌 Needs attention`. It
  **omits** `TL;DR`, `Knowledge base` health, `💡 Updated concepts`, and `🧪 Synthesis`
  (all weekly-synthesis artifacts). Title is `🗞 Daily digest — <date>`.
- **Filename:** `digest_daily_YYYY-MM-DD.md` (+ optional `.html`), so a daily and a
  weekly build on the same date never collide.
- **Quiet:** a daily digest is quiet when there are **no new sources and no
  attention items** (concepts are irrelevant to the daily render). It emits a
  `Quiet day — …` one-liner; `deliver.is_quiet_digest` is widened to match
  `Quiet (week|day) —` so `--skip-quiet` works for both.
- **Surfacing:** `daily_digest` joins the `brain_status` block list and is
  validated by `validate_config.py` (cron + positive-int `lookback_days`) **when
  present**.
- **Invocation:** `build_digest.py --daily` (default out = the daily path, default
  lookback from `daily_digest.lookback_days`). The single run-lock still serializes
  it against the weekly run.

## Consequences
- **No duplicated knowledge or orchestration.** The daily digest is a render mode
  of the existing builder; the same `gather()` feeds both. The weekly path is
  untouched (every existing test stays green).
- **Daily stays cheap and quiet-friendly.** It never waits on synthesis and skips
  empty synthesis/concept sections, so it reads as a fast inflow scan.
- **The "fixed schema" gains one optional block**, consistent with how
  `curate`/`synthesis` were already added as optional §2.2 blocks.
- **Separate receipt/idempotency per cadence** falls out of the distinct filename —
  daily and weekly deliveries don't clobber each other's `.delivered/` receipts.
- Daily digests use a distinct filename, so they do **not** appear in
  `brain_status`'s weekly `digest_*.md` list (intentional — the two cadences list
  separately); a future change can list them under their own heading if wanted.

## Alternatives considered
- **Retune the single `digest:` block to daily.** Rejected — the user wants both
  cadences; one block can express only one.
- **Full weekly render, just daily.** Rejected (and explicitly declined by the
  user) — at `lookback_days: 1` the synthesis/concept sections are almost always
  empty, so a full render is mostly noise; the light mode is the point.
- **A separate `daily-run` task stack + skill.** Rejected for now — the daily digest
  needs only build+deliver over already-collected inflow, so a render mode plus the
  existing delivery path is the KISS path; a dedicated orchestrator can come later
  if daily collection is added.
