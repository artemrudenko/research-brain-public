---
name: run-now
description: "Run the whole weekly pipeline NOW, on demand, in conversation — the same gated sequence as the scheduled weekly run: collect (per active topic) → sanitize-incoming → curate → synthesis → brain-hygiene → digest-build → deliver, each step gated on the previous finishing. It does NOT reimplement any step — it invokes schedule/weekly-run.md (the single source of truth). Default is the full run including delivery to enabled channels; if the user says 'build but don't send' it stops after digest-build, and if no channel is enabled it still builds locally and reports the path. Triggers: «run now», «run the pipeline now», «do a full run», «collect and send me a digest now», «update now», «прогони цикл сейчас», «собери всё сейчас», «обнови базу и пришли дайджест», «обнови сейчас», «прогони цикл», «собери всё и пришли дайджест»."
metainfo:
  type: orchestrator
  domain: research-methodology
  last_updated: 2026-07-05
---

# run-now — run the whole weekly pipeline now, on demand

The user wants the **entire** pipeline run **immediately**, not on the schedule:
collect → sanitize-incoming → curate → synthesis → brain-hygiene → digest-build → deliver. This skill is
the conversational **on-demand trigger** for that whole loop.

It owns **no logic of its own**. It is a thin wrapper that **invokes
[`schedule/weekly-run.md`](../../schedule/weekly-run.md)** — the single, gated
orchestrator that already sequences every step — and runs it *now* instead of waiting
for `digest.cron`. weekly-run.md itself notes at the bottom: *"On demand — 'Run the
weekly pipeline now' runs this same task immediately, in the same order."* This skill is
exactly that trigger; it does not duplicate or re-specify the step bodies.

---

## When to Use

**Use when:**
- The user says: "run now", "run the pipeline now", "do a full run", "collect and send
  me a digest now", "update now", "обнови сейчас", "прогони цикл", "прогони цикл сейчас",
  "собери всё сейчас", "собери всё и пришли дайджест", "обнови базу и пришли дайджест".
- They want the **whole** loop (collect → … → deliver) done right now, on demand.

**Skip / don't use for:**
- **Building only** the digest (no fresh collect/curate/synthesis) — that is
  `digest-build`.
- **Sending only** an already-built digest — that is `digest-deliver`.
- The **scheduled** weekly run — that is the `/schedule` routine pointed at
  `schedule/weekly-run.md` (this skill runs the *same task*, just on demand now). See
  [`docs/scheduling.md`](../../docs/scheduling.md).
- A single quick source/topic edit — that is `source-manage`; configuring channels or
  cadence — that is `setup-wizard`.
- **"sync the vault / ingest this" right after research** (post-research, new
  in-session knowledge) — that is `wiki-ingest`. run-now is the full cold-start
  pipeline (collect→…→deliver), not the post-research vault sync.

> **RU near-collision.** «собери всё сейчас» = the whole loop (this skill);
> «собери дайджест сейчас» = just the digest (`digest-build`).

---

## What it does (delegates — does not reimplement)

Invoke **[`schedule/weekly-run.md`](../../schedule/weekly-run.md)** and follow it
exactly. That task already:

- reads `config/schedule.yaml` (`synthesis.min_sources_per_topic`, `digest.lookback_days`,
  `curate.min_text_chars`, `timezone`) and the topics config — `config/topics.yaml` — (the active-topic list);
- runs the steps **in order**, each gated on the previous finishing —
  collect per active topic ([`collect-topic.md`](../../schedule/collect-topic.md)) →
  sanitize-incoming (`python3 scripts/sanitize_incoming.py sanitize`) →
  curate ([`weekly-curate.md`](../../schedule/weekly-curate.md)) →
  synthesis ([`weekly-synthesis.md`](../../schedule/weekly-synthesis.md)) →
  brain-hygiene (`python3 scripts/validate_brain.py`) →
  digest-build ([`weekly-digest.md`](../../schedule/weekly-digest.md) build steps) →
  deliver (the `digest-deliver` skill);
- **stops on a failed step** so a half-built `brain/` is never digested or delivered.

Do **not** re-derive any of that here. This skill's only added value is recognizing the
on-demand trigger phrases, applying the delivery choice below, and reporting progress.

---

## Steps

1. **Confirm scope and the delivery choice — but first guard the un-set-up template.**

   **Empty-state guard (do this BEFORE running anything).** If the config still has
   only the shipped EXAMPLE topic/sources (no real source added yet —
   `scripts/brain_status.py sources` skips EXAMPLE placeholders, so it prints
   "No monitored sources configured." on the un-set-up template), do **not** run the pipeline. A first run
   on the template would only fetch the placeholder `example.com` and return a
   confusing empty "quiet week". Tell the user they haven't added real sources yet and
   hand off to `source-manage` ("start monitoring …") or `setup-wizard`.

   The default is the **full run including
   deliver** to whatever channels are enabled in `config/channels.yaml`. Decide the
   delivery endpoint *before* running, applying clarify-don't-invent:
   - **"build but don't send" / "не отправляй" / "just build" / "no deliver":** run the
     full loop **but stop after digest-build** (weekly-run Step 5). Do not run Step 6
     (deliver). The hand-off boundary is exactly digest-build vs digest-deliver.
   - **No channel enabled** in `config/channels.yaml` (every `enabled: false`): run the
     **whole** loop including the deliver step, but delivery simply **no-ops** — it sends
     nothing and reports "no enabled channels". This is **not** a failure: the digest was
     still built locally. Tell the user the path
     (`pipeline/3-synthesis/digest_YYYY-MM-DD.md`) and that they can read it there, and
     how to enable a channel (`setup-wizard`, or edit `config/channels.yaml`).
   - **Channels enabled + the request is ambiguous** about sending (e.g. just "run the
     pipeline" with no send/no-send signal): you **may ask once** — "send the digest to
     your enabled channels too, or just build it?" — then proceed. One question only; do
     not interrogate.
   - **Channels enabled + the request clearly wants delivery** ("collect and send me a
     digest now", "обнови базу и пришли дайджест"): run the whole loop through deliver.

2. **Set expectations — this can take a while.** Collection does a WebFetch (and, per the
   allow-list, browser) pass **per source per active topic**, so a full run is not
   instant. Tell the user it's running and that you'll report progress per step.

3. **Run `schedule/weekly-run.md` now, in order.** Invoke the orchestrator and execute
   its gated sequence exactly. After **each** step, confirm it finished before starting
   the next, and **report progress per step** (e.g. "collect done for 2 topics → curate
   done → synthesis done → hygiene done → digest built"). A step that legitimately has
   nothing to do (e.g. a quiet collect, a no-op curate) is **not** a failure — continue.

4. **Stop on a failed step — never deliver a half-built brain.** If any step fails, stop
   the run there, report which step failed and why, and do **not** start the following
   steps. In particular, a failed collect/curate/synthesis/hygiene/build must **not** be
   followed by delivery. This is weekly-run's gating, surfaced to the user — not new
   logic here. **Always run weekly-run Step 8 (release the run lock with the captured
   token) before you stop** — every early exit must free the lock, or the next run is
   needlessly blocked until the lease expires.

5. **Apply the delivery choice at the deliver gate.** When the run reaches weekly-run
   Step 6 (deliver): if the user chose "build but don't send", **stop after Step 5**
   (then run weekly-run Step 8 — release the lock) and
   report the built digest path plus an offer to send later via `digest-deliver`.
   If **every** channel in `config/channels.yaml` is `enabled: false`, **skip the deliver
   step** and report the local digest path (don't rely on the deliver step to no-op for
   you) plus how to enable a channel. Otherwise run the deliver step normally.

6. **Report the outcome.** A concise end-to-end summary: which steps ran and finished, a
   one-line volume note (e.g. "N new sources across M topics, K updated concepts" — or
   "quiet week"), the digest path, and the per-channel delivery result (SENT / SKIPPED /
   not-attempted), or — if a step failed — where it stopped and why.

---

## Output

- A run of the **same gated sequence** as `schedule/weekly-run.md`, executed now.
- A digest at `pipeline/3-synthesis/digest_YYYY-MM-DD.md` reflecting a `brain/` that
  synthesis finished writing (plus the run-log and brain-health files weekly-run
  produces), unless an earlier step failed and stopped the run.
- Delivery to the enabled channels (full run), or nothing sent (when "build but don't
  send" was chosen, or no channel is enabled).
- A per-step progress trail and an end-to-end summary back to the user.

---

## Verification

- The steps ran **in order** — collect (per active topic, from the active topics config) →
  sanitize-incoming → curate → synthesis → brain-hygiene → digest-build → deliver — via
  `schedule/weekly-run.md`, **not** reimplemented here.
- Each step started only **after** the previous finished; a **failed** step stopped the
  run **before** the digest was built or delivered (no half-built `brain/` was digested).
- The delivered/built digest reflects a fully-synthesized `brain/` (the
  synthesis→digest gate held).
- **No channel enabled →** the digest is still built and its local path is reported;
  nothing is sent and that is reported as success, not an error.
- **"build but don't send" →** the run stops after digest-build (weekly-run Step 5);
  nothing is sent; the path is reported with an offer to deliver later.
- **Adding a topic (via source-manage / `manage_sources.py add-topic`) then running →** the new topic is collected,
  because weekly-run enumerates the active-topic list as the source of truth (no
  hardcoded category).

---

## Boundaries

- **vs `digest-build`** — digest-build *only* builds the digest from what is already in
  the vault (no collect, no curate, no synthesis, no hygiene). run-now runs the **whole**
  loop, of which digest-build is just step 5.
- **vs `digest-deliver`** — digest-deliver *only* sends an already-built digest. run-now
  runs the whole loop and reaches deliver as its final, gated step.
- **vs the scheduled `weekly-run`** — **same steps, same task, same order** — the only
  difference is *when*: run-now fires it **now** on a conversational trigger; the
  `/schedule` routine fires the identical `schedule/weekly-run.md` at `digest.cron`.

---

## Examples

**Example 1 — full run, channels enabled:**
> User: "обнови базу и пришли дайджест"
> Runs `schedule/weekly-run.md` now: collect per active topic → sanitize-incoming → curate → synthesis →
> brain-hygiene → digest-build → deliver. Reports per-step progress, then
> "Done: 4 new sources across 2 topics, 1 updated concept →
> pipeline/3-synthesis/digest_2026-06-16.md; telegram SENT".

**Example 2 — a step fails, stop before deliver:**
> User: "run the pipeline now"
> Collect and curate finish, but synthesis fails. The run **stops** — brain-hygiene,
> digest-build, and deliver do not run. Reports: "Stopped at synthesis (…reason). Nothing
> was built or delivered; rerun once resolved."

**Example 3 — no channels enabled:**
> User: "do a full run"
> `config/channels.yaml` has every channel `enabled: false`. The whole loop runs through
> the deliver step, which no-ops. Reports: "Digest built →
> pipeline/3-synthesis/digest_2026-06-16.md (read it there). No channels enabled —
> nothing sent; enable one via setup-wizard or config/channels.yaml to receive it."

**Example 4 — build but don't send:**
> User: "прогони цикл, но не отправляй"
> Runs collect → sanitize-incoming → curate → synthesis → brain-hygiene → digest-build, then **stops** before
> deliver. Reports the built digest path and offers to send it later via `digest-deliver`.

**Example 5 — new topic gets collected:**
> User just added a `quantum-sensing` topic to the config, then: "собери всё
> сейчас". weekly-run enumerates the active topics, so the new topic is collected in this
> run alongside the others — no code change needed, the topic list is the source of truth.
