# Telegram quick commands

> **Source of truth for the Telegram command list.** CLAUDE.md's command table and
> `skills/capabilities/help-card.md` (and its Russian twin `help-card.ru.md` — the
> auto-help reply for Russian chats) mirror this file — edit here first, then sync them.
>
> This file is only the slash-command **menu**. To connect a Telegram bot from scratch
> (create bot → token → chat_id → test), see the "Connect Telegram" section in
> [`QUICKSTART.md`](../QUICKSTART.md). If the bot seems to ignore commands, it is almost
> always owned by a session in **another project** — a token has only one live listener;
> see [`telegram-multiproject.md`](telegram-multiproject.md).

These are convenience aliases the agent recognises on incoming Telegram messages
(MCP mode only — see the "Telegram quick commands" section in [`CLAUDE.md`](../CLAUDE.md)).
Each one routes to an existing skill from the `AGENTS.md` trigger table; there is no
extra code behind them.

> **The primary verb is simpler than any command: just send the link.** A bare URL —
> or "add this" in any phrasing — routes to the `intake` skill, which classifies it:
> a feed → monitored (via `source-manage`), a one-off article → the inbox (via
> `source-capture`), ambiguous → one question. `/add` and `/save` below are **expert
> shortcuts** that skip that classification when you already know which one you mean;
> they stay for back-compat and remain in the BotFather menu.

## Register the menu with BotFather

The slash commands work the moment the agent reads them as triggers, but to make them
appear in Telegram's command menu (the `/` button next to the message box), register
them once with [@BotFather](https://t.me/BotFather):

1. Open a chat with **@BotFather**.
2. Send `/setcommands` and pick your bot.
3. Paste the block below **verbatim** (one `command - description` per line, no leading
   slash), then send.

```
new - What's new? Quick fresh check, answered right here
trends - How is it changing? Topic movers, rising tags, growth
know - What does my brain know about X: /know <topic>
digest - Build this week's digest
send - Send the last built digest
run - Run the full pipeline now (collect → … → deliver)
sources - List monitored topics & sources
discover - Propose NEW sources for a topic: /discover <topic> (never adds them)
add - Expert shortcut: monitor a source: /add <url> (or just send the link)
save - Expert shortcut: capture one article: /save <url> (or just send the link)
process - Process the captured-article inbox into concepts
research - Research a topic: /research <question>
concept - Manage concepts: /concept new | list | update | archive | restore
author - Manage followed authors: /author add | list | nodes | pause | resume | remove
audience - Set output detail: /audience technical | balanced | non-technical
```

> **Why no `help` / `status` / `start` in the list?** The official Telegram plugin
> swallows those three slashes before they reach the project, so registering them as
> `/`-menu commands would only advertise buttons that do nothing. They work as **bare
> words** instead — see the note below. (`status` and `help` route to `brain-ask` /
> `capabilities` exactly like the others; only the leading slash is the problem.)

To change the list later, re-run `/setcommands` with the edited block. To clear it,
use `/deletecommands`.

## What each command does

| Command | Routes to skill | Behavior |
|---|---|---|
| `/new` | `whats-new` | The everyday verb: quick fresh collect (capped, RSS) + an inline "what's new" answer in the chat. Persists no digest, sends nothing. |
| `/trends` | `trends` | "How is it changing?": inline top movers — topic volume vs last week, rising tags, activity, knowledge growth — from data already on disk. Read-only; persists no report. |
| `/know <topic>` | `wiki-query` | Vault-only answer to "what does my brain know about X?" (`VAULT_ONLY`): reads `brain/` via the INDEX.md MOC; honest miss + research offer, never silently researches the web. |
| `/digest` | `digest-build` | Builds the weekly digest locally (no send); offers to deliver it afterward. |
| `/send` | `digest-deliver` | Delivers the most recently built digest to the channels in `config/channels.yaml`. |
| `/run` | `run-now` | Runs the whole gated loop (collect → sanitize-incoming → curate → synthesis → hygiene → digest → deliver). |
| `status` (bare word) | `brain-ask` | Read-only: health (feeds, delivery, freshness), what we monitor, recent digests. Type `status`, not `/status` (plugin-intercepted). |
| `/sources` | `brain-ask` | Read-only: lists monitored topics & sources. |
| `/discover <topic>` | `discover-sources` | Proposes NEW sources worth monitoring for a topic: searches, groups by site, drops what is already monitored, returns at most ten with the reason each surfaced. Read-only — it never adds anything; accepted candidates go to `source-manage`, which is where the trust tier is set. |
| `/add <url>` | `source-manage` | **Expert shortcut** — adds a source/feed/topic to monitoring directly, skipping `intake` classification (writes the YAML config — `config/sources.yaml` + `topics.yaml`). Primary path: just send the link. |
| `/save <url>` | `source-capture` | **Expert shortcut** — captures a **one-off** article (read-it-later) into the inbox queue directly, skipping `intake` classification; acks the queued count and offers to process when it fills. Primary path: just send the link. |
| `/process` | `source-capture` | Drains the captured-article inbox: fan-out readers → route each to its topic → curate→synthesis→ingest into concepts. |
| `/research <q>` | `research-frame` | Enters the research chain (gateway routes onward to `wiki-query`, etc.). |
| `/concept <sub>` | `concept-manage` | Manage one concept: `new` (interview → monitored concept + note), `list`, `update <name>` (re-research), `archive <name>` (soft-delete), `restore <name>`. Bare `/concept` lists; the old `/concepts` alias is retired (auto-help catches it). |
| `/author <sub>` | `author-manage` | Manage the followed-authors roster (`config/authors.yaml`): `add` (follow one the user has decided to follow), `list`, `nodes` (list author nodes in `brain/authors/` with `followed: yes/no`, read-only), `pause <name>`, `resume <name>`, `remove <name>`. Bare `/author` lists. Distinct from `/add` (a feed/site) and from Source Insights, which only **suggests** authors — it can never add one. |
| `/audience <level>` | `setup-wizard` | Sets `delivery.technical_level` (`technical` \| `balanced` \| `non-technical`) — how much output is explained vs assumed. Render-time only; jumps to the wizard's audience step. |
| `help` (bare word) | `capabilities` | Plain-language menu of everything the system can do. Type `help`, not `/help` (plugin-intercepted). |

> **First contact: type `help`, not `/help`.** `/help`, `/status`, and `/start` are the
> three slashes the official Telegram plugin intercepts, so they never reach this project.
> The fix is simply to **drop the slash**: send the bare word `help` or `status` (or just
> ask in plain language) and it routes normally. The table above is still correct for the
> bare-word path. See [`skills/capabilities/help-card.md`](../skills/capabilities/help-card.md).

> **Auto-help.** On the **first message from a chat in a session** and on **any
> unrecognized slash command** (including retired aliases like `/concepts`), the agent
> replies with the short menu from
> [`skills/capabilities/help-card.md`](../skills/capabilities/help-card.md) — so
> discovery never depends on the user guessing the bare-word forms. When a first-contact
> message also carries a real request, the card prefaces the answer, never replaces it.

Arguments after the command (`/add https://blog.example.com/feed`, `/research RAG eval`)
are passed through as the request body to the target skill.
