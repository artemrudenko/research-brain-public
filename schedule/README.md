# schedule/

Scheduled-task definitions — the recurring work that drives the pipeline. Each file is a
plain-Markdown instruction set the agent executes; cadences come from
`config/schedule.yaml`.

**Recommended entry point — `weekly-run.md`.** It runs the whole weekly pipeline in order
(collect → sanitize-incoming → curate → synthesis → extract lessons/playbooks → brain-hygiene → digest → deliver), each step gated on the previous finishing.
Register **one** trigger for it instead of four separate timers; that removes the clock-race
where the digest could read a `brain/` synthesis hadn't finished writing. The tasks below are its
components — still usable individually if you prefer separate headless jobs.

| File | Role |
|------|------|
| `weekly-run.md` | **Recommended.** Sequential orchestrator: runs collect (always, incl. the followed-authors roster pass) → sanitize-incoming → curate → synthesis → extract lessons/playbooks → brain-hygiene → digest → deliver in order, each step gated on the previous. Run as one `/schedule` agent or one cron entry. Owns no logic — sequences the tasks below. |
| `collect-base.md` | Shared collection logic. **Not run directly** — invoked by a thin wrapper with parameters. |
| `collect-topic.md` | Thin per-topic wrapper: reads `config/` and runs `collect-base` for one topic. Cadence: `collect.cron`. |
| `weekly-curate.md` | Thin wrapper: runs the `pipeline-curate` skill to promote `1-incoming` → `2-curated`. Cadence: `curate.cron`. |
| `weekly-synthesis.md` | Automatic synthesis driver: for each topic with enough curated sources, runs `research-build` → `wiki-ingest` (auto) into `brain/`. Cadence: `synthesis.cron`, after curate. |
| `weekly-digest.md` | Builds the digest over the `lookback_days` window, then hands off to the `digest-deliver` skill. Cadence: `digest.cron`. |
| `health-watchdog.md` | **Recommended second trigger.** Tiny independent daily check: alert (opt-in, one line) when the health verdict is DEGRADED — the alert that still fires when the weekly run itself crashed early or never started. Daily, decoupled from `weekly-run.md` by design. |
| `claude-run.sh` | Thin **cron wrapper** (not a task definition): runs `weekly-run.md` through the Claude Code CLI (`claude -p`) on a LOCAL install — the case a `/schedule` cloud routine can't reach. Least-privilege by construction: `--tools` = the `config/agents.yaml` role union, `--permission-mode dontAsk`, a spend ceiling; never `--dangerously-skip-permissions`. See `docs/scheduling.md` "D. Claude Code via OS cron". |
| `_agentic-run.sh` | **Sourced, never run**: the preamble both cron wrappers share — project root resolution and the `python3 >= 3.11` guard, in one copy so the two cannot drift. |
| `codex-run.sh` | Thin **cron wrapper** (not a task definition): runs `weekly-run.md` agentically via `codex exec` for Codex / Cowork or any agentic CLI without a cloud scheduler. See `docs/scheduling.md` "C. Codex". |

The ways to run these (Claude Code `/schedule` cloud agents; external `cron` calling
`scripts/delivery/deliver.py`; or Codex/Cowork via `codex-run.sh` cron), the recommended single
sequential run, the thin-wrapper pattern, the `timezone` key, and the headless transport rules
are all documented in **[../docs/scheduling.md](../docs/scheduling.md)**.
