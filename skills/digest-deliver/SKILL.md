---
name: digest-deliver
description: "Deliver a built weekly digest to the channels configured in config/channels.yaml — email, Telegram, Rocket.Chat. Picks the right transport per channel (MCP tools in Cowork/Claude Code, or the headless scripts/delivery/ module for cron). Renders the digest appropriately per channel and reports what was sent where. Triggers: «deliver digest», «send digest», «send the weekly digest», «push the digest», «разошли дайджест», «отправь дайджест»."
metainfo:
  type: worker
  domain: research-methodology
  last_updated: 2026-06-21
---

# digest-deliver — send the weekly digest to configured channels

Takes a digest markdown file (built by the `digest-build` skill) and delivers
it to every channel marked `enabled: true` in `config/channels.yaml`. Each channel
chooses its transport from the config; secrets always come from the environment,
never from YAML.

This skill is the **MCP-mode** counterpart to the headless `scripts/delivery/`
module. In Cowork / Claude Code it prefers MCP tools (Telegram MCP, Gmail MCP);
for cron / no-agent runs the same channels go through `scripts/delivery/deliver.py`.
See `docs/CONVENTIONS.md` §3 ("two transports").

---

## When to Use

**Use when:**
- The user says: "deliver digest", "send digest", "send the weekly digest",
  "push the digest", "разошли дайджест", "отправь дайджест".
- A digest markdown file exists (just built, or named explicitly) and needs to
  reach the user's channels.

**Skip / don't use for:**
- Building the digest itself (that is the `digest-build` skill).
- Configuring channels or secrets (that is `setup-wizard`).
- Ad-hoc one-off messages unrelated to a digest file.

---

## Inputs

| Input | Source | Notes |
|-------|--------|-------|
| Digest file | CLI arg / latest built digest | Markdown; its body is the message payload |
| `config/channels.yaml` | repo config | Fixed schema, CONVENTIONS §2.1 — read, don't edit |
| Secrets | env / `config/.env` | Resolved by name via the `*_env` keys; never read from YAML |
| `delivery.language` | `config/channels.yaml` | Language the digest is rendered in |

---

## Steps

1. **Resolve the digest file.** Use the path the user gave, else the most recent
   built digest. Read its markdown body once. Confirm the file exists.

2. **Read `config/channels.yaml`.** Parse the `delivery:` block. Note
   `delivery.language` and the three channel sub-blocks (`email`, `telegram`,
   `rocketchat`). Skip any channel with `enabled: false` (report it as skipped).

3. **Verify channels before the first send.** Before delivering for the first
   time (or after changing config/secrets), run a dry-run to confirm each enabled
   channel is wired up:

   ```
   python3 scripts/delivery/deliver.py --dry-run
   ```

   With no digest file, this uses a tiny **built-in test message**, resolves the
   config + secrets, and prints per channel what *would* be sent — transport,
   recipient/chat target, and whether each secret env-var is **SET** or
   **MISSING** (never the secret value). It sends nothing and exits 0 even if a
   secret is missing (it is a check, not a delivery). Pass a real digest path to
   dry-run that exact payload: `deliver.py <digest_file.md> --dry-run`. For a
   full end-to-end pre-flight that builds *today's* digest from the lookback
   window into a temp file and dry-run-delivers it in one shot, use `deliver.py
   --rehearse` (it still sends nothing).

3.5. **Pre-send review gate (opt-in).** Before the real send, check
   `delivery.pre_send_review` in `config/channels.yaml`. Absent or `false` (the
   default): skip this step. When `true`, run the **`digest-review`** skill
   (`skills/digest-review/SKILL.md`) on the resolved digest — the slot between
   the dry-run above and the actual transport calls (`weekly-run.md` Step 5.5).
   Proceed to send only once its verdict allows it: advisory by default (it
   surfaces findings for a decision; unattended it stays soft and records the
   findings), but a strict-run blocking finding **halts** the send and hands
   back to synthesis/curation. Under `weekly-run.md` the review already ran as
   Step 5.5 (via `critic`); when that step recorded a pass for this digest, this
   gate is the deterministic backbone under `deliverer` and need not repeat the
   full adversarial pass — it re-checks only that the digest is unchanged.

4. **Choose mode.** Default is **MCP mode** (running inside Cowork / Claude Code).
   If running headless (cron / no agent) or the user asks for it, use **Headless
   mode** instead — a single call to `scripts/delivery/deliver.py <digest_file>`,
   which reads the same config and reports per-channel status. In headless mode
   `deliver.py` **auto-loads `config/.env`** (resolved against the project root,
   regardless of cwd) before resolving secrets, so a cron run needs no
   pre-exported env vars.

5. **Pre-send idempotency check (MCP mode) — MANDATORY.** The MCP path shares the
   headless receipt, so a re-run of this skill (retry after a partial failure,
   a second `/send`) must not re-send an already-delivered channel:

   ```bash
   python3 scripts/delivery/deliver.py <digest.md> --mcp-status
   ```

   Per enabled MCP channel it prints `DELIVERED <timestamp>` (skip it — report
   `SKIPPED (already delivered)`), `IN-FLIGHT` (another sender has it — skip it,
   report `SKIPPED (in flight elsewhere)`), or `PENDING` (send it). A rebuilt
   digest with changed content reads `PENDING` again on purpose. Only when the
   user explicitly asks to re-send may a DELIVERED channel be sent again.

   **Then claim each PENDING channel before you send it — MANDATORY:**

   ```bash
   python3 scripts/delivery/deliver.py <digest.md> --reserve-mcp telegram
   # same for every other PENDING channel: --reserve-mcp email / --reserve-mcp rocketchat
   ```

   Exit 0 means the channel is yours: send it now, then stamp it (step 8). **Any
   non-zero exit means do NOT send that channel** — another agent claimed it
   first, it is already delivered, or delivery is locked; report it as `SKIPPED`
   with the printed reason and move to the next channel. The status check alone
   is not enough: two agents can both read `PENDING` and both send, because
   nothing was written before the send. Reserving writes the claim under the
   delivery lock, so exactly one of them gets the 0.

   **Per enabled channel (MCP mode), pick transport and render:**
   - **Telegram** (`transport: mcp`): render the body as Telegram Markdown; if it
     exceeds 4096 chars, split on paragraph boundaries and send sequentially via
     the Telegram MCP tool to `chat_id`. (`transport: bot-api` -> defer to headless.)
     **Chunked sends record progress after each chunk**, so an interrupted send
     resumes instead of re-delivering messages the user already has:

     ```bash
     python3 scripts/delivery/deliver.py <digest.md> --record-mcp telegram --chunks-sent 3
     ```

     If `--mcp-status` reported `N chunk(s) already delivered`, start from chunk
     N+1 — the split is deterministic for identical content, so the numbering
     matches. This also refreshes the reservation, so a slow multi-chunk send
     cannot outlive its own claim.
     When a sibling browser report exists (`<digest>.report.html`, written by the
     build's `--report`), **attach it** to the last message (the reply tool's
     `files` parameter) so "open the full report" is one tap — strip or keep the
     footer link either way; the headless bot-api path stays text-only.
   - **Email** (`provider: gmail-mcp`): build a subject (`Research digest — <stem>`).
     Render the **same premium HTML** the SMTP path sends — reuse the
     `digest_*.html` already produced when the digest was built with `--html`, or
     render it on the fly with
     `python3 scripts/delivery/email_html.py <digest.md> --title "Research digest — <stem>" --out <digest>.html`.
     Send that as the **HTML body** to every address in `to:` via the Gmail MCP
     tool, keeping the digest markdown as the plain-text fallback. If the render
     fails, fall back to sending the plain markdown (never let formatting block a
     send). (`provider: smtp` -> defer to headless.)
   - **Rocket.Chat**: send it with the project's guarded CLI — **never** a raw
     `curl` / WebFetch POST:

     ```bash
     python3 scripts/delivery/rocketchat_webhook.py --text-file <digest.md>
     ```

     The CLI applies the same SSRF guards the headless path uses (http(s)-only,
     private/loopback/metadata addresses refused, host resolved before connecting,
     every redirect hop re-validated) and reads the webhook URL from `config/.env`
     itself. Do **not** pass the URL as an argument — it carries the channel's
     secret token, and argv lands in `ps`, in shell history, and in this
     transcript. Exit 0 = sent; any non-zero exit means nothing was delivered.
     Same webhook for both modes — but in MCP mode YOU run the send, so it takes
     part in the shared receipt like the others: it appears in `--mcp-status`
     (skip it when DELIVERED) and you MUST `--record-mcp rocketchat` after a
     successful send (step 8) — never after a non-zero exit.

6. **Handle a missing secret** for an enabled channel by stopping that channel with
   an actionable message ("set TELEGRAM_BOT_TOKEN in config/.env"), not a silent skip.

7. **Report** a per-channel status line: SENT / SKIPPED (disabled, MCP-only in the
   other mode, or *already delivered* — see Idempotency) / FAILED (with reason).
   Respect `delivery.language` in the rendered digest and in the summary back to
   the user.

8. **Stamp the receipt (MCP mode) — MANDATORY after each successful send.** This
   is what makes step 5's check work on the next run; without it every re-run
   re-sends. Immediately after a channel goes through:

   ```bash
   python3 scripts/delivery/deliver.py <digest.md> --record-mcp telegram
   # and/or: --record-mcp email  --record-mcp rocketchat
   ```

   Rocket.Chat counts here too: in MCP mode you POST its webhook yourself, so it
   shares the receipt — stamp it after a successful POST, or a re-run re-sends it.

   It writes the same `.delivered/{stem}.json` receipt (with the digest content
   hash) the headless path uses, under the same `.delivery.lock`, promoting the
   step-5 reservation to `sent`. Do NOT stamp a channel that failed — a failed
   channel must stay eligible for retry. A channel you reserved but could not
   send stays reserved until its lease expires, then becomes sendable again;
   that is deliberate, so a crash mid-send does not silently re-deliver.

9. **Record delivery health** (observability). In MCP mode you sent the channels
   yourself, so the headless `deliver.py` health hook did not run — append one
   event per channel you delivered so the history is complete:

   ```bash
   python3 scripts/health.py record --kind deliver --channel telegram --status sent
   # use --status failed for a channel that did not go through
   ```

   Best-effort; never block on a logging failure. (Headless `deliver.py` records
   this automatically from the receipt — only the MCP path needs this step.)

---

## Idempotency & re-runs (both modes, CONVENTIONS §10)

**One receipt, two writers.** Headless `deliver.py` stamps it automatically on
each live send; the MCP path stamps it explicitly via `--record-mcp` (step 8)
and consults it via `--mcp-status` (step 5). Either way a re-run skips
already-delivered channels and re-attempts only failures.

`scripts/delivery/deliver.py` is safe to re-run. On each live run it writes a
per-digest **receipt** at `pipeline/3-synthesis/.delivered/{digest-stem}.json`
(`{digest-stem}` = the digest filename without its extension), mapping each
channel to `{status, timestamp}`:

- A channel already recorded as **`sent`** for this digest is **skipped** on a
  re-run (reported `SKIPPED (already delivered <timestamp>)`). So re-running after
  a partial failure only re-attempts the channels that did **not** succeed.
- A channel recorded as **`failed`** is **retried** on the next run.
- Each send also gets **one bounded retry** in-process on a transient transport
  error (timeout / 5xx) before it is marked `failed`.
- The transport error reason (host/port for SMTP, "Bot API send failed", "webhook
  POST failed") is surfaced in the FAILED status line — it is not a secret.
- The receipt also records the digest **content hash** per channel: a same-day rebuild
  with **changed** content re-sends; an unchanged re-run still skips. A failure to write
  the **final** receipt is surfaced (clear error + non-zero exit), so a lost receipt
  never silently re-sends next run.
- **Concurrency:** a real delivery takes a short-lived lock
  (`pipeline/3-synthesis/.delivered/.delivery.lock`), so two overlapping `deliver.py`
  runs (cron overlap / accidental double-invoke) can't both send the same digest — the
  second refuses (`exit 1`, "another delivery is already in progress"). Dry-run never locks.

**`--force`** ignores the receipt and re-sends every enabled channel:

```
python3 scripts/delivery/deliver.py <digest_file.md> --force
```

**`--dry-run`** never reads or writes a receipt and never skips based on one — it
is a pure pre-send check.

---

## Output

- The digest delivered to each enabled channel via its chosen transport.
- A concise per-channel report, e.g.:

  ```
  email      SENT (-> you@example.com)
  telegram   SENT (-> 42)
  rocketchat SKIPPED (disabled)
  ```

- No files are written; `config/channels.yaml` is read-only here.

---

## Verification

- All-disabled config -> no sends, explicit "no enabled channels" message, success.
- Each enabled channel reports SENT only after the transport confirmed delivery
  (MCP tool success, or HTTP 2xx for the webhook).
- A missing env secret on an enabled channel surfaces a clear, actionable error
  naming the env var — never a silent pass.
- Headless mode: `python3 scripts/delivery/deliver.py <digest>` exits 0 only when
  every enabled channel succeeded; nonzero on any failure. It auto-loads
  `config/.env` before resolving secrets.
- Dry-run: `deliver.py --dry-run` (optionally with a digest path) sends nothing,
  reports each enabled channel's target and SET/MISSING secret state, and exits 0
  even when secrets are missing.
- Idempotency: re-running `deliver.py <digest>` skips channels already `sent` for
  that digest (per the receipt) and re-attempts only the failed ones; `--force`
  re-sends all enabled channels; `--dry-run` neither reads nor writes a receipt.

---

## Examples

**Example 1 — one channel enabled (Telegram, MCP):**
> User: "send the weekly digest"
> Reads `config/channels.yaml`: only `telegram.enabled: true`, `transport: mcp`,
> `chat_id: 42`. Renders the digest as Telegram Markdown, sends via Telegram MCP,
> reports `telegram SENT (-> 42)`; email and rocketchat reported as SKIPPED.

**Example 2 — all channels disabled:**
> User: "разошли дайджест"
> Every channel is `enabled: false`. The skill sends nothing and replies
> "no enabled channels — nothing to deliver; enable one in config/channels.yaml".

**Example 3 — missing secret:**
> Rocket.Chat is enabled but `ROCKETCHAT_WEBHOOK_URL` is unset. The skill stops
> that channel and reports: "rocketchat FAILED — set ROCKETCHAT_WEBHOOK_URL in
> config/.env (see config/.env.example)."

**Example 4 — headless / cron:**
> No agent present. Cron runs `python3 scripts/delivery/deliver.py pipeline/3-synthesis/digest_YYYY-MM-DD.md`,
> which reads the same config and delivers via the SMTP / Bot API / webhook adapters.
