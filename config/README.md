# config/

All user configuration for research-brain lives here. Run the **`setup-wizard`** skill
to fill these out interactively, or edit them by hand.

| File | Format | What it does |
|------|--------|--------------|
| `sources.yaml` | YAML | **The** source config — where to collect from, one entry per source (url, type, **tier**, priority, filter, active), grouped by category. Written by the wizard / `manage_sources.py`; filled on first setup or by `python3 scripts/schema.py migrate-config`. |
| `topics.yaml` | YAML | **The** topics config — the topics you track (name, tags, include/exclude rules). Drives collection and digest grouping. |
| `sources.md` / `topics.md` | markdown | **Retired before public 0.1.0** — the runtime no longer reads the legacy `.md` tables; a legacy install imports them once via `python3 scripts/schema.py migrate-config` (the `.md` files stay untouched as rollback). |
| `tags.yaml` | YAML | Controlled tag vocabulary (`domains` → topics, `synonyms`, `pending`). Machine-owned: derived by `setup-wizard`; `validate_brain.py` (advisory) *recommends* promotions and `promote_tags.py` *applies* them. Don't hand-garden. |
| `authors.yaml` | YAML | Optional: the **followed-authors roster** (CONVENTIONS §2.4) — people you explicitly chose to follow, each with a `monitoring:` variant. Absent until the first `/author add`; written only by `scripts/manage_authors.py` (never by hand-editing during a run, and never by Source Insights, which can only *suggest*). |
| `channels.yaml` | YAML | Digest delivery channels (email / Telegram / Rocket.Chat). All disabled by default. |
| `schedule.yaml` | YAML | Cadence: `collect` / `curate` / `synthesis` / `digest` crons + `timezone`; plus the OPTIONAL `daily_digest` (ADR 0016) and `weekly_trends` (ADR 0017) blocks. |
| `glossary.yaml` | YAML | Optional term→explanation map. A `📖 Glossary` of the jargon a digest uses is appended to it (only matching terms). Edit freely / delete to turn off. |
| `agents.yaml` | YAML | **Source of truth** for the pipeline-role agents (collector / curator / synthesizer / critic / digest-maker / deliverer): model tier + tool allowlist per role. `.claude/agents/*.md` and the Codex profiles are **generated** from it by `uv run python scripts/gen_agents.py` (needs the project venv — pyyaml) — edit the spec, then regenerate; never edit the generated files. |
| `codex-profiles.example.toml` | TOML | Generated Codex counterpart of the agent roles (model tier only — Codex has no per-profile tool allowlist). Copy the profiles into `~/.codex/config.toml`; regenerate via `scripts/gen_agents.py`. |
| `search.yaml` | YAML | Optional web-search provider (default `claude-websearch`, in-agent, no key); set `tavily`/`perplexity` + key in `.env` for headless/corroboration. |
| `research.yaml` | YAML | Optional Sonar cross-check for the manual research chain (key-gated; off by default). |
| `.env.example` | env | Template documenting every secret env key. Copy to `.env` and fill in. |

## Notes

- **Secrets never live in YAML.** `channels.yaml` references env var names only; the real
  values go in `config/.env` (gitignored — see `.env.example`).
- **The YAML twins are the only config the runtime reads** (CONVENTIONS §2.3):
  `sources.yaml` / `topics.yaml`. The legacy `.md` tables were retired before public 0.1.0 — a
  legacy install fails loudly everywhere until it imports them once with
  `python3 scripts/schema.py migrate-config` (a sidecar import: the `.md` files stay
  untouched as the rollback copy and are otherwise ignored).
- Keep topic/category names consistent between the sources and topics files (the
  `manage_sources.py` backend does this for you).
- The archive ships `sources.yaml` / `topics.yaml` as empty structures; the wizard (or
  `manage_sources.py`) fills them on first setup.
- **Quick start:** copy `sources.example-starter.md` over `sources.md` and
  `topics.example-starter.md` over `topics.md` for a ready-to-run set of public feeds
  (tech-news + ai-ml), then run `python3 scripts/schema.py migrate-config --force` to land
  it in the YAML config — the copied `.md` files are import material only and can be
  deleted after. (The `setup-wizard` skill offers this as a one-step "starter pack" on
  first run.)

## First-run setup checklist

The **`setup-wizard`** skill writes the config for you; a few things only you can do.

**The wizard writes / derives (no hand-editing needed):**
- `topics.yaml`, `sources.yaml` (with a `tier` per source), `channels.yaml`,
  `schedule.yaml` (`collect` / `curate` / `synthesis` / `digest` + `timezone`).
- `tags.yaml` — **derived from your topics** as nested `domain/topic` tags, then grown
  automatically (`validate_brain.py` recommends, `promote_tags.py` applies — no hand-management).
- Then it runs `validate_config.py` and offers a delivery **rehearsal** (dry-run, sends nothing).

**You do manually (the wizard tells you which apply):**
1. **Secrets → `config/.env`.** `cp config/.env.example config/.env`, then set only the keys
   for channels you enabled: `SMTP_PASSWORD` (Gmail SMTP = an *app password*),
   `TELEGRAM_BOT_TOKEN` (from @BotFather), `ROCKETCHAT_WEBHOOK_URL`. `.env` is gitignored —
   secrets never go in the YAML.
2. **Connect / create the channel transport.**
   - *MCP mode (default):* connect the **Telegram MCP / Gmail MCP** in Cowork / Claude Code.
     Get a Telegram `chat_id` by messaging the bot then calling `getUpdates`, or via @userinfobot.
   - *Rocket.Chat:* create an **Incoming Webhook** (Admin → Integrations → New → Incoming
     Webhook → copy the URL) and put the URL in `.env`.
3. **(Optional) Headless cron.** If you run the pipeline without an agent, schedule
   `schedule/weekly-run.md` (or the four crons). For **headless** OS-cron the box's `TZ` /
   `CRON_TZ` drive the schedule (not the YAML `timezone:`) — set them to match; a Claude Code
   `/schedule` agent instead reads the YAML `timezone:` directly.
4. **(Optional) Obsidian front door.** Open the vault in Obsidian ≥1.7 for the live
   `brain/concepts.base` map; otherwise use `brain/INDEX.md`.

## How to change settings later

Config is **read fresh on every run**, so edits apply on the **next** run — no rebuild.
Re-run `setup-wizard` for a guided change, or edit the file directly. After any edit,
`python3 scripts/validate_config.py` checks it is still sane; tag vocabulary grows
automatically (no manual edits to `tags.yaml`).

| Setting | How to change | Takes effect |
|---|---|---|
| Topics tracked | `setup-wizard` ("add a topic") or `python3 scripts/manage_sources.py add-topic <name>` (writes the YAML twins and keeps sources/topics/tags in sync) | next collect |
| Sources / tiers | `setup-wizard`, `manage_sources.py add-source … --tier high`, or edit `sources.yaml` | next collect |
| Tag vocabulary | **Automatic** — derived once, then grown automatically: `validate_brain.py` (advisory) *recommends* promotion (pending → at ≥3 uses) and `scripts/promote_tags.py` *applies* it in brain-hygiene (`source-manage` seeds a new topic's tag on add-topic). Edit `tags.yaml` only to seed a domain | next synthesis |
| Delivery channels | `setup-wizard` ("reconfigure delivery") or edit `channels.yaml` (`enabled` / params) | next digest |
| Digest language | `setup-wizard` or edit `channels.yaml` (`delivery.language`) | next digest |
| Audience level (how much is explained) | `/audience technical\|balanced\|non-technical`, `setup-wizard`, or edit `channels.yaml` (`delivery.technical_level`) — render-time only, so `brain/` is untouched | next digest / answer |
| Followed authors | `/author add\|list\|nodes\|pause\|resume\|remove` (→ `scripts/manage_authors.py`) | next collect |
| Secrets (tokens etc.) | edit `config/.env` (never the YAML) | next digest / delivery |
| Cadence (crons) | `setup-wizard` or edit `schedule.yaml` (`collect` / `curate` / `synthesis` / `digest`) | next scheduled run |
| Timezone | `setup-wizard` ("change timezone") or edit `schedule.yaml` `timezone:` (+ box `TZ`/`CRON_TZ` for headless cron) | next scheduled run |
