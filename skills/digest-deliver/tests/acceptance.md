---
title: "Acceptance tests — digest-deliver"
type: acceptance-test
status: active
related_skill: skills/digest-deliver/SKILL.md
generated_by: ai-then-human-edited
---

# Acceptance tests — digest-deliver

> Living spec for the digest delivery skill. Covers the all-disabled no-op, a
> single enabled channel happy path, the missing-secret actionable error, the
> headless-transport fallback, and a pre-send dry-run check. All channel selection
> follows the FIXED schema in `docs/CONVENTIONS.md` §2.1; secrets always come from
> env, never YAML.

## Scope

- **Skill:** `digest-deliver`
- **SKILL.md:** [`../SKILL.md`](../SKILL.md)
- **Coverage:** 5 scenarios — 1 no-op + 1 happy path + 1 error path + 1 transport
  mode + 1 dry-run check.

---

## Scenarios

### Scenario 1: All channels disabled -> no-op

**Given:**
- A built digest markdown file exists.
- `config/channels.yaml` has `email.enabled: false`, `telegram.enabled: false`,
  `rocketchat.enabled: false`.

**When:**
- User: "send digest".

**Then:**
- Nothing is sent over any transport (no MCP tool calls, no webhook POST).
- The skill reports each channel as SKIPPED (disabled) and a clear summary whose
  wording is exactly `no enabled channels — nothing to deliver` (identical to the
  string `deliver.py` prints — see `NO_CHANNELS_MESSAGE`).
- The run is treated as success (no error raised).

---

### Scenario 2: One channel enabled -> sends

**Given:**
- A built digest markdown file exists.
- `config/channels.yaml` has `telegram.enabled: true`, `transport: mcp`,
  `chat_id: "42"`; the other two channels disabled.

**When:**
- User: "deliver digest".

**Then:**
- The digest body is rendered as Telegram Markdown (chunked on paragraph
  boundaries if longer than 4096 chars) and sent via the Telegram MCP tool to
  chat 42.
- The skill reports `telegram SENT (-> 42)`; email and rocketchat SKIPPED.
- The reply respects `delivery.language`.

---

### Scenario 3: Missing secret -> actionable error

**Given:**
- A built digest markdown file exists.
- `config/channels.yaml` has `rocketchat.enabled: true` with
  `webhook_url_env: ROCKETCHAT_WEBHOOK_URL`.
- The `ROCKETCHAT_WEBHOOK_URL` environment variable is **unset**.

**When:**
- User: "разошли дайджест".

**Then:**
- The Rocket.Chat channel does not silently skip; the skill reports
  `rocketchat FAILED` with an actionable message naming the env var and pointing
  to `config/.env.example`.
- The overall run is reported as failed for that channel (nonzero exit in
  headless mode).

---

### Scenario 4: Headless / cron transport

**Given:**
- No agent is present (a cron-triggered run).
- `config/channels.yaml` has at least one enabled channel with a headless
  transport (`email.provider: smtp`, `telegram.transport: bot-api`, or rocketchat).
- Required secrets are present in the environment.

**When:**
- `python3 scripts/delivery/deliver.py <digest_file.md>` runs.

**Then:**
- The dispatcher reads the same `config/channels.yaml`, delivers each enabled,
  headless-capable channel via its adapter (SMTP / Bot API / webhook), and skips
  MCP-only channels with a note.
- Before resolving secrets it auto-loads `config/.env` (resolved against the
  project root, regardless of cwd) if that file exists.
- It prints a per-channel status line and exits 0 only if all enabled channels
  succeeded; nonzero if any failed.

---

### Scenario 5: Dry-run pre-send check

**Given:**
- `config/channels.yaml` has at least one enabled headless channel (e.g.
  `telegram.transport: bot-api`, `chat_id: "42"`, `token_env: TELEGRAM_BOT_TOKEN`).
- The required secret may be present or absent in the environment.

**When:**
- `python3 scripts/delivery/deliver.py --dry-run` runs (no digest path → a tiny
  built-in test message is used), or `deliver.py <digest_file.md> --dry-run`.

**Then:**
- Nothing is sent over any transport.
- For each enabled channel the dispatcher prints what it *would* send — transport,
  recipient/chat target, and whether its secret env-var is `SET` or `MISSING`
  (never the secret value).
- The command exits 0 even when a secret is `MISSING` (it is a check, not a send).
