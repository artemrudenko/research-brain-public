# weekly-curate — promote incoming into curated

**Schedule:** from `config/schedule.yaml` → `curate.cron` (default: Mondays 08:00 — before synthesis and digest)
**Logic:** the `pipeline-curate` skill (`skills/pipeline-curate/SKILL.md`)

This is a thin wrapper. It owns no curation logic of its own — it just runs the
`pipeline-curate` skill on the configured cadence, after collection and before synthesis.
Every topic-specific value (include/exclude rules, save folder) is read from `config/` by the
skill at runtime, not hardcoded here.

All paths are relative to the project root (`{{VAULT_ROOT}}`).

---

## Step 0a: Take the run lock (skip if the orchestrator already holds it)

Curate rewrites shared state (`pipeline/2-curated/{topic}/index.md`, and the registry
rows it stamps `processed`) that `synthesis_freshness.combined_hash` and the weekly run
read. So a **standalone** curate must serialise against an in-flight run, exactly like
`run-now` / `weekly-run` / `source-capture` do.

- **Invoked BY `weekly-run`** (Step 2) — the orchestrator already holds the single run
  lock, so **skip acquiring it here** (re-acquiring would refuse against its own lock).
  Just run the body below; `weekly-run` releases the lock at the end.
- **Standalone** (the `curate.cron` timer, or run by hand) — take the lock first:

  ```bash
  python3 scripts/run_lock.py acquire --note "weekly-curate"
  ```
  - **Exit 0** — the lock is yours. **Capture the `lock-token:` value it prints**; you
    must pass it to `release` in Step 0b.
  - **Exit 1 (`REFUSED: a run is already in progress`)** — a run holds the lock. **Stop
    here**, do nothing else; this is **not** a failure. (A genuinely orphaned lock is
    auto-reclaimed after its ~6h lease.)

  Only when this task acquired the lock itself must it release it in Step 0b.

---

## Step 0: Read config

1. Read `config/schedule.yaml` → `curate.min_text_chars` → the candidate-relevance floor used
   by the skill.
2. Topics + their include/exclude rules come from the topics config (`config/topics.yaml` — AGENTS.md config map) — read by the skill.

---

## Run

Invoke the **`pipeline-curate`** skill. It:
- reads each topic and its include/exclude rules from the active topics config,
- scans `pipeline/1-incoming/{topic}/` for not-yet-`processed` articles (cross-checking
  `pipeline/registry.md`),
- applies the rules + `curate.min_text_chars` to decide keep/drop,
- appends/updates `pipeline/2-curated/{topic}/index.md` (CONVENTIONS §9 line format),
- marks promoted registry rows `status=processed`.

It is idempotent: re-running without new collection is a no-op.

---

## Step 0b: Release the run lock (only if this task acquired it)

If — and only if — **this task** acquired the lock in Step 0a (the standalone path),
release it now, on **every** exit path (normal completion or any failure), with the
token you captured:

```bash
python3 scripts/run_lock.py release --token <lock-token>
```

When invoked by `weekly-run` (which owns the lock), **do not** release it here — the
orchestrator releases it at the end of its own run.

---

## Success criteria

- `pipeline-curate` ran over every topic in the active topics config.
- Kept articles appear in `pipeline/2-curated/{topic}/index.md` and their registry rows read `processed`.
- The run is safe to repeat — a second run with no new incoming articles changes nothing.
