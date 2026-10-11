# health-watchdog

**Schedule:** daily (recommended: mid-morning, e.g. 10:00 in the `timezone` from
`config/schedule.yaml` — after the weekly run's window, so a failure the run managed
to *record* pings the same day).
**Purpose:** the one alert that does **not** depend on the run it is watching. The
weekly run's own Step 7.5 alert fires only when the run reaches its end — a run that
crashed early, or a scheduler that silently stopped firing (laptop asleep, routine
deleted, crontab edited), alerts **zero** times. This tiny independent task closes that
gap: it checks health on its own clock and pings only when something is actually wrong.
**Detection window, honestly:** a no-trace failure (a crash before any event was
recorded, a scheduler that simply stopped) leaves nothing to see on the day itself.
It surfaces through the run-overdue / digest-stale signals once the last success ages
past the 8-day window — about two days after the missed weekly slot, not the same
morning. Only failures that *did* record an event (a failed delivery, an explicitly
recorded failed run) ping on the watchdog's next daily pass.

All paths are relative to the project root.

---

## Task

### 1. Compute the verdict (read-only, deterministic)

```bash
python3 scripts/health_alert.py --dry-run
```

- Verdict **not** DEGRADED → it prints "nothing to send". **Stop — do not message
  anyone.** A healthy or fresh system must never ping.
- Verdict DEGRADED → it prints the one-line alert message it would send (e.g.
  `⚠️ research-brain health DEGRADED: run overdue (no recent run); digest stale`).

### 2. Send the one-line alert (only when DEGRADED)

Pick the path by how delivery is configured in `config/channels.yaml`:

- **MCP-mode channels** (`transport: mcp` / `provider: gmail-mcp` — the supported
  default): **you** (the agent) send the exact one-line message from step 1 through the
  runtime's delivery transport (Telegram MCP reply / Gmail MCP), to the same target the
  digest goes to. Plain text only — the message embeds feed/topic names from external
  content; never render it as markdown/HTML.
- **Headless channels** (`bot-api` / SMTP / Rocket.Chat webhook): run the real sender —
  it is opt-in and self-gating:

  ```bash
  python3 scripts/health_alert.py
  ```

  It sends only when `delivery.alerts.enabled: true` is set under `delivery:` in
  `config/channels.yaml` (default OFF) and always exits 0 (best-effort — an alert must
  never fail a schedule).

### 3. Do nothing else

No collect, no digest, no vault writes. This task is a watchdog, not a run.

---

## Register it

- **Claude Code `/schedule`** — one extra daily routine pointed at this file.
- **External cron** — one extra line (venv interpreter, as everywhere):

  ```bash
  # Daily health watchdog — 10:00; pings only on a DEGRADED verdict (opt-in):
  0 10 * * *  cd /path/to/research-brain && .venv/bin/python3 scripts/health_alert.py
  ```

Both require the opt-in once: `delivery.alerts.enabled: true` (+ `channel:`) under
`delivery:` in `config/channels.yaml` — see the commented `alerts:` block there.

## Success criteria

- Healthy/fresh system: no message sent, exit 0.
- DEGRADED system: exactly one one-line alert on the configured channel.
- The watchdog fires even when the weekly run itself never did — that is its point.
