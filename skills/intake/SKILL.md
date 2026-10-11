---
name: intake
description: "THE primary add-a-link verb: the user just sends a link (or says add this) and this skill classifies it — feed → monitor via source-manage, one-off article → inbox via source-capture, ambiguous → exactly one question. Also unified intake for OPML subscription imports. Use for a bare/plain https://... URL, «add this», «add this link», «here is a URL», «what should we do with this link», «добавь это», «добавь эту ссылку», «вот ссылка», «забери эту ссылку», «что делать с этой ссылкой», and for import OPML / import subscriptions / migrate feeds — whenever the user has NOT explicitly said /add, /save, monitor-this, or save-this-article (those are expert shortcuts that skip classification). Runs scripts/import_opml.py for OPML preview/apply and scripts/intake.py for read-only URL classification, then asks for approval before persistence unless explicit automation is requested."
metainfo:
  type: worker
  domain: intake
  last_updated: 2026-07-14
  predecessor: [source-manage, source-capture]
  successor: [source-manage, source-capture]
---

# intake — just send a link (the primary add verb)

**This is the ONE advertised way to add something: the user just sends a link** — no
pre-classifying, no command to remember. It is the user-facing intake gateway for two
common inputs:

- a plain or bare HTTP(S) URL ("add this", «вот ссылка») where the user has not said
  whether it is a feed to monitor or an article to save — classified here: feed →
  `source-manage`, article → `source-capture`, ambiguous → exactly one question;
- an OPML file of existing subscriptions.

`/add <url>` and `/save <url>` stay available as **expert shortcuts** that skip this
classification (see *Explicit Overrides*). The skill previews or proposes first, then
persists only after the required approval gates.

## When to Use

Use this skill when the user asks to:

- handle a plain URL such as `https://example.com/post` with no explicit `/add`, `/save`, monitor, or save intent;
- "add this" / "add this link" / "here is a URL" — and the RU equivalents «добавь это»,
  «добавь эту ссылку», «вот ссылка», «забери эту ссылку» — i.e. any bare link plus a
  generic add/take verb;
- classify "here is a URL" / "what should we do with this link?" («что делать с этой
  ссылкой») into monitoring or one-off capture;
- import OPML, import subscriptions, migrate feeds, or bring over RSS subscriptions;
- handle a **forwarded Telegram post, a photo/screenshot (`image_path`), or a file
  attachment (`attachment_file_id`)** — see *Telegram forwards, photos, and file
  attachments* below.

## When to Skip

- Explicit `/add <url>` (expert shortcut) or explicit monitor/add-source intent («start monitoring X», «add this RSS feed») routes directly to `source-manage`; do not run `scripts/intake.py` and do not add a generic plain-URL approval.
- Explicit `/save <url>` (expert shortcut) or explicit save/read-it-later intent («save this article: <url>», «сохрани эту статью») routes directly to `source-capture`; do not run `scripts/intake.py` and do not add a generic plain-URL approval.
- Research questions route through `research-frame`.
- Read-only status questions route through `brain-ask`.

## OPML Import

1. Run a read-only preview:

   ```bash
   python3 scripts/import_opml.py PATH --json
   ```

2. Summarize in plain language:
   - proposed topics;
   - selected feeds;
   - already-existing feeds;
   - invalid or unsupported entries;
   - resulting topic assignment for each feed.

3. Let the user deselect feeds and reassign topics. Preserve those choices as:
   - `--select feed-001,feed-003`
   - repeated `--assign feed-003=topic-slug`

4. Ask one final confirmation before persistence.

5. After confirmation, apply with the same selection and assignments:

   ```bash
   python3 scripts/import_opml.py PATH --select feed-001,feed-003 --assign feed-003=topic-slug --apply --confirmed --json
   ```

6. Use automatic OPML import only when the user explicitly requests automation:

   ```bash
   python3 scripts/import_opml.py PATH --automatic --json
   ```

Report repeated imports as already-existing/no-op outcomes rather than errors.

## Plain URL

1. Run the read-only classifier:

   ```bash
   python3 scripts/intake.py URL --json
   ```

2. For `recurring_source`, show all handoff fields before persistence:
   - `source_url`
   - `source_type`
   - `topic_mode`
   - `proposed_topic`
   - reason
   - `tier` — ask: "How much do you trust this source — high / medium / low? (default medium)"
   - `priority=medium`
   - `filter_note="all posts"`
   - `active=yes`

   Confident recurring classifications still require approval before `source-manage` is invoked.
   If `topic_mode=create`, explicitly ask for approval to create that topic. A single-URL path must not auto-create a topic from a site name.

3. For `one_off_article`, show:
   - input URL;
   - reason;
   - proposed one-off capture action.

   Confident article classifications still require approval before `source-capture` is invoked. No topic is required at capture time.

4. For `ambiguous`, ask exactly:

   `Should I save this one article, or monitor this site for future updates?`

   Ask no second generic clarification. If the user chooses save, that authorizes the generic action and hands off to `source-capture`. If the user chooses monitor, that removes only the generic action approval: still ask for missing trust, still require approval to create a proposed new topic, and do not persist until those required fields/approvals are resolved. Existing-topic monitor handoff may proceed after the required trust field is supplied.

5. Automatic mode may bypass generic action approval only. One-off automatic intake and recurring automatic intake with an existing topic may proceed through existing backends. If recurring classification has `topic_mode=create`, return/report exact outcome `needs_topic_approval` and perform no `add-topic` or `add-source`.

## Telegram forwards, photos, and file attachments

Forwarding a post (or sharing a screenshot) to the bot is the most natural mobile
capture gesture — treat these as intake input, never silently ignore them. The
Telegram channel tag carries the surfaces:

- **`image_path` attribute** (a photo/screenshot): `Read` the image. If a URL or a
  clearly identifiable article/source title is visible, recover it and classify as a
  normal Plain URL above (feed → monitor, article → capture). If nothing actionable
  is recoverable, say what you saw and ask ONE question ("хотите, сохраню как
  заметку, или пришлёте ссылку?").
- **`attachment_file_id` attribute** (a document): call `download_attachment`, `Read`
  the returned file. An HTML/PDF/text article → offer one-off capture into the inbox
  via `source-capture` (the file is the source; keep its origin in the note). An OPML
  file → the OPML Import path above.
- **A forwarded post with text but no URL**: the text itself is the content — offer
  to capture it as a one-off inbox note (quote its first line back so the user sees
  what will be saved). With a URL inside, classify the URL as usual.

Every path ends in the same approval gates as the rest of this skill: propose first,
persist only after a yes.

## Explicit Overrides (expert shortcuts)

`/add` and `/save` are kept for back-compat (and stay in the BotFather command menu) as
**expert shortcuts** for users who have already classified their link themselves; the
advertised primary verb remains "just send the link".

- `/add <url>` and explicit "monitor this source" / "add this feed" intent skip `scripts/intake.py` and execute immediately through `source-manage`.
- `/save <url>` and explicit "save this article" intent skip `scripts/intake.py` and execute immediately through `source-capture`.
- The expert paths keep their existing contracts: required source-manage fields are still resolved by `source-manage`, and source-capture still uses its fetch/sanitize/inbox flow.

## Output

Keep user output plain:

- "I found an RSS feed and propose monitoring it under `ai-agents`."
- "This looks like one article; I can save it to the inbox."
- "This link has both article and feed signals, so I need one choice."

Do not expose internal pipeline vocabulary unless the user asks for implementation detail.

### Show what was found, not just the verdict

`classify_url` returns an optional `preview` alongside the verdict — the title,
publication, author(s), publication date and any discovered feed, read from the same
parse the verdict is based on (so it costs no extra request). Lead with those facts:
a confidence number is unverifiable, but "Deep dive, by Jane Doe, in Example Research"
is something the user can confirm at a glance before approving anything.

- Say what was detected, then what you propose doing about it.
- The preview may be sparse or absent — a page can say nothing about itself, and
  enrichment failure is deliberately non-fatal. Just omit what is missing; never
  invent a title or guess an author.
- **Authors are reported, not actionable.** Mention a detected author, but do NOT
  offer to "monitor this author" — that capability does not exist yet, and offering
  an action that silently does nothing costs more trust than staying quiet.
- The proposed actions remain exactly two: save the article, or monitor the source.

## Verification

- OPML preview writes nothing before `--apply --confirmed` or explicit `--automatic --json`.
- Plain URL classification writes nothing before approval.
- Ambiguous URLs ask exactly one generic question.
- Ambiguous→monitor retains trust and new-topic approval gates.
- Automatic recurring no-topic returns `needs_topic_approval` and makes no `add-topic` or `add-source` call.
- `/add <url>` and `/save <url>` bypass `scripts/intake.py`.
