---
title: "Acceptance tests — digest-build"
type: acceptance-test
status: active
related_skill: skills/digest-build/SKILL.md
generated_by: ai-then-human-edited
---

# Acceptance tests — digest-build

> Living spec for the on-demand digest-build skill. Covers the default-lookback
> happy path, the `--lookback` override, the quiet-week one-liner, the rich-vs-
> deterministic path choice, the output-path report, and the build/deliver
> boundary (it builds locally and offers a hand-off but sends nothing). It scans
> the same inputs as `schedule/weekly-digest.md` and writes the same
> `pipeline/3-synthesis/digest_YYYY-MM-DD.md` file; building never has external
> side effects.

## Scope

- **Skill:** `digest-build`
- **SKILL.md:** [`../SKILL.md`](../SKILL.md)
- **Coverage:** 6 scenarios — 1 default build + 1 lookback override + 1 quiet week
  + 1 path choice + 1 report/hand-off + 1 no-send boundary.

---

## Scenarios

### Scenario 1: Default build with configured lookback

**Given:**
- `pipeline/1-incoming/` has at least one article whose `collected:` date is within
  `config/schedule.yaml` → `digest.lookback_days` (default 7), and/or
  `brain/concepts/` has at least one non-SEED concept updated within that window.
- No explicit lookback was requested.

**When:**
- User: "build the weekly digest".

**Then:**
- The skill reads `digest.lookback_days` from `config/schedule.yaml` and builds
  over that window.
- A digest file is written at `pipeline/3-synthesis/digest_YYYY-MM-DD.md` (today's
  date), following the CONVENTIONS §3 section structure (volume header, New sources,
  Updated concepts, optional Synthesis, Needs attention), with `[tier]` markers and
  corroboration trust lines where present.
- In-window items are scoped by `collected:` / `last_updated` frontmatter (not
  mtime); SEED/EXAMPLE concepts are excluded.

---

### Scenario 2: Honors an explicit lookback override

**Given:**
- The user asks for a non-default window (e.g. "build a digest for the last 14
  days").

**When:**
- The skill builds, passing `--lookback 14` (deterministic path) or applying the
  same 14-day window when authoring the rich digest.

**Then:**
- Only items whose `collected:` / `last_updated` date falls within the 14-day
  window are included; the section headings read "(last 14 days)".
- `config/schedule.yaml` is **not** edited — the override is per-run only.

---

### Scenario 3: Quiet week → one-line quiet digest

**Given:**
- There are **no** new sources and **no** updated concepts within the lookback
  window.

**When:**
- User: "собери дайджест сейчас".

**Then:**
- The digest file contains the one-line "Quiet week — no new sources and no concept
  updates in the last N days." note (the deterministic path also prints the
  `QUIET_WEEK` marker on stdout).
- The run is reported as **success** (no error), and the skill notes it is a quiet
  week and suggests skipping delivery so the user is not pinged with nothing new
  (CONVENTIONS §10 / D7).

---

### Scenario 4: Rich vs deterministic path choice

**Given:**
- The same in-window inputs exist.

**When:**
- (a) Running as an agent in Cowork / Claude Code with vault access, **or**
- (b) Running headless (no agent) or the user asks for the plain build.

**Then:**
- In case (a) the skill produces the **rich** agent-authored digest following
  `schedule/weekly-digest.md` — a prose "this week in one line" lead, inline
  `[title](url)` citations, and source→concept `(feeds: …)` links — while keeping
  the section structure, tier markers, trust lines, and the Knowledge base health
  line.
- In case (b) the skill runs `python3 scripts/build_digest.py [out] [--lookback N]`
  for the deterministic list-based build.
- Both write the same path and the same section structure; the choice changes only
  the body's richness, not the file location or format.

---

### Scenario 5: Reports the output path and offers the deliver hand-off

**Given:**
- A digest was just built (any of the above).

**When:**
- The skill finishes building.

**Then:**
- It reports the exact output path (`pipeline/3-synthesis/digest_YYYY-MM-DD.md`)
  and a one-line volume summary (or "quiet week").
- It **offers to hand off to `digest-deliver`** rather than sending — preserving the
  build/deliver boundary (build is local; deliver has external side effects).

---

### Scenario 6: Builds locally — sends nothing

**Given:**
- Any build request, regardless of how `config/channels.yaml` is configured.

**When:**
- The skill builds the digest.

**Then:**
- **Nothing is sent over any transport** — no Telegram/Gmail MCP call, no webhook
  POST, no SMTP / Bot-API send.
- Only the digest markdown file is written; `config/` is read-only. Delivery happens
  only if the user accepts the `digest-deliver` hand-off, which is a separate skill.
