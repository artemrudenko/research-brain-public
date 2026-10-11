# Digest feedback — the digest tunes itself

Every delivered (non-quiet) digest ends with a muted invite:

> _💬 Feedback tunes future digests — reply e.g. 'too technical', 'simpler',
> 'less of \<topic\>', 'mute \<source\>' (docs/feedback.md)._

Reply in plain words (EN or RU) — in Telegram, or any chat the agent listens in.
The `digest-feedback` skill maps the reaction onto **one reversible change through
an existing surface**, tells you what changed and how to undo it, and records the
event. Nothing here adds a new config mechanism.

## What each phrase does

| You say | What changes | Undo |
|---|---|---|
| "too technical" / "simpler" / «попроще» | `delivery.technical_level` steps DOWN one (`technical → balanced → non-technical`) | `/audience <old level>` |
| "more technical" / "more detail" / «потехничнее» | level steps UP one | `/audience <old level>` |
| "less of X" / "mute X" (topic) | topic paused via `source-manage` — **asks first** | "resume topic X" |
| "mute X" / "stop showing X" (source) | source paused via `source-manage` — **asks first** | "resume source X" |
| "not useful" / 👎 | nothing yet — the agent asks ONE question (topics? depth? volume?) | — |
| "useful" / 👍 | nothing — noted with thanks | — |

> **👍/👎 are messages, not tap-reactions.** Send the emoji **as a reply message** —
> tapping a reaction on the digest bubble never reaches the agent (the Telegram
> plugin's reaction API is outbound-only), so a tap is silently ignored.

Level shifts apply immediately (they are render-time only and explicitly requested);
anything that changes **what is monitored** (pausing a topic/source) is confirmed in
one line first, and is always a pause, never a removal.

## Where feedback is remembered

Every event — including "useful" and unanswered "not useful" — is appended by
`scripts/feedback.py` to `pipeline/.feedback/feedback.jsonl` (one JSON line per
event; relocated under `RESEARCH_BRAIN_STATE_DIR` when set, like all runtime
state). Review it anytime:

```bash
python3 scripts/feedback.py list            # recent feedback, newest first
python3 scripts/feedback.py list --json     # machine-readable
```

The log is the durable half of the loop: it lets future value reporting count
what readers actually said (how often "too technical" recurs, which topics get
muted) instead of guessing.
