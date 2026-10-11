---
title: "Acceptance tests — run-now"
type: acceptance-test
status: active
related_skill: skills/run-now/SKILL.md
generated_by: ai-then-human-edited
---

# Acceptance tests — run-now

> Living spec for the on-demand `run-now` skill — the conversational trigger that runs
> the **whole** weekly pipeline immediately by invoking `schedule/weekly-run.md` (the
> single gated orchestrator). It does **not** reimplement any step; these scenarios assert
> the wrapper behavior: the gated full-run happy path, stop-before-deliver on a failed
> step, the no-channels-enabled local-build outcome, the "build but don't send" stop after
> digest-build, and that adding a topic is collected because the topic list is the source
> of truth.

## Scope

- **Skill:** `run-now`
- **SKILL.md:** [`../SKILL.md`](../SKILL.md)
- **Delegates to:** [`../../../schedule/weekly-run.md`](../../../schedule/weekly-run.md)
  (collect → sanitize-incoming → curate → synthesis → brain-hygiene → digest-build → deliver, gated).
- **Coverage:** 5 scenarios — full-run happy path + step-fails-stop-before-deliver +
  no-channels-enabled local build + build-but-don't-send + new-topic-gets-collected.

---

## Scenarios

### Scenario 1: Full run happy path (channels enabled)

**Given:**
- At least one active topic in `config/topics.yaml` with sources to collect.
- At least one channel `enabled: true` in `config/channels.yaml`.

**When:**
- User: "обнови базу и пришли дайджест" (or "collect and send me a digest now").

**Then:**
- The skill invokes `schedule/weekly-run.md` and runs its steps **in order**:
  collect (once per active topic) → sanitize-incoming → curate → synthesis → brain-hygiene → digest-build →
  deliver. It does **not** reimplement any step body.
- Each step starts only **after** the previous one finished (the synthesis→digest gate
  holds — the digest reflects a fully-written `brain/`).
- A digest is written at `pipeline/3-synthesis/digest_YYYY-MM-DD.md` and delivered to the
  enabled channel(s); the skill reports per-step progress and a final per-channel result
  (e.g. `telegram SENT`).

---

### Scenario 2: A step fails → stop before deliver

**Given:**
- A full run is requested with channels enabled.

**When:**
- An early step (e.g. synthesis) **fails** during the run.

**Then:**
- The run **stops at the failed step**. The following steps — brain-hygiene, digest-build,
  and **deliver** — do **not** run.
- **Nothing is delivered** and no half-built `brain/` is digested (weekly-run's gating,
  surfaced by the skill — not new logic).
- The skill reports which step failed and why, and that nothing was built or sent.

---

### Scenario 3: No channels enabled → builds locally, reports path, sends nothing

**Given:**
- Every channel in `config/channels.yaml` is `enabled: false` (the default config state).

**When:**
- User: "do a full run".

**Then:**
- The whole loop still runs through to the deliver step; the deliver step **no-ops** —
  it sends nothing and reports "no enabled channels".
- This is reported as **success**, not an error: the digest was still built. The skill
  reports the local path (`pipeline/3-synthesis/digest_YYYY-MM-DD.md`), tells the user
  they can read it there, and how to enable a channel (`setup-wizard` or editing
  `config/channels.yaml`).

---

### Scenario 4: "build but don't send" → stops after digest-build

**Given:**
- Channels may be enabled or not (irrelevant to this scenario).

**When:**
- User: "прогони цикл, но не отправляй" (or "run a full pass but don't send").

**Then:**
- The skill runs collect → sanitize-incoming → curate → synthesis → brain-hygiene → digest-build, then
  **stops after digest-build** (weekly-run Step 5). The deliver step (Step 6) does
  **not** run.
- **Nothing is sent over any transport.** The skill reports the built digest path and
  offers to send it later via `digest-deliver` — preserving the digest-build vs
  digest-deliver hand-off boundary.

---

### Scenario 5: Adding a new topic, then run-now collects it

**Given:**
- A new `## Topic:` section was just added to `config/topics.yaml` (e.g. "Quantum Sensing"),
  with at least one source.

**When:**
- User: "собери всё сейчас".

**Then:**
- The new topic is collected in this run alongside the existing ones, because
  `schedule/weekly-run.md` enumerates the **active-topic list** from `config/topics.yaml`
  as the source of truth and runs collect once per topic — there is no hardcoded category.
- No code or skill change is needed for the new topic to be picked up; it flows through
  sanitize → curate → synthesis → digest like any other topic.
