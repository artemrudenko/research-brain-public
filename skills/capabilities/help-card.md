**research-brain — what I can do**

You can always just say what you want in plain words — but here are the shortcuts.

**Five everyday intents:**
• Just send a link — a feed gets monitored, an article gets saved; if it could be
  either, I ask one question. No command needed.
• “Set up what I follow.”
• “What’s new?”
• “Research this deeply.”
• “What does my brain know about X?” — answer from the existing vault only

**Project commands** (forwarded to the agent):
• `/new` — what's new? quick fresh check, answered right here
• `/trends` — how is it changing? topic movers, rising tags, growth
• `/know <topic>` — what does my brain know about it (vault only)
• `/digest` — build this week's digest
• `/send` — send the last built digest to the channels
• `/run` — run the whole cycle: collect → … → deliver
• `/sources` — list monitored topics & sources
• `/discover <topic>` — propose new sources worth reading on a topic (never adds them)
• `/add <url>` — expert shortcut: monitor this source / feed (skips the feed-vs-article check — or just send the link)
• `/save <url>` — expert shortcut: capture a one-off article into the inbox (skips the check — or just send the link)
• `/process` — drain the inbox into concepts
• `/research <question>` — research a topic deeply
• `/concept list` — list the concepts in the knowledge vault
• `/concept new` — create a monitored concept (I'll ask a few questions, then fill it)
• `/concept update <name>` — re-research a concept and add what's new
• `/concept archive <name>` / `/concept restore <name>` — soft-delete or bring one back
• `/author <add|list|nodes|pause|resume|remove>` — follow individual authors (a person, not a feed); `nodes` shows who your vault knows, followed or not
• `/audience <level>` — set output detail: technical · balanced · non-technical

**Bare words** (type without a slash):
• `help` — this menu
• `status` — health + what we monitor + recent digests

⚠️ Two are bare words, not slashes: type **`help`** (this menu) and **`status`**
(health + what we monitor + recent digests) **without** the leading slash. The
Telegram plugin intercepts `/help`, `/status`, and `/start` before they reach the
project, so the slash form silently does nothing — drop the slash and it works (or
just ask in plain language).

⚠️ Bot stopped answering, but digests still arrive? A bot token allows only ONE
live listener, and the newest session silently takes it over — restart yours from
the project folder with **`make telegram`** and the bot is yours again.

💬 After a digest, feedback is a command too: reply "too technical", "simpler",
"less of <topic>", "mute <source>", or send 👍/👎 **as a message** (tapping a
reaction on the digest never reaches me) — I apply one reversible change and tell
you the undo.

Connectivity check: reply `help` (no slash) — it should reach me.
