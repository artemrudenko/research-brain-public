# ADR 0009 — One gated weekly-run orchestrator over four independent cron timers

- **Status:** Accepted (backfilled 2026-06-24)
- **Tags:** scheduling, orchestration, ordering

## Context
The weekly pipeline is an ordered chain (collect → curate → synthesis → digest). Registering its
stages as four independent timers (curate 08:00, synthesis 08:30, digest 09:00) introduces a
clock-race: if synthesis runs long, the 09:00 digest can start before `brain/` is consistent and
read a half-written vault.

## Decision
Prefer **one gated orchestrator** — `schedule/weekly-run.md` — that runs the steps **sequentially,
each gated on the previous finishing**: collect → (drain capture inbox) → **sanitize
incoming** (anti-injection gate) → curate → synthesis → brain-hygiene → digest (build) → deliver, then record
the run and release the run lock. Register it as a single `/schedule` cloud agent (or a single
external-cron entry) at `digest.cron`, rather than four separate timers. `weekly-run.md` owns no
logic of its own — it only sequences existing tasks/skills and stops if a step fails.

## Consequences
- Removes the synthesis→digest clock-race: the digest never reads a `brain/` synthesis hasn't
  finished writing — the ordering becomes a guarantee, not a hope.
- A run lock (Step 0) plus the sanitize gate before synthesis are enforced in one place.
- One trigger to register and reason about; `run-now` reuses the same path.
- Cost: the orchestrator is a Markdown instruction, not an executable state machine — no `run_id` /
  per-stage checkpoints / crash recovery.

## Alternatives considered
Four independent cron timers (one per stage) — rejected for the clock-race described above. External
cron driving the headless `build_digest.py` + `deliver.py` pair remains a supported alternative for
non-agent runtimes (CLAUDE.md Scheduling).

## References
- `schedule/weekly-run.md` (Step 0 + Run order, each step gated).
- `docs/scheduling.md` ("Recommended: one gated pass … instead of four separate timers").
- `AGENTS.md` — "Prefer the gated single `weekly-run.md` orchestrator over four independent timers."
