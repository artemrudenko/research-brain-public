# Telegram MCP — one listener per bot token (multi-project setup)

> **The one-line rule:** a Telegram bot **token** can have **exactly one live listener
> at a time**. This is a Telegram Bot API limit, **not** a Claude Code / project limit.
> To run Telegram in several projects *simultaneously*, give each project **its own bot
> token**. One shared token = one session at a time.

This is an architectural gotcha worth understanding before wiring the bot into more than
one project. It explains why `/save`, `/help`, etc. sometimes "do nothing" (the bot is
owned by a session in another project) and how to fix it properly.

---

## Why the limit exists

The Telegram bot receives messages by long-polling `getUpdates`. **Telegram permits only
one `getUpdates` consumer per token** — a second poller gets `409 Conflict`. The official
plugin's MCP server (launched per Claude session via `bun run … start`) is that single poller.

The plugin is explicit about it:

```
// Telegram allows exactly one getUpdates consumer per token. If a previous
// [holder is still running] ... 409 Conflict. Kill any stale holder before we start.
const STATE_DIR = process.env.TELEGRAM_STATE_DIR ?? ~/.claude/channels/telegram
// token, access.json, approved/, .env, inbox/, bot.pid all live under STATE_DIR
```

So when a **new** Claude session starts the Telegram MCP, it **kills the previous holder**
recorded in `<STATE_DIR>/bot.pid` and takes over the poll. Net effect:

- **The newest session to connect the Telegram MCP "steals" the bot** from the prior one.
- The prior session is still alive, but its bot link is dead — it no longer receives
  messages. That is exactly the "nothing happens" symptom: your message reaches the bot,
  but the session that *owns* it is in a different project (with different skills) or is
  idle/stuck.

`<STATE_DIR>/.in_use/<pid>` is the single-owner marker the plugin keeps for this reason.

---

## Why project-level vs user-level MCP config does **not** lift the limit

The constraint is keyed on the **token**, and the token is read from `<STATE_DIR>/.env`.
By default every project shares the same `STATE_DIR` (`~/.claude/channels/telegram`), so
every project's MCP instance targets the **same bot** → still one live listener.

Moving the MCP config from user scope to project scope only changes *which sessions load
the MCP*. It does **not** give each project a different token by itself. You must also
point each project at a **different `STATE_DIR` with a different token**.

---

## The fix: one bot (token) per project, via `TELEGRAM_STATE_DIR`

The plugin already supports this — it resolves all of its state from `TELEGRAM_STATE_DIR`
(falling back to `~/.claude/channels/telegram`). Give each project its own state dir +
bot, and the pollers no longer collide:

**1. Create a dedicated bot** in [@BotFather](https://t.me/BotFather) (`/newbot`) — e.g.
`research_brain_bot`. One Telegram account can own many bots; copy the token.

**2. Create a per-project state dir** with that bot's credentials and allowlist:

```bash
DIR=~/.claude/channels/telegram-research-brain
mkdir -p "$DIR/approved" && chmod 700 "$DIR"
printf 'TELEGRAM_BOT_TOKEN=123456789:AAH...your-research-brain-bot-token\n' > "$DIR/.env"
chmod 600 "$DIR/.env"
# allowlist your own Telegram numeric id (same shape as the default channel)
cat > "$DIR/access.json" <<'JSON'
{ "dmPolicy": "allowlist", "allowFrom": ["<your-chat-id>"], "groups": {}, "pending": {} }
JSON
```

**3. Point this project's session at that state dir.** Two ways:

- **Per-project MCP entry** — add a Telegram server to the project's `.mcp.json` that sets
  the env (so any session opened in this project uses this bot):

  ```jsonc
  // research-brain/.mcp.json
  {
    "mcpServers": {
      "telegram": {
        "command": "bun",
        "args": ["run", "--cwd",
          "~/.claude/plugins/cache/claude-plugins-official/telegram/0.0.6",
          "--shell=bun", "--silent", "start"],
        "env": { "TELEGRAM_STATE_DIR": "~/.claude/channels/telegram-research-brain" }
      }
    }
  }
  ```

  > The `…/telegram/0.0.6` path segment is the **plugin version** — check your installed
  > version (`ls ~/.claude/plugins/cache/claude-plugins-official/telegram/`) and use that.

- **Or export before launching** the session for this project:

  ```bash
  TELEGRAM_STATE_DIR=~/.claude/channels/telegram-research-brain claude
  ```

**Recommended: the shipped launcher.** The project ships both requirements — the
per-project `TELEGRAM_STATE_DIR` *and* the inbound `--channels` flag — wrapped in
[`scripts/telegram-launch.sh`](../scripts/telegram-launch.sh), reachable as
**`make telegram`** from the project folder. It resolves the project root from its own
location (nothing to edit) and derives the state dir from the folder name, so two
installs get two listeners automatically.

```bash
cd /path/to/research-brain && make telegram     # or scripts/telegram-launch.sh
```

Thanks to `--channels plugin:telegram@claude-plugins-official` the session receives
**inbound** messages. Without that flag the plugin is **send-only**: outgoing replies
work, but your `/save`, `help`, etc. never reach the agent.

To launch from *anywhere* with one word, add a thin alias to your shell rc (the
`setup-wizard` offers to append it):

```bash
# ~/.zshrc — one-word launcher for this install
alias claude-telegram='~/projects/research-brain/scripts/telegram-launch.sh'
```

> Per-project bots → per-project aliases: give each project its own alias
> (`claude-telegram-foo` → *that* project's `scripts/telegram-launch.sh`); each launcher
> derives its own `STATE_DIR` from its folder name, so each opens in the right repo with
> the right bot.

**Result:** the research-brain session polls the research-brain bot's token; another
project's session polls *its* bot. No 409, both live at once, and each bot drives the
project whose skills that session actually has (so `/save` → `source-capture` works here).

---

## If you keep a single shared bot (no per-project token)

You can only have **one live listener at a time**. To move the bot to research-brain:

- Open a Claude session **in `research-brain`** with the Telegram MCP enabled — it will
  **steal** the bot from whatever session held it (it kills the old `bot.pid` holder).
- Switching back to another project means that project's session steals it again.

There is no way to share one token across two simultaneous listeners — that is the
Telegram-side limit, full stop.

---

## Diagnosing "which session owns the bot right now?"

```bash
# who is the live poller, and which project is it in?
PID=$(cat ~/.claude/channels/telegram/.../bot.pid)   # use the right STATE_DIR
ps -o pid,ppid,etime,command= -p "$PID"              # the plugin's bun MCP poller process
GP=$(ps -o ppid= -p "$(ps -o ppid= -p "$PID")")      # → its claude session pid
lsof -a -p "$GP" -d cwd | tail -1                    # → that session's working directory
ls ~/.claude/channels/telegram*/.in_use/             # single-owner markers (<pid> files)
```

If the cwd is **not** the project whose skills you expect, that is why the bot "ignores"
your commands — the owning session lives in the wrong project.

---

## See also

- [`docs/telegram-commands.md`](telegram-commands.md) — the `/`-command menu (incl. `/save`,
  `/process`) and BotFather `/setcommands` registration.
- "Connect Telegram (end to end)" in [`QUICKSTART.md`](../QUICKSTART.md) — first-time setup.
- [`CLAUDE.md`](../CLAUDE.md) → "Telegram quick commands" — MCP-mode behavior.
