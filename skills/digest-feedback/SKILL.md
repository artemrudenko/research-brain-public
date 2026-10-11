---
name: digest-feedback
description: "Turn a reader's reaction to a delivered digest into a concrete tuning change + a recorded event: 'too technical'/'simpler' or 'more technical' shifts delivery.technical_level one step; 'less of <topic>'/'mute <topic>' or 'mute <source>' pauses it via source-manage (confirm first); 'not useful'/👎 asks ONE clarifying question; 👍/'useful' just records. EVERY event is logged via scripts/feedback.py so metrics can count reader signal. Triggers: «too technical», «too complex», «simpler please», «more technical», «more detail», «less of X», «mute X», «stop showing X», «not useful», «useful», «👍», «👎», «слишком технично», «слишком сложно», «попроще», «потехничнее», «поменьше X», «замьють X», «не полезно», «полезно»."
metainfo:
  type: operational
  domain: meta-process
  last_updated: 2026-07-12
  relation: "Applies changes ONLY via existing surfaces: the audience knob (delivery.technical_level, same as /audience) and source-manage pause. Records via scripts/feedback.py. Sibling of digest-deliver (which sends) — this listens after the send."
---

# digest-feedback — the digest tunes itself from reader reactions

Every delivered (non-quiet) digest carries a muted footer inviting feedback. When the
reader answers — in Telegram, chat, anywhere the agent listens — this skill maps the
reaction onto a concrete, reversible tuning change **through existing surfaces only**,
and records the event so the product remembers what readers said.

---

## When to Use

**Use when** the user reacts to a digest (or to the system's output style in general):
- "too technical" / "too complex" / "simpler please" / «слишком технично» / «попроще»
- "more technical" / "more detail" / «потехничнее» / «подробнее»
- "less of <topic>" / "mute <topic>" / "stop showing <source>" / «поменьше X» / «замьють X»
- "not useful" / "useful" / a bare 👍 / 👎 **sent as a message** (a tap-reaction on
  the digest bubble never reaches the agent — the plugin's reaction API is
  outbound-only, so only the typed/replied emoji arrives)

**Skip / don't use for:**
- Questions about digest **content** ("show the last digest", findings) — `brain-ask`.
- **Adding** a source/topic — `source-manage` (this skill only pauses on request).
- Setting an explicit level by name ("/audience non-technical") — `setup-wizard`'s
  audience step handles the direct form; this skill handles the *reactive* form.
- Editorial complaints about one specific article — acknowledge + record `other`;
  don't mutate config off a single-article complaint.

---

## Steps

1. **Classify the reaction** onto one kind (the `scripts/feedback.py` slug):

   | Reader says | kind | Change |
   |---|---|---|
   | too technical / simpler / «попроще» | `too_technical` | step `delivery.technical_level` DOWN one: `technical → balanced → non-technical` (floor: stay + say so) |
   | more technical / more detail / «потехничнее» | `too_simple` | step level UP one: `non-technical → balanced → technical` (ceiling: stay + say so) |
   | less of / mute <topic> | `mute_topic` | pause the topic via `source-manage` — **confirm first** |
   | mute / stop showing <source> | `mute_source` | pause the source via `source-manage` — **confirm first** |
   | not useful / 👎 | `not_useful` | ask ONE clarifying question ("what missed — topics, depth, volume?"); record even if unanswered |
   | useful / 👍 / thanks | `useful` | no change — record only |
   | anything else digest-shaped | `other` | no change — record with the wording as `--note` |

2. **Apply the change via the existing surface** (never invent a new config path):
   - **Level shifts**: edit `config/channels.yaml` → `delivery.technical_level` to the
     stepped value (exactly what the `/audience` step does; render-time only —
     docs/audience-levels.md). Reversible and explicitly requested → apply WITHOUT an
     extra confirmation, then state the change and the undo (`/audience <old>`).
   - **Topic/source pause**: these change what gets monitored — **one-line confirm
     first** ("pause topic 'ai-ml'? Sources stay, collection stops; `resume` undoes"),
     then hand off to `source-manage` (pause). Never remove, only pause.

3. **Record the event — ALWAYS, even when nothing changed:**

   ```bash
   python3 scripts/feedback.py record --kind <kind> [--target <topic-or-source>] \
       --note "<reader's wording, short>" [--action "<what was changed>"]
   ```

4. **Confirm inline, one line**: what was understood, what changed (or why not), how to
   undo. In Telegram send it with the **reply** tool. Match the user's language.

---

## Output

- At most ONE config change per reaction (level step, or one pause) — via existing
  surfaces, reversible, stated back to the user with its undo.
- One appended line in `pipeline/.feedback/feedback.jsonl` (state-dir aware).
- No digest rebuild, no delivery, no vault writes.
