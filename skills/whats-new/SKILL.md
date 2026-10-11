---
name: whats-new
description: "The ONE casual verb for 'what's new?': quickly collect fresh items from the configured RSS sources (bootstrap cap of 3 per topic, fast), sanitize, build a light inflow snapshot to a TEMP file, and answer INLINE in the chat with the top items — no digest artifact persisted, nothing delivered, no follow-up questions required. Offers the formal paths (digest-build / digest-deliver / run-now) only as follow-ups. Triggers: «what's new», «what's new?», «anything new?», «/new», «news?», «что нового», «что новенького», «есть что-то новое», «новости есть?»."
metainfo:
  type: operational
  domain: research-methodology
  last_updated: 2026-07-03
---

# whats-new — one casual verb: fresh items, answered inline, right now

A casual user does not want to learn the `digest-build` / `digest-deliver` / `run-now`
trio to ask the everyday question. This skill is the single obvious verb: **fetch what's
fresh, tell me in the chat, don't make me decide anything.** It persists no digest
artifact and sends nothing to channels — the answer IS the chat reply.

---

## When to Use

**Use when:**
- The user asks casually: "what's new?", "anything new?", "news?", "/new",
  "что нового", "что новенького", "есть что-то новое", "новости есть?".
- The intent is a quick inline answer, not a document, not a delivery, not a full run.

**Skip / don't use for:**
- **A formal digest artifact** (a file in `pipeline/3-synthesis/`, offered for delivery) —
  that is `digest-build` («собери дайджест»).
- **Sending** to configured channels — that is `digest-deliver` («отправь дайджест»).
- **The whole loop** incl. curate/synthesis/deliver — that is `run-now`
  («прогони цикл», «собери всё сейчас»).
- **"Show the LAST digest" / status / health** (read-only, nothing fetched) — that is
  `brain-ask`. whats-new *fetches fresh items*; brain-ask reads existing state.
- Research questions ("what do we know about X") — `research-frame` (the gateway).

> **RU near-collision.** «что нового» = quick inline answer (this skill);
> «собери дайджест» = the formal artifact (`digest-build`); «собери всё сейчас» =
> the whole loop (`run-now`).

---

## Steps

1. **Quick bootstrap collect** (seconds, RSS plus static article-page top-up — same cap the
   setup-wizard's first digest uses):

   ```bash
   python3 scripts/collect.py --max-articles 3
   ```

   - If the run lock is held (a scheduled run is in progress), `collect.py` skips
     cleanly — proceed with what is already on disk and say so in one line.
   - Zero RSS sources configured → skip the collect, answer from what's on disk, and
     note that fresh fetching needs at least one `rss` source (`source-manage` adds one).

2. **Sanitize** (the build gate is fail-closed by default; idempotent, cheap):

   ```bash
   python3 scripts/sanitize_incoming.py sanitize
   ```

3. **Build the light inflow snapshot to a TEMP file** — the daily "inflow" variant is
   exactly "what's new"-shaped (new sources + needs-attention, no concepts):

   ```bash
   SNAP="$(mktemp -t whats-new).md"
   python3 scripts/build_digest.py "$SNAP" --daily --lookback 3
   ```

   (A unique `mktemp` name per invocation — never a fixed path, so concurrent or stale
   runs can't collide.) Use `--lookback 3` as the default "recently" window; stretch it
   (e.g. 7) if the user asks "this week". Delete the temp file after answering.

4. **Answer INLINE.** Summarize the snapshot as a short chat message — the top 3–5 items
   as `title — one-line takeaway (link)`, grouped by topic only if more than one topic has
   items. In Telegram, send it with the **reply** tool (never just the transcript). Keep it
   a *message*, not a document: no headers ceremony, no health lines, no glossary.
   - **Quiet result is an honest answer:** "ничего нового за последние 3 дня" + the one
     newest older item, so the user still gets something anchoring.

5. **Offer follow-ups, don't perform them:** "хочешь полный дайджест (`/digest`),
   отправить в каналы (`/send`) или полный прогон (`/run`)?" — one line, only after the
   answer.

---

## Output

- An inline chat reply with the fresh items (or an honest "nothing new").
- **No** digest artifact persisted (temp file deleted), **no** delivery, **no** vault writes.
- Registry/incoming DO gain the newly collected articles — that is normal pipeline
  state (the weekly run will pick them up), not a side effect to undo.
