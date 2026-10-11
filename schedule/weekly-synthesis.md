# weekly-synthesis — automatic synthesis driver

**Schedule:** from `config/schedule.yaml` → `synthesis.cron` (default: Mondays 08:30 — **after** `weekly-curate`)
**Purpose:** for every topic that has accumulated enough curated sources, automatically build a
synthesis document and ingest its concepts into `brain/` — no human gate.

All paths are relative to the project root (`{{VAULT_ROOT}}`).

This task closes the core loop: `weekly-curate` promotes incoming articles into
`pipeline/2-curated/`, and this task turns curated material into `brain/concepts/`
automatically. It runs unattended on `synthesis.cron`, right after curate.

---

## Task

For each topic whose `pipeline/2-curated/{topic}/index.md` lists at least
`synthesis.min_sources_per_topic` sources, run `research-build` **with `PROFILE=internal-corpus`**
over that curated corpus to produce a synthesis document, then run `research-build`'s downstream
`research-audit` in **soft mode** (`SOFT_MODE=true`), then run `wiki-ingest` in
**unattended/auto mode** to write the resulting concepts into `brain/concepts/`. No per-write
approval gate, no upstream `research-frame` brief, no `research-grep` inventory, no `sources/`
tier-registry, no `>30% 🔴` block — this is the automatic synthesis driver and runs unattended
per `docs/CONVENTIONS.md` §10 (internal-corpus synthesis profile).

---

## Steps

### 1. Read config

Read `config/schedule.yaml`:
- `synthesis.min_sources_per_topic` → `{MIN_SOURCES}` (default 3) — the curated-source
  threshold a topic must clear to be synthesized this run.

### 2. Select eligible topics

Eligibility is decided by a **content-hash trigger** (not a clock), so new curated material on
an existing topic is picked up immediately rather than waiting out a staleness window:

```bash
python3 scripts/synthesis_freshness.py list --min-sources {MIN_SOURCES}
```

It prints the topics that need (re)synthesis this run — each is **NEW** (no synthesis yet) or
**STALE** (its `pipeline/2-curated/{topic}/index.md` changed since the last synthesis, detected
by a hash recorded in the sidecar `pipeline/3-synthesis/{topic}/.synthesis-meta.json`) **and**
clears the `{MIN_SOURCES}` curated-source threshold. Topics that are **FRESH** (index unchanged)
or **below threshold** are skipped this run (below-threshold ones keep accumulating until they
cross it). Synthesize exactly the topics this command lists.

### 2.5 Anti-injection gate (per-topic, mandatory before synthesizing each topic)

Incoming articles are untrusted external text. Gate **only the topic(s) you are about to
synthesize** (the ones Step 2 listed) — scope the check with `--topic`, so a stale/missing/corrupt
companion in an UNRELATED topic never blocks this run:

```bash
python3 scripts/sanitize_incoming.py gate --topic {topic}   # repeat --topic per eligible topic
```

If it **exits 1** for a topic, that topic's corpus is not safe — **skip that topic** (and record
the reason), but continue with the others. **Also emit a health event** so a topic that is
silently gate-skipped week after week surfaces in `/status` instead of vanishing:

```bash
python3 scripts/health.py record --kind hygiene --status degraded --note "{topic}"
```

The gate fails on a missing companion, a `source_hash`
drift (the article changed since sanitization), OR a `sanitized_hash` mismatch (the companion body
was corrupted/tampered — integrity check). (The orchestrator `weekly-run.md` writes the companions
in its Step 2; if you run this skill standalone, run `python3 scripts/sanitize_incoming.py sanitize
--topic {topic}` first.) Synthesis below reads the **sanitized companions**
(`pipeline/1-incoming/{topic}/sanitized/{file}.md`), never the raw originals — this is the code
enforcement of the CONVENTIONS §12 anti-injection guarantee on the unattended path.

> **Synthesis must run AFTER curate's reject-purge.** `pipeline-curate` Step 6.5 (`python3
> scripts/purge_rejected.py`) removes rejected articles and their companions from `1-incoming/`,
> so this step never ingests rejected content. The orchestrator `weekly-run.md` runs curate before
> synthesis; if you run this skill standalone on a vault that was just curated, run
> `python3 scripts/purge_rejected.py` first as a safety net (idempotent; a no-op when nothing was
> rejected) before sanitizing/synthesizing.

### 3. Synthesize each eligible topic — `research-build PROFILE=internal-corpus` (auto)

For each eligible topic, delegate to the **`research-build`** skill **with
`PROFILE=internal-corpus`**, passing the curated material in `pipeline/2-curated/{topic}/` (and
the **sanitized** `pipeline/1-incoming/{topic}/sanitized/` companions) as the corpus. In this profile `research-build`:

- does NOT require a `research-frame` brief or a `research-grep` inventory (the curated `index.md`
  IS the inventory — absence is a soft proceed, never a halt),
- synthesizes from the local corpus (no web-source minimum), writing a plain-Markdown research
  document into `pipeline/3-synthesis/{topic}/`,
- may run a few opt-in WebSearch queries to refresh a fast-moving topic (still via `source-archive`),
- skips the manual-only Anti-AI Audit / Critique passes.

Do not reimplement its logic here — invoke it.

**Context-bounded reading (matters most on the unattended path).** A topic with many curated
articles is exactly where reading them all full-text into one context window exhausts it.
`research-build`'s **reader-subagent fan-out** handles this: at **≥5 sanitized sources** it
dispatches one reader subagent per article (or per cluster when >~12), each returning a compact
**extract** while the **main agent never loads the full bodies** — synthesis runs on the bounded
extract set. This is built into `research-build` (it reads the same sanitized companions), so just
invoking it gets the behaviour; do not flatten the corpus into the main context yourself. Contract:
[`../skills/research-build/references/reader-contract.md`](../skills/research-build/references/reader-contract.md).

Running unattended: take `research-build`'s `internal-corpus` defaults; do not pause for
interactive depth/angle choices.

**Downstream extraction hints are part of the synthesis contract.** When the curated corpus
contains reusable atomic facts or repeatable operating procedures, `research-build` should render a
`## Downstream extraction hints` section with candidate lessons and candidate playbooks. These are
not standalone vault writes; they are hints for `wiki-ingest`, which turns them into explicit
`## Lessons` / `## Playbook: ...` sections in concept notes. The later `weekly-run` extractor then
creates the actual `brain/lessons/` and `brain/playbooks/` notes.

**Evidence grading — soft mode.** When `research-build` hands off to `research-audit`, run it with
**`SOFT_MODE=true`**: tier-grading is skipped (no `sources/` registry required), the `>30% 🔴`
threshold gate is **disabled** (a missing registry is NOT treated as "everything T3"), but the
citation/quote-hallucination guard and recency annotation are retained. The audit emits a
confidence note and `gate_status: soft-pass` — never a hard block — so the unattended loop always
reaches the ingest step (and `wiki-ingest` accepts `soft-pass` as a valid closure signal). There
is no "audit hard block → skip ingest" branch on the auto path (the threshold gate cannot fire).

The **citation guard still runs**, but on this operator-less path it cannot stop on an
AskUserQuestion: any unresolved `[CITATION-UNVERIFIED: …]` PLACEHOLDER is **auto-downgraded to its
generic, explicitly-unverified phrasing** and recorded in the confidence note — the mode-independent
hard rule "a raw PLACEHOLDER never ships" is *satisfied* by the downgrade, not waived (see
[`research-audit/references/citation-guard.md`](../skills/research-audit/references/citation-guard.md)
§ Threshold gate). Only a true content failure (e.g. the synthesis doc could not be written) skips a
topic, and that is recorded in the run log with its reason.

### 4. Ingest into `brain/` — `wiki-ingest` (auto, no human gate)

**First, back up the concepts this run is about to touch** so a corrupting re-write can be rolled
back (NOT just deleted). Before invoking `wiki-ingest`, copy the existing `brain/concepts/` notes
this topic will update into a staging dir — that snapshot is the last-known-good to restore on a
gate failure.

> **The staging dir MUST be emptied first.** It is persistent (gitignored), so a leftover backup
> from a *previous* run would otherwise be used to "restore" a **stale** version of a same-named
> concept on this run's failure — silently reverting good edits. Clear it, then copy, and do **not**
> swallow copy errors (`|| true`): a backup that didn't land means rollback can't protect that note,
> so the run must see the failure rather than proceed with a false safety net.

```bash
# 1) Reset staging so ONLY this run's last-known-good snapshots are present.
rm -rf pipeline/3-synthesis/.staging
mkdir -p pipeline/3-synthesis/.staging
# 2) Copy the pre-write version of each concept this run will write/update. Only the
#    ones that already exist need backing up; `cp` errors must NOT be hidden — if a
#    backup fails, stop and investigate rather than running without a rollback net.
for f in brain/concepts/<will-write-this-run>.md ...; do
  [ -e "$f" ] && cp "$f" pipeline/3-synthesis/.staging/
done
```

After the strict gate below passes for the topic, **empty the staging dir again** so a later run can
never see this run's backups as its own "last-known-good".

After a topic's synthesis document is written, invoke the **`wiki-ingest`** skill on it in
**unattended/auto mode**: apply its proposed concept writes to `brain/concepts/` directly,
without the usual per-write `AskUserQuestion` approval gate. Source links and provenance tags
are still mandatory (that is `wiki-ingest`'s own contract). This is what makes `brain/`
auto-populate. Do not reimplement `wiki-ingest` — invoke it.

**Lessons / playbook pass — an explicit per-concept decision, not a leftover.** For EVERY
concept written or updated this topic, decide and act:
- Does the material contain an **atomic, source-backed fact useful outside this concept**
  (a number, a threshold, a named failure mode, an anti-pattern)? → author a `## Lessons`
  section (1–5 bullets, each atomic and already cited above).
- Does it contain a **repeatable procedure, checklist, review loop, or decision rule**
  (e.g. a "3-strikes" policy, a rollout sequence, an evaluation recipe)? → author a
  `## Playbook: <method name>` section (trigger sentence + numbered steps).
- When the synthesis document carries `## Downstream extraction hints`, promote them into
  these exact sections. When nothing qualifies, write **neither** — an empty layer is honest
  (plain news items usually do not qualify; how-to-bearing material usually does).

The exact shapes live in `brain/concept-template.md`. Do not write `brain/lessons/` or
`brain/playbooks/` here; `weekly-run` runs `scripts/extract_vault_notes.py` after synthesis so
those notes are generated in one deterministic additive pass. Report the decision's outcome in
the run log's `## Totals` (below) so an always-zero layer is **visible**, never a silent default.

**Then enforce the tagging/citation contract at write time** — `wiki-ingest`'s "sources mandatory,
tags from `config/tags.yaml`" rule is an instruction to the model; turn it into a hard gate on the
concepts this topic just wrote, so a fabricated/missing source or an off-vocabulary tag can't land
permanently in `brain/` on the unattended path:

```bash
# pass ONLY the concept files this topic wrote this run. --quarantine sets a failing
# note aside; --restore-from rolls a previously-valid concept BACK to its pre-write
# version (so a corrupting UPDATE never deletes existing knowledge / breaks links).
python3 scripts/validate_brain.py --strict \
  --quarantine pipeline/3-synthesis/.quarantine \
  --restore-from pipeline/3-synthesis/.staging \
  --paths brain/concepts/<written-this-run>.md ...
```

It exits **1** if any in-scope concept has a missing/empty `sources:` or an off-vocabulary live tag
(a `pending:` tag is allowed — that's the sanctioned new-tag path); exit **0** when clean. With
`--quarantine`, the failing write is **moved out of `brain/concepts/`** into
`pipeline/3-synthesis/.quarantine/`; with `--restore-from`, a concept that was **valid before this
run** is then **rolled back to its staged last-known-good** version (a brand-new, never-valid
concept with no backup is simply evicted). Either way the vault stays contract-clean —
`build_digest` reads `brain/concepts/`, so a half-written, unsourced concept can no longer leak into
the digest, and a valid prior version is never lost. On a non-zero exit, treat the topic as
**failed**:
record it in the run log, emit `python3 scripts/health.py record --kind hygiene --status degraded
--note "{topic}"`, and **skip the freshness stamp below** so the topic stays eligible and is
re-synthesized next run. (Default `validate_brain.py` without `--strict` stays advisory and is run separately in
weekly-run Step 4 — this scoped `--strict --paths` call is the write-time gate, not the vault-wide
advisory pass.)

**Then stamp the topic's freshness sidecar** (only for a topic that synthesized, ingested **and
passed the strict gate** above) so it reads FRESH until the curated corpus changes
again (this is what closes the content-hash trigger from Step 2):

```bash
python3 scripts/synthesis_freshness.py stamp {topic}
```

Stamp only **after** a topic's synthesis + ingest succeeded — if a topic was skipped on a content
failure, do **not** stamp it, so it stays eligible next run.

**Then write the topic's one-line digest lead** — do this for **every** topic synthesized this run,
one sidecar per topic: a plain-language "what happened in this topic this week" sentence (**12–22
words, one line**), distilled from the synthesis doc / curated takeaways. The deterministic digest
builder reads it and renders it under the topic's `🏷 {topic}` badge — every topic with a current
sidecar gets its lead in the weekly digest, not just the busiest; the daily inflow digest renders
no leads (ADR 0016). This is the prose the headless builder can't generate on its own:

```bash
# one line, no heading / no frontmatter — first non-empty line is used
printf '%s\n' "Agents gained runtime governance and PEFT moved past LoRA; export-control pressure intensified." \
  > pipeline/3-synthesis/{topic}/digest-lead.md
```

Write it only for a topic you actually synthesized this run. A skipped topic's lead from a prior run
is **auto-suppressed** by the builder — it renders a lead only when the topic's synthesis still matches
the current corpus (the same content-hash freshness check from Step 2), so a stale lead can't appear
beside fresh sources even if its sidecar lingers. Keep it factual and specific to the week's material —
no hype, no "this week we explored…" filler.

### 5. Record the run

Save a run log to `pipeline/3-synthesis/synthesis-run_YYYY-MM-DD.md`. **Another part of the system
reads this file** (the deterministic digest builder `scripts/build_digest.py` pulls a "Synthesis
this week" section and the value-evidence lines `Knowledge base changes` / `Reused existing
knowledge` from the latest `synthesis-run_*.md`), so the structure below is a contract — keep the
headings. It MUST record, per run: each topic **synthesized**, each topic **skipped + the reason**,
the number of **concepts written** into `brain/`, the number of concepts **created** and
**updated**, the number of **existing concepts reused**, and the **backlog count** (topics still
below threshold, accumulating).

Definitions for the machine-readable `## Totals` fields:
- `concepts created` means new concept files written to `brain/concepts/`.
- `concepts updated` means existing concept files changed by wiki-ingest.
- `existing concepts reused` means existing concept notes read or referenced during synthesis
  before deciding what to write.
- The digest renders `Knowledge base changes` from created/updated counts and
  `Reused existing knowledge` only from the explicit reused count.
- Raw source count is not reuse; raw source count is not reuse evidence and must not be reported
  as `existing concepts reused`.

```markdown
# Synthesis run — [DATE]

Synthesized <n> topic(s), wrote <total> concept(s) to brain/; <n> skipped, backlog <n>. (profile: internal-corpus, audit: soft)

## Synthesized this run
| Topic | Curated sources | Synthesis file | Concepts written to brain/ | Audit |
|-------|-----------------|----------------|----------------------------|-------|
| ...   | N               | [link]         | M (concept slugs)          | soft-pass (note) |

## Skipped this run
| Topic | Reason |
|-------|--------|
| ...   | below threshold (K/{MIN_SOURCES}) / synthesis-write failed / ingest issue |

## Backlog (below threshold, accumulating)
- topic: K sources (need {MIN_SOURCES})
- backlog_count: <number of topics still below threshold>

## Totals
- topics synthesized: <n>
- concepts written: <total M across topics>
- concepts created: <n>
- concepts updated: <n>
- existing concepts reused: <n>
- lessons sections written: <n>
- playbook sections written: <n>
- topics skipped: <n>
- backlog count: <n>

## Notes
[any topic skipped with reason; any soft-audit confidence note worth surfacing]
```

The `backlog_count` / `Totals` block makes the run machine-readable for the digest builder and for
trend tracking.

---

## Success criteria

- Every topic with `≥ {MIN_SOURCES}` curated sources and no fresh synthesis was synthesized via
  `research-build PROFILE=internal-corpus` and ingested via `wiki-ingest` (auto mode) this run —
  with no upstream brief / inventory / `sources/` registry required.
- `research-audit` ran in soft mode (no `>30%` block); the loop reached ingest for every
  synthesized topic.
- Concepts were written into `brain/concepts/` without a human approval gate.
- A run log exists at `pipeline/3-synthesis/synthesis-run_YYYY-MM-DD.md` recording, per run:
  synthesized topics, skipped topics + reason, concepts written, and the backlog count.
- Topics below the threshold are listed as skipped/backlog (not silently ignored).

## Notes

- This task runs **after** `weekly-curate` on `synthesis.cron`; it relies on
  `pipeline/2-curated/{topic}/index.md` having been refreshed by the curate step.
- It does process the pipeline forward: curated material → `pipeline/3-synthesis/` →
  `brain/concepts/`. This is intentional and automatic; there is no on-demand-only gate.
- `wiki-ingest` runs unattended here. If you want a human in the loop for a particular run,
  invoke `wiki-ingest` manually instead of relying on this scheduled task.
