---
name: capabilities
description: "Present a friendly, plain-language menu of what this system can do, grouped by the user's goal, with concrete example sentences they can say. This is an ORIENTATION skill — it does NOT do the work itself; it shows the user what's possible and routes them to the right capability. Named `capabilities` (not `help`) to avoid colliding with the built-in /help CLI command, but its triggers include help-style phrasing. Triggers: «what can you do», «help», «what can I say», «what commands», «show me what's possible», «how do I use this», «что ты умеешь», «помощь», «что можно сказать», «какие команды»."
metainfo:
  type: lookup
  domain: meta-process
  last_updated: 2026-07-26
---

# capabilities — the friendly "what can you do?" menu

When the user asks what the system can do — "what can you do?", "help", "what can
I say?", "что ты умеешь?", "помощь" — this skill answers with a short, plain-language
menu of what's possible, **grouped by what the user wants to achieve**, with a few
example sentences they can copy. It then invites them to just say what they want.

**This skill orients — it does not do the work.** Its only job is to present the menu
and route the user to the right capability. It never edits config, builds or sends a
digest, or runs research. Once the user picks something, the matching skill takes over.

**The `/help` / `help` answer is a PREPARED card, not a generated menu.** For an
open-ended "what can you do?" / "help", emit [`help-card.md`](help-card.md) **verbatim**
(Russian conversation → the Russian twin [`help-card.ru.md`](help-card.ru.md), same rule)
— don't re-assemble it from prose each time. A canned card is deterministic and stays
operationally accurate about which slash commands actually reach the agent (the bare
`/help` and `/status` are swallowed by the Telegram plugin — the card says so). You may
translate the framing prose to mirror the conversation language, but keep the command
list and the ⚠️ interception warning intact. The grouped menu below is the fallback for
richer, goal-shaped "how do I…" questions and for keeping the card in sync.

---

## When to Use

**Use when the user asks (EN or RU):**
- "what can you do?", "what can I say?", "what commands are there?", "show me what's
  possible", "how do I use this?", "help"
- "что ты умеешь?", "помощь", "что можно сказать?", "какие команды?"

**Use automatically (no ask needed) when, in a channel (e.g. Telegram):**
- it is the **first message from that chat in this session** — send the short
  `help-card.md` menu first; if the message also carries a real request, answer it
  right after (the card is a preface, never a substitute);
- the message is an **unrecognized slash command** (not in the command table — including
  retired aliases like `/concepts`) — reply with the card instead of a bare error, so a
  typo'd command still teaches the user what works.

**Use a single example, not the whole menu, when:**
- The user names a concrete task ("how do I add a source?", "how do I send the
  digest?"). Don't dump the full menu — point them at the one matching capability
  and its example sentence (see *Routing a concrete "help with X"* below).

**Skip / don't use for:**
- An actual request to do something ("start monitoring AI agents", "send the digest").
  That is not a help question — let the matching skill handle it directly.
- The built-in `/help` CLI command (that's the runtime's own help, not this skill).

---

## The capability menu

Present this menu in the **conversation's language** (mirror EN or RU). Lead with the
user's goal; mention skill names only in light parentheses. Keep it tight — a couple
of example sentences per group, not an exhaustive list.

**1. Set things up** *(setup-wizard)*
First-time setup defaults to the full agentic research-brain path. Advanced users can
ask for RSS Digest Lite or headless transports; otherwise the wizard keeps those details
out of the way.
- "let's set this up"
- "configure my sources and channels"
- "set up where the digest gets delivered"

**2. Add a link — just send it** *(intake)*
The primary add verb: paste a URL (or say "add this") and it figures the rest out —
a feed becomes a monitored source, a one-off article goes to the inbox, and when it
could be either it asks exactly one question. OPML subscription imports land here too.
(`/add` and `/save` are expert shortcuts that skip the question.)
- just paste the URL — nothing else needed
- "add this: https://example.com/post" / «добавь это», «вот ссылка»
- "import my OPML subscriptions"

**3. Manage what I monitor** *(source-manage · discover-sources · author-manage)*
Add, pause, or stop watching a topic or a source — just say it in plain words. Ask for
*proposals* when you don't know what to add yet (they are only proposals — nothing is
added until you pick), and follow individual **people** as well as feeds.
(A bare link goes through *Add a link* above; `/add <url>` is the expert shortcut.)
- "start monitoring AI agents"
- "watch this blog: https://example.com/"
- "pause this source" / "stop monitoring topic markets"
- "who else should I read about X?" / "/discover X" *(discover-sources — proposes, never adds)*
- "follow this author" / "/author list" *(author-manage — a person, not a feed)*

**4. Capture & read-it-later articles** *(source-capture)*
Explicitly save a single article to read later; the queue becomes concepts in
batches — captured instantly, processed when enough has accumulated (or on request).
(A bare link goes through *Add a link* above; `/save <url>` is the expert shortcut.)
- "save this article: https://example.com/post"
- "read this and keep it" / "сохрани эту статью"
- "process the inbox" / "разбери накопленное"

**5. Ask about my brain** *(brain-ask · wiki-query · trends)*
A read-only question about the system's own state — what it watches, how often, and
what it has produced — or about what the vault already knows. It changes nothing.
- "what are we monitoring?" / "how often do we collect?" *(brain-ask)*
- "show me the last digest" / "key findings this week" *(brain-ask)*
- "what does my brain know about X?" / "/know X" *(wiki-query — vault only)*
- "how are my topics changing?" / "/trends" *(trends — top movers over time)*

**6. Get a digest**
- Just ask "what's new?" *(whats-new)* — the everyday verb: a quick fresh check answered
  right in the chat, no digest file, nothing sent — "что нового" / "/new"
- Build one now *(digest-build)* — "build a digest now" / "make the weekly digest"
- Send a built one *(digest-deliver)* — "send the digest" / "deliver the digest"
- Do the whole cycle now *(run-now)* — "run the whole pipeline now" / "прогони цикл сейчас"
- After reading, just react *(digest-feedback)* — "too technical" / "less of X" /
  "mute X" / 👍👎 sent as a message (tap-reactions never arrive) — it tunes itself
  (one reversible change, undo stated)
- Want it daily too? *(setup-wizard)* — "add a daily digest" / "добавь ежедневный
  дайджест" (and "remove the daily digest" turns it back off)

**7. Research a topic deeply** *(research-frame chain)*
Investigate a subject — it checks what we already know (the vault), gathers more, and
builds a cited answer. This is the front door for any "about a topic" question — it
routes through the vault automatically.
- "research retrieval-augmented generation"
- "what do we know about X?"
- "what concepts do we have on this topic?"
- "deep dive on this topic"

**8. Browse & manage the knowledge base** *(concept-manage · the Obsidian vault)*
Open your saved notes in Obsidian to explore everything it has learned — or directly
create, list, refresh, and archive the concepts it tracks (archive is a reversible
soft-delete).
- "open my knowledge base" / "where is the vault?"
- "create a concept for X" / "track this as a concept"
- "list my concepts" / "update the X concept" / "archive the X concept"

Close by inviting the user to **just say what they want** in plain language — they
don't need to memorize commands.

---

## Routing a concrete "help with X"

When the user asks for help with a **specific** task, skip the full menu and route to
the one matching group, quoting its example sentence:

| The user asks… | Point them to… |
|---|---|
| "how do I add a link I found?" / "what do I do with this URL?" | **Add a link — just send it** — *just paste the URL*; it classifies feed vs one-off article and asks at most one question |
| "how do I add a source / a feed / a topic?" | **Manage what I monitor** — *"start monitoring X"* / *"watch this blog: <url>"* (or just paste the link — *Add a link* classifies it) |
| "how do I save / capture one article (a link)?" | **Capture & read-it-later articles** — *"save this article: <url>"* (or just paste the link) |
| "how do I process what I've saved?" | **Capture & read-it-later articles** — *"process the inbox"* |
| "how do I stop / pause watching something?" | **Manage what I monitor** — *"pause this source"* / *"stop monitoring topic X"* |
| "what else should I be reading / follow?" | **Manage what I monitor** — *"who else should I read about X?"* (proposals only) / *"follow this author"* |
| "how do I see what's being watched?" | **Ask about my brain** — *"what are we monitoring?"* |
| "how do I build / make a digest?" | **Get a digest** — *"build a digest now"* |
| "how do I send / deliver a digest?" | **Get a digest** — *"send the digest"* |
| "how do I run everything now?" | **Get a digest** — *"run the whole pipeline now"* |
| "how do I research / look something up?" | **Research a topic deeply** — *"research X"* |
| "how do I create / track / refresh / archive a concept?" | **Browse & manage the knowledge base** — *"create a concept for X"* / *"list my concepts"* |
| "how do I set things up / configure?" | **Set things up** — *"let's set this up"* |

If it's still ambiguous which they mean, ask ONE clarifying question (clarify, don't
invent — see AGENTS.md mandatory rules), then point them at the right group.

---

## Keeping the menu accurate (don't let it go stale)

This menu mirrors the **skill trigger table in `AGENTS.md`**, which is the source of
truth for what the system can do. If that table changes — a skill is added, removed,
renamed, or its triggers shift — **update this menu AND [`help-card.md`](help-card.md)
to match** so neither advertises something that no longer exists (or omits something
new). `help-card.md` is integrity-checked by `tests/test_help_card.py`, which pins the
working-command list and the ⚠️ interception warning — run it after any edit. When in
doubt, re-read the `AGENTS.md` trigger table and reconcile both against it.

---

## Output

- A short, grouped, plain-language menu in the conversation's language, each group with
  2–3 quoted example sentences and the skill named only lightly in parentheses.
- For a concrete "help with X", a single routed pointer instead of the whole menu.
- A closing invitation to just say what they want — no jargon, no code, no file paths
  the user has to touch.

---

## Examples

**Example 1 — open-ended "what can you do?":**
> User: "what can you do?"
> Presents the eight grouped capabilities above, each with a couple of example
> sentences, then invites the user to just say what they want.

**Example 2 — concrete task, route don't dump:**
> User: "how do I add a source?"
> Skips the full menu. Replies that the simplest way is to just send the link (the
> **intake** capability classifies it — feed vs one-off article — and asks at most one
> question), or to say it explicitly, e.g. *"watch this blog: https://example.com/"* or
> *"add this RSS feed to tech-news"* (the **source-manage** capability); either way it
> confirms the topic and type.

**Example 3 — Russian trigger, same menu in the conversation language:**
> User: "что ты умеешь?"
> Presents the same eight-group menu, written in Russian, with example sentences in
> the user's language, and closes by inviting them to just say what they need.
