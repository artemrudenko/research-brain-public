---
name: source-manage
description: "Fast, single-intent conversational CHANGES to monitored topics & sources. The user says one thing — \"start monitoring topic X\", \"watch this blog\", \"add this RSS feed\", \"/add <url>\" (expert shortcut), \"pause that source\", \"stop monitoring topic Z\", \"remove this source\" — and this skill mutates the topics+sources config (config/topics.yaml + config/sources.yaml) accordingly via scripts/manage_sources.py: idempotent, name-synced, formatting-preserving, then re-validates with validate_config.py. It clarifies missing fields (type / tier / which topic) by ASKING — it never invents them. Distinct from setup-wizard (bulk first-run interview); use this for one quick change at a time. Read-only questions («what are we monitoring», «how often», «show my sources», recent digests/findings) belong to brain-ask, NOT this skill. A bare URL or a generic «add this <link>» without recurring intent belongs to intake — the advertised primary verb (just send the link); «/add <url>» is the expert shortcut that skips intake's classification and lands here directly. Triggers: «/add <url>», «monitor this topic», «start monitoring X», «watch this blog», «add this RSS feed», «add a source», «pause this source», «resume this feed», «stop monitoring», «remove this source», «remove topic», «начни мониторить тему», «следи за блогом», «добавь RSS-фид», «поставь источник на паузу», «перестань мониторить тему», «убери источник»."
metainfo:
  type: worker
  domain: config
  last_updated: 2026-07-12
  predecessor: [setup-wizard]
  successor: [concept-manage]
---

# source-manage — conversational topic & source edits

Fast, single-intent edits to **what this brain monitors**. The user says one
thing in plain language and this skill makes the matching change to the two
config files that drive collection, then confirms back in plain language:

| File | What this skill changes |
|------|-------------------------|
| `config/topics.yaml`  | adds / removes a topic entry |
| `config/sources.yaml` | adds a source; flips a source's `active` flag; deletes a single source; adds / removes the matching category |

The YAML twins are the only config the runtime reads (CONVENTIONS §2.3). On an
unmigrated legacy `.md` install the backend refuses loudly with the
`python3 scripts/schema.py migrate-config` pointer — relay it to the user (one-command
sidecar import; the `.md` files stay untouched as rollback). Leftover legacy `.md` files
next to the YAML are ignored and never touched.

All mutations go through **`scripts/manage_sources.py`** — a deterministic,
idempotent backend. The skill never hand-edits the markdown: it parses the
user's intent, fills any missing fields by **asking** (never inventing), then
calls the script and re-validates.

Secrets are **never** involved here (sources are public URLs). Tags, channels,
and schedule are out of scope — those belong to `setup-wizard`.

---

## When to Use

**Use when** the user wants ONE quick change to monitoring, e.g.:
- "/add <url>" → the expert shortcut: direct add-source route, skipping `intake`
  classification (the advertised primary verb — just sending the link — goes to `intake`).
- "start monitoring AI agents" / "начни мониторить тему ai-agents" → add a topic.
- "watch this blog: https://…" / "следи за блогом …" → add a source.
- "add this RSS feed …" / "добавь RSS-фид …" → add an `rss` source.
- "pause that feed" / "поставь источник … на паузу" → set a source inactive.
- "resume …" / "включи обратно …" → set a source active.
- "stop watching THIS blog / delete this source" / "убери этот источник" →
  delete ONE source row (`remove-source`) — leaves the topic and other sources.
- "stop monitoring topic Z" / "перестань мониторить тему Z" → remove a topic.

> A bare **read-only** question — "what are we monitoring?", "how often do we
> collect?", "show my sources" — is **brain-ask**, not this skill. This skill only
> uses `list` internally (to confirm a change, or to resolve "which topic?").

> **Unified intake boundary:** the advertised primary verb is "just send the link" —
> a bare URL or a generic «add this» without recurring intent routes to `intake`,
> which classifies (feed → here, one-off article → `source-capture`) and asks generic
> approval first. `/add <url>` and explicit monitor/add intent («start monitoring X»,
> «watch this blog», «add this RSS feed») are the expert shortcut: they route directly
> here and do not run `scripts/intake.py`.

**Skip / use `setup-wizard` instead when:**
- It is **first-run / bulk** setup ("set up sources", "configure", "starter
  pack", "онбординг") — the wizard does topics + sources + tags + channels +
  schedule + the delivery rehearsal in one interview.
- The change is to **tags**, **delivery channels**, **schedule**, or
  **language** — those are wizard territory, not this skill.
- The user wants secrets handled — direct them to `config/.env` (this skill
  touches no secrets).

> **Boundary in one line:** `setup-wizard` is the multi-step interview that
> stands the config up (and owns tags/channels/schedule). `source-manage` is
> the quick, in-conversation editor for topics & sources only, one intent at a
> time. When a single source/topic tweak is asked, prefer this skill.

---

## DO / DON'T

**DO:**
- Parse exactly ONE intent per turn; do the smallest change that satisfies it.
- **Clarify, don't invent — in plain words.** If a required field is missing or
  ambiguous, ASK, but never expose internal jargon to a non-technical user:
  - no topic given for a new source → ask which topic (or offer to create one);
  - type → **detect from the URL, then confirm in plain language** (e.g. "I'll
    watch this page for new posts — sound right?"); never make the user pick the raw
    `rss/blog/medium-tag/webpage` enum — only fall back to a friendly type question
    as a last resort if detection is genuinely unclear;
  - trust not given → ask "how much you trust it" (high / medium / low), defaulting
    to `medium` only after offering it. **Never say the word "tier" to the user.**
- Detect the source **type** from the URL, then confirm: `.xml` / `/feed` /
  `/rss` / `/atom` → `rss`; `medium.com/tag/…` → `medium-tag`; a blog *index*
  (`…/blog`) → `blog`; anything else → `webpage`. Prefer `rss` when a feed exists.
  This detection is internal — confirm it back in plain words, not as the enum.
- **Prefer the gentlest action that fits the intent** (clarify, don't invent):
  - `pause` — keep the row, just stop collecting. The **default** when the user
    says "stop"/"pause" without clearly asking to delete. Reversible via `resume`.
  - `remove-source <url>` — delete exactly ONE source row. Use only when the user
    clearly wants the source **gone** ("delete this source", "remove this blog").
  - `remove-topic <name>` — drop the WHOLE topic + all its sources. Use only for
    "stop monitoring the entire topic". Confirm first — it is destructive.
  - If it's unclear whether the user wants to pause or delete, **ask**; default to
    pause (it's reversible).
- **Guard `remove-topic`:** before removing, confirm with the user, and warn if
  the topic still has other sources (they all go) or if it is the **last** topic —
  a brain with zero sources collects nothing. Suggest pausing the sources
  instead in that case.
- Call `scripts/manage_sources.py` for every mutation (never hand-edit the files).
- After any write, run `python3 scripts/validate_config.py` and report the result.
- Keep topic ↔ category names in sync — the script does this; don't fight it.
- Confirm the change back in plain, non-technical language.

**DON'T:**
- Don't invent a topic name, tier, type, or URL the user didn't supply — ask.
- Don't run the full `setup-wizard` interview for a one-line change.
- Don't touch `config/tags.yaml`, `channels.yaml`, `schedule.yaml`, `brain/`,
  or `pipeline/` — out of scope here.
- Don't write secrets anywhere. Sources are public URLs only.
- Don't duplicate a source — the script is idempotent on URL; trust it.

---

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `INTENT` | enum | yes | — | add-topic / add-source / pause / resume / remove-source / remove-topic / list |
| `TOPIC` | string (slug) | for topic/source ops | — | lowercase slug, e.g. `ai-agents` |
| `URL` | string | for source/pause/resume/remove-source | — | full `http(s)://` URL |
| `TYPE` | enum `rss`/`blog`/`medium-tag`/`webpage` | **yes for add-source** (CLI `--type` is `required=True`) | detected, then confirmed | source type — confirm with the user first; never call `add-source` without it |
| `TIER` | enum `high`/`medium`/`low` | for add-source | `medium` (after asking) | source credibility |
| `PRIORITY` | enum `high`/`medium`/`low` | no | `medium` | collection ordering |
| `FILTER` | string | no | `—` | short filter note |
| `ACTIVE` | bool | no | `yes` | start active? |

Use AskUserQuestion-style prompts: ask one focused question, wait, confirm, then act.

---

## Steps

### Step 1 — Parse the single intent

Map the user's sentence to one `INTENT` and pull whatever fields are present:
- "monitor / start monitoring / track topic **X**" → `add-topic`, TOPIC=X.
- "watch this blog / add this feed / add source **URL** [to topic **X**]" → `add-source`.
- "pause / stop **URL**" → `pause`; "resume / re-enable **URL**" → `resume`.
- "delete / remove this source **URL**" → `remove-source`, URL=URL (one row only).
- "stop monitoring / remove topic **X**" → `remove-topic`, TOPIC=X (whole topic).

Disambiguate "stop": a single **URL** → `pause` (default) or `remove-source` (if
the user wants it deleted); a **topic name** → `remove-topic`. When unsure, ask.
- post-change confirmation / "which topic exists?" → `list` (internal only — a
  bare "what are we monitoring" question is **brain-ask**).

Normalize a free-text topic to a slug (`AI Agents` → `ai-agents`). If the
slug is unclear, propose one and confirm.

### Step 2 — Clarify any missing field (don't invent)

Only ask for what's actually missing for the chosen intent — always in plain words:
- **add-source with no topic** → "Which topic should this go under? (or shall I
  create one named …?)" If the topic doesn't exist, the script creates it — tell
  the user it will.
- **add-source, type** → **detect from the URL, then confirm in plain language**
  (e.g. "I'll watch this page for new posts — sound right?" for a blog index, or
  "Looks like an RSS feed — I'll subscribe to it, ok?"). Don't surface the raw
  `rss/blog/medium-tag/webpage` enum; only ask a friendly type question as a last
  resort if detection is genuinely unclear.
- **add-source, no trust level** → "How much do you trust this source —
  high / medium / low? (default medium)". (Never call it a "tier".)
- **bad/typo'd URL** → don't write it; show what's wrong and ask for a fix.

Never fill a field with a guessed value. A wrong source is worse than a question.

### Step 3 — Call the backend script

Run exactly one command (relative path, from the project root):

```bash
# add a topic (creates the topic + matching category in the active config)
python3 scripts/manage_sources.py add-topic ai-agents

# add a source (auto-creates the topic if it's new)
python3 scripts/manage_sources.py add-source ai-agents https://blog.example/feed.xml \
    --type rss --tier high --priority medium --filter "all posts" --active yes

# pause / resume a source by URL (reversible — keeps the row)
python3 scripts/manage_sources.py pause  https://blog.example/feed.xml
python3 scripts/manage_sources.py resume https://blog.example/feed.xml

# delete ONE source row by URL (gone — topic + other rows untouched)
python3 scripts/manage_sources.py remove-source https://blog.example/feed.xml

# stop monitoring a WHOLE topic (drops both its topic + category sections)
python3 scripts/manage_sources.py remove-topic ai-agents

# show current state (human summary, or --json for machine view)
python3 scripts/manage_sources.py list
python3 scripts/manage_sources.py list --json
```

The script is **idempotent** (re-adding the same URL/topic is a no-op;
`remove-source` on an absent URL reports `not found (already absent)` and writes
nothing),
**name-synced** (topics ↔ sources config), and **targeted** (it changes only the
relevant entry). A malformed URL/type/tier/priority or
topic name makes it exit non-zero with a clear message — relay that to the user
and ask for a correction rather than retrying blindly.

### Step 4 — Validate and confirm

1. Run `python3 scripts/validate_config.py` (bare — it validates the real
   `config/` from a POSITIONAL dir; **do not** pass `--config-dir`, that flag is
   `manage_sources.py`'s, not the validator's). Success looks like:
   `OK: channels.yaml, schedule.yaml, sources.yaml, topics.yaml, tags.yaml valid.` (an
   unmigrated legacy `.md` install instead FAILs with the `migrate-config` pointer —
   relay it). On a not-yet-configured
   (template) brain it ALSO prints `WARN: EXAMPLE placeholders still present` —
   that WARN is **benign and expected**, exit code stays 0; treat it as success
   and do NOT report it to the user as an error. A `FAIL:` (non-zero exit) is a real
   validation failure — report the exact violation and fix it. An `ERROR:` line (or
   any non-zero exit where validation **couldn't run** — e.g. PyYAML missing) means
   **validation didn't run**: do NOT claim "validated ✓" — surface it to the user
   verbatim and tell them the change was written but could not be validated.
2. Confirm the change back to the user in plain language, e.g. "Done — I'm now
   monitoring **ai-agents** and watching the RSS feed `blog.example/feed.xml`
   (high trust). Want to add another source or set the cadence?"
3. If the user just created their **first** topic, mention they may want
   `setup-wizard` to set delivery + schedule if they haven't yet.

---

## Output

After the run, the skill has changed only the file(s) the intent required
(`config/topics.yaml` / `config/sources.yaml`):

- `topics.yaml` — a `topics:` entry added or removed.
- `sources.yaml` — a source added, a source's `active` flipped, a single
  source deleted (`remove-source`), or the matching category added/removed.
  The file stays schema-valid.

Names stay in sync across the two files; no other config is touched; no secrets
are written. End by summarizing the new monitoring state in plain language and
the `validate_config.py` result.

---

## Verification

Run after writing; report results to the user:

1. **Validator green.** `python3 scripts/validate_config.py` (no `--config-dir`)
   reports `OK: channels.yaml, schedule.yaml, sources.yaml, topics.yaml, tags.yaml valid.` and exits 0. A
   `WARN: EXAMPLE placeholders still present` on a template brain is benign — not
   a failure. A `FAIL:` / non-zero exit counts as broken. An `ERROR:` line (or any
   non-zero exit where validation could not run, e.g. PyYAML missing) means
   validation **didn't run** — don't report "validated ✓"; surface it to the user.
2. **Names in sync.** `python3 scripts/manage_sources.py list --json` shows each
   topic with a matching category (the same names).
3. **Idempotent.** Repeating the same command makes no further change
   ("already present" / "no-op").
4. **Targeted.** Unrelated topics/rows are unchanged (a `git diff config/` shows
   only the intended section/row).
5. **Type/tier valid.** Any new source row has a `Type` in
   rss/blog/medium-tag/webpage, a `Tier` in high/medium/low, and a `http(s)` URL.

Report e.g.: "verification: validate_config OK / 3 topics in sync / re-run no-op
/ diff shows only the ai-agents row / type rss + tier high valid".

---

## Examples

**Start monitoring a new topic**
> User: "хочу начать мониторить тему ai-agents"
> → `add-topic ai-agents`. Creates the `ai-agents` topic and its matching (empty)
> category in the config (`topics.yaml` + `sources.yaml`).
> validate_config OK. "Готово — слежу за темой **ai-agents**. Какие источники
> добавить? Просто пришлите ссылку — я сам определю, как за ней следить, и уточню."

**Watch a blog (type clarified, not invented)**
> User: "следи за блогом https://simonwillison.net/"
> → It's a blog index, no `/feed` in the URL → internally `blog`; the skill confirms
> in plain words ("I'll watch this site for new posts") and notes "this site also
> has an RSS feed at `/atom/everything/` — want me to subscribe to that instead, it's
> more reliable?". Asks which topic + how much they trust it. After answers:
> `add-source ai-agents https://simonwillison.net/atom/everything/ --type rss
> --tier high --priority medium --filter "Simon Willison"`. Confirms.

**Add an RSS feed to an existing topic**
> User: "добавь RSS-фид https://hnrss.org/frontpage в tech-news"
> → URL ends in a feed path → `rss`. Tier not given → asks (defaults medium).
> `add-source tech-news https://hnrss.org/frontpage --type rss --tier medium …`.

**Pause / resume a source**
> User: "поставь источник https://hnrss.org/frontpage на паузу"
> → `pause https://hnrss.org/frontpage` → its row `Active` becomes `no`. Resume
> later with "включи обратно …" → `resume …`. Idempotent: pausing an already-
> paused feed reports "no-op".

**Stop watching one blog (delete a single source, keep the topic)**
> User: "stop watching this one blog: https://oldblog.example/feed"
> → This targets ONE source, and the user said "stop watching … this blog" — if
> they mean *delete*, `remove-source https://oldblog.example/feed` drops just that
> row; the topic and its other sources stay. If they might just want a break,
> offer `pause` instead (reversible). Idempotent: removing an absent URL reports
> "not found (already absent)". "Removed that source — the topic and its other
> feeds are untouched."

**Stop monitoring a topic (whole topic — confirm first)**
> User: "перестань мониторить тему tech-news"
> → `remove-topic tech-news` drops the `## Topic:` and `## Category:` sections,
> leaves every other topic untouched. Confirm first (it's destructive), and warn
> if it's the **last** topic (zero rows left → validator FAILs) — offer to pause
> its sources instead. "Больше не слежу за **tech-news**."

**Show what we monitor**
> User: "покажи что мониторим"
> → `list` → "You are monitoring these topics: ai-agents: 2 source(s) (1 paused);
> tech-news: 4 source(s)". Plain-language, no markdown dumped at the user.

**Bad URL — clarify, don't write**
> User: "add source medum,com/tag/ai to ai-agents"
> → URL is malformed → the script would reject it; the skill catches that first:
> "That doesn't look like a valid URL — did you mean
> `https://medium.com/tag/ai/latest`?" Writes nothing until corrected.

**Boundary nudge to setup-wizard**
> User: "set up everything from scratch — topics, delivery, schedule"
> → That's bulk first-run. The skill hands off: "That's a full setup — run the
> `setup-wizard` skill; it walks topics → sources → tags → delivery → schedule
> in one go. I'm for quick single edits afterwards."
