---
name: research-audit
description: "Use to verify factual claims in a draft research artifact against source tier and recency. Triggers: \"check facts\", \"verify claims\", \"run research-audit\", \"is this ready to ship?\", \"check the sources in this draft\", \"check the citations\". Outputs a 🟢/🟡/🔴 verification log; >30% 🔴 → return to Gather. Two modes: FULL (manual, brief + sources/ registry) and SOFT (internal-corpus / no-registry — skip tier-grading, KEEP citation-guard + recency, emit a confidence note, NEVER fail-fast or block ingest)."

metainfo:
  category: [research]
  type: validator
  domain: meta-process
  subagent_capability: general
  last_updated: 2026-06-16
  predecessor: [research-build]
  successor: [research-build]
---

# Research-Audit — Verify step of the research lifecycle

**Purpose:** before final formatting / critique — guarantee that the factual claims in a draft (the markdown produced by `research-build`) rest on sources of adequate tier and freshness. The most expensive failure of a research artifact is shipping a polished document with a wrong fact; this skill is the last safety net between synthesis and publication.

**Position in the research chain:** `research-frame → wiki-query → research-grep → research-build (Gather + Synthesize → draft md) → research-audit (this skill, Verify) → research-build Critique → format → wiki-ingest (archive)`.

**Modes** (default `audit` = Phases 1-7.5): `revise` (Reviewer-Revisor loop when the verify gate exceeds 30% 🔴, max 2 iterations) · `parallel` (N=3 parallel hypothesis investigators, structured contradicting-evidence merge). Detail: [`references/optional-modes.md`](references/optional-modes.md).

### Soft mode (`SOFT_MODE=true`) — internal-corpus / no-registry

Per `docs/CONVENTIONS.md` §10. Activated when (a) `SOFT_MODE=true` is passed explicitly (the `weekly-synthesis` unattended path passes it for `PROFILE=internal-corpus` synthesis), OR (b) auto-detected: no `sources/trusted-registry.md` AND no `sources/always-volatile-domains.md` exist, OR no brief is findable. In soft mode:

- **NO fail-fast** on a missing brief or missing `sources/` registry.
- **NO tier-grading** — "registry missing" is NOT treated as "everything is T3", so it does **not** inflate `red_pct` into a `>30% 🔴` block. The threshold gate is **disabled** (`gate_status: soft-pass`).
- **KEEP** the Phase 5.5 citation / quote-hallucination guard (PLACEHOLDER for unverified citations) and the Phase 4 recency annotation (relative dates / "recency-unknown" flags) — these need no registry.
- **Corroboration is a LIGHT signal** (per §16): annotate each factual/news claim (and the concept) with its **publisher-count proxy** (legacy `independent_sources` field) and the `single` / `multi` level; record whether independence was actually reviewed, but do **NOT** hard-block ingest on it — consistent with §10. (The citation-guard above stays mode-independent as before.)
- **EMIT a confidence note** in the log (`confidence_note:` field) summarising what could and could not be checked (e.g. "tier-grading skipped: no registry; N citations matched, M flagged; recency annotated") instead of blocking ingest.
- If a `sources/` registry **is** present, it is still used for tier annotation (best-effort), but a missing registry never blocks.

Full procedure: [`references/soft-mode.md`](references/soft-mode.md).

---

## When to Use

**Always:**
- After the `research-build` Synthesize + Phase 5 Sources section (auto hand-off on the draft, before the Phase 6 Editorial / Phase 6.5 Critique)
- Explicit triggers: "check facts", "verify claims", "run research-audit", "is this ready to ship?", "check the sources in this draft", "check the citations", "fact-check this artifact"
- When the brief sets a high-stakes audience (e.g. leadership / decision-grade output)
- For any deliverable-bound output

**ESPECIALLY when:**
- The artifact contains numeric claims (statistics, percentages, benchmarks)
- Vendor claims (features, prices, limits) — risk if vendor docs are stale
- Always-volatile topics (model releases, AI API prices, regulation) — strict recency check
- Multi-source artifacts (≥10 sources) — higher cumulative risk

**Skip — Don't use for:**
- Artifacts without a research-brief (no input contract → no `recency_max` / `min_tier`)
- Already-verified artifacts (verification log exists, is fresh <24h, and the draft has not changed)
- Conversational answers without citations
- Internal-process drafts (planning notes, backlog entries)
- When `format: chat-answer` — use light mode (citation tier check only)

**Don't skip when:**
- Any deliverable-bound artifact = mandatory Verify
- The artifact contains numeric / vendor claims in an always-volatile domain

"It's just a draft"? One wrong fact in a shipped artifact costs more reputation than the hours spent on research-audit.

---

## DO / DON'T

**DO:**
- ✅ Read the research-brief FIRST for `recency_max` + `min_tier` + `format`
- ✅ Extract verifiable claims only (numeric / vendor / factual / quoted), skip subjective
- ✅ Always-volatile override (3mo) → trumps brief `recency_max` for AI tools / API prices / regulatory
- ✅ Delegate all WebFetch to the `source-archive` skill (NEVER direct WebFetch)
- ✅ Write the verification log to `planning/research/{date}_{slug}.verification-log.md` (canonical path)
- ✅ Update brief lifecycle checkbox + `verification_log:` field + `last_updated:`
- ✅ Hard block the transition to formatting when `red_pct > 30%` — return to Gather

**DON'T:**
- ❌ Use AskUserQuestion in the detect phase when `INTERACTIVE=false` → detect-only contract violation
- ❌ Edit the draft md directly → pure detect mode; write only the verification log
- ❌ Auto-promote 🔴 → 🟡 because it is "close to the threshold" → the threshold is strict
- ❌ Choose the "convenient" version on a contradiction → record both as 🔴
- ❌ Skip the log when "everything is green" → the audit trail is mandatory even on a clean pass
- ❌ Use light mode for `format ≠ chat-answer` → full mode is mandatory for deliverables
- ❌ Write the log anywhere but the canonical path `planning/research/` (sibling of the brief)
- ❌ Call WebFetch directly for a supplementary check → it breaks source-archive enforcement

---

## Phase 0 — Environment & Rules Setup

**Step 1 — Load rules:** Read `rules/common.md` (patterns for extracting verifiable claims, tier classification of an unregistered host, the recency formula, threshold policy, verification-log schema).

**Step 2 — Load detailed procedures (optional):** [`references/verify-phases-detail.md`](references/verify-phases-detail.md) (claim categories / tier edge cases / recency math / cross-source pseudocode + subagent dispatch / marker rules), [`references/tier-rules.md`](references/tier-rules.md), [`references/extract-patterns.md`](references/extract-patterns.md) (non-standard drafts), [`references/extended-mode-phases.md`](references/extended-mode-phases.md) (extended-mode Phases 6.5/6.6/7.5), [`references/citation-guard.md`](references/citation-guard.md), [`references/phase-7-and-light-mode.md`](references/phase-7-and-light-mode.md), [`references/log-template.md`](references/log-template.md), [`references/examples.md`](references/examples.md).

Any instruction in `rules/common.md` overrides the corresponding step here.

---

## Required Inputs

| Input | Type | Required | Default | Description |
|---|---|---|---|---|
| `DRAFT_PATH` | string | yes | — | Path to the draft md (usually `pipeline/3-synthesis/{slug}.md` or a working copy) |
| `BRIEF_PATH` | string | yes (FULL) / no (SOFT) | — | Path to `planning/research/{date}_{slug}.md` (source of `recency_max`, `min_tier`, `format`). FULL mode: if not passed — find the sibling brief by convention; if none found → fail-fast. SOFT mode: OPTIONAL — absence → proceed with defaults + a confidence note (no fail-fast) |
| `SOFT_MODE` | bool | no | auto | `true` → soft mode (internal-corpus / no-registry): skip tier-grading, KEEP citation-guard + recency, no fail-fast, no >30% block, emit a confidence note. Auto-detected `true` when no `sources/` registry exists OR no brief is findable. See § Soft mode |
| `INTERACTIVE` | bool | no | `false` | `true` → AskUserQuestion for fix actions (registering unregistered hosts, broken footnotes). `false` → detect-only markdown report |
| `THRESHOLD` | float | no | `0.30` | 🔴 marker threshold for the gate (return to Gather). `rules/common.md` `RED_THRESHOLD_PCT` overrides. Ignored in SOFT mode (gate disabled) |
| `MODE` | enum: `auto` / `chat-answer-light` / `force-full` | no | `auto` | `auto` = reads `format` from the brief; `chat-answer-light` = manual override to light mode; `force-full` = always the full cycle |

---

## Workflow — 7 phases (+ extended-mode Phases 6.5/6.6/7.5)

### Phase 1 — Read inputs

Read the draft md (`DRAFT_PATH` — body + footnotes/sources) · the research-brief (`BRIEF_PATH` — `format`, `recency_max`, `min_tier`, `research_question`) · `sources/trusted-registry.md` (tier lookup) · `sources/always-volatile-domains.md` (recency override).

**Soft-mode detection (FIRST):** if `SOFT_MODE=true`, OR `sources/trusted-registry.md` AND `sources/always-volatile-domains.md` are both absent, OR no brief is findable → enter **Soft mode** ([`references/soft-mode.md`](references/soft-mode.md)): brief / registry reads are best-effort (absent → proceed, no fail-fast), Phase 3 tier-grading is skipped, the Phase 7 threshold gate is disabled, but Phase 4 recency annotation and Phase 5.5 citation-guard still run. Emit a `confidence_note:` instead of blocking. If the registry IS present it is still used for best-effort tier annotation.

**Chat-answer downgrade gate:** if `format == chat-answer` (or `MODE=chat-answer-light`) → go to **Light mode** (Phase 7 alternative), skip Phases 2-6.

### Phase 2 — Extract verifiable claims

Parse the draft → `claims_list`. Each claim = `{text, footnote_ref, source_url, claim_type}`. Verifiable categories (numeric / vendor-claim / factual statement / quoted figure) + the non-verifiable list + output schema: [`references/verify-phases-detail.md`](references/verify-phases-detail.md) § Phase 2.

### Phase 3 — Tier lookup

For each claim → find the `host` in `sources/trusted-registry.md`; host not found → `unregistered` (= T3 + flag). Edge cases (vendor sub-hosts / GitHub repos / unregistered_critical): [`references/verify-phases-detail.md`](references/verify-phases-detail.md) § Phase 3.

**Soft mode:** if no registry is present, **skip this phase entirely** — do NOT mark everything T3 (that would inflate `red_pct` and falsely trigger the block). Record "tier-grading skipped: no registry" in the confidence note and continue to Phase 4.

### Phase 4 — Recency check

Compute `age_days` against `recency_max` from the brief; flag `recency_stale`. **Always-volatile override:** a keyword in the claim → 3mo even if the brief allowed 12mo. Math: [`references/verify-phases-detail.md`](references/verify-phases-detail.md) § Phase 4.

### Phase 5 — Cross-source corroboration (numeric + vendor-claim + factual/news)

**numeric + vendor-claim (unchanged):** ≥2 sources with ≥1 T1/T2 → ok; single T1/T2 → single-authoritative; single T3 → supplementary fetch (via `source-archive`, never directly); otherwise unsupported. Contradiction = 🔴 (record both versions).

**factual / news (per `docs/CONVENTIONS.md` §16):** inspect the exact passages supporting
that claim and whether they trace to the same upstream report, announcement or dataset.
Two publisher domains or dissimilar texts do not by themselves establish independent support.
For 🟢 eligibility, establish at least two independently supporting sources, applicable recency
and no contradiction. If independence is unknown or all reports share one upstream source,
retain 🟡 with that limitation. Zero supporting evidence or a material contradiction follows
🔴; record both versions. Soft mode records these limits without blocking on coverage.

**Publisher proxy and independence review:** lexical near-duplicate grouping can reduce
reprints, then `scripts/corroborate.py` counts publisher groups. The legacy
`independent_sources: N` log field records that proxy; it must not be presented as a verified
independence count. Record `independence_review: unknown` unless the supporting passages and
upstream provenance were actually assessed, then state the assessment and its evidence in
prose. Dispatch for more than 20 claims follows the existing phase detail. See
[`references/verify-phases-detail.md`](references/verify-phases-detail.md) § Phase 5.

**Optional search enrichment (§15):** when a claim has one publisher group and a provider
is configured, `python3 scripts/corroborate.py enrich "<claim>" --source <existing-url>`
returns additional publisher-domain candidates and a coverage level. It never confirms
claims. Search-disabled/unavailable results soft-skip. Read the discovered passages and
trace their provenance before adding URLs to concept `sources:`; a raw search hit is not
supporting evidence.

### Phase 5.5 — Citation hallucination guard + PLACEHOLDER

Guard against naked citations without a matching source in the raw materials. 4 detection patterns → 3 verdicts (🟢 MATCHED / 🟡 AMBIGUOUS / 🔴 UNVERIFIED → insert `[CITATION-UNVERIFIED: {citation}]`). **Hard rule:** a PLACEHOLDER never ships; the Phase 7 gate halts the hand-off. Default auto-run; mandatory for high-stakes deliverables; skip only on internal review AND zero attribution markers. Full procedure: [`references/citation-guard.md`](references/citation-guard.md).

### Phase 6 — Assign markers

Assign 🟢/🟡/🔴 per claim by the rules (numeric requires cross-source; a vendor's own docs at T1 = 🟢). Marker table + edge cases: [`references/verify-phases-detail.md`](references/verify-phases-detail.md) § Phase 6 + [`references/tier-rules.md`](references/tier-rules.md).

**Extended mode branch (opt-in):** if `grading_mode == extended` (auto-set when the brief marks a high-stakes / leadership audience) — the 3-level table is replaced by a 6-level taxonomy (🟢🟢 Definitive / 🟢 High / 🟢- Moderate / 🟡 Low / 🔴 Very-Low / ⚫ Insufficient), with an evidence-type per claim mandatory. Standard mode is unchanged (regression-safe). Table: [`references/extended-mode-phases.md`](references/extended-mode-phases.md).

### Phases 6.5 / 6.6 / 7.5 — Extended-mode passes (extended mode only)

- **6.5 Inversion adversarial pass** — top-3 thesis claims → ≥3 inversions each → marker; **gate:** ≥1 🔴 thesis-broken → block formatting (overrides the 30% rule).
- **6.6 Misinformation classifier** (4 categories: 🚨 Fabrication / ⚠️ Distortion / 📅 Outdated / 🔀 Conflation) — orthogonal to evidence quality; **hard gate:** ≥1 🚨 Fabrication = block; ≥3 flags = recommend Critique.
- **7.5 6-dim rigor reviewer** (D1 Clarity / D2 Accuracy / D3 Completeness / D4 Objectivity / D5 Actionability / D6 Source-quality) — rigor_score gate: ≥85% Strong / 70-84% Adequate / 55-69% Marginal (revision) / <55% block.

Full procedures: [`references/extended-mode-phases.md`](references/extended-mode-phases.md).

### Phase 7 — Generate verification log + Threshold gate

Compute aggregate stats (total / green / yellow / red / red_pct). **Threshold gate (hard rule, FULL mode):** `red_pct > 30%` → block formatting, return to Gather (`gate_status: blocked`); otherwise `gate_status: passed` → Critique → formatting. Write the verification log to `planning/research/{date}_{slug}.verification-log.md` (template: [`references/log-template.md`](references/log-template.md)). Update brief lifecycle (`verification_log`, `last_updated`, checkbox). Unregistered hosts: AskUserQuestion if `INTERACTIVE=true`, otherwise a recommendation in the log. Detail + Light mode (chat-answer alternative, inline summary, no log file): [`references/phase-7-and-light-mode.md`](references/phase-7-and-light-mode.md).

**Soft mode:** the threshold gate is **disabled** (`gate_status: soft-pass`) — never block ingest. The log records the citation-guard verdicts, the recency annotation, and a `confidence_note:` ("tier-grading skipped: no registry; N citations matched, M flagged; recency annotated"). If `planning/research/` does not exist, write the log there after creating the dir, OR — when there is no brief at all (internal-corpus) — write the log alongside the draft in `pipeline/3-synthesis/{topic}/`; there is no brief lifecycle to update.

---

## Hard rules

> Rules marked **(FULL only)** apply in FULL mode. In SOFT mode (internal-corpus / no-registry) they are relaxed per § Soft mode — no fail-fast on a missing brief/registry, no >30% block; the citation-guard + recency annotation are retained.

- **Detect-only contract:** the detect phase MUST support `INTERACTIVE=false` — markdown-only output, fail-fast recommendations instead of questions. AskUserQuestion only when `INTERACTIVE=true` (the fix phase).
- **(FULL only) Brief mandatory.** In FULL mode, without `BRIEF_PATH` — fail-fast (neither `recency_max` nor `min_tier` can be sourced otherwise). In SOFT mode the brief is OPTIONAL: absence → proceed with defaults + a confidence note, never fail-fast.
- **(FULL only) 30% threshold = hard block.** Exceeding it → return to Gather, no formatting. No "just publish anyway" without an AskUserQuestion with explicit acknowledgment. In SOFT mode the gate is disabled (`gate_status: soft-pass`) and a missing registry is NEVER treated as "everything T3 → >30% block".
- **Citation-guard is retained in BOTH modes.** Phase 5.5 (citation / quote-hallucination guard, PLACEHOLDER for unverified citations) runs regardless of mode — it needs no registry.
- **Contradiction = 🔴.** Both versions are recorded in the log. Do not pick the convenient one.
- **Always-volatile override raises strictness** (3mo even if the brief allows 12mo).
- **A numeric claim requires cross-source.** Even with 1×T1 → 🟡, not 🟢.
- **Factual/news 🟢 requires independently supporting passages and provenance review**, not
  a count of domains or lexically different texts. At least two independent sources, recency
  and contradiction checks are required. Unknown independence retains 🟡. The legacy
  `independent_sources` field is a publisher proxy, not the audit verdict; soft-mode coverage
  remains advisory and never blocks ingest.
- **A vendor's own primary docs = T1 without a cross-source requirement** (the vendor is a primary source by definition).
- **Web fetch only via source-archive.** Never WebFetch directly — supplementary fetch is delegated.
- **`last_updated` update in the brief** after writing the verification log.

---

## Stop conditions

- **(FULL only)** `BRIEF_PATH` not provided AND not findable → fail-fast with instructions. In SOFT mode: proceed with defaults + a confidence note (no fail-fast).
- Draft contains no verifiable claim → return the notice "no verifiable claims, skipping"; no log.
- All footnotes broken / unparseable → `INTERACTIVE=true`: AskUserQuestion; `false`: fail-fast "fix manually and re-run".
- `sources/trusted-registry.md` empty / corrupted → **(FULL only)** fall through to unregistered-everywhere mode (all T3); flag "registry-error". In SOFT mode (or when the registry is simply ABSENT): skip tier-grading entirely (do NOT mark all T3 → no inflated `red_pct`), record "tier-grading skipped: no registry" in the confidence note, never block.

---

## Success criteria

- ✅ Verification log created at `planning/research/{date}_{slug}.verification-log.md`
- ✅ Frontmatter valid (`type: audit-report`, `gate_status` populated)
- ✅ Every verifiable claim has a 🟢/🟡/🔴 marker + reason
- ✅ `red_pct` rendered correctly; the threshold gate is applied
- ✅ Brief updated (`verification_log` field + lifecycle checkbox + `last_updated`)
- ✅ Unregistered hosts surfaced via AskUserQuestion (if any)
- ✅ Contradictions recorded explicitly (if any)

---

## Example runs

5 worked examples (full-mode pass / blocked / chat-answer light / extended mode / inversion pass on a multi-agent orchestration thesis): [`references/examples.md`](references/examples.md).

---

## Integration with other skills

| Skill | When to hand off |
|---|---|
| `research-build` (incoming) | Caller — usually after the draft md is complete |
| `source-archive` | For every supplementary fetch in Phase 5 |
| `research-build` (outgoing Critique) | After `gate=passed` → hand control to the Critique pass |
| formatting | Never directly — only via the `research-build` Critique pass |
