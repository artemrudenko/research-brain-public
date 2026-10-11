# weekly-run — the whole weekly pipeline, in order

**Schedule:** once per week, at or before `digest.cron` (default: Mondays 09:00). One trigger.
**Purpose:** run the weekly pipeline **sequentially**, each step gated on the previous one
finishing, so the digest never reads a `brain/` that synthesis hasn't finished writing.

This is the **recommended** way to run the weekly pipeline — especially as a single Claude Code
`/schedule` cloud agent, or a single external-cron entry. It removes the clock-race that exists
when curate (08:00), synthesis (08:30) and digest (09:00) are registered as four independent
timers: if synthesis runs long, the 09:00 digest can start before `brain/` is consistent.

This file owns **no logic of its own**. Each step is an existing task / skill; this task only
sequences them and stops if a step fails. Do not reimplement their bodies — invoke them.

All paths are relative to the project root (`{{VAULT_ROOT}}`).

---

## Read config first

Read `config/schedule.yaml` once:
- `synthesis.min_sources_per_topic`, `digest.lookback_days`, `curate.min_text_chars` → passed
  through to the steps that own them; nothing to compute here.
- `timezone` → the timezone the cron times are written in (informational here; the scheduler,
  not this task, applies it — see [../docs/scheduling.md](../docs/scheduling.md)).

Read the topics config once — `config/topics.yaml` (each `topics:` entry) — and enumerate every active topic. Step 1
runs collection for **each** of these topics — there is no hardcoded category here.

---

## Step 0 — pre-flight: take the run lock, then refuse to run on an un-set-up vault

**First, take the single run lock** so a manual `run-now` (or a second scheduled
trigger) can't interleave writes to `registry.md` / curated indexes / `brain/` with
this run:

```bash
python3 scripts/run_lock.py acquire --note "weekly-run"
```

- **Exit 0** — the lock is yours. **Capture the `lock-token:` value it prints** — you
  must pass it to `release` at the end of the run (it is how a later, separate process
  proves ownership).
- **Exit 1 (`REFUSED: a run is already in progress`)** — another run holds the lock.
  **Stop here**, do nothing else; this is not a failure. (A genuinely orphaned lock is
  auto-reclaimed after its lease, default 6h.)

From this point on, **whenever the run ends — normal completion, the un-set-up skip
below, or any failed step — release the lock** with the captured token:

```bash
python3 scripts/run_lock.py release --token <lock-token>
```

**Heartbeat the lease on a long run.** The lock's lease is a fixed window (default
6h); a slow agentic run could exceed it and be reclaimed mid-flight by the next
trigger, breaking serialization. So **after each major step below** (collect →
sanitize → curate → synthesis → extract lessons/playbooks → digest), refresh the lease with the
captured token:

```bash
python3 scripts/run_lock.py renew --token <lock-token>
```

This keeps an actively-progressing run's lock alive indefinitely while a genuinely
crashed run still frees its lock once the lease lapses.

**Then** confirm the system is actually configured. Run:

```bash
python3 scripts/brain_status.py sources
```

If it prints **`No monitored sources configured.`** (the shipped template still has only the
`EXAMPLE` placeholder rows), **stop here** — do **not** collect, synthesize, or deliver. This is
**not a failure**: it just means setup is unfinished. **Release the run lock** (above), record a
one-line note that the run was skipped pending setup, and exit cleanly.

This guard mirrors the one in the on-demand `run-now` / `digest-build` skills, so a `/schedule`
routine registered **before** real sources are added can never collect the placeholder
`example.com` rows and deliver a baffling empty digest to a non-technical user.

→ gate: at least one real monitored source exists. Otherwise the run ends here, cleanly.

---

## Run order (each step gated on the previous completing)

Run the steps **in this order**. After each step, confirm it finished successfully before
starting the next. If a step **fails**, stop the run, record the failure, and do **not** start
the following steps (a half-built `brain/` must never be digested). A step that legitimately has
nothing to do is **not** a failure — continue.

> **Role delegation (Claude Code / Cowork only).** Each agentic step below has a least-privilege
> role subagent in [`.claude/agents/`](../.claude/agents/) pinned to a model tier + tool
> allowlist. On Claude Code / Cowork, **delegate the step to its role** so the model tier and the
> capability boundary bind: collect → `collector`, curate → `curator`, synthesis →
> `synthesizer` (which fans out
> `critic` for its audit pass), digest build → `digest-maker`, deliver → `deliverer`. Only
> `deliverer` may carry delivery **MCP** servers, so a synthesis/critique step can't send via the
> MCP transports; the headless transports stay reachable through `Bash`, so that boundary is prompt
> instruction + review, not a technical impossibility (see [`.claude/agents/README.md`](../.claude/agents/README.md)).
> On **Codex or any headless runtime without subagents, run the step inline** — the steps are
> identical either way. The run lock and cwd are inherited, so delegation never affects
> serialization. (See [`.claude/agents/README.md`](../.claude/agents/README.md).)

### 1. collect (always — the weekly freshness guarantee)

*(Claude Code / Cowork: delegate to the `collector` subagent.)*

**Always run a collect pass at the start of the weekly run.** Enumerate the active topics from
the active topics config (the topic list read above) and run [`collect-topic.md`](collect-topic.md)
**once per topic**, setting `{CATEGORY}` to that topic's name — exactly the way Step 3
(`weekly-synthesis`) iterates per-topic. Do **not** hardcode a single `{CATEGORY}`; the topic
list is the source of truth, so adding a topic to the config automatically gets it
collected here.

Collecting every weekly run is safe: collection dedups against `pipeline/registry.md` and curate
is idempotent, so over-collecting never produces duplicates or double-processing. This pass is the
**freshness guarantee** — it ensures the digest is built on up-to-date material even if no other
collection ran this week.

The standalone `collect` cron (`config/schedule.yaml` → `collect.cron`, e.g. every 3 days) handles
**more-frequent intra-week** collection between weekly runs; it is independent of this step. There
is no "due today" state to compute — drop any such conditional (there is no last-run marker, and
none is needed). This step simply always runs.

→ gate: collection finished for every active topic.

### 1b. collect monitored authors (the roster — CONVENTIONS §2.4)

*(Claude Code / Cowork: delegate to the `collector` subagent — same role as Step 1.)*

Step 1's agentic per-topic pass reads `config/sources.yaml` only; it does **not** see the
followed-authors roster (`config/authors.yaml`). Collect the roster now, as a companion pass,
so a followed author's new writing lands in `pipeline/1-incoming/<topic>/` alongside the
topic's ordinary collection — then flows through sanitize → curate → synthesis unchanged:

```bash
python3 scripts/collect.py --authors-only --lock-held
```

- `--authors-only` collects **only** the roster's feeds (an `rss` author's own feed taken
  whole; a `publication-filter` author's paused publication feed with the per-item identity
  predicate applied, so another writer's article is never credited to them) — never the
  topic's ordinary sources, which Step 1 already handled.
- `--lock-held` tells it the orchestrator already owns the single run lock (Step 0): it
  collects under that lock and does **not** acquire or release it.
- **Absent/empty `authors.yaml` → a clean no-op** (nobody is followed, the default). This is
  RSS-only by design: `rss` and `publication-filter` *are* feeds; `scholarly` has
  **no collection path yet** (headless *or* agent-mode). Legacy `search` rows are
  also withheld because that variant was retired.
- Withheld and unresolvable roster entries alike are **printed** (`WARN: author monitoring: …`;
  a withheld `scholarly` author says `… not built yet`; a legacy `search` row says
  `… retired`), never silently skipped — an
  author who collects nothing otherwise reads as "published nothing lately".

→ gate: the roster pass finished (collecting zero articles — no followed authors, or none
published — is a success, not a failure). Refresh the lock lease (Step 0) and continue.

### 1.5 drain the capture inbox (read-it-later articles)

If the user has captured one-off articles via **`source-capture`** (`/save`), they wait in
`pipeline/1-incoming/_inbox/`. Drain them now so they are routed to their topics **before**
curate, and get curated + synthesized alongside the freshly collected material:

```bash
python3 scripts/inbox.py count   # queued: N
```

If `N > 0`, run the **PROCESS** path of **`source-capture`** (sanitize `_inbox` → fan-out
one reader subagent per article → `inbox.py route <article> <topic>`). The run lock is
already held by this orchestrator, so `source-capture` skips re-acquiring it here. If the
queue is empty, this step is a no-op — continue.

→ gate: the inbox is drained — captured articles now live under their real topics.

### 2. sanitize incoming (anti-injection gate for every LLM-facing step)

Everything downstream that puts article text in front of a model — curate's keep/drop
judgment (next) and `research-build` internal-corpus synthesis (Step 3) — must read
sanitized text, because the RSS-collected `pipeline/1-incoming/` articles are untrusted
external content. Write a sanitized companion for each, stripping
indirect-prompt-injection patterns (S1–S9), BEFORE any step reads bodies:

```bash
python3 scripts/sanitize_incoming.py sanitize
```

Cheap and idempotent: an unchanged article whose companion is current is skipped
byte-for-byte (no churn, no freshness invalidation).

→ gate: every incoming article now has an up-to-date `sanitized/{file}.md` companion.
Curate (Step 2.5) and synthesis (Step 3) read the **sanitized** companions, never the raw
originals. The gate is verified **per topic** at synthesis: a topic whose companions fail
(missing / drifted / corrupted) is **skipped and recorded**, while the other topics
proceed — one bad article no longer blocks the whole run. This is the real code
enforcement of CONVENTIONS §12 (previously prose-only).

### 2.5 curate

*(Claude Code / Cowork: delegate to the `curator` subagent — `sonnet` tier, no web, no
delivery MCP; it judges only the sanitized companions.)*

Run [`weekly-curate.md`](weekly-curate.md) — the `pipeline-curate` skill promotes
`pipeline/1-incoming/` → `pipeline/2-curated/{topic}/index.md`, judging each candidate's
**sanitized companion** (Step 2 wrote them). Idempotent; a no-op if there is
nothing new.

→ gate: curate finished — `pipeline/2-curated/` reflects the latest incoming.

### 3. synthesis

*(Claude Code / Cowork: delegate to the `synthesizer` subagent — `opus` tier, no delivery MCP; it fans out `critic` for the audit pass.)*

`weekly-synthesis.md` verifies the sanitization gate **per topic** (`sanitize_incoming.py gate
--topic {topic}`) right before synthesizing each one — a topic whose gate fails (missing /
drifted / corrupted companion) is **skipped and recorded**, while the other topics proceed. A
gate failure in one topic no longer blocks the whole run. (Step 2 above already wrote the
companions; the gate also catches a corrupted companion via its `sanitized_hash` integrity check.)

Then run [`weekly-synthesis.md`](weekly-synthesis.md) — for each topic with
`≥ synthesis.min_sources_per_topic` curated sources and no fresh synthesis, it runs
`research-build` (internal-corpus, reading the **sanitized companions**) → `research-audit`
(soft) → `wiki-ingest` (auto) into `brain/concepts/`, and writes
`pipeline/3-synthesis/synthesis-run_YYYY-MM-DD.md`. It also enforces the tagging/citation
contract at write time (`validate_brain.py --strict --paths` over each topic's freshly-written
concepts) — a topic whose concepts miss `sources:` or use an off-vocabulary tag is **failed,
not stamped, and re-tried next run** — and emits a `health.py` `hygiene/degraded` event for any
gate-skipped topic, so a silently-failing topic surfaces in `/status`.

→ gate: synthesis finished — **all** writes into `brain/` are complete and the run log exists.
**This gate is the whole point of weekly-run:** the next step must not start until it is met.

### 3.5 extract lessons/playbooks

Run the deterministic vault-note extractor:

```bash
python3 scripts/extract_vault_notes.py
```

It scans existing `brain/concepts/` notes for explicit `## Lessons` / `## Key lessons`
sections and `## Playbook: ...` sections, then writes only missing notes into
`brain/lessons/` and `brain/playbooks/`. It is additive and idempotent: existing lesson/playbook
files are skipped, no concept is rewritten, and nothing in `brain/` is deleted.

This step runs after synthesis because weekly synthesis is what refreshes concept notes, and before
brain hygiene so the generated notes are immediately checked for orphan links. The digest then sees
them through its existing vault-front-door scan.

→ gate: extractor completed (writing zero notes is a success).

### 4. brain hygiene

First run `python3 scripts/validate_brain.py` — the single brain-hygiene pass (CONVENTIONS §13).
It scans `brain/concepts/` for orphans, broken `[[concepts/...]]` links, concepts missing
`sources:`, uncited `## Key facts` bullets, tag normalization/synonym/pending/one-off issues,
and stale (`last_verified + ttl_days`) notes. It is **advisory** — it never edits or deletes
notes — and always exits 0 (no `--strict` here), so a finding never stops the run. It writes
`pipeline/3-synthesis/brain-health_YYYY-MM-DD.md`, whose machine-matched headline
(`Health: N concepts · X orphans · Y broken links · Z missing-sources · U uncited-facts · W stale`)
the digest surfaces so the reader sees vault health alongside the week's content (the report
also carries a human `brain health: …, …` summary line — the digest keys on the `Health:` one).

Then run `python3 scripts/promote_tags.py` — the **applier** for the one finding validate_brain
can only *recommend*. validate_brain merely warns when a `pending:` tag has recurred across enough
concepts; this script actually promotes it into `config/tags.yaml` (a `domain/topic` pending tag is
added under its domain; a bare pending tag becomes a new domain key), and drops it from `pending:`,
so the controlled vocabulary grows on the weekly cycle instead of accumulating advisory warnings.
It is idempotent and **does not fail when it promotes nothing** (no pending tag reached the
threshold is the normal case), so it never stops the run — keep the gating semantics intact. See
the script for the exact threshold and rules; do not restate them here.

→ gate: hygiene scan finished, `pipeline/3-synthesis/brain-health_YYYY-MM-DD.md` exists, and the
promotion pass completed (promoting zero tags is a success, not a failure).

### 5. digest (build)

*(Claude Code / Cowork: delegate to the `digest-maker` subagent — `haiku` tier, build only, no send.)*

Run [`weekly-digest.md`](weekly-digest.md) **build steps only** (Steps 1–5: scan
`pipeline/1-incoming/` + `brain/concepts/` over `digest.lookback_days`, add the "Synthesis this
week" line from the run log written in Step 3, save `pipeline/3-synthesis/digest_YYYY-MM-DD.md`).
Do **not** let it hand off to delivery yet — that is the next step, run explicitly so the order
stays visible.

**Build with the synthesis-log code barrier on** — pass `--require-synthesis-log` to the builder
so it *refuses* to build unless today's `pipeline/3-synthesis/synthesis-run_YYYY-MM-DD.md` exists
(exit 3, writes nothing):

```bash
python3 scripts/build_digest.py --require-synthesis-log --report   # plus the usual args
```

(`--report` also writes the browser-grade `digest_YYYY-MM-DD.report.html` next to the
markdown and links it from the digest's footer; the delivery step attaches it on
Telegram MCP. The trends section is embedded by default already.)

This makes the synthesis→digest gate a **code** guarantee, not just this routine's step ordering:
if Step 3 never finished (a crash, a miscount, an empty/failed synthesis), the digest cannot be
built from a half-written `brain/`. The standalone headless cron path leaves the flag **off** by
default, so it is unaffected — see `docs/scheduling.md`.

→ gate: `pipeline/3-synthesis/digest_YYYY-MM-DD.md` exists and reflects this run's `brain/`.

### 5.5 pre-send review (opt-in gate)

*(Claude Code / Cowork: delegate to the `critic` subagent — no delivery MCP; it reviews, and the send step is left to `deliverer`.)*

**Only when `delivery.pre_send_review: true` in `config/channels.yaml`** (default off — skip this
step entirely otherwise). Invoke the **`digest-review`** skill (`skills/digest-review/SKILL.md`) on
the Step-5 digest: it runs the deterministic backbone (`scripts/presend_review.py` — injection-leak
scan + link resolution) and, in the agent runtime, an adversarial grounding pass (claims vs. cited
sources, trust markers, no injection leaked into the delivered text). It is **advisory by design** —
it surfaces findings and, unattended, still lets the digest go (recording the findings) rather than
silently failing to deliver; a strict run halts on a blocking-candidate finding. Headless with no
agent runtime: the deterministic `presend_review.py` verdict IS the gate.

→ gate: pre-send review complete (PASS, or findings surfaced/decided) — proceed to deliver.

### 6. deliver

*(Claude Code / Cowork: delegate to the `deliverer` subagent — the only role sanctioned to send, and the only one that may carry delivery MCP servers.)*

Invoke the **`digest-deliver`** skill (`skills/digest-deliver/SKILL.md`) on the digest file from
Step 5. It reads `config/channels.yaml` and sends over each enabled channel (email / Telegram /
Rocket.Chat). This is `weekly-digest.md`'s own Step 6, run here explicitly to keep the gated
sequence in one place.

→ done: the digest built from a fully-synthesized `brain/` has been delivered.

### 7. record the run (observability)

Append one health event marking a completed weekly run, so the system has a
traceable heartbeat (`brain-ask` health and the health report use it to detect a
run that silently stopped happening):

```bash
python3 scripts/health.py record --kind run --status ok --note "weekly-run completed"
```

If the run aborted at Step 0 (no sources configured) or a step failed, record it
with `--status skipped` / `--status failed` and a short `--note` instead. This is
best-effort and must never itself fail the run.

→ done: the run is recorded in `pipeline/.health/events.jsonl`.

### 7.5 push a health alert if the run degraded (opt-in, best-effort)

Now that the run is recorded, roll up the health verdict and — **only if the operator
has opted in** — PUSH a one-line alert when health is DEGRADED (a failed run, a dead
feed, a gate-skipped topic, an overdue run), so they find out without checking `/status`:

```bash
python3 scripts/health_alert.py
```

This is **opt-in (default OFF)**: it sends nothing unless `delivery.alerts.enabled: true`
is set in `config/channels.yaml` (which existing channel to alert through is
`delivery.alerts.channel`). It alerts **only** on DEGRADED — OK / UNKNOWN / UNCONFIGURED
are no-ops. It is **best-effort** and **always exits 0**: a missing opt-in, a healthy
verdict, or a send failure are all reported on stdout but **never fail the run**. See
[../docs/scheduling.md](../docs/scheduling.md) → "Health alerts (opt-in)".

→ done: a DEGRADED, opted-in run has pinged the operator; otherwise this was a no-op.

### 7.7 rotate old pipeline artifacts (housekeeping, best-effort)

Keep the working set bounded — archive dated `3-synthesis/` artifacts older than 90
days into `pipeline/0-archive/3-synthesis/` (moved, never deleted) and compact the
health event log to the same window:

```bash
python3 scripts/rotate_pipeline.py
```

It never touches delivery receipts (`.delivered/`), the per-topic dirs
(`digest-lead.md`, `.synthesis-meta.json`), or undated files. Best-effort: a rotation
failure must never fail the run — note it and continue.

→ done: the pipeline working set stays bounded as months accumulate.

### 8. release the run lock

Always last — release the lock taken in Step 0, using the token you captured:

```bash
python3 scripts/run_lock.py release --token <lock-token>
```

This must run on **every** exit path (success, the Step 0 un-set-up skip, or a failed
step), so a finished run never leaves the lock held. (Even if it's missed, the lease
auto-expires after ~6h, but release promptly so the next run isn't needlessly blocked.)

→ done: the lock is free for the next run.

---

## Success criteria

- The steps ran **in order**: collect (always, per active topic) → collect-authors (roster) → sanitize-incoming → curate → synthesis → extract-lessons/playbooks → brain-hygiene → digest-build → deliver.
- Synthesis ran only after the sanitization gate passed; it read the `sanitized/` companions, never raw incoming articles.
- Each step started only **after** the previous finished; a failed step **stopped** the run
  before the digest was built or delivered.
- The delivered digest reflects a `brain/` that synthesis had **finished** writing — no clock-race
  between synthesis and digest.
- A `pipeline/3-synthesis/synthesis-run_YYYY-MM-DD.md` and a
  `pipeline/3-synthesis/digest_YYYY-MM-DD.md` both exist for this run.

## Notes

- **Why this exists.** The individual cron times (`curate.cron` 08:00, `synthesis.cron` 08:30,
  `digest.cron` 09:00) are wall-clock *timers*, not *dependencies*. weekly-run replaces the timing
  assumption with an explicit gate, so a long synthesis run can never be overtaken by the digest.
- **One trigger.** Register **one** routine / cron entry for this task (at `digest.cron`, the end
  of the window), not four. The component cron times remain in `config/schedule.yaml` for users
  who deliberately prefer separate headless jobs — see [../docs/scheduling.md](../docs/scheduling.md).
- **On demand.** "Run the weekly pipeline now" runs this same task immediately, in the same order.
