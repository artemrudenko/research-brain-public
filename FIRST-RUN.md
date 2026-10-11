# FIRST RUN — research-brain

Welcome. This is your weekly research assistant: it watches the sources you pick, builds
a digest, and quietly grows an Obsidian knowledge vault — without you gardening it. The
recommended path is the **full agentic** setup in Cowork / Claude Code. The advanced
**RSS Digest Lite** path exists for no-agent/headless installs, but it is a reduced
fallback. This page takes you from a freshly unpacked folder to your first digest in
seven steps. Deeper detail lives in [`QUICKSTART.md`](QUICKSTART.md),
[`USER_GUIDE.md`](USER_GUIDE.md), and [`docs/`](docs/).

**Out of the box nothing is configured and every delivery channel is OFF**, so you can poke
around safely — you decide what to monitor and where digests go before anything is sent.

---

## Before you start — which computer?

- **macOS / Linux** — you're ready; go to the steps below. (Python 3.11+ is usually already
  installed.)
- **Windows** — supported natively. In step 2 run **`.\install.ps1`** instead of
  `./install.sh`, and use `.\` paths in PowerShell. If PowerShell blocks the script, run it as
  `powershell -ExecutionPolicy Bypass -File .\install.ps1`. (Prefer a Unix-identical setup?
  Install **WSL** with `wsl --install` in PowerShell, copy this folder into your Ubuntu home,
  and follow the macOS/Linux steps there.)

You'll need **Python 3.11+** (macOS/Linux usually have it; Windows: the uv install in step 2
can fetch it, or get it from python.org).

---

## Seven steps

1. **Unzip the archive, then open that folder in Cowork / Claude Code** (*File → Open
   folder*) — the folder containing `Makefile` and `README.md`. Say **"install and set
   up this project"** and the assistant runs steps 2–4 for you — no terminal needed.
   Prefer doing it by hand? Open a terminal in that folder instead and follow the steps
   below. If you downloaded a ZIP, unpack it first. If you cloned the source,
   use a separate copy for your configured installation.

2. **Install the dependencies with one command** — it installs `uv`, creates the virtual
   environment, and pulls dependencies. It asks you nothing and configures nothing —
   picking topics and channels happens in step 4:
   ```bash
   make install          # macOS / Linux
   ```
   No `make`? Run `./install.sh` directly. **On Windows (PowerShell):** `.\install.ps1`.
   Already have `uv`? `uv sync` is enough.

3. **Add your secret(s) — only if your path needs them.** On the happy in-app path
   (email via MCP, Telegram via MCP/plugin mode) **no secret goes into any file**:
   accounts connect inside the assistant. `config/.env` is needed only for
   **Rocket.Chat** and the **headless/cron** transports (`smtp` / `bot-api`):
   ```bash
   cp config/.env.example config/.env   # then fill in only what your path uses
   ```

   > **Telegram — one token, one home.** `TELEGRAM_BOT_TOKEN` in `config/.env` is read
   > **only** by the headless `bot-api`/cron path. Using the plugin instead? Skip that
   > line entirely — the plugin does not read `config/.env`, and putting the token in
   > both places is the classic "why doesn't one of them work" trap.

4. **Pick what to monitor.** Easiest: open this folder in Cowork / Claude Code and say
   **"let's set up sources"** — the **setup-wizard** interviews you, uses intake for OPML
   and plain URLs when needed, and writes the config for the full agentic path. Prefer the
   advanced RSS Digest Lite/headless route? Copy the starters, then land them in the
   YAML config (`config/sources.yaml` + `config/topics.yaml` — the only format the
   runtime reads; the copied `.md` files are import material you can delete after)
   and edit the YAML:
   ```bash
   cp config/sources.example-starter.md config/sources.md
   cp config/topics.example-starter.md config/topics.md
   python3 scripts/schema.py migrate-config --force
   ```

5. **Turn on a delivery channel** — in `config/channels.yaml`, set your channel's
   `enabled: true` and its target (an email address, or a Telegram chat id).

6. **Check activation — this sends nothing.** The wizard runs the shared setup checker:
   ```bash
   python3 scripts/setup_check.py
   ```
   It reports the same six fields the wizard shows:

   - `Source:`
   - `Config:`
   - `Delivery:`
   - `Schedule:`
   - `First value:`
   - `Next action:`

   If everything is ready except recurring execution, setup ends as
   `ready_schedule_not_registered` / "ready, schedule not registered" — not complete yet.
   Missing secrets, unsupported headless/MCP combinations, config errors, and transient
   source failures are shown as `needs_attention` with the failed category.

   The `Schedule:` field is **detected, not taken on faith**: the checker probes your
   crontab / Task Scheduler for an entry referencing this install and reports
   `registered` when it finds one. (Cloud-agent routines can't be probed from the box —
   confirm yours exists, then run
   `python3 scripts/setup_check.py --scheduler-state registered`.)

   > **Don't want to wait?** If you set up sources with the wizard, it offers a small
   > **first digest right in that session** — a quick bootstrap collect from your RSS
   > sources (3 articles per topic), sanitized and built on the spot. You can also ask
   > for it any time: *"build my first digest now"*.

7. **Do the first real run** — collect → sanitize → curate → synthesis → digest → deliver,
   in one gated pass. Easiest: in Cowork / Claude Code, say **"run now"** (the **run-now**
   skill). For unattended weekly delivery, register one recurring run for
   `schedule/weekly-run.md` at the digest cadence; writing `config/schedule.yaml` is only
   the cadence, not scheduler registration. One command does that registration for you,
   from your own config:

   ```bash
   python3 scripts/install_schedule.py --path claude --apply
   ```

   (`--path headless` if no agent CLI is on the box, `--path codex` for Codex; drop
   `--apply` to just write the crontab file and paste it yourself.) For the full picture,
   see [`docs/scheduling.md`](docs/scheduling.md).

   > **Driving it from Telegram?** The chat commands (`/run`, `/digest`, `/save …`) only
   > reach the agent while a **research-brain** Claude session owns the bot — and a bot
   > token allows exactly **one** live listener, so the newest session to connect steals
   > it. Run several projects on Telegram? Give each its own bot token. Details:
   > [`docs/telegram-multiproject.md`](docs/telegram-multiproject.md).

That's it — your first digest arrives on the channel you enabled, and `brain/` starts filling
with linked concept notes you can browse in Obsidian.

---

## If something looks off

- **One full check (read-only):** `uv run python scripts/doctor.py` — config schema, sources,
  delivery wiring, health, locks and version in one plain-language report (the installer
  already runs it once at the end of setup).
- **Narrow operational health only:** `uv run python scripts/health.py report`
- **Delivery skipped/failed, moving machines, a stuck run:** [`docs/OPERATIONS.md`](docs/OPERATIONS.md)
- **Full reference:** [`USER_GUIDE.md`](USER_GUIDE.md) · **automation & scheduling:** [`docs/scheduling.md`](docs/scheduling.md)

## Getting updates later

When a new release arrives, you don't re-configure or lose anything. From inside this
folder, point `update.sh` at the new archive:

```bash
./update.sh path/to/research-brain-<new>.zip     # add --dry-run to preview
```

It replaces the code, keeps your vault, secrets and settings, and backs up first. See
[`docs/updating.md`](docs/updating.md) and the [`CHANGELOG.md`](CHANGELOG.md).
