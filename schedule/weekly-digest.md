# weekly-digest

**Schedule:** from `config/schedule.yaml` → `digest.cron` (default: Mondays 09:00)
**Purpose:** build a weekly digest of what's new in the knowledge base, then hand it off to the `digest-deliver` skill for sending.

---

## Task

Build a weekly digest of recently collected sources and recently updated concepts, save it as a Markdown file, then hand off to the `digest-deliver` skill to send it over the configured channels.

All paths are relative to the project root (`{{VAULT_ROOT}}`).

---

## Steps

### 1. Read the lookback window

Read `config/schedule.yaml` → `digest.lookback_days` → `{LOOKBACK}` (default 7). "Recent" below means "changed within the last `{LOOKBACK}` days".

### 2. Scan `pipeline/1-incoming/`

Walk every topic subfolder under `pipeline/1-incoming/`.
- List recent files — those whose frontmatter `collected:` date (**not** file mtime)
  falls within `{LOOKBACK}` days — grouped by frontmatter `category` (topic).
  Skip the `sanitized/` companion subfolders when listing (they mirror the raw
  articles, not separate sources).
- For each recent file, read the frontmatter `title` and the first `## Key takeaways`
  bullet (fallback: first non-empty body line) so the digest can summarize it.
  **Read these from the sanitized companion** (`{topic}/sanitized/{file}.md`) when one
  exists **and is current** (its `source_hash` still matches the raw article) — the
  digest ships this text to the reader, and the companion is the S1–S9-stripped view.
  Fall back to the raw file when there is no companion or the companion is stale
  (matches the headless `scan_incoming`).
- Also read the optional frontmatter `tier:` field (high / medium / low — source
  credibility, CONVENTIONS §12). Only `high` renders a marker — a trailing ` ⭐` after
  the title (matching the deterministic builder's `_tier_marker`); `medium` / `low` /
  absent render **no** marker (graceful).
- Also note any files that have sat in `1-incoming/` for more than 14 days whose
  `pipeline/registry.md` `status` is still blank (not `processed`/`rejected`) — these
  are candidates for attention.

### 3. Scan `brain/concepts/`

List concept notes in `brain/concepts/` whose frontmatter `last_updated` (**not** file
mtime) falls within `{LOOKBACK}` days — these are the recently added or revised concepts.
**Exclude any note tagged or marked `SEED`/`EXAMPLE`** (per CONVENTIONS §5.1) — those ship
with the vault to demonstrate the format and are not real knowledge.

For each in-window concept, read the **first line of its `## What it is` (or `## Definition`)
section** — that is the concept's real one-line definition. Use it verbatim; do **not** invent
a "what changed" changelog. The digest should tell the reader what the concept *is*, not guess
at the diff.

Also read the concept's `sources:` block: if any source carries `tier: high`, append a
trailing ` ⭐` after the concept name (the strongest tier wins; `medium`/`low` render no
marker) — so the reader can weigh the evidence behind it. No `tier` on any source → no marker.

**Publisher-diversity line (CONVENTIONS §16).** Derive the publisher-group count from
`sources:` with `scripts/corroborate.py`. Render it indented under the concept:
- **at least 2** → `🔵 N retained publisher domains — check the claim`;
- **exactly 1** → `🟡 One retained publisher domain — check the claim`;
- **no usable source URLs** → render nothing.
Optional lexical text deduplication cannot prove independent reporting or claim support.
Use the same marker with and without bodies. A separately cited factual review may discuss
support and shared upstream provenance, but the automatic marker is never confirmation.
Do not store a separate counter on the concept.

### 3a. Read the brain-health report

Look for the most recent `pipeline/3-synthesis/brain-health_*.md` (written by
`scripts/validate_brain.py` in the weekly run; CONVENTIONS §13). If present, take its one-line
headline (the `Health:` line, else its first body line) — e.g. "12 concepts · 0 orphans ·
0 broken links · 0 missing-sources · 0 uncited-facts · 1 stale" — and surface it as a single
**Knowledge base health** line near the top of the digest. If no report exists, omit the line
entirely (best-effort, graceful).

### 3b. Read per-run value evidence

Look for the newest non-future `pipeline/3-synthesis/synthesis-run_*.md` run log and read only its
`## Totals` block. The machine-readable field names are exact:
- `concepts created`
- `concepts updated`
- `existing concepts reused`

Render the weekly digest line `Knowledge base changes` from `concepts created` and
`concepts updated`. Render `Reused existing knowledge` only when `existing concepts reused` is
explicitly present and greater than zero. Missing, malformed, negative, or absent values count as
zero. Do not infer reuse from recent `brain/concepts/` lookback volume; raw source count is not
reuse.

### 4. Build the digest

Compose the digest in this format:

```
# Weekly digest — [DATE]

_[N new sources across M topics, K updated concepts.]_

## ⚡ TL;DR
[up to three highlight lines — the essence of the week at a glance:
 - 📰 Most active: **<busiest topic>** (<its share of the new sources>)
 - 🔎 Worth a look: the single most credible source ([title](url), ⭐ if high-tier)
 - 💡 N concepts updated: the first few names (+M more)
 The deterministic builder derives these mechanically; when you enrich, keep the
 three-line shape but sharpen the wording.]

**🟢 Knowledge base:** [the `Health:` headline from the latest brain-health_*.md,
 e.g. "12 concepts · 0 orphans · 0 broken links · 0 missing-sources · 0 uncited-facts · 1 stale";
 the dot is ⚠️ instead of 🟢 when any issue counter is non-zero; omit this whole line if no
 report exists — exactly the deterministic builder's rendering]

**🧠 Knowledge base changes:** [N] concepts created, [M] updated this run.
**🔁 Reused existing knowledge:** [K] existing concepts reused during synthesis.
[Render the reuse line only when the explicit `existing concepts reused` count is > 0.]

[This week in one line — a 1-2 sentence lead you write from the combined set of
 new sources + updated concepts: the throughline of the week, written for a
 non-technical reader. This is the one piece the deterministic builder cannot
 produce, so it is the most valuable thing you add.]

## 📰 New sources (last {LOOKBACK} days)
[grouped by topic, each group headed "### 🏷 <topic> (<count>)" so the tag groups
 stand out and their sizes are scannable; directly under each badge, an italic
 one-line topic lead — "what happened in this topic this week" (persist it per
 Step 4a so headless builds render it too); then under each: "title" ⭐ — one-line
 takeaway, or "no new sources".
 The trailing ⭐ appears only for tier: high sources (medium/low render no marker).
 Where a new source clearly fed an updated concept, note that link, e.g.
 "title" ⭐ — takeaway (feeds: <Concept Name>).]

## 💡 Updated concepts (last {LOOKBACK} days)
[concept name ⭐ — its real one-line definition (first line of "What it is"),
 or "no concept updates"; the ⭐ appears only when the strongest source tier is high.
 Indented under each concept, a publisher-diversity line (CONVENTIONS §16):
 "🔵 N retained publisher domains — check the claim" (at least 2 retained groups), or
 "🟡 One retained publisher domain — check the claim" (1); omitted when there are no usable URLs.]

## 🧪 Synthesis this week
[one-line summary from the latest pipeline/3-synthesis/synthesis-run_*.md log;
 omit the whole section if there is no run log]

## 📌 Needs attention
[files in pipeline/1-incoming/ sitting > 14 days with a blank registry status, or "nothing pending"]
```

Keep it concise and skimmable. The digest language follows `delivery.language` in
`config/channels.yaml` (default `en`).

**Audience level (render-time).** Also read `config/channels.yaml` →
`delivery.technical_level` (default `balanced`) and render the digest body at that level —
`technical` (terse, keeps jargon, raw specifics), `balanced` (defines non-obvious terms,
one plain-language takeaway each), or `non-technical` (leads with "why it matters",
expands acronyms, analogies, fewer raw IDs). Wording only — never the underlying sources,
counts, ⭐ tier markers, or section structure. Full semantics:
[`docs/audience-levels.md`](../docs/audience-levels.md). When you enrich the deterministic
file (below): it may carry a trailing `_🎚 Audience level …_` footer noting that the
no-agent build could not apply the level — once you have re-rendered at the configured
level, **replace** that footer with the short factual form `_🎚 Detail level: <level>_`.

> **Write it as a brief, not a dump.** When **you** (the agent) author the digest, render
> the week as short **prose with inline `[title](url)` citations** — a few skimmable
> sentences that connect the new sources and updated concepts into a throughline — rather
> than a raw bulleted dump. Every claim about a source links to that source inline (borrowed
> from the research workflow's prose-with-citations discipline). The deterministic builder
> below stays list-based (it cannot write prose); your agent-authored digest should read
> like a brief while still preserving the section structure and the tier / health signals.

> **Headless equivalent.** `scripts/build_digest.py <out.md> [--lookback N]` produces this
> same digest **deterministically** (no agent) — it is what the external-cron path runs
> before `deliver.py`. It applies the exact rules above: scans by `collected:`/`last_updated`
> frontmatter, groups by topic, excludes `SEED`/`EXAMPLE` concepts, emits the one-line volume
> header (`N new sources across M topics, K updated concepts.`), a **TL;DR** block of up to three
> highlight lines (busiest topic · standout source · updated concepts), heads each topic group with
> a `### 🏷 <topic> (<count>)` badge, renders under each badge the one-line prose lead from
> `pipeline/3-synthesis/{topic}/digest-lead.md` for **every** topic whose synthesis is still
> current (a stale sidecar is auto-suppressed; with no sidecar only the busiest topic gets a
> derived lead, and the daily digest renders no leads at all), surfaces the **Knowledge base
> health** line from the latest `brain-health_*.md` (omitted when absent), renders the
> **Knowledge base changes** line from the latest synthesis run log's `concepts created` /
> `concepts updated` fields, renders **Reused existing knowledge** only from the explicit
> `existing concepts reused` field, renders each source
> and concept with its high-tier ⭐ marker when present, renders each updated concept with its real
> "What it is" definition line **plus a publisher-diversity line** (CONVENTIONS §16, via
> `scripts/corroborate.py` — "N retained publisher domains — check the claim" / "One retained publisher domain — check the claim"),
> embeds the **📈 Trends** section (ADR 0017 — topic volume vs last week, rising tags,
> activity, knowledge growth) in every **non-quiet** weekly digest by default
> (`--no-trends` opts out; quiet weeks and `--daily` never embed it),
> includes the synthesis-run summary, and writes a one-line "quiet
> week" digest (printing a `QUIET_WEEK` marker on stdout and embedding the structural
> `<!-- research-brain: quiet-digest -->` line that `deliver.py --skip-quiet` detects —
> keep that line if you rephrase or localize the quiet text) when there are no new sources and no
> concept updates. When **you** (the agent) run this task, you may start from that file and
> **enrich** it: rewrite the week as short prose with inline `[title](url)` citations, add the
> "this week in one line" lead, cross-topic synthesis, source→concept links, and editorial
> framing the deterministic builder cannot produce.

### 4a. Persist the per-topic leads (sidecars)

For **each topic group** in the digest, also write the one-line "what happened in this topic this
week" lead you composed (**12–22 words, one line** — the same contract as
`schedule/weekly-synthesis.md` Step 4) into that topic's sidecar, so the deterministic builder
renders it on the next headless build too:

```bash
# one line, no heading / no frontmatter — first non-empty line is used
printf '%s\n' "<the topic's one-line lead>" > pipeline/3-synthesis/{topic}/digest-lead.md
```

Write it only for a topic whose synthesis is **current** — `python3
scripts/synthesis_freshness.py status {topic}` reads `fresh`. Never stamp freshness from this
task (the stamp is the record that a topic was *synthesized*; `weekly-synthesis` owns it) — a
sidecar for a non-current topic is auto-suppressed by the builder's freshness gate anyway. The
weekly digest renders every current lead under its topic badge; the daily inflow digest renders
none (ADR 0016).

### 5. Save the digest file

Save to:
`pipeline/3-synthesis/digest_YYYY-MM-DD.md`
where `YYYY-MM-DD` is today's date.

### 6. Hand off to delivery

Invoke the **`digest-deliver`** skill, passing it the path of the digest file just saved.
`digest-deliver` reads `config/channels.yaml` and sends the digest over each enabled
channel (email / Telegram / Rocket.Chat). This task does **not** send anything itself —
it only builds the file and hands off.

> **Quiet weeks (D7).** When the week is quiet (no new sources and no concept updates),
> the headless cron path should pass `--skip-quiet` to `deliver.py` so users are **not**
> pinged with a "nothing new" digest:
> `python3 scripts/delivery/deliver.py <digest.md> --skip-quiet`. Dry-runs still report
> normally so a channel can be verified even on a quiet week.

---

## Rehearsal (D10) — try it before the first real send

Before the very first real delivery, do an end-to-end dry run that builds today's digest
from the configured lookback window and shows what *would* go out — without sending anything:

```
python3 scripts/delivery/deliver.py --rehearse
```

It prints `would deliver a digest with N source(s) / M concept(s) to <channels>` plus, per
enabled channel, the target and whether each secret is SET or MISSING (never the secret value).
Equivalent explicit one-liner:

```
python3 scripts/sanitize_incoming.py sanitize && \
    python3 scripts/build_digest.py /tmp/digest.md && \
    python3 scripts/delivery/deliver.py /tmp/digest.md --dry-run
```

(The builder's sanitize gate is fail-closed by default; for fully-controlled feeds
`--allow-unsanitized` skips the sanitize step.)

---

## Success criteria
- A digest file exists at `pipeline/3-synthesis/digest_YYYY-MM-DD.md`.
- Both `pipeline/1-incoming/` and `brain/concepts/` are reflected, scoped to the `{LOOKBACK}`
  window by `collected:` / `last_updated` frontmatter (not mtime); `SEED`/`EXAMPLE` concepts excluded.
- A "Synthesis this week" section reflects the latest `synthesis-run_*.md` (omitted when none exists).
- Files older than 14 days in `pipeline/1-incoming/` with a blank registry status are flagged under "Needs attention".
- The digest path was handed off to the `digest-deliver` skill.
