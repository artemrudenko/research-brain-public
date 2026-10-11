---
title: "Acceptance tests — brain-ask"
type: acceptance-test
status: active
related_skill: skills/brain-ask/SKILL.md
generated_by: ai-then-human-edited
---

# Acceptance tests — brain-ask

> Living spec for the read-only status & findings skill. Covers the four query
> intents (sources / cadence / digests / findings), the graceful empty/quiet
> states, and the hard boundary against `wiki-query` (external-topic questions
> are routed away, never answered here). All answers are grounded in
> `scripts/brain_status.py`; nothing is written and no URL is fetched.

## Scope

- **Skill:** `brain-ask`
- **SKILL.md:** [`../SKILL.md`](../SKILL.md)
- **Coverage:** 7 scenarios — 4 happy-path intents + 2 empty/quiet edge cases +
  1 boundary (route to wiki-query).

---

## Scenarios

### Scenario 1: Monitored sources (RU)

**Given:**
- `config/sources.yaml` lists two active sources across two categories and one
  parked (`Active: no`) row.

**When:**
- User: "что мы мониторим и с какой периодичностью?"

**Then:**
- The skill runs `scripts/brain_status.py sources` (active-only) and reports the
  two active sources grouped by category, each with its URL, type, and tier.
- The parked row and any Candidate-table rows are NOT listed.
- The cadence half of the question is answered from `cadence` (see Scenario 2).
- No file is written; no URL is fetched.

---

### Scenario 2: Cadence / schedule

**Given:**
- `config/schedule.yaml` has the four blocks (collect / curate / synthesis /
  digest), `timezone: "Europe/Minsk"`, and `digest.lookback_days: 7`.

**When:**
- User: "how often do we collect and when does the digest go out?"

**Then:**
- The skill runs `scripts/brain_status.py cadence` and replies in plain language:
  the timezone once, one friendly line per step ("collects every 3 days at
  09:00", "builds the digest every Monday at 09:00"), and the 7-day lookback.
- Raw cron strings are not shown unless the user explicitly asks for them.

---

### Scenario 3: Top N digests

**Given:**
- `pipeline/3-synthesis/` contains several `digest_YYYY-MM-DD.md` files.

**When:**
- User: "show me the last 5 digests".

**Then:**
- The skill runs `scripts/brain_status.py digests -n 5` and lists them
  newest-first: each line a date plus a one-line summary.
- A quiet-week digest is labelled "Quiet week" in its line.

---

### Scenario 4: Latest digest only

**Given:**
- At least one digest exists.

**When:**
- User: "дай последний дайджест".

**Then:**
- The skill shows the single newest digest (date + summary), optionally offering
  to open the full file.

---

### Scenario 5: Key findings — quiet week

**Given:**
- The most recent digest is a quiet-week digest ("Quiet week — no new sources…").

**When:**
- User: "ключевые находки за последнюю неделю".

**Then:**
- The skill runs `scripts/brain_status.py findings`; the query returns a quiet
  signal. The skill replies "the latest digest (<date>) was a quiet week —
  nothing new to report", with no invented highlights and no error.

---

### Scenario 6: Key findings — no digests yet

**Given:**
- `pipeline/3-synthesis/` contains no `digest_*.md` files.

**When:**
- User: "key findings this week".

**Then:**
- `findings` returns a "no digests yet" signal. The skill replies clearly that no
  digests have been produced yet and suggests building one — it does NOT crash
  and does NOT fabricate findings.

---

### Scenario 7: Boundary — external topic routes to wiki-query

**Given:**
- A populated knowledge vault under `brain/concepts/`.

**When:**
- User: "what do we know about retrieval-augmented generation?"

**Then:**
- brain-ask recognizes this as an external-topic (research-intent) question,
  declines to answer from its own queries, and routes to `research-frame` →
  `wiki-query`.
- brain-ask does NOT read `brain/concepts/` itself and does NOT call
  `brain_status.py` for this question.
