# collect — single-topic wrapper

**Schedule:** from `config/schedule.yaml` → `collect.cron`
**Logic:** `schedule/collect-base.md`

This is a thin wrapper that collects one topic. It is intentionally generic: every
topic-specific value (sources, tags, filter rules, save folder) is read from `config/`
at runtime, not hardcoded here. Copy this file per topic if you want a separate task per
topic, or run it once per topic with a different `{CATEGORY}`.

> **Set `{CATEGORY}`** to the topic name you want this wrapper to collect. It must match a
> topic and a matching source category in the config (`config/topics.yaml` +
> `config/sources.yaml` — AGENTS.md config map).

```
{CATEGORY} = <topic name, e.g. a topic's `name` in config/topics.yaml>
```

---

## Step 0: Read config

1. **Sources** — read the sources config (`config/sources.yaml`) → the `categories:` entry
   named `{CATEGORY}`. Keep only sources with `active: true`; from each, read `url`, `type`
   **and `tier`**. This is `{SOURCE_URLS}`. Each source's `tier` is carried through
   so it lands in that article's `tier:` frontmatter (source credibility, surfaced in the digest —
   see collect-base Step 6 and CONVENTIONS §5).
2. **Topic** — read the topics config (`config/topics.yaml`) → the `{CATEGORY}` entry under
   `topics:`. Take:
   - `tags:` → `{TAGS_FRONTMATTER}`
   - `include:` + `exclude:` → `{FILTER_CRITERIA}`
   - `{OUTPUT_FOLDER}` is derived, never stored: always `pipeline/1-incoming/{CATEGORY}/`.
3. **Caps** — read `config/schedule.yaml` → `collect.candidate_pool_per_topic` → `{CANDIDATE_POOL}`
   (gather pool, default 25) and `collect.max_articles_per_topic` → `{MAX_ARTICLES}` (read/save
   cap, default 10). This wrapper collects a single topic, so both apply to **this topic** for
   this run: gather up to `{CANDIDATE_POOL}` candidates, rank, save the best `{MAX_ARTICLES}`.

`{REGISTRY_CATEGORY}` = `{CATEGORY}`.

---

## Step 0a: Take the run lock (skip if the orchestrator already holds it)

Collection rewrites shared state (`pipeline/registry.md` — the dedup ledger that
`synthesis_freshness.combined_hash` and the weekly run read). So a **standalone** collect
must serialise against an in-flight run, exactly like `run-now` / `weekly-run` /
`source-capture` do.

- **Invoked BY `weekly-run`** (Step 1, once per topic) — the orchestrator already holds
  the single run lock, so **skip acquiring it here** (re-acquiring would refuse against
  its own lock). Just run the body; `weekly-run` releases the lock at the end.
- **Standalone** (the `collect.cron` timer, or run by hand) — take the lock first:

  ```bash
  python3 scripts/run_lock.py acquire --note "collect-topic"
  ```
  - **Exit 0** — the lock is yours. **Capture the `lock-token:` value it prints**; you
    must pass it to `release` in Step 0b.
  - **Exit 1 (`REFUSED: a run is already in progress`)** — a run holds the lock. **Stop
    here**, do nothing else; this is **not** a failure. (A genuinely orphaned lock is
    auto-reclaimed after its ~6h lease.)

  Only when this task acquired the lock itself must it release it in Step 0b.

---

## Run

Read `schedule/collect-base.md` and run Steps 1–7, substituting the parameters resolved above.

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
