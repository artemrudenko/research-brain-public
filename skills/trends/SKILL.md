---
name: trends
description: "Answer 'how is it changing over time?' INLINE in the chat: render the deterministic weekly trends signals (ADR 0017 — topic volume this week vs last, rising tags, activity, knowledge growth) from pipeline/registry.md + brain/concepts/ into a TEMP file and reply with the top movers. Read-only: collects nothing, persists no report, sends nothing. Triggers: «/trends», «trends», «what's trending», «how are my topics changing», «what's rising», «show trends», «тренды», «что растёт», «динамика тем», «как меняются темы»."
metainfo:
  type: lookup
  domain: meta-process
  last_updated: 2026-07-11
  relation: "Sibling of whats-new (fresh items right now) and brain-ask (state/health). trends answers change-over-time from the durable data already on disk; the weekly digest embeds the exact same section by default (build_digest.py, --no-trends opts out)."
---

# trends — how is it changing over time, answered inline

Where `whats-new` answers "what arrived?", this skill answers **"how is it moving?"** —
topic volume this week vs last, rising tags, activity, and knowledge growth. It reads only
the two durable local sources (`pipeline/registry.md` + `brain/concepts/`), renders
the deterministic report to a temp file, and replies with the top movers. Nothing is
collected, persisted, or delivered — the answer IS the chat reply.

---

## When to Use

**Use when:**
- The user asks about direction or change: "/trends", "what's trending?",
  "how are my topics changing?", "what's rising?", "тренды", "что растёт",
  "динамика тем", "как меняются темы".
- The intent is a quick inline answer from data already on disk.

**Skip / don't use for:**
- **"What's new?"** (fresh items, a quick collect) — that is `whats-new` (`/new`).
- **Status / health** ("is everything ok", "what do we monitor") — that is `brain-ask`.
- **A persisted trends report file** on a cadence — that is the optional
  `weekly_trends` block in `config/schedule.yaml` (standalone `scripts/trends.py`).
- **The weekly digest** — it already embeds this same trends section by default
  (`build_digest.py`; `--no-trends` opts out), so don't rebuild a digest here.

---

## Steps

1. **Render the trends report to a TEMP file** (read-only inputs; atomic write):

   ```bash
   TR="$(mktemp -t trends).md"
   python3 scripts/trends.py "$TR"
   ```

   (A unique `mktemp` name per invocation — never a fixed path. The default no-arg
   invocation would persist `pipeline/3-synthesis/trends_<date>.md`; this skill
   deliberately does NOT persist.)

2. **Cold-start honesty.** Trends compare the last 7 days against the 7 before. If the
   report shows zero activity in BOTH periods (fresh install, or nothing collected for
   two weeks), don't recite zeros — answer honestly: "Not enough history yet — trends
   light up after a week or two of collection" and offer `/new` (fresh check) or
   `/run` (full cycle) as the way to start accumulating.

3. **Answer INLINE.** Summarize the report as a short chat message — 3–6 lines, not a
   document dump:
   - the busiest topics with their ↑/↓ deltas (and 🌱 new / 💤 fading topics, if any);
   - rising tags, if any;
   - one activity line (inflow vs last week, backlog if non-zero);
   - one knowledge-growth line (concepts created/updated; most-connected if notable).
   In Telegram, send it with the **reply** tool (never just the transcript). Keep the
   answer in the user's language (`delivery.language` / the language they asked in).

4. **Clean up + follow-ups.** Delete the temp file. Close with one line: the weekly
   digest already carries this section automatically; offer `/digest` (build now) or
   the standalone `weekly_trends` cadence for a persisted report file.

---

## Output

- An inline chat reply with the top movers (or an honest "not enough history yet").
- **No** report artifact persisted (temp file deleted), **no** collect, **no** vault
  writes, **no** delivery.
