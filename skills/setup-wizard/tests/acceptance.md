---
title: "Acceptance tests — setup-wizard"
type: acceptance-test
status: active
related_skill: skills/setup-wizard/SKILL.md
generated_by: ai-then-human-edited
---

# Acceptance tests — setup-wizard

Living spec for the conversational onboarding skill. The default first-run path is the
full agentic research-brain flow; RSS Digest Lite and headless transports remain advanced
choices. Setup completion is an activation checklist, not just written config files.

## Scope

- **Skill:** `setup-wizard`
- **SKILL.md:** [`../SKILL.md`](../SKILL.md)
- **Coverage:** 12 scenarios covering default agentic setup, advanced RSS Lite/headless
  setup, intake reuse, truthful scheduler state, delivery failure classification, secret
  redaction, and first-value reporting.

---

## Scenarios

### Scenario 1: Default first-run agentic path

**Given:**
- A freshly unpacked project with template config files.

**When:**
- User says: "let's set up sources".

**Then:**
- The wizard says exactly: "We'll set up the full research-brain path. Advanced users can choose RSS Digest Lite or headless transports."
- The wizard does not ask the user to choose `agentic`, `headless`, or `RSS Digest Lite`.
- Delivery choices are explained as user outcomes: where the digest goes, prerequisites, schedule, first value.
- The final check runs `python3 scripts/setup_check.py --runtime agentic --scheduler-state ready-not-registered`.

**Acceptance signal:**
- Transcript contains the exact default sentence above.
- Transcript contains `scripts/setup_check.py`.
- Transcript contains `Source:`, `Config:`, `Delivery:`, `Schedule:`, `First value:`, and `Next action:`.

---

### Scenario 2: Advanced RSS Lite path

**Given:**
- A first-run user explicitly asks for "advanced setup" or "RSS Digest Lite".

**When:**
- The wizard enters the Advanced setup fork.

**Then:**
- The wizard explains that RSS Digest Lite is reduced fallback, not full agentic synthesis.
- The wizard requires at least one active `rss` source for the headless collector.
- The final check runs `python3 scripts/setup_check.py --runtime headless --scheduler-state ready-not-registered`.

**Acceptance signal:**
- Transcript contains `Advanced setup fork`, `RSS Digest Lite`, `--runtime headless`, and `active rss source`.

---

### Scenario 3: Advanced SMTP email path

**Given:**
- User explicitly chooses advanced/headless email delivery.

**When:**
- The wizard configures email.

**Then:**
- `channels.yaml` keeps `provider: smtp`.
- SMTP password is not written to YAML.
- The wizard tells the user the secret belongs in `config/.env` under `SMTP_PASSWORD`.

**Acceptance signal:**
- `config/channels.yaml` contains `provider: smtp` and `password_env: SMTP_PASSWORD`.
- No literal SMTP password appears in `config/channels.yaml`.

---

### Scenario 4: Advanced Telegram Bot API path

**Given:**
- User explicitly chooses advanced/headless Telegram delivery.

**When:**
- The wizard configures Telegram.

**Then:**
- `channels.yaml` keeps `transport: bot-api`.
- Bot token is not written to YAML.
- The wizard tells the user the secret belongs in `config/.env` under `TELEGRAM_BOT_TOKEN`.

**Acceptance signal:**
- `config/channels.yaml` contains `transport: bot-api` and `token_env: TELEGRAM_BOT_TOKEN`.
- No literal bot token appears in `config/channels.yaml`.

---

### Scenario 5: OPML source establishment through intake

**Given:**
- During source setup the user supplies an OPML file.

**When:**
- The wizard establishes sources.

**Then:**
- It routes through the `intake` OPML flow.
- It previews proposed topics, selected feeds, existing feeds, and invalid entries.
- It applies only after confirmation.

**Acceptance signal:**
- Transcript references `scripts/import_opml.py`, preview, confirmation, and apply.

---

### Scenario 6: Bare URL source establishment through intake

**Given:**
- During source setup the user supplies a plain URL without `/add` or `/save`.

**When:**
- The wizard classifies the URL.

**Then:**
- It runs `python3 scripts/intake.py URL --json`.
- A recurring-source proposal shows `source_url`, `source_type`, `topic_mode`, `proposed_topic`, `tier`, `priority=medium`, `filter_note="all posts"`, and `active=yes`.
- Persistence waits for approval.

**Acceptance signal:**
- Transcript references `scripts/intake.py`, `source_url`, `source_type`, `tier`, and approval.

---

### Scenario 7: Explicit /add and /save boundaries

**Given:**
- During setup the user says `/add https://example.com/feed.xml`.

**When:**
- The wizard routes the request.

**Then:**
- `/add <url>` goes directly to `source-manage`; it does not run `scripts/intake.py`.
- `/save <url>` remains a direct `source-capture` read-it-later action and is not treated as a monitored source unless the user asks to monitor it.

**Acceptance signal:**
- Transcript states `/add <url>` is direct and `/save <url>` is separate from setup source monitoring.

---

### Scenario 8: No false complete before scheduler registration

**Given:**
- Config is valid, delivery rehearses, and source evidence exists.
- No scheduler registration has been verified.

**When:**
- The wizard finishes setup.

**Then:**
- It reports `ready, schedule not registered`.
- It does not say setup is `complete`.
- It gives the next action to register one recurring run for `schedule/weekly-run.md`.

**Acceptance signal:**
- Transcript contains `ready, schedule not registered`.
- Transcript contains `register one recurring run for schedule/weekly-run.md`.
- Transcript does not contain `Setup status: complete`.

---

### Scenario 9: Registered scheduler complete path

**Given:**
- Source, config, delivery, and scheduler checks all pass.

**When:**
- The wizard reruns the final setup check after verifying scheduler registration.

**Then:**
- The checklist may report `Setup status: complete`.

**Acceptance signal:**
- Transcript contains `Schedule: registered`.
- Transcript contains `Setup status: complete`.

---

### Scenario 10: Delivery missing secret classification

**Given:**
- Advanced SMTP or Bot API delivery is enabled but the relevant env var is missing.

**When:**
- The wizard runs `scripts/setup_check.py`.

**Then:**
- Delivery is classified as `missing_secret`.
- The env-var name may be shown.
- The secret value is never shown.

**Acceptance signal:**
- Transcript contains `Delivery: missing_secret`.
- Transcript may contain `SMTP_PASSWORD` or `TELEGRAM_BOT_TOKEN`.
- Transcript contains no pasted password/token value.

---

### Scenario 11: MCP-only headless unsupported runtime classification

**Given:**
- The user chooses Advanced/headless setup but email is still `provider: gmail-mcp` or Telegram is still `transport: mcp`.

**When:**
- The wizard runs `scripts/setup_check.py --runtime headless`.

**Then:**
- Delivery is classified as `unsupported_runtime`.
- The next action tells the user to choose SMTP/Bot API or run inside an MCP-capable agent runtime.

**Acceptance signal:**
- Transcript contains `Delivery: unsupported_runtime`.
- Transcript mentions `smtp` or `bot-api`.

---

### Scenario 12: Secret redaction and first-value result

**Given:**
- User accidentally pastes a real token, password, or webhook URL into the conversation.
- Source check returns no current content or a quiet result.

**When:**
- The wizard reports final setup status.

**Then:**
- The report never repeats the secret value.
- The checklist shows `First value: empty` or `First value: not_checked` instead of implying content was found.
- The next action tells the user whether to add/fix a source, wait for scheduled collection, or run the pipeline now.

**Acceptance signal:**
- Transcript contains `First value:`.
- Transcript contains no literal pasted secret value.

