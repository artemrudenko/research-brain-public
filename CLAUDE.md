# CLAUDE.md — Claude Code / Cowork layer for research-brain

> **The universal baseline is in [`AGENTS.md`](AGENTS.md)** — read it first. It defines
> the project, the core loop, the mandatory rules, the skill trigger table, the config
> map, and the workspace map. This file adds only the Claude-Code/Cowork-specific
> behavior on top; it does not restate the baseline.

## Invoking skills

Skills live at `skills/{name}/SKILL.md` (see the trigger table in `AGENTS.md`). In
Claude Code / Cowork:

- **Trigger-phrase recognition** — when a user request matches a skill's trigger phrases,
  invoke that skill (via the Skill tool) before doing the work, then follow its `SKILL.md`.
- **Manual load** — to run one deliberately, `Read skills/{name}/SKILL.md` and execute its
  steps.
- The research chain is order-sensitive: `research-frame` is the gateway and runs first;
  `research-build` never responds first.

## Subagents (least-privilege roles) — Claude Code / Cowork only

[`.claude/agents/`](.claude/agents/) defines pipeline-role subagents — `collector`,
`curator`, `synthesizer`, `critic`, `digest-maker`, `deliverer` — each pinned to a **model tier** and a
**tool allowlist**. Delegating a step to its role gives two things at once: a cheaper or stronger
model where it fits (the `opus` tier is confined to `synthesizer`; the rest run `sonnet`/`haiku`
— the same cost lever as `docs/scheduling.md`), and a capability boundary that is hard for MCP
tools — only `deliverer` may carry delivery MCP servers, so an injection surviving the S1–S9
sanitize gate still can't send via the MCP delivery transports from a synthesis/critique role
(headless transports remain reachable through `Bash`, so the allowlist boundary is real for MCP
only; the headless ban is prompt instruction + review). This is **Claude-Code/Cowork-specific** (Codex/headless ignore
the directory; the Codex equivalent is `config/codex-profiles.example.toml` — same roles, but
model-tier only, no per-profile tool/MCP allowlist). Both the `.claude/agents/*.md` files and the
Codex profiles are **generated** from one source of truth, [`config/agents.yaml`](config/agents.yaml),
by `scripts/gen_agents.py` (edit the spec, then regenerate; `--check` guards drift) — so the two
formats can't diverge. Three honest limits (matching [ADR 0015](docs/adr/0015-least-privilege-role-subagents.md)):
Claude Code can't allowlist *which* skills load (`Skill` is all-or-nothing — the **tool/MCP
allowlist** is what binds); the allowlist binds hard only for MCP tools, so a role's `Bash`/`WebFetch`
stay open surfaces (headless send/exfil is contained by prompt + sanitize gate + review, not the
allowlist); and `weekly-run.md` delegates each step to its role on Claude Code/Cowork (inline
elsewhere). Full role table, enforcement reality, and rationale:
[`.claude/agents/README.md`](.claude/agents/README.md).

## Delivery transports in this runtime

`digest-deliver` picks the transport **per channel** from `config/channels.yaml`. The
runtime-specific part: channels set to `provider: gmail-mcp` (email) or `transport: mcp`
(Telegram) are sent by the **skill calling the Gmail / Telegram MCP tools directly**;
Rocket.Chat goes via its incoming webhook. The headless `scripts/delivery/deliver.py` path,
the full set of transport values, the `SKIPPED (MCP-only)` skip rule, and the idempotency
mechanics (`.delivered/` receipts + the `.delivery.lock`) are the deep contract — see
**CONVENTIONS §3** (transports) and **§10** (receipts + lock).

Before the first real send, always **rehearse** with a dry run — it sends nothing and reports
each channel's target plus whether its secret is SET / MISSING. With no file it rehearses
against a built-in sample; pass a digest to rehearse the real one:

```bash
python3 scripts/delivery/deliver.py pipeline/3-synthesis/digest_*.md --dry-run
```

## Telegram quick commands

Incoming Telegram messages reach the agent only in **MCP mode** (the Telegram MCP
runtime) — they arrive as `<channel source="telegram" chat_id="…">` and are answered
with the **reply** tool (`chat_id` echoed back; never the transcript). The headless
bot-API adapter is send-only, so these commands do **not** work under cron.

> **One listener per bot token.** A Telegram token allows exactly one live `getUpdates`
> consumer, so only **one Claude session at a time** can own the bot (the newest to connect
> *steals* it). For the bot to drive this project, a `research-brain` session must own it;
> to run Telegram in several projects at once, give each project its **own bot token** via
> a per-project `TELEGRAM_STATE_DIR`. Full architecture + setup:
> [`docs/telegram-multiproject.md`](docs/telegram-multiproject.md).

The commands below are thin **aliases onto the existing skills** in the `AGENTS.md`
trigger table — recognise the leading slash as the trigger, then read that skill's
`SKILL.md` and follow it (do **not** restate or fork its behavior here). A bare word
after the bot name is the same as the matching natural-language trigger.

> **Auto-help (first contact & unrecognized input).** Because the plugin swallows
> `/help`/`/start`, discovery must not depend on the user guessing the bare word: on the
> **first message from a chat in a session**, and on **any slash command not in this
> table**, reply with the short menu from
> [`skills/capabilities/help-card.md`](skills/capabilities/help-card.md) — or its
> Russian twin [`skills/capabilities/help-card.ru.md`](skills/capabilities/help-card.ru.md)
> when the chat is in Russian (message language, or an earlier RU exchange in the
> session). When a first-contact message also carries a real request, answer the
> request too — the card is a preface, never a substitute.

| Command | Routes to | Does |
|---|---|---|
| `/new` | **whats-new** | The everyday verb: quick fresh collect + inline "what's new" answer right in the chat. Persists no digest, sends nothing to channels. |
| `/trends` | **trends** | "How is it changing?": inline top movers (topic volume vs last week, rising tags, activity, knowledge growth) from data already on disk. Read-only, persists nothing. |
| `/know <topic>` | **wiki-query** | Vault-only answer to "what does my brain know about X?" (`VAULT_ONLY=true`): reads `brain/` via INDEX.md, honest miss + research offer — never silently starts external research. |
| `/digest` | **digest-build** | Build the weekly digest locally; offer to send it after. |
| `/send` | **digest-deliver** | Deliver the last built digest to the configured channels. |
| `/run` | **run-now** | Run the whole gated loop (collect→…→deliver) now. |
| `status` † (bare word in Telegram) | **brain-ask** | Health + what we monitor + recent digests (read-only). |
| `/sources` | **brain-ask** | List monitored topics & sources (read-only). |
| `/discover <topic>` | **discover-sources** | Propose NEW sources worth monitoring for a topic (searches, groups by site, drops what is already monitored, ≤10 with a reason each). Read-only — it never adds one; accepted candidates go to `source-manage`, which sets the tier. |
| `/add <url>` | **source-manage** | Expert shortcut: start monitoring a source/feed/topic directly, skipping `intake` classification. (Primary path: just send the link — `intake` classifies it.) |
| `/save <url>` | **source-capture** | Expert shortcut: capture a one-off article into the inbox directly, skipping `intake` classification; offers to process when the queue fills. (Primary path: just send the link.) |
| `/process` | **source-capture** | Drain the captured-article inbox into concepts (fan-out → route → synthesis). |
| `/research <q>` | **research-frame** | Research a topic (the gateway routes onward). |
| `/concept <sub>` | **concept-manage** | Manage one concept: `new` (interview → monitored concept + note), `list`, `update <name>` (re-research), `archive <name>` (soft-delete), `restore <name>`. Bare `/concept` lists. (The old `/concepts` alias was retired — auto-help catches it.) |
| `/author <sub>` | **author-manage** | Manage the followed-authors roster (`config/authors.yaml`): `add` (follow one you've decided to follow), `list`, `nodes` (list author nodes in `brain/authors/` with `followed: yes/no`, read-only), `pause <name>`, `resume <name>`, `remove <name>`. Bare `/author` lists. Distinct from `/add` (a feed/site) and from Source Insights, which only *suggests* authors — it never adds one. |
| `/audience <level>` | **setup-wizard** | Set `delivery.technical_level` (`technical`/`balanced`/`non-technical`) — render-time detail level; jumps to the wizard's audience step. |
| `help` † (bare word in Telegram) | **capabilities** | Plain-language menu of what the system can do. |

> **† Plugin-intercepted slashes.** `/help`, `/status`, and `/start` are swallowed by the
> official Telegram plugin and never reach this project. To trigger them, use the **bare
> word** (no slash) — `help`, `status` — or just ask in plain language. The route is the
> same; only the leading slash is the problem. (Source of truth:
> [`docs/telegram-commands.md`](docs/telegram-commands.md); this table and
> [`skills/capabilities/help-card.md`](skills/capabilities/help-card.md) mirror it.)

To surface these in Telegram's command menu, the user registers them once with
BotFather via `/setcommands` (the agent cannot do this — it has no BotFather access).
The list to paste is kept in [`docs/telegram-commands.md`](docs/telegram-commands.md).

## Scheduling

`config/schedule.yaml` is the cadence source of truth (its four blocks + `timezone` schema
live in CONVENTIONS §2.2). **Recommended:** register **one** gated orchestrator, not four timers:

- **Claude Code cloud agents** — register **one** `/schedule` routine pointed at
  [`schedule/weekly-run.md`](schedule/weekly-run.md) at `digest.cron` (e.g. Mon 09:00). It runs
  collect → **sanitize-incoming** → curate → synthesis → brain-hygiene → digest → deliver in
  order, each step gated on the previous finishing (see `weekly-run.md` for the full step list,
  including the anti-injection sanitize gate before synthesis). This path has MCP access
  (MCP-mode delivery + the full research chain). `/schedule` agents interpret the cron in the
  `timezone` from `config/schedule.yaml` — set the routine's schedule to match.
- **Claude Code on OS cron (local install)** — a `/schedule` routine runs **off-box**, so it cannot
  drive a local, git-less install. For that, register [`schedule/claude-run.sh`](schedule/claude-run.sh)
  in crontab: it runs the same `weekly-run.md` through `claude -p`, from the project root, with a
  least-privilege surface — `--tools` fixed to the `config/agents.yaml` role union, `--permission-mode
  dontAsk` (never `--dangerously-skip-permissions`), and a spend ceiling. MCP delivery still works
  when the session carries the servers. See `docs/scheduling.md` "D. Claude Code via OS cron".
- **External cron** — drive the headless `scripts/build_digest.py` + `scripts/delivery/deliver.py`
  pair from the OS scheduler; set `CRON_TZ` (or the box `TZ`) to match the YAML `timezone`.
- **Codex / Cowork (any agentic CLI without a cloud scheduler)** — drive the thin wrapper
  [`schedule/codex-run.sh`](schedule/codex-run.sh) from OS cron; it runs the same gated
  `weekly-run.md` **agentically** via `codex exec` (the agentic path A, triggered by cron like
  B). Use the headless delivery transports unless you register the MCP servers in
  `~/.codex/config.toml`. The run lock serializes it against the other paths safely.

Details, the crontab example, the Codex `config.toml`, and timezone handling: [`docs/scheduling.md`](docs/scheduling.md).

## For developers (this repo)

The sections above are the runtime/product contract. If you are here to **change the code**
rather than run the product — toolchain (`uv` / `make gate`), the TDD + stdlib-only runtime
rule, the "never do a live run in this checkout" guard, and the zip-handoff distribution
model — see **`DEVELOPING.md`** (present only in the dev checkout). That file is
contributor-only and is excluded from the shipped archive, so its dev guidance never
reaches end users — in a shipped install it intentionally does not exist.

## Notes

Keep this file lean — link to `docs/` rather than restating `AGENTS.md` (whose rules apply
here unchanged) or `docs/CONVENTIONS.md`.
