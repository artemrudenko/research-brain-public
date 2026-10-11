# Support boundaries & upgrade policy

What this distribution promises, what is best-effort, and how versions move.
(The audit asked for these boundaries to be written down — this page is the
single place; README links here.)

## Supported (the contract)

| Surface | Supported shape |
|---|---|
| **Python** | 3.11 and 3.12 (both run in CI). Runtime `scripts/` import only the stdlib + PyYAML. |
| **Platforms** | macOS and Linux, fully. Windows: the Python runtime and both installers are supported; see best-effort notes below. |
| **Runtimes** | The **full agentic path** (Claude Code / Cowork driving the skills) is the supported default. The **headless path** (`collect → sanitize → build_digest → deliver` under cron) is supported as **RSS Digest Lite** — a reduced product, not a smaller copy of the full one. |
| **Delivery transports** | Email via Gmail MCP (agentic) or SMTP (headless); Telegram via MCP (agentic, incl. inbound commands) or bot API (headless, **send-only**); Rocket.Chat via incoming webhook. |
| **Install / update** | Unpack the release zip + `./install.sh` (or `install.ps1`); update in place with `./update.sh` (or `update.ps1`). Both installers end with a read-only `doctor.py` verify. |
| **Data durability** | `brain/`, `pipeline/`, `config/` (incl. `.env` and customized sources/topics/channels/tags) are **user data**: updates never overwrite or delete them (add-only scaffolding excepted). |

## Best-effort (known, honest limits)

- **Windows updater runtime**: `update.ps1` mirrors `update.sh`'s safety contract
  (backup, no-delete overlay, downgrade refusal, orphan report, add-only `brain/`
  scaffolding). It is AST-parse-checked with real PowerShell in CI **and** run
  end-to-end on a real `windows-latest` host each build — the overlay, the
  preserve set, the backup, and the downgrade refusal execute against a fixture
  install, so its first real run is never on your vault. What remains untested is
  the long tail: real antivirus/file-locking interference, network drives, and
  non-NTFS targets. Keep the automatic backup it prints until you've eyeballed
  the result.
- **Telegram inbound under cron**: incoming commands need a live agent session
  owning the bot (`make telegram`); the headless bot-API adapter is send-only.
- **One bot token = one listener**: the newest session steals the bot; per-project
  tokens are the fix (docs/telegram-multiproject.md).
- **Cloud-agent schedules** (`/schedule` routines) cannot be detected on-box;
  `setup_check.py` probes crontab / Task Scheduler only and accepts an explicit
  `--scheduler-state registered` for routines.
- **Cost metering**: no token/price meter exists headless; cost-per-digest is a
  manual pilot measurement (docs/PILOT.md), reported as such by
  `scripts/value_metrics.py`.
- **Outbound SSRF guards are check-then-connect**: webhook and feed URLs are
  validated (http(s) only, private/loopback/link-local/metadata addresses
  refused, every redirect hop re-checked) by resolving the host *before* the
  request — but the connection then resolves it again, so a DNS entry that
  changes between the two answers can slip past. Closing that needs the
  connection pinned to the validated IP, which the stdlib-only HTTP path does not
  expose. It requires an attacker who controls DNS for a hostname **you** put in
  `config/.env` or `config/sources.yaml`, so the practical exposure is low;
  prefer webhook hosts you control.
- **Duplicate delivery is bounded, not impossible**: an external send cannot be
  rolled back. The agent path claims a channel before sending (`--reserve-mcp`)
  and refuses a second sender, but a claim abandoned mid-send is reclaimable
  after an hour, so a pathologically slow send can still be duplicated
  (CONVENTIONS §10).

## Upgrade policy

- **Versioning**: the version lives in `pyproject.toml` (mirrored in
  `.claude-plugin/plugin.json`) and travels inside the archive. Check yours with
  `python3 scripts/version.py current` (or `doctor.py`).
- **No downgrades**: `update.sh` / `update.ps1` refuse a lower incoming version.
- **Config changes are additive by default**: a new release may add OPTIONAL
  config keys with code defaults; it must not repurpose or remove existing keys
  without a `schema_version` bump (CONVENTIONS §5.5, ADR 0020). Your customized
  `config/` files are never overwritten — new defaults arrive as new files or
  documented opt-ins.
- **Breaking shape changes** ride the `schema_version` stamp + a migrator in
  `scripts/schema.py` (`(kind, N) → N+1`); the update prints what moved. The
  supported legacy sources/topics config move — `(sources, 1) → 2` +
  `(topics, 1) → 2` via `python3 scripts/schema.py migrate-config`, offered by
  the updaters after an update, never auto-applied. This migration exists for
  older installs that still have the Markdown tables.
- **Version line**: public `0.1.0` starts with both updaters included. Future
  updates within this line use the normal updater. It refuses downgrades and
  requires a backup and compatibility review for any separate installation.
- **What an update delivers**: code (`scripts/`, `skills/`, `schedule/`), docs,
  and config *defaults*; plus add-only `brain/` scaffolding (templates, `.base`
  views, front-door READMEs — never `concepts/`). An orphan report lists files
  the new release no longer ships; nothing is auto-deleted.
- **Release gate**: every release passes `make gate` (incl. the hermetic golden
  journey `tests/test_golden_journey.py`); releases described as autonomous /
  production-ready additionally pass the live two-cycle protocol (docs/PILOT.md).

## Getting help

Start with `python3 scripts/doctor.py` (one read-only "is everything OK?" pass),
then [docs/OPERATIONS.md](OPERATIONS.md) for recovery recipes and
[USER_GUIDE.md](../USER_GUIDE.md) §Troubleshooting. This is a zip-distributed,
self-hosted tool — there is no hosted service behind it; the operator (you, or
whoever handed you the archive) is the support line.
