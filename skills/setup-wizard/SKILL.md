---
name: setup-wizard
description: "Conversational onboarding for the supported full agentic research-brain path. Offers a starter pack or interview, establishes sources through intake/source-manage, writes the topics+sources config (config/topics.yaml + config/sources.yaml — YAML only; an unmigrated legacy .md install is stopped and offered migrate-config), config/channels.yaml, config/schedule.yaml and derived config/tags.yaml, then closes with scripts/setup_check.py activation status. Advanced users can choose RSS Digest Lite, SMTP, or Telegram Bot API. Triggers: «set up sources», «configure», «let's set up», «first-time setup», «настроить источники», «онбординг», «starter pack»."
metainfo:
  type: worker
  domain: config
  last_updated: 2026-07-06
  successor: [source-manage]
---

# setup-wizard — guided config onboarding

Turns a freshly-unpacked research-brain into a configured and truthfully activated one.
The user opens the project root in Cowork / Claude Code, says "let's set up sources", and
this skill leads with the supported product default:

> We'll set up the full research-brain path. Advanced users can choose RSS Digest Lite or headless transports.

The normal path does not ask the user to choose an implementation mode. It talks in user
outcomes: sources, delivery, schedule, first value, and the next action. Advanced setup is
explicit and preserves RSS Digest Lite, SMTP, and Telegram Bot API for users who need a
headless/no-agent path.

It is **conversational** and **idempotent**: on first run it fills in the shipped
templates (or copies the starter); on a later run ("let's reconfigure email",
"add a topic", "change the timezone") it re-reads the current config and changes
only what the user asks. "Add a topic" also updates `tags.yaml`; "change the
timezone" only touches `schedule.yaml`.

The config files this skill owns:

| File | Format | Written in step |
|------|--------|-----------------|
| `config/topics.yaml` | YAML (schema CONVENTIONS §2.3) — the topics config | a — Topics |
| `config/tags.yaml` | YAML (fixed registry, CONVENTIONS §11) | a — derived from topics |
| `config/sources.yaml` | YAML (schema §2.3, incl. per-source `tier`) — the sources config | b — Sources |
| `config/channels.yaml` | YAML (fixed schema, CONVENTIONS §2.1) | c — Delivery |
| `config/schedule.yaml` | YAML (fixed schema, CONVENTIONS §2.2) | d — Schedule |

**Config format rule (§2.3):** `config/sources.yaml` / `config/topics.yaml` are the ONLY
sources/topics config the runtime reads — every ordinary path in this skill reads/writes
the YAML twins via the `manage_sources.py` backend. The legacy `.md` tables are retired
(0.8.0): when Step 0 detects an unmigrated legacy install (real `.md` config, no YAML
twin), the wizard STOPS and offers exactly one action — `python3 scripts/schema.py
migrate-config` — then continues on the YAML files. The shipped archive carries the twins
as empty structures; the backend fills them.

Secrets are **never** written by this skill — they go in `config/.env` (copied from
`config/.env.example`); the YAML only ever holds the *name* of the env var.

---

## When to Use

**Use when:**
- The user says: "set up sources", "configure", "let's set up", "first-time setup",
  "onboarding", "starter pack", "настроить источники", "онбординг", "давай настроим".
- A fresh checkout where `config/` files still hold the shipped EXAMPLE placeholders.
- The user wants to change one part of an existing config ("reconfigure Telegram",
  "add a topic", "change the digest day", "change the timezone") — run only the
  relevant step. Adding/removing a topic re-derives `tags.yaml` too.

**Skip / don't use for:**
- Filling in secret values (tokens, passwords, webhook URLs). Direct the user to `config/.env`.
- Running a collection or building a digest — collection is a scheduled task
  (`schedule/collect-*.md`, not a skill); building is the `digest-build` skill (sending
  is `digest-deliver`). setup-wizard only writes config (Step f *offers* a rehearsal but
  sends nothing).
- Editing `brain/`, `pipeline/`, or any file outside `config/`.
- Hand-gardening `tags.yaml` long-term — after the first derivation it grows automatically
  via the weekly brain-hygiene pass (`scripts/validate_brain.py`).

---

## DO / DON'T

**DO:**
- Inspect repo state first; tell the user whether this is a first run or a reconfigure.
- On first run, OFFER the starter-pack fast path before the full interview (Step 0).
- Ask one topic at a time. Confirm the collected values back before writing each file.
- Derive `config/tags.yaml` from the topics (nested `domain/topic`), show it, confirm.
- Ask a per-source `Tier` (high/medium/low credibility), default `medium`.
- For each chosen channel, explain its PREREQUISITES (MCP connected / webhook created / secret in `.env`).
- Write `channels.yaml`, `schedule.yaml`, `tags.yaml` to their EXACT fixed schemas (CONVENTIONS §2.1 / §2.2 / §11).
- Write the FULL schedule schema — `collect` / `curate` / `synthesis` / `digest` + `timezone`.
- Use relative paths only (`config/...`, `pipeline/1-incoming/...`). Never absolute paths.
- Keep topic names in sync between `topics.yaml`, `sources.yaml`, and the `tags.yaml` synonyms.
- Detect source type from the URL (rss / blog / medium-tag / webpage); prefer `rss` when a feed exists.
- After writing, run `python3 scripts/setup_check.py --runtime agentic --scheduler-state ready-not-registered`
  and report its activation checklist (Step f).
- Before claiming `complete`, verify recurring execution is actually registered. A written
  `config/schedule.yaml` is only `ready, schedule not registered`.

**DON'T:**
- Don't write secrets (tokens, passwords, webhook URLs) into any `.yaml` or `.md`. Ever.
- Don't change the structure / keys of the YAML schemas — only the values.
- Don't wipe a configured file on a reconfigure run — re-read and patch only what changed.
- Don't invent topics or sources the user didn't give. Leave a section empty rather than guess.
- Don't interrogate the user about tags — derive them, show the result, ask one yes/no confirm.
- Don't write absolute paths or any brand/project-specific hardcoding.
- Don't actually send a digest — Step f is a dry-run rehearsal only.

---

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `MODE` | enum `first-run` / `reconfigure` | no | auto-detected | Decided by inspecting config state (see Step 0) |
| `USE_STARTER` | bool | no | asked on first run | Copy the starter pack instead of the full interview (Step 0) |
| `TARGET` | string | no | all steps | For reconfigure: which part to change ("email", "topics", "schedule", "timezone"...) |
| User answers | interactive | yes | — | Collected through the step-by-step interview |

Use AskUserQuestion-style prompts: ask one focused question, wait, confirm, then move on.

---

## Steps

### Step 0 — Inspect repo state + offer the starter pack

Determine where we are before asking anything.

1. Check which config files exist: `config/sources.yaml` + `config/topics.yaml` (the only
   sources/topics config the runtime reads), any leftover legacy `config/topics.md` +
   `config/sources.md`, plus `config/channels.yaml`, `config/schedule.yaml`,
   `config/tags.yaml`. Note any missing.
2. Detect whether the install is still a **shipped template** (not yet configured). Markers:
   - `sources.yaml` / `topics.yaml` exist (possibly as the shipped empty structures) →
     configured iff they carry real topics/sources (`python3 scripts/manage_sources.py list`).
   - **no YAML twin at all**, but `topics.md` / `sources.md` hold real topic/source
     content → an **unmigrated legacy install** (the state `scripts/sources/store.py`
     refuses loudly everywhere) — go to 2a. `.md` files carrying only `# EXAMPLE —
     replace` rows or the literal `Updated: YYYY-MM-DD` header are templates, not user
     data — they never block; treat the install as unconfigured.
   - `channels.yaml`: every channel has `enabled: false` AND `to: []` is empty AND
     `chat_id: ""` is empty → not yet configured.
   - `schedule.yaml`: present with default crons → treat as configurable (always offer).
2a. **Unmigrated legacy install → STOP; offer exactly one action — the migration**
   (never auto-apply): "Your sources/topics config is in the retired markdown format,
   which the runtime no longer reads — nothing (collection, validation, this wizard's
   writes) works until it is imported. Run `python3 scripts/schema.py migrate-config`?
   One command, nothing is lost — your `.md` files stay untouched as the rollback."
   On yes run it, show its output, and continue the wizard on the YAML files. On no,
   stop here — leave the config untouched and name the command for later; there is no
   `.md` path to continue on.
3. Decide `MODE`:
   - All config files are still templates → **first-run**. Greet, then go to the
     **starter-pack fork** below.
   - At least one file is configured → **reconfigure**. Ask which part the user wants to
     change (`TARGET`) and jump to only that step. Re-read the current file first.
4. Tell the user what you found: e.g. "Fresh setup — none of the config is filled in yet."
   or "Looks configured already — what would you like to change? (topics / sources /
   delivery / schedule / timezone / language)".

On first run, lead with this exact default copy:

> We'll set up the full research-brain path. Advanced users can choose RSS Digest Lite or headless transports.

Do **not** ask the user to choose `agentic`, `headless`, or `RSS Digest Lite` unless they
explicitly ask for advanced setup.

### Advanced setup fork

Use this fork only when the user explicitly asks for advanced/headless setup, RSS Digest
Lite, SMTP, Telegram Bot API, cron-only operation, or when the current runtime cannot
support the recommended MCP transport.

Advanced choices preserve existing capability:

- **RSS Digest Lite** — deterministic RSS collection + sanitize + digest + headless delivery.
  This path requires at least one active `rss` source.
- **Email SMTP** — set `provider: smtp`, collect SMTP host/user/recipient, and keep
  `password_env: SMTP_PASSWORD`.
- **Telegram Bot API** — set `transport: bot-api`, collect `chat_id`, and keep
  `token_env: TELEGRAM_BOT_TOKEN`.

The normal first-run path stays full agentic with MCP-first delivery defaults.

**Starter-pack fork (first-run only).** Before the full interview, ask one question:

> "Want a ready-to-go starter so you get a working setup in one step, then tweak?
> It imports `config/sources.example-starter.md` + `config/topics.example-starter.md`
> (public feeds for **tech-news** + **ai-ml**) into your `sources.yaml` / `topics.yaml`."

- **Yes (`USE_STARTER`)** → copy the two starter files in as migration input:
  `cp config/sources.example-starter.md config/sources.md` and
  `cp config/topics.example-starter.md config/topics.md`. Stamp today's date over the
  `Updated: YYYY-MM-DD` header in both, then land them in the YAML config:
  `python3 scripts/schema.py migrate-config --force` (writes `config/sources.yaml` +
  `config/topics.yaml` from the copied starters; the copied `.md` files are import
  material only — they can be deleted after).
  Then **still derive `config/tags.yaml`** from the starter topics (Step a.4), and
  continue to delivery (Step c), schedule (Step d), language (Step e), and verify
  (Step f). Skip the topic/source interview (a.1–a.3, b).
- **No** → run the full interview a → e, then f.

Read commands (illustrative, relative paths):
- `ls config/sources.yaml config/topics.yaml` — do the YAML twins exist yet?
- `python3 scripts/manage_sources.py list` — what is actually configured (reads the YAML;
  on an unmigrated legacy install it fails with the migrate-config pointer — Step 2a).
- `grep -l "EXAMPLE — replace" config/*.md` — leftover `.md` files that are templates,
  not user data (they never block; real `.md` content without YAML twins is Step 2a).
- Read `config/channels.yaml` and check the `enabled:` flags.

### Step a — Topics / categories → `config/topics.yaml` (+ derive `config/tags.yaml`)

1. Ask: "What topics do you want to track? Give me a short name for each (e.g.
   `ai-agents`, `ai-governance`)." Collect a list.
2. For each topic, ask (can batch sensibly): include rules (what belongs), exclude rules
   (what to drop), and frontmatter tags (default to `[<name>]` if the user has no preference).
3. Confirm the full topic list back to the user.
4. **Derive `config/tags.yaml`** from the topics (auto-derive + grow — CONVENTIONS §11).
   For each topic, split a `<domain>-<topic>` name into a nested `domain/topic` tag:
   - `ai-agents` → domain `ai`, topic `agents` → tag `ai/agents`
   - `ai-governance` → domain `ai`, topic `governance` → tag `ai/governance`
   - `tech-news` → domain `tech`, topic `news` → tag `tech/news`
   - a single-word topic (`security`) → use it as the topic under a sensible domain, or
     `misc/<topic>` if no domain is implied; ask only if genuinely ambiguous.

   Then write the registry:
   - `domains:` — each domain mapped to its list of topics (e.g. `ai: [agents, governance]`).
   - `synonyms:` — map the **raw topic name** and obvious aliases to the canonical nested
     tag (`ai-agents: ai/agents`, `agentic: ai/agents`, `tech-news: tech/news`). This is
     what RSS `<category>` values and concept tags normalize through.
   - `pending: []` — empty quarantine for tags the system proposes later.

   Show the user the resulting tag list (e.g. "domains: ai → agents, governance; tech → news")
   and confirm with ONE yes/no — don't interrogate. Tell them: **"You never hand-manage
   tags — this vocabulary grows automatically. When a new tag recurs across ≥3 notes the
   weekly hygiene pass *recommends* it (`scripts/validate_brain.py`, advisory) and
   `scripts/promote_tags.py` *applies* the promotion from `pending:` into the registry."**
   Keep the file's header comment block intact; only fill `domains:` /
   `synonyms:` / `pending:`.
5. Write the topics into `config/topics.yaml`. First create each topic through the
   deterministic backend (it writes the YAML twins and keeps names in sync):
   `python3 scripts/manage_sources.py add-topic <name>` — then set the interview's
   include/exclude rules and tags on each entry by editing `config/topics.yaml` —
   one `topics:` entry per topic (schema CONVENTIONS §2.3); replace the backend's
   default prose with the user's answers:

   ```yaml
   topics:
     - name: ai-agents
       tags: [ai-agents, agents]
       include: "Substantive pieces about autonomous agents, orchestration, tool use."
       exclude: "Generic LLM hype with no agent angle; route product news elsewhere."
   ```

> On a **reconfigure** "add/remove a topic": use `manage_sources.py add-topic` /
> `remove-topic` (it patches BOTH `config/topics.yaml` and `config/sources.yaml`),
> AND re-derive the `tags.yaml` entry for that topic (add the `domain/topic` to
> `domains:` + a `synonyms:` alias; never delete a tag that existing concepts may use —
> leave it or fold it up to its domain).

### Step b — Sources per topic → `config/sources.yaml`

(Skipped when the starter pack was copied — the starter already carries sources with tiers.)

Source establishment should reuse the Phase 1 `intake` path when the user supplies OPML,
a plain URL, or an explicit shortcut:

- OPML import: run the `intake` flow, preview first, then apply only after confirmation.
- Bare URL: run `python3 scripts/intake.py URL --json`; approve the proposed recurring-source
  handoff before persistence.
- Explicit `/add <url>` or explicit monitor/add intent: route directly to `source-manage`.
- Explicit `/save <url>` remains a read-it-later capture path and is not part of source setup
  unless the user deliberately wants to capture an article during onboarding.

1. For each topic from Step a, ask: "Which URLs should we collect `<topic>` from?"
2. For each URL, **detect the type** and confirm:
   - ends in `.xml` / `/feed` / `/rss` / `/atom`, or is a known feed path → `rss`
   - `medium.com/tag/<tag>` (optionally `/latest`) → `medium-tag`
   - a blog *index* page (e.g. `.../blog`) → `blog`
   - anything else (a single page, no feed) → `webpage`
   **Prefer `rss` whenever a feed exists** — say so to the user. The verified feed
   patterns in `config/sources.example-starter.md` (YouTube `feeds/videos.xml?channel_id=`,
   arXiv `export.arxiv.org/rss/{cat}`, Google News, Substack `/feed`, Medium `/feed/tag/`,
   HN `hnrss.org`, Reddit `/.rss`) are good shapes to copy + adapt — remind the user to
   verify a feed resolves before relying on it.
3. Ask **`Tier`** (`high` / `medium` / `low`, default `medium`) — this is the source's
   **credibility**, copied onto each collected article and shown in the digest. Then ask
   `Priority` (`high` / `medium` / `low`, default `medium`, collection ordering — independent
   of Tier), a short filter note, and whether it is active (`yes` / `no`, default `yes`).
4. **Validate each URL** before accepting: must start with `http://` or `https://` and
   contain a host. If it is malformed (typo, missing scheme, "just the site name"), do
   **not** write it — tell the user what's wrong and ask for a corrected URL.
5. Confirm the source table back per topic.
6. Write each source through the deterministic backend — it appends to
   `config/sources.yaml`, dedups URL variants, and keeps category names in sync with
   Step a:

   ```bash
   python3 scripts/manage_sources.py add-source ai-agents https://example.com/feed.xml \
       --type rss --tier high --priority high --filter "all articles" --active yes
   ```

   The resulting YAML shape (CONVENTIONS §2.3), for reference when reviewing the file:

   ```yaml
   categories:
     - name: ai-agents
       sources:
         - url: "https://example.com/feed.xml"
           type: rss
           tier: high
           priority: high
           filter: "all articles"
           active: true
   ```

   Category names must match the topic names from Step a exactly (the backend enforces this).

### Step c — Delivery channels → `config/channels.yaml` (with prerequisites)

1. Ask: "Where should the digest be delivered? Pick any of: email, Telegram, Rocket.Chat."
2. For each chosen channel, collect **non-secret** params, confirm, set `enabled: true`,
   AND explain the **prerequisites** the user must set up themselves:

   - **email** — default to `provider: gmail-mcp` in agent-runtime setup. Collect recipients
     → `to: [...]`. Ask about `smtp` only in the Advanced setup fork or when the current
     runtime cannot support Gmail MCP. If `smtp`: collect `host`, `port` (default 587), `user`.
     - *Prereq (gmail-mcp):* the **Gmail MCP must be connected** in Cowork / Claude Code first.
     - *Prereq (smtp):* the password lives in `.env` as `SMTP_PASSWORD` (referenced by
       `password_env`). For Gmail SMTP use an **app password** (Google Account → Security →
       App passwords), not your account password. Do NOT ask for it here.

   - **telegram** — default to `transport: mcp` in agent-runtime setup. Collect `chat_id`
     (numeric id or `@channel`). Ask about `bot-api` only in the Advanced setup fork or when
     the current runtime cannot support Telegram MCP.
     - *Prereq (mcp):* the **Telegram MCP must be connected** in Cowork / Claude Code first.
     - *How to get a `chat_id`:* message the bot once, then call `getUpdates`
       (`https://api.telegram.org/bot<TOKEN>/getUpdates`) and read `message.chat.id`; or
       message **@userinfobot** which replies with your numeric id. For a channel use
       `@channelusername`.
     - *Prereq (bot-api):* the bot token lives in `.env` as `TELEGRAM_BOT_TOKEN` (referenced
       by `token_env`) — get it from **@BotFather**. Do NOT ask for it here.

   - **rocketchat** — no inline params; delivery is via an **Incoming Webhook**.
     - *Prereq:* in Rocket.Chat go **Admin → Integrations → New → Incoming Webhook**,
       enable it, pick the target channel, and **copy the webhook URL**. Put that URL in
       `.env` as `ROCKETCHAT_WEBHOOK_URL` (referenced by `webhook_url_env`). The URL is a
       secret — do NOT write it in the YAML.

3. For any channel the user did NOT pick, leave `enabled: false`.
3.5. **Offer health alerts (recommend yes).** Ask: *"If something breaks — a feed goes
   dead, a delivery fails, a run is overdue — should I send you ONE short alert message
   on <their main channel>? (recommended)"*. On yes, add the opt-in block under
   `delivery:` (schema in `scripts/health_alert.py`; `channel` = the channel they just
   enabled):

   ```yaml
     alerts:
       enabled: true
       channel: telegram   # or email / rocketchat — their primary channel
   ```

   Without this the system is silent about its own degradation between digests — the
   user only finds out if they ask `status`. On no, skip; `/status` and the digest's
   System-health line still cover them.
4. **Secrets reminder:** tell the user which env vars to fill in and how:
   "Copy the secret template once — `cp config/.env.example config/.env` — then set
   <the relevant keys> in `config/.env`. That file is gitignored; never put secrets in the YAML."
5. Write `config/channels.yaml` to the **fixed schema** (CONVENTIONS §2.1). Keep the
   `delivery:` → `language` / `email` / `telegram` / `rocketchat` structure and all
   `*_env` key names byte-for-byte; only fill in the values:

   ```yaml
   delivery:
     language: en
     technical_level: balanced   # set in Step e.5 (technical | balanced | non-technical)
     email:
       enabled: true
       provider: gmail-mcp
       to: ["you@example.com"]
       smtp:
         host: ""
         port: 587
         user: ""
         password_env: SMTP_PASSWORD
     telegram:
       enabled: true
       transport: mcp
       chat_id: "-1001234567890"
       token_env: TELEGRAM_BOT_TOKEN
     rocketchat:
       enabled: false
       webhook_url_env: ROCKETCHAT_WEBHOOK_URL
   ```

   Optionally, `delivery.pre_send_review: true` turns on the opt-in pre-send review gate
   (`digest-review` vets a built digest before the real send; default off — leave it out
   unless the user asks for it).

### Step d — Schedule cadence → `config/schedule.yaml` (full schema)

Write the **FULL** schedule schema (CONVENTIONS §2.2): `collect`, `curate`, `synthesis`,
`digest` crons + a `timezone`. Don't interrogate — ask two questions and derive the rest
from the recommended weekly sequence.

1. Ask the **timezone** (default `UTC`; e.g. `Europe/Minsk`) and the **digest day + time**
   (default Mondays 09:00). Optionally confirm collection cadence (default: every 3 days
   at 09:00) and `max_articles_per_topic` (default 10 — the per-topic article cap).
2. Derive the weekly sequence around the digest: collect (ongoing, every 3 days) →
   **curate one hour before digest** (default Mon 08:00) → **synthesis 30 min before
   digest** (default Mon 08:30) → **digest** (the user's day/time, default Mon 09:00),
   `lookback_days` 7. Keep curate before synthesis before digest.
3. Confirm the human-readable meaning back ("collect every 3 days at 09:00; curate Mon
   08:00; synthesis Mon 08:30; digest Mon 09:00, looking back 7 days; timezone Europe/Minsk").
4. Write `config/schedule.yaml` to the **fixed schema** — keys `collect.cron`,
   `collect.max_articles_per_topic`, `curate.cron`, `curate.min_text_chars`,
   `synthesis.cron`, `synthesis.min_sources_per_topic`, `digest.cron`,
   `digest.lookback_days`, and `timezone`:

   ```yaml
   collect:
     cron: "0 9 */3 * *"        # every 3 days at 09:00
     max_articles_per_topic: 10 # per-topic cap
   curate:
     cron: "0 8 * * 1"         # Mon 08:00 — before synthesis
     min_text_chars: 500
   synthesis:
     cron: "30 8 * * 1"        # Mon 08:30 — after curate
     min_sources_per_topic: 3
   digest:
     cron: "0 9 * * 1"         # Mon 09:00
     lookback_days: 7
   timezone: "UTC"
   ```

   Cron is `"min hour day month weekday"`. Add a short trailing comment with the plain-English meaning.
5. Mention the **recommended single sequential run**: rather than racing four separate
   crons, run the whole pipeline in order via `schedule/weekly-run.md`
   (collect → sanitize-incoming → curate → synthesis → brain-hygiene → digest → deliver, each step gated on the previous). The
   separate crons remain valid for headless/split jobs. **For headless cron, the `timezone:`
   value alone isn't enough** — the box's `TZ` or a `CRON_TZ=` line in the crontab must match,
   or cron fires in the machine's local time.
6. **Register the recurring run (make it actually fire).** Writing `schedule.yaml` is
   *config only* — it sets the cadence but starts nothing on its own. Register **one**
   scheduler pointed at the gated `schedule/weekly-run.md`, set to fire at `digest.cron` in
   the chosen `timezone` (the "one gated orchestrator, not four timers" recommendation).
   User confirmation alone must not mark scheduler status `registered` — verify with the
   detection probe (below). Per runtime:
   - **External OS cron — the wizard can do this one for the user.** Offer explicitly:
     "Хочешь, я добавлю запись в crontab сейчас?" / "Want me to add the crontab entry now?"
     On consent, append the headless chain from `docs/scheduling.md` (venv interpreter +
     the trailing run heartbeat), non-destructively:

     ```bash
     ( crontab -l 2>/dev/null; \
       echo "0 9 * * 1  cd {{ABS_PROJECT_ROOT}} && .venv/bin/python3 scripts/sanitize_incoming.py sanitize && .venv/bin/python3 scripts/build_digest.py pipeline/3-synthesis/digest_\$(date +\%F).md && .venv/bin/python3 scripts/delivery/deliver.py pipeline/3-synthesis/digest_\$(date +\%F).md && .venv/bin/python3 scripts/health.py record --kind run --status ok" \
     ) | crontab -
     ```

     Adjust `0 9 * * 1` to the user's `digest.cron`, use the **absolute** project path, and
     remind about `CRON_TZ=`/box `TZ` when `timezone:` isn't the machine's local zone. Also
     offer the collect entry (`collect.cron` → `.venv/bin/python3 scripts/collect.py`) and
     the **daily health watchdog** (`0 10 * * *` → `.venv/bin/python3 scripts/health_alert.py`
     — the alert that still fires when the weekly run itself never did; opt-in via
     `delivery.alerts` in `channels.yaml`, see `schedule/health-watchdog.md`) the same way.
     Never *replace* an existing crontab — always the append form above; show the
     line before installing it. If the runtime's permission layer (an auto-mode
     classifier, a sandbox) refuses the in-session `crontab` write, don't fight it:
     print the append one-liner with every placeholder filled for the user to paste
     into their own terminal, then re-run the detection probe
     (`python3 scripts/setup_check.py`) once they confirm it's installed.
   - **Claude Code cloud agents** — the wizard cannot create the routine (it lives
     off-box), so hand over a FILLED-IN spec, never a bare pointer. Render this block
     with the user's real values and tell them to register it via `/schedule`:

     ```text
     Register one routine:
       name:     research-brain weekly run
       schedule: {{DIGEST_CRON}}    # digest.cron from config/schedule.yaml
       timezone: {{TIMEZONE}}       # must equal schedule.yaml `timezone` — the routine
                                    # assumes it; there is no auto-conversion
       prompt:   Run schedule/weekly-run.md end to end (collect → sanitize-incoming →
                 curate → synthesis → brain-hygiene → digest → deliver), each step
                 gated on the previous one.
     ```

     After the user confirms the routine exists, record it explicitly — off-box
     routines cannot be probed: `python3 scripts/setup_check.py --scheduler-state registered`.
   - **Codex / Cowork** — drive `schedule/codex-run.sh` from OS cron (same gated task file,
     no cloud scheduler); the crontab-append offer above applies with that command instead.

   **Then verify, don't assume:** run `python3 scripts/setup_check.py` — it now
   auto-detects a crontab / Task Scheduler entry referencing this install and reports
   `Schedule: registered (detected)`. Cloud-agent routines live off-box and can't be
   probed — after the user confirms one exists, pass the explicit override:
   `python3 scripts/setup_check.py --scheduler-state registered`.

   Point them at [`docs/scheduling.md`](../../docs/scheduling.md) for the crontab example and
   the per-path details.

### Step d.5 — Optional cadences (jump-in: "add a daily digest" / "weekly trends report")

The two OPTIONAL `schedule.yaml` blocks (CONVENTIONS §2.2) are conversational toggles —
never make the user hand-edit commented YAML. Direct triggers jump straight here:
"add a daily digest" / «добавь ежедневный дайджест», "remove the daily digest",
"add a weekly trends report" / «включи отдельный отчёт по трендам», "remove weekly trends".

- **Daily inflow digest ON** (`daily_digest`, ADR 0016): ask only the send time
  (default 08:00 daily), then append to `config/schedule.yaml`, keeping every existing
  block untouched:

  ```yaml
  daily_digest:
    cron: "0 8 * * *"        # every day at 08:00
    lookback_days: 1         # one day's arrivals
  ```

  Then validate (`python3 scripts/validate_config.py`) and remind: **config alone starts
  nothing** — the daily cadence needs its own trigger, separate from the weekly run.
  Offer the crontab append (same consent + append-only rules as Step d.6):

  ```
  0 8 * * *  cd {{ABS_PROJECT_ROOT}} && .venv/bin/python3 scripts/sanitize_incoming.py sanitize && .venv/bin/python3 scripts/build_digest.py --daily && .venv/bin/python3 scripts/delivery/deliver.py pipeline/3-synthesis/digest_daily_$(date +\%F).md --skip-quiet
  ```

  (`--skip-quiet` matters twice as much daily — no "nothing new" pings every morning.)
  On the cloud-agent path, guide a second `/schedule` routine running those commands.

- **Daily inflow digest OFF**: show the block and the matching crontab line, confirm,
  then remove the block (validate after) and — only with explicit consent — filter the
  line out of the crontab (`crontab -l | grep -v 'build_digest.py --daily' | crontab -`;
  show what will be removed first, never touch other lines).

- **Standalone weekly trends** (`weekly_trends`, ADR 0017): say first that trends
  **already ride every non-quiet weekly digest by default** (`--no-trends` disables), so
  most users need nothing. The block only adds a *separate* `trends_<date>.md` artifact
  on its own cron (default Mon 10:00, after the digest) — append it and offer the cron
  line (`.venv/bin/python3 scripts/trends.py`) the same consent-first way. To stop
  trends *inside* the digest instead, point at `--no-trends` on the build command.

- Close the toggle the same way as Step d: read the human-readable meaning back, and
  re-run `python3 scripts/setup_check.py` when a scheduler entry was added.

### Step e — Digest language

1. Ask: "What language should the digest be written in?" (e.g. `en`, `ru`).
2. Set `delivery.language` in `config/channels.yaml` (this lives in the same file as Step c,
   so fold it into that write rather than a second write when possible).
3. Default to `en` if the user has no preference.

### Step e.5 — Audience level

1. Ask **one** question: "Who reads the output — should I assume technical background or explain
   things more?" Offer three choices: **technical** (terse, keeps jargon and raw specifics) ·
   **balanced** (defines non-obvious terms, keeps useful detail) · **non-technical** (plain
   language, expands acronyms, explains why it matters). A *less* technical reader sees **more
   explanation**, not more raw detail.
2. Set `delivery.technical_level` in `config/channels.yaml` (same file as Step c/e — fold into
   that write). It is a **render-time** preference for the digest and answers; it never changes
   what is stored in `brain/`. Full semantics: [`docs/audience-levels.md`](../../docs/audience-levels.md).
3. Default to `balanced` if the user has no preference. Changeable later by re-running this wizard
   or via the `/audience` Telegram alias.

> **Fast path — `/audience <level>` (single-field reconfigure).** When this skill is invoked just
> to change the audience level (the `/audience` alias, or "make it more/less technical"), do **only**
> this step: validate `<level>` against the enum (default `balanced` on an empty/invalid value), write
> `delivery.technical_level` in `config/channels.yaml` (inserting the key if an older config lacks it),
> run `validate_config.py`, confirm the new level — then stop. Do **not** run the full topics/sources/
> channels/schedule interview.

### Step f — Verify it works (close the loop)

Before the first real send, produce an activation receipt. This is a check only — it sends
nothing and must not write delivery receipts.

1. **Run the shared setup checker:**

   ```bash
   python3 scripts/setup_check.py --runtime agentic --scheduler-state ready-not-registered
   ```

   For Advanced setup / RSS Digest Lite, use `--runtime headless`.

   Report the checklist with these exact labels:

   - `Source:`
   - `Config:`
   - `Delivery:`
   - `Schedule:`
   - `First value:`
   - `Next action:`

   `complete` is allowed only when `scripts/setup_check.py` would return final status
   `complete`: productive source verified, config valid, delivery rehearsed, and scheduler
   registered. If the recurring run is not verifiably registered, say `ready, schedule not
   registered` and give the exact next action to register one recurring run for
   `schedule/weekly-run.md` — which is one command, not a manual crontab edit:
   `python3 scripts/install_schedule.py --path claude --apply` (it renders the block from the
   `config/schedule.yaml` you just wrote and merges it into the user's crontab; `--path
   headless` when no agent CLI is on the box, `--path codex` for Codex, and dropping
   `--apply` writes the paste-ready file instead). Offer to run it; never run it unasked —
   registering a recurring job is the user's decision. If a gate fails, say `needs attention` and preserve the failure
   category (`config_error`, `missing_secret`, `unsupported_runtime`, `transient_failure`,
   `disabled`, etc.). Secret values must never be printed; env-var names may be shown.

2. **Runtime-aware source verification:**
   - Full agentic setup may verify any active source that the agentic collector can process.
     A configured source row alone is not success; it needs actual probe/evidence.
   - Advanced RSS Digest Lite/headless setup requires at least one active `rss` source,
     because `scripts/collect.py` only processes RSS/Atom feeds and their linked static
     article pages.

3. **Offer the FIRST DIGEST — right now, in this session when evidence supports it.**
   Close the loop with real value when the source check can produce content — a one-time
   bypass of the collection cadence (nothing here waits for cron):

   ```bash
   python3 scripts/collect.py --max-articles 3          # quick bootstrap collect (RSS + static top-up)
   python3 scripts/sanitize_incoming.py sanitize
   python3 scripts/build_digest.py                      # writes pipeline/3-synthesis/digest_<today>.md
   ```

   Then SHOW the digest to the user (render/summarize its highlights inline — don't just name
   the path) and offer to deliver it via `digest-deliver`. Framing matters: "here is your
   first digest, from your own sources, three minutes after setup." Notes:
   - `--max-articles 3` is a PER-TOPIC save cap (so expect up to 3 × active topics
     articles); it keeps the bootstrap fast and the digest small — the weekly run will
     use the configured caps. Concepts are expectedly absent — say so in one line ("the
     knowledge base fills in on the first full run") rather than letting the user think
     something failed.
   - `collect.py` reads only `rss` sources, using feed bodies plus static article-page top-up.
     If the user chose Advanced RSS Digest Lite with zero RSS sources, skip the offer and
     explain that RSS Lite needs an active feed. On the full agentic path, non-RSS first value
     comes from the agentic scheduled/manual run.
   - If a scheduled run holds the run lock, `collect.py` skips cleanly — just tell the user a
     run is already in progress.
   - A genuinely quiet feed set can still produce few/zero items; deliver whatever was
     fetched honestly and point at the weekly cadence.
4. **Optional advanced step — source tier-registry.** *Offer* (don't impose) to turn on
   **source credibility-grading**: "Want me to grade your sources by trust (peer-reviewed
   docs vs random blogs)? I can drop in a starter registry you edit." If yes, copy the
   shipped templates and let the user adjust them:
   - `sources/trusted-registry.example.md` → `sources/trusted-registry.md` (host → T1/T2/T3)
   - `sources/always-volatile-domains.example.md` → `sources/always-volatile-domains.md`
   Its presence puts `research-audit` in FULL mode (the `>30% 🔴` verification gate — which
   only fires on the **manual `/research` chain**, where the user can override) and makes
   `source-archive` stamp each source's tier. **It is not required and changes nothing on
   the unattended weekly digest** (that path is soft by design). On a default setup just
   skip it — `research-audit` runs in soft mode, which is fine. Don't copy the files unless
   the user opts in.
5. **If Telegram is enabled with `transport: mcp`, point at the shipped launcher.**
   For the bot to *answer* incoming commands (not just receive digests) the session must run
   with the per-project `TELEGRAM_STATE_DIR` **and** the inbound `--channels` flag. The
   project ships this ready-made — no rc editing, nothing to configure:

   > "Start Telegram-enabled sessions from the project folder with **`make telegram`**
   > (or `scripts/telegram-launch.sh`). It resolves the folder by itself, sets the
   > per-project state dir, and turns inbound on. Plain `claude` is send-only —
   > digests arrive, but `/save`, `help`, … never reach me."

   **f.4a — Optional one-word alias (opt-in rc append).** If the user wants to launch from
   *anywhere* with one word, offer to append a thin alias — only with explicit consent:

   > "Want me to add a `claude-telegram` alias to your shell startup file? I'll only
   > append — I won't touch anything else."

   If **yes**:
   - **(a) Consent first — never write without an explicit yes.** Otherwise show the manual
     line from **f.4b**.
   - **(b) Pick the right rc file from `$SHELL`:** `~/.zshrc` for zsh, `~/.bashrc` for bash.
     If `$SHELL` is something else or unclear, **ask** rather than guess; create the file if
     it doesn't exist.
   - **(c) Be idempotent — check before writing.** Grep the rc for an existing
     `claude-telegram` alias/function; never append a duplicate. If a stale full-function
     form from an older version exists, replace that block with the alias.
   - **(d) Use the real checkout absolute path** detected in Step 0. Append exactly:

     ```bash
     # research-brain — launch Claude with the Telegram channel live
     alias claude-telegram='/real/abs/path/to/research-brain/scripts/telegram-launch.sh'
     ```

   - **(e) Tell them to reload the shell:** "Run `source <rcfile>` (or open a new terminal)."

   **f.4b — Manual fallback.** Show the same one-line alias for them to paste by hand,
   with the real path substituted.

   Either way, close with the ownership rule: **one listener per bot token** — a token
   allows exactly one live `getUpdates` consumer, so only ONE session at a time can own the
   bot (the newest to connect steals it); to drive Telegram from several projects at once,
   give each its own bot token via a per-project `TELEGRAM_STATE_DIR` (the launcher derives
   one from the folder name automatically). Full setup: `docs/telegram-multiproject.md`.

6. **Tell the user what happens next:**
   - After the first **collect + synthesis** run, `scripts/validate_brain.py` reports
     knowledge-base health (orphans, broken links, missing sources, uncited key facts,
     stale concepts, tag merges) and that one-line health summary is surfaced in the digest.
   - They can browse concepts via **`brain/concepts.base`** in Obsidian (requires Obsidian
     ≥1.7 — Bases) for a live, self-updating map, or via the plain-markdown fallback
     **`brain/INDEX.md`**.

---

## Output

After the run, the skill has written (only the files touched in this run):

- `config/topics.yaml` — one `topics:` entry per topic (name, tags, include, exclude).
- `config/tags.yaml` — derived registry: `domains:` (domain → topics), `synonyms:`
  (raw topic name + aliases → nested `domain/topic`), `pending: []`. Header comment intact.
- `config/sources.yaml` — one `categories:` entry per topic with its sources
  (url/type/tier/priority/filter/active).
- `config/channels.yaml` — fixed schema, chosen channels `enabled: true`, non-secret params
  filled, `*_env` names untouched.
- `config/schedule.yaml` — fixed schema with `collect` / `curate` / `synthesis` / `digest`
  crons + `timezone`.

No secrets are written anywhere. `config/.env` remains the user's responsibility.

End by **summarizing the final config back** to the user: topics tracked, the derived tag
vocabulary (domains → topics), source counts + tiers per topic, which channels are enabled
(and which env vars + prerequisites they still need — MCP connected / webhook created /
`.env` secret), the collect/curate/synthesis/digest cadence in plain English + timezone, and
the activation checklist from `scripts/setup_check.py` with `Source:`, `Config:`,
`Delivery:`, `Schedule:`, `First value:`, and `Next action:`.

---

## Verification

Run after writing; report results to the user:

1. **YAML parses.** Validate all three YAML files, e.g.
   `python3 -c "import yaml; yaml.safe_load(open('config/channels.yaml')); yaml.safe_load(open('config/schedule.yaml')); yaml.safe_load(open('config/tags.yaml')); print('yaml ok')"`.
2. **`tags.yaml` well-formed.** It has `domains:` (a mapping of domain → list of topics),
   `synonyms:` (alias → canonical), and `pending:` (a list). Every synonym value is in
   **nested `domain/topic`** form and resolves to a real `domains:` entry; each tracked
   topic has a `synonyms:` alias pointing at its canonical tag.
3. **Schedule has the full schema.** `schedule.yaml` has `collect.cron`,
   `collect.max_articles_per_topic`, `curate.cron`, `curate.min_text_chars`,
   `synthesis.cron`, `synthesis.min_sources_per_topic`, `digest.cron`,
   `digest.lookback_days`, and a string `timezone`. Cron order keeps curate < synthesis < digest.
4. **Channels schema intact.** `channels.yaml` still has `delivery.language`, the three
   channels, and the `password_env` / `token_env` / `webhook_url_env` keys.
5. **No secrets leaked.** `grep -nE "(token|password|webhook).*[:=].*[A-Za-z0-9]{12,}" config/channels.yaml`
   returns nothing that looks like a real secret value (only `*_env` var names allowed).
6. **Sources config well-formed.** `python3 scripts/validate_config.py` passes — it
   validates the YAML twins: every source has a `type` in
   `rss` / `blog` / `medium-tag` / `webpage`, a `tier` in `high` / `medium` / `low`, and an
   `http(s)` URL.
6a. **Runtime-aware source evidence.** Full agentic setup has productive source evidence
    from the agentic runtime or reports `needs attention`; Advanced RSS Digest Lite/headless
    setup has ≥1 active row with `Type` = `rss` and `Active` = `yes`.
7. **Names in sync.** `python3 scripts/manage_sources.py list --json` shows every topic
   with a matching category (same names), and each topic has a
   `synonyms:` entry in `tags.yaml`.
8. **No placeholders left** in the files you wrote — the YAML twins never carry
   placeholders; check `python3 scripts/validate_config.py` prints no template WARN.
9. **Setup checker runs.** `python3 scripts/setup_check.py --runtime agentic --scheduler-state ready-not-registered`
   runs after config writes. For Advanced RSS Digest Lite/headless, `--runtime headless` is used.
10. **Activation checklist reported.** The transcript contains `Source:`, `Config:`,
    `Delivery:`, `Schedule:`, `First value:`, and `Next action:`.
11. **No false completion.** `complete` appears only after scheduler status is verified as
    `registered`; otherwise the transcript says `ready, schedule not registered` or
    `needs attention`.

Report e.g.: "activation: Source: verified / Config: valid / Delivery: rehearsed /
Schedule: ready_not_registered / First value: available / Next action: register one recurring
run for schedule/weekly-run.md".

---

## Examples

**First-run, starter-pack fast path**
> User: "let's set up sources"
> → Step 0 detects all-template config → first-run, and offers the starter. User says
> "yes, use the starter". Copies `sources.example-starter.md` → `sources.md` and
> `topics.example-starter.md` → `topics.md` (tech-news + ai-ml, public feeds with tiers),
> stamps today's date, and lands them in the YAML config with
> `python3 scripts/schema.py migrate-config --force`. Derives `tags.yaml`: `domains: {tech: [news], ai: [ml]}`,
> `synonyms: {tech-news: tech/news, ai-ml: ai/ml, ...}`, `pending: []`. Then delivery →
> schedule → language → verify. Summarizes: "2 topics, 5 sources (tiers set), tag vocab
> tech/news + ai/ml, Telegram enabled, full weekly schedule, validate_config OK — want me
> to run the rehearsal?"

**First-run, full interview**
> User: "configure, I'll pick my own topics"
> → first-run, starter declined. Walks topics → derives + shows tags.yaml ("ai/agents,
> ai/governance — confirm?") → sources (asks a Tier per source) → delivery (explains
> Telegram MCP prereq + how to get chat_id) → schedule (asks timezone + digest day, writes
> collect/curate/synthesis/digest + timezone) → language → verify. Reminds user to
> `cp config/.env.example config/.env`. Runs `scripts/setup_check.py` and reports whether
> the setup is ready, needs attention, or is only waiting for scheduled-run registration.

**tags.yaml derived from topics**
> Topics `ai-agents`, `ai-governance`, `tech-news` →
> `domains: {ai: [agents, governance], tech: [news]}`,
> `synonyms: {ai-agents: ai/agents, agentic: ai/agents, ai-governance: ai/governance,
> ai-policy: ai/governance, tech-news: tech/news}`, `pending: []`. Skill explains the
> vocabulary grows itself (pending → ≥3 recurrences: `validate_brain.py` recommends,
> `scripts/promote_tags.py` applies the promotion).

**Verify-it-works step**
> After writing config: runs
> `python3 scripts/setup_check.py --runtime agentic --scheduler-state ready-not-registered`.
> Reports `Source:`, `Config:`, `Delivery:`, `Schedule:`, `First value:`, and
> `Next action:`. If a Telegram secret is missing, it says the secret env-var name is
> missing and does not print any secret value. If everything except recurring registration
> is ready, it says to register one recurring run for `schedule/weekly-run.md`. It also
> explains that brain health appears in the digest after the first synthesis, and that the
> user can browse `brain/concepts.base` (Obsidian ≥1.7) or `brain/INDEX.md`.

**Reconfigure: change the timezone**
> User: "change the timezone to Europe/Minsk"
> → Step 0 detects configured → reconfigure, TARGET=schedule/timezone. Re-reads
> `schedule.yaml`, sets `timezone: "Europe/Minsk"`, leaves all crons + other files
> unchanged. Reminds: for headless cron, also set the box `TZ` or `CRON_TZ=Europe/Minsk`.

**Reconfigure one channel**
> User: "reconfigure delivery — switch off email, turn on Rocket.Chat"
> → reconfigure, TARGET=delivery. Re-reads `channels.yaml`, sets `email.enabled: false`,
> `rocketchat.enabled: true`. Explains the Rocket.Chat Incoming Webhook prereq (Admin →
> Integrations → New → Incoming Webhook → copy URL) and to set `ROCKETCHAT_WEBHOOK_URL` in
> `config/.env`. Leaves topics / sources / schedule / tags untouched.

**Add a topic (also updates tags.yaml)**
> User: "add a topic ai-rag"
> → reconfigure, TARGET=topics. Adds a `topics:` entry `ai-rag` to `config/topics.yaml`, a
> matching empty `categories:` entry to `config/sources.yaml`, and re-derives `tags.yaml`:
> adds `rag` under domain `ai` and `synonyms: {ai-rag: ai/rag}`. Leaves existing tags intact.

**Invalid URL handling**
> User gives `medum,com/tag/ai` as a source.
> → Step b validation rejects it (no scheme, malformed host), does not write the row, asks:
> "That doesn't look like a valid URL — did you mean `https://medium.com/tag/ai/latest`?"

**Secrets go to .env, not yaml**
> User: "the Telegram bot token is 123456:ABC..."
> → Skill refuses to write it into `channels.yaml`. Replies: "Tokens never go in the YAML.
> Put it in `config/.env` as `TELEGRAM_BOT_TOKEN=...` (gitignored). The YAML just references
> it via `token_env: TELEGRAM_BOT_TOKEN`."
