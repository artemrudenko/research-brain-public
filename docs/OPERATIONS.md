# OPERATIONS — running, recovering, and moving research-brain

Operator runbook for the live product. For the cadence/cron setup see
[`scheduling.md`](scheduling.md); for the Telegram bot see
[`telegram-multiproject.md`](telegram-multiproject.md); this file covers the gaps:
**migration, troubleshooting, recovery, and durable state.**

All commands are run from the project root. Secrets live in `config/.env` (gitignored);
none of the steps below print them.

## Health first

When anything looks off, start here — both are read-only and never mutate the vault.
The one-command check that covers everything (config schema, sources, delivery secrets
SET/MISSING, operational health, lock state, versions) in plain language:

```bash
python3 scripts/doctor.py
```

The narrower operational-health report behind it:

```bash
python3 scripts/health.py report
```

It rolls up dead feeds (a feed with ≥2 consecutive empty/error collects), delivery
outcomes, and digest freshness (a digest older than 8 days is **stale**). The same report
backs `brain-ask`'s *health* intent. A fresh/unconfigured vault reports "unknown", not failure.

## Setup activation check

When first-run setup looks ambiguous, use the read-only activation checker:

```bash
python3 scripts/setup_check.py
python3 scripts/setup_check.py --json
```

It sends nothing and reports `Source:`, `Config:`, `Delivery:`, `Schedule:`,
`First value:`, and `Next action:`. `ready_schedule_not_registered` means config,
source evidence, and delivery rehearsal are ready, but the scheduler is not yet
registered. The next action is to register one recurring run for `schedule/weekly-run.md` —
`python3 scripts/install_schedule.py --path claude --apply` does it from the cadence already
in `config/schedule.yaml` (merges into the existing crontab; `--path headless|codex` for the
other run paths).
`needs_attention` points at the failing category, such as `config_error`,
`missing_secret`, `unsupported_runtime`, or `transient_failure`.

## Value evidence (is it paying off?)

Activation says "it can run"; this says "it keeps delivering". The read-only
report computes recurring-value signals from artifacts the pipeline already
persists — nothing is instrumented, nothing is written:

```bash
python3 scripts/value_metrics.py report          # human summary
python3 scripts/value_metrics.py report --json   # machine-readable
```

It reports **retention** (of the last 4 ISO weeks, how many saw at least one
delivery receipt), **yield** (collected → processed conversion from the
registry, per topic), **reuse** (created / updated / reused from the newest
synthesis run log), and **feedback** (reader reactions by kind from
`pipeline/.feedback/`, last 28 days). **Cost per digest is deliberately not
computed** — the headless runtime has no token meter; record it manually during
a pilot cycle per [docs/PILOT.md](PILOT.md). Receipts and the feedback log
follow `RESEARCH_BRAIN_STATE_DIR` when relocated.

## Troubleshooting delivery

Delivery is idempotent: each send writes a receipt to
`pipeline/3-synthesis/.delivered/{digest-stem}.json` (channel → status), and a
`.delivery.lock` serialises concurrent sends. A channel already marked delivered is skipped.

**Rehearse before blaming the pipeline** — this is an end-to-end pre-flight that sends nothing
and reports each channel's target plus whether its secret is SET / MISSING:

```bash
python3 scripts/delivery/deliver.py --rehearse                          # build + dry-run-deliver today's digest
python3 scripts/delivery/deliver.py <digest.md> --dry-run               # rehearse a specific existing digest
```

(The positional to `--rehearse` is an alternate `channels.yaml`, **not** a digest — to
rehearse one already-built digest, use the `<digest.md> --dry-run` form.)

| Symptom | Likely cause | Fix |
|---|---|---|
| "Delivery skipped" | The digest is a **quiet week** and the caller passed `--skip-quiet`; or the channel already has a receipt | Expected. To resend intentionally, pass `--force`; do not manually edit delivery receipt JSON |
| One channel silent, others fine | That channel's secret is MISSING | Run `python3 scripts/delivery/deliver.py --rehearse`, set the missing secret in `config/.env`, then rerun delivery normally; do not manually edit delivery receipt JSON |
| Nothing sends, no error | Stuck `.delivery.lock`, or `RESEARCH_BRAIN_STATE_DIR` points where the receipts/lock are stale | Confirm no delivery is active, then wait for the delivery lease to expire and rerun delivery normally; leave `.delivery.lock` to lease handling |
| Want to re-send the last digest | Receipts mark it done | Pass `--force` to re-deliver regardless of receipts; do not manually edit delivery receipt JSON |

## Inspecting a digest build

Every deterministic digest build writes two local review artifacts next to the Markdown:

- `pipeline/3-synthesis/digest_YYYY-MM-DD.audit.json` — machine-readable selection provenance:
  digest hash, totals, and per-topic source decisions (`selected_by_source_credibility` /
  `hidden_topic_cap`).
- `pipeline/3-synthesis/digest_YYYY-MM-DD.report.html` — when built with `--report`, a static
  browser page for operators. It is a local file, not a service or dashboard backend.

Regenerate both from the project root:

```bash
python3 scripts/build_digest.py --report
```

Treat these files as read-only outputs. Do not hand-edit the JSON to change what a digest
shows; fix the source data/config and rebuild. Delivery receipts remain separate under
`pipeline/3-synthesis/.delivered/` and still control idempotent sending.

## Recovering a stuck run

The gated loop (`weekly-run` / `run-now`) holds a single mutual-exclusion lock at
`pipeline/.run.lock` (relocated under `RESEARCH_BRAIN_STATE_DIR` when set). If a run crashed
and left it held:

```bash
python3 scripts/run_lock.py status                    # who holds it, if anyone
python3 scripts/run_lock.py release --token <token>   # release the run you acquired
```

Only release after confirming no run is actually in progress. A partially-completed run is
safe to re-trigger: collection dedups against `pipeline/registry.md`, and delivery skips
channels that already have a receipt — so a re-run resumes rather than duplicates.
Do not manually edit pipeline/registry.md, .synthesis-meta.json, or delivery receipt JSON
files to force progress.

## Dead or stale feeds

`health.py report` flags feeds dead after 2 consecutive empty/error collects. To act on it,
pause the source with `source-manage` (for example, say "pause this source") or replace it
with a working feed (for example, say "start monitoring <feed-url>"). Then run:

```bash
python3 scripts/sanitize_incoming.py sanitize
```

After that, trigger the normal `weekly-run` / `run-now` path. A persistently empty topic
usually means the feed URL moved or the include/exclude filters in the topics config (`config/topics.yaml`) are
too tight. Do not manually edit pipeline/registry.md; registry dedup is what makes the
next collection safe.

## Safe reruns after correction

| Correction | Safe next command | State boundary |
|---|---|---|
| Source or feed fixed/paused | `python3 scripts/sanitize_incoming.py sanitize`, then `weekly-run` / `run-now` | Do not manually edit pipeline/registry.md |
| Sanitizer correction with unchanged content | `python3 scripts/sanitize_incoming.py sanitize`, then normal synthesis | Do not manually edit .synthesis-meta.json |
| Delivery secret/channel fixed | `python3 scripts/delivery/deliver.py --rehearse`, then rerun delivery normally | Do not manually edit delivery receipt JSON |
| Stale run lock | `python3 scripts/run_lock.py status`; wait for lease expiry or release only a lock you own with `python3 scripts/run_lock.py release --token <token>` | Lock files are owned by lease handling |

## Migrating to a new machine

The product is **config + data**; everything else is reinstallable from the archive.

1. **Back up** (from the old machine): the **whole `config/` directory** (including `.env`),
   the `brain/` vault, `pipeline/` (registry + archives + synthesis + `.health/`), and any
   user-created `sources/*.md` tier registries.
2. **Install** on the new machine: unpack the archive and run `make install` (or `./install.sh`).
3. **Restore** the backed-up `config/` files, `brain/`, and `pipeline/` over the fresh tree.
4. **Verify** before the first real send:
   ```bash
   python3 scripts/validate_config.py
   python3 scripts/delivery/deliver.py --rehearse
   python3 scripts/health.py report
   ```
5. Reconnect MCP delivery in the assistant if you use it. For headless delivery, restore
   the bot/SMTP/webhook secrets, then re-register the schedule per
   [`scheduling.md`](scheduling.md).

## Durable state on ephemeral hosts (containers, redeploys)

By default all runtime state lives in-repo (`pipeline/.health/`,
`pipeline/3-synthesis/.delivered/`, `.delivery.lock`, `pipeline/.run.lock`). On a host whose
filesystem is wiped on redeploy, set **`RESEARCH_BRAIN_STATE_DIR`** to a persistent volume so
delivery receipts, the health log, and the locks survive — otherwise a redeploy can re-send the
last digest (lost receipts) or lose run history. The same variable also isolates state when one
machine runs multiple projects; see [`telegram-multiproject.md`](telegram-multiproject.md) for
the per-project bot-token + state-dir pattern.
