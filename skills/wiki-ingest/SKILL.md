---
name: wiki-ingest
description: "Use AFTER research-build (or manual addition of new knowledge) to propose updates to the Obsidian vault under brain/concepts/. Activates POST-TASK only — not mid-session, not parallel. Triggers: 'update the vault', 'sync brain', 'ingest into concepts', 'add this fact to a concept'. Source-link + provenance tag mandatory; AskUserQuestion gate per write."

metainfo:
  category: [kb-management]
  type: worker
  domain: knowledge-management
  subagent_capability: general
  last_updated: 2026-06-16
  predecessor: [research-build, concept-manage]
  successor: []
---

# wiki-ingest — update the knowledge vault after new knowledge arrives

After `research-build` (or another source of new knowledge) produces an artifact, this skill **inspects** which concept notes in `brain/concepts/` the new knowledge touches and **proposes** updates through `AskUserQuestion`.

The knowledge base is an **Obsidian vault** under `brain/` (`brain/concepts/`, `brain/lessons/`, `brain/playbooks/`). `brain/INDEX.md` is the **hand-curated MOC** (Map of Content). When a concept is added, you update `brain/INDEX.md` by hand and rely on Obsidian `[[wikilinks]]` (backlinks) and the graph view for navigation — there is no generated index.

If `brain/` is still empty — in **interactive mode** the skill refuses to run with a clear message (there is nothing to update and no operator intent to bootstrap). In **automatic mode** (`INTERACTIVE=false`, the scheduled `weekly-synthesis` path) an empty vault is instead the documented **cold-start**: the crosslink hard-gate's cold-start exception applies and the run CREATEs the first concept(s) as self-standing root notes rather than refusing (see § Modes → *Cold-start in automatic mode*). **Terminal write** to `brain/`.

---

## When to Use

**Always:**
- After `research-build` finishes its Output phase (proposed automatically)
- After an MCP-assisted research task is complete, its evidence has passed `research-audit`, and
  the user explicitly asks to save the result
- When new factual content is manually added and warrants concept-level value
- Triggers: 'update the vault', 'sync brain', 'ingest this into concepts', 'add {fact} to concept {name}', 'integrate lessons into concepts'

**ESPECIALLY when:**
- Upstream produced substantive factual content with source-links — concept-level value
- A lesson in `brain/lessons/` matches an existing concept slug (UPDATE candidate)

**Boundary (tie-break vs run-now):** Fires only immediately AFTER research-build / new in-session knowledge. A cold-start "update everything / refresh the brain" is `run-now` (the full pipeline), not this skill.

**Skip — Don't use for:**
- Only formatting/style changed (cosmetics without new facts)
- The artifact is narrowly scoped with no general applicability
- `brain/` contains no concepts yet — halt with explanation
- **Mid-session activation NEVER allowed** — strictly post-task. Upstream in progress (Synthesize / Format not closed) → halt "return after full closure of upstream skill"
- **Parallel-running NEVER allowed** — race condition: `brain/concepts/` updates before closure → inconsistent state
- **Speculative ingest NEVER allowed** — never ingest a "potentially useful" fact without upstream artifact closure. `brain/` = post-validated layer, not a speculative scratchpad

**Don't skip when:**
- Upstream produced an artifact with solid factual content — otherwise knowledge stays uncompiled and future research re-treads the same ground
- A lesson draft was created — without ingest the knowledge stays orphaned in `brain/lessons/`

---

## DO / DON'T

**DO:**
- Activate ONLY after a completed upstream task (research-build, or a finalized manual note)
- Source-link mandatory: every new fact → URL + (for web) local archive path (`pipeline/0-archive/...`)
- Provenance tag mandatory: `[research:{slug}]` / `[lesson:{date}]` in the body / "Change history" section
- Frontmatter stamp mandatory: every concept write sets `last_updated: <today>` in YAML frontmatter (the digest reads this field, not mtime); CREATE also sets `created: <today>` per `docs/CONVENTIONS.md` §5.1. Any write that **re-confirms** an existing concept also stamps `last_verified: <today>` (see § TTL / staleness)
- Dedup before CREATE (anti-sprawl): search `brain/concepts/` for a near-duplicate by normalized title + tag overlap (Phase 1.6) — on a clear match prefer UPDATE over CREATE; on ambiguity CREATE but log `possible duplicate of [[X]]`. No embeddings — simple string/tag heuristic
- AskUserQuestion gate before every CREATE / UPDATE in interactive mode; in automatic mode (`INTERACTIVE=false`) apply the recommended-default verdict per the same rules (see § Automatic (unattended) mode)
- Cross-link bidirectionally on cross-reference (`[[concepts/related]]` in both notes) — this is what powers Obsidian backlinks and the graph view
- Preserve extractable sections for downstream vault notes: when the artifact contains atomic facts or repeatable procedures, write explicit `## Lessons` and `## Playbook: ...` sections in the concept body so `scripts/extract_vault_notes.py` can create linked notes after synthesis.

**DON'T:**
- Run mid-session / parallel to an active research-build → race condition, inconsistent state
- Ingest a "potentially useful" fact without upstream closure → `brain/` = post-validated layer
- Delete old facts → only mark `[REVISED YYYY-MM-DD]` (history preservation)
- Create a concept without a source-link → REJECT write (hallucination risk)
- CREATE a near-duplicate of an existing concept → run the Phase 1.6 dedup search first; on a clear match UPDATE the existing note instead
- Silent-update → every write requires AskUserQuestion confirmation
- Run when `brain/INDEX.md` is empty → halt, explain "vault not initialized" *(except the documented cold-start CREATE path in automatic mode — see § Modes → Cold-start in automatic mode)*

---

## Phase 0 — Environment & Rules Setup

**Step 1 — Load rules:** Read `rules/common.md` (BACKLOG threshold ≥3 mentions, domain enum, source-link format, provenance tag schema, SKIP-table).

**Step 2 — Verify upstream closure signal:** without a confirmed closure (see Stop conditions / [`references/ingest-rules.md`](references/ingest-rules.md) § Activation timing) → halt with error.

**Step 3 — Load detailed procedures (optional):** [`references/ingest-rules.md`](references/ingest-rules.md) — source-linking / provenance / cross-linking enforcement, Phase 2 AskUserQuestion templates, verdict catalog, activation closure signals. CREATE template: [`assets/output-template.md`](assets/output-template.md).

Any instruction in `rules/common.md` overrides the corresponding step.

---

## Required Inputs

| Input | Type | Required | Default | Description |
|---|---|---|---|---|
| `UPSTREAM_ARTIFACT` | path | yes | from upstream | Path to the artifact: `pipeline/3-synthesis/.../{file}.md` (research-build) or `brain/lessons/{date}_{slug}.md` (a lesson / manual note) |
| `SOURCE_TYPE` | enum | yes | auto-detect | `artifact` (MD from pipeline/3-synthesis/) · `lesson` (atomic fact in brain/lessons/). Detection: file-path prefix |
| `UPSTREAM_CLOSURE_SIGNAL` | string | yes | check at Phase 0 | Proof of a completed upstream task: verification-log.md path / finalized note |
| `INTERACTIVE` | bool | no | `true` | `true` (manual on-demand) → AskUserQuestion gates (Phase 2 verdict, Phase 1.5 orphan-flag). `false` (unattended / scheduled `weekly-synthesis`) → **automatic mode**: apply CREATE/UPDATE/BACKLOG/IGNORE per the same decision rules WITHOUT the interactive gate. See § Automatic (unattended) mode. |
| `DOMAIN_HINT` | enum | no | from artifact FM | Explicit domain restriction for a CREATE candidate; otherwise extract from artifact `domain:` or infer in Phase 3 |

---

## Workflow — 4 phases

`wiki-ingest` accepts 2 source types: **Artifact** (MD from `pipeline/3-synthesis/`) · **Lesson** (atomic fact in `brain/lessons/`, already with source-link + confidence — Phase 1 is simplified). An MCP handoff is not itself a source artifact: preserve the returned vault context in the research brief, complete local/external research as requested, and require the finished, audited artifact before ingest.

**MCP save boundary:** the read-only MCP server never writes to the vault. A consuming agent may
start `wiki-ingest` only after the user explicitly asks to save the completed research and the
result is available in the trusted research-brain checkout. Force `INTERACTIVE=true` and follow
the normal verdict gate for each CREATE/UPDATE; never use the unattended weekly mode for this
request path. If the consuming host cannot access that checkout and run `wiki-ingest`, return a
source-linked proposal to the user; do not claim the vault was updated.

### Phase 1 — Diff

(1) Read the new artifact / lesson. (2) Read `brain/INDEX.md` (the MOC) for a semantic map of the vault. (3) Extract key entities (concepts, tools, figures, sources); for a lesson — already in frontmatter (`topic_tags`, `related_concept`). (4) Match against existing concepts via keyword match on `topic_tags` + titles; a lesson with `related_concept:` → first UPDATE candidate. (5) **Cross-link presence check** (Phase 1.5): a lesson without `related_concept:`/`parent_playbook:` → `ORPHAN_RISK_HOLD` (soft-flag in Phase 2) — an orphan note has no backlinks and disappears from the graph view. (6) **Dedup search before any CREATE** (Phase 1.6, below) — run for every CREATE candidate; a clear match downgrades CREATE → UPDATE. Verdict per entity: UPDATE / CREATE / IGNORE / BACKLOG / RETIRE_LESSON / ORPHAN_RISK_HOLD. Verdict definitions + cross-link check: [`references/ingest-rules.md`](references/ingest-rules.md).

### Phase 1.6 — Concept dedup search (anti-sprawl, before CREATE)

Per `docs/CONVENTIONS.md` §9 (concept dedup), **before** emitting any CREATE verdict, search the existing `brain/concepts/` for a near-duplicate using a **simple string/tag heuristic** — **no embeddings, no vectors**. For the CREATE candidate:

1. **Normalize the title** of the candidate and of every existing concept: lowercase, strip punctuation, drop common stopwords (`a, an, the, of, for, and, to, in, on, with, vs`). Compare on the resulting token sets — treat token-set equality, subset, or a high overlap (≥ ~60% of the smaller set) as a title match. This catches near-synonyms like "AI agent orchestration" vs "multi-agent orchestration" (shared tokens `agent`/`orchestration`).
2. **Tag overlap:** compare the candidate's `tags`/`topic_tags` against each existing concept's `tags`. Two or more shared tags is a strong signal.

Decision:

- **Clear match** (normalized titles overlap strongly **and** ≥1 shared tag, or one normalized title is a subset of the other with ≥1 shared tag) → **downgrade the verdict from CREATE to UPDATE** of that existing concept. Do not create a near-duplicate note; merge the new facts in via the normal UPDATE path (Phase 3), which also re-stamps `last_verified` (see § TTL below).
- **Ambiguous** (some title-token overlap but no shared tags, or shared tags but unrelated titles) → **proceed with CREATE**, and write a `possible duplicate of [[X]]` line into the synthesis-run log (`pipeline/3-synthesis/synthesis-run_*.md`) naming the closest existing concept, so a human can merge later. Do not block the run on ambiguity.
- **No match** → CREATE as normal.

This is a heuristic the agent applies by reading titles + tags — it is intentionally lightweight and may occasionally defer a merge to the human via the log line. That is acceptable: the goal is to prevent obvious sprawl, not perfect dedup.

### Phase 2 — Verdict gate

**Interactive mode (`INTERACTIVE=true`, manual on-demand):** one block of questions per run, ≤4 options. If ORPHAN_RISK_HOLD — a separate AskUserQuestion BEFORE the main verdict (assign crossref / accept orphan / skip). Templates: [`references/ingest-rules.md`](references/ingest-rules.md) § Phase 2.

**Automatic mode (`INTERACTIVE=false`, unattended / scheduled `weekly-synthesis`):** no AskUserQuestion — apply the SAME Phase 1 verdict (UPDATE/CREATE/BACKLOG/IGNORE) directly, picking the recommended default the interactive prompt would have offered. ORPHAN_RISK_HOLD resolves automatically (assign `related_concept:` by best `domain`/`topic_tags` match, else BACKLOG) instead of prompting. All hard rules below still apply (source-link, provenance, crosslink, all-🔴 halt). See § Automatic (unattended) mode.

### Phase 3 — Apply

- **UPDATE:** Edit the concept — add facts to "Key facts" with a source-link, the source to "Sources", a new row in "Change history", and **stamp `last_updated: <today>` in the YAML frontmatter** (this is the field the digest reads — never rely on file mtime); on confidence change — update with justification. When the write **re-confirms** the concept (a fresh source restates / corroborates its facts), also **stamp `last_verified: <today>`** so the TTL clock resets (see § TTL / staleness).
- **CREATE:** from `brain/concept-template.md` ([`assets/output-template.md`](assets/output-template.md) mirror) — fill it in, lead with the mandatory YAML frontmatter per `docs/CONVENTIONS.md` §5.1: `title, type: concept, tags` (nested `domain/topic`, **only** from `config/tags.yaml` — see § Tagging), `created, last_updated`, `related_concept:` (the machine-checkable links the graph is built from), and a structured `sources:` list (`url, archive, date, tier`) **derived from the curated/incoming article frontmatter the synthesis used — one entry per distinct source, never collapsing different domains** (so corroboration is computable downstream; see § Every key fact cites a source). **Set both `created: <today>` and `last_updated: <today>`.** Add a **mandatory** source citation on every key fact (each fact must trace to an entry in `sources:` — see § Every key fact cites a source) + confidence. Place in `brain/concepts/{slug}.md`, then **by hand add a MOC entry to `brain/INDEX.md`** and add `[[wikilinks]]` / `related_concept:` to related notes (cold-start root note: skip the outbound link per the § Hard rules cold-start exception).
- **BACKLOG:** a row in `brain/INDEX.md` § Backlog (topic, sources, priority).
- **Author nodes (CREATE and UPDATE):** as a gated byproduct of the concept write, resolve the concept's cited-source authors and offer to CREATE `brain/authors/<slug>.md` (if absent) + add `[[authors/<slug>]]` to the concept's `contributors:`, through the SAME `AskUserQuestion` confirmation. Best-effort — never halts the concept write. Full contract: § Author nodes (contributors).

**Extractable vault-note sections (CREATE and UPDATE):** When the upstream artifact or
`research-build` "Downstream extraction hints" contains material suitable for smaller reusable
notes, include it in the concept body using these exact headings:

- `## Lessons` — 1-5 bullets, each one atomic, source-backed, and useful outside the concept.
  These bullets become `brain/lessons/` notes after `weekly-run` calls
  `scripts/extract_vault_notes.py`.
- `## Playbook: <method name>` or `## Playbook draft: <method name>` — a short trigger paragraph
  plus ordered steps for a repeatable method, checklist, review loop, or decision procedure. This
  becomes a draft `brain/playbooks/` note.

Do not bury lesson/playbook candidates only under `## How to apply it`, `## Context / Application`,
or prose paragraphs: the deterministic extractor intentionally ignores ambiguous prose. Omit these
sections when there is no high-signal candidate; empty boilerplate sections create noise.

**Frontmatter stamping (every write, hard requirement):** on **every** concept write — CREATE *and* UPDATE — the YAML frontmatter MUST carry a fresh `last_updated: <today>`; on CREATE also set `created: <today>` (and never mutate `created` afterwards). The weekly digest / `build_digest` selects "updated concepts" by `last_updated` from the frontmatter, **not** by file mtime — an un-stamped write is invisible to the digest. SEED/EXAMPLE notes carry `tags: [seed, example, ...]` so the digest excludes them.

**Atomic write (unattended path):** on the automatic / unattended path (`INTERACTIVE=false`, the scheduled `weekly-synthesis` run) a **CREATE** SHOULD write the concept file through `python3 scripts/concept_write.py brain/concepts/{slug}.md --body-file <draft>` (or pipe the body on STDIN) rather than a plain editor write. That helper writes via a temp sibling + `os.replace`, so a crash mid-write can never leave a truncated `brain/concepts/{slug}.md` for the next run to read as a real concept. The helper only writes the bytes atomically — assemble the full file (frontmatter + body, fully stamped per the rules above) first, then hand it to the script. Interactive UPDATEs that edit in place can keep using the normal edit path. The helper also **safety-net-lists** the concept in `brain/INDEX.md` under “Recently added (file into a cluster)” when nothing there references it yet (idempotent, same listed-predicate as the hygiene check; `--no-index` skips) — so a missed Phase-4 MOC edit can never leave a concept invisible to `wiki-query`. This does NOT replace Phase 4: still file the entry under the right thematic cluster, replacing the auto “Recently added” line.

**Pre-write hard-rule check:** source-link + provenance tag on every new fact (missing → halt) AND a `last_updated: <today>` frontmatter stamp present on the write. Full enforcement (double link, forbidden unsourced, provenance format/where/why, cross-linking, confidence): [`references/ingest-rules.md`](references/ingest-rules.md).

### Phase 4 — Sync the MOC

Update `brain/INDEX.md` by hand (add/adjust the one-line `[[wikilink]]` entry under the right thematic cluster — start a new cluster if none fits; park thin topics under § Backlog). On CREATE — add the note to the MOC and ensure at least one `[[wikilink]]` connects it to a related note so Obsidian backlinks and the graph view pick it up. Report a short change summary to the user.

---

## TTL / staleness (lightweight)

The concept frontmatter already supports the optional `ttl_days` and `last_verified` fields (`docs/CONVENTIONS.md` §5.1). `wiki-ingest` keeps these honest with one simple discipline — **no separate audit skill is needed**:

- **On re-confirmation, stamp `last_verified: <today>`.** Whenever a write re-confirms an existing concept (a fresh source restates or corroborates a fact already in the note), set `last_verified: <today>` in the frontmatter in addition to the mandatory `last_updated` stamp. This resets the staleness clock. (A pure correction/`[REVISED]` is an UPDATE of `last_updated` only; re-verification of standing facts is what moves `last_verified`.)
- **Staleness flag is read-only, in the digest.** A concept is "stale" when `last_verified + ttl_days` is in the past. The digest / `scripts/build_digest.py` **may** surface such concepts in a "needs re-verification" line so a human can refresh them. This is an **optional** advisory flag — `wiki-ingest` itself never auto-retires or rewrites a stale note; it only keeps `last_verified` current. Concepts without `ttl_days` are never flagged (TTL is opt-in per note).

`wiki-ingest` runs in one of two modes, selected by the `INTERACTIVE` input — this is a documented mode switch, **not** a silent removal of the gate:

| Mode | Trigger | Verdict gate (Phase 2) | ORPHAN_RISK_HOLD |
|---|---|---|---|
| **Interactive** (default, `INTERACTIVE=true`) | Manual on-demand ("update the vault", "sync brain") with a human present | AskUserQuestion — user confirms each CREATE/UPDATE | Separate AskUserQuestion before the main verdict |
| **Automatic** (`INTERACTIVE=false`) | Scheduled `weekly-synthesis` run — no human present | **No prompt** — apply the recommended default verdict per the same Phase 1 decision rules | Auto-resolve: assign `related_concept:` by best `domain`/`topic_tags` match, else BACKLOG (never silently orphan) |

**Why a mode switch, not a removal:** the scheduled `weekly-synthesis` (`research-build → wiki-ingest`, per `docs/CONVENTIONS.md` §9) has no operator to answer an AskUserQuestion. Blocking on a gate would stall the whole synthesis cron. Automatic mode keeps every decision rule and **every hard rule** identical (source-link mandatory, provenance mandatory, crosslink hard-gate *with its cold-start exception*, no fact deletion, all-🔴 halt) — it only swaps the confirmation prompt for the recommended default the prompt would have surfaced. The interactive gate stays the default for manual use.

**Cold-start in automatic mode (must not stall a fresh vault):** when the vault has no real (non-SEED/EXAMPLE) concept in the candidate's cluster, the crosslink gate's **cold-start exception** (see § Hard rules) applies — automatic mode **CREATEs the first concept(s) as self-standing root notes** rather than BACKLOGging every candidate for want of a link target. The loop must actually write those first concepts; it falls back to BACKLOG only when the normal decision rules (e.g. thin material, <3 facts) call for it — never merely because no link target exists yet. Once a real sibling exists, the normal crosslink gate resumes for the rest of the run.

**Automatic-mode safety:** the hard rules below are the unattended safety net. Any write that would violate a hard rule (missing source-link / provenance / all-🔴 confidence, or missing crosslink **outside** the cold-start exception) still **halts and logs** rather than writing — automatic mode never relaxes a hard rule, it only removes the human confirmation step (and honours the documented cold-start crosslink exception).

---

## Tagging (closed-book, controlled vocabulary)

Concept `tags:` are the knowledge layer's index. Per `docs/CONVENTIONS.md` §11 + §5.1, tagging is **closed-book** against the registry `config/tags.yaml`:

- **Pick tags ONLY from `config/tags.yaml`.** Read the registry's `domains:` map first; valid tags are the `domain` itself plus every `domain/topic` pair it lists. Do **not** invent a tag from memory or from the article text.
- **Format = nested `domain/topic`** (e.g. `ai/agents`, `ai/rag`, `tech/security`). A bare `domain` (`ai`) is valid and natively groups its `ai/*` children — there is no separate super-tag feature.
- **Domain tag FIRST in the `tags:` list.** The first tag must carry the concept's primary domain (a bare `domain` like `ai`, or a `domain/topic` whose first segment is that domain) — `brain/concepts.base` groups the **By domain** cards on `tags[0]`'s first segment, so a non-domain first tag mis-groups the note. Example: `tags: [ai/agents, pkm/workflow]` (correct) — not `tags: [pkm/workflow, ai/agents]` if `ai` is the primary domain.
- **Cap/floor: 2–5 tags per concept, ≥1 domain-level tag.** Fewer than 2 or more than 5 → re-pick.
- **Nothing fits → ≤1 new tag into quarantine.** If no registry tag fits, propose **at most one** new tag in `domain/topic` form and **append it to the `pending:` list in `config/tags.yaml`** — NOT into the live `domains:` vocabulary. `pending:` is a quarantine; `scripts/validate_brain.py` is **advisory** and only *recommends* promotion, while the actual promotion of a `pending:` tag into `domains:` (after it recurs across ≥3 concepts) is applied by `scripts/promote_tags.py` in the weekly-run brain-hygiene step. Never expand `domains:` directly from this skill. (A brand-new topic isn't stuck in `pending:` either: `source-manage` add-topic seeds the new topic's tag into `config/tags.yaml` up front.)
- **Synonyms normalize through the registry.** If a candidate label is an alias listed in `synonyms:`, use its canonical `domain/topic` instead. Article seed-tags (from RSS `<category>`) are already normalized upstream by collection/curate via the same map — re-normalize any that slipped through.
- **SEED/EXAMPLE notes** keep their `seed` / `example` tags (in addition to ≥1 real domain tag) so the digest excludes them.

## Every key fact cites a source (anti-hallucination, hard rule)

This is the central anti-hallucination guarantee of the knowledge layer:

- **Build `sources:` from the inputs.** On CREATE/UPDATE, populate the concept's structured `sources:` frontmatter (`url, archive, date, tier`) from the frontmatter of the curated/incoming articles the synthesis actually used (`pipeline/2-curated/` + `pipeline/1-incoming/`). Do not fabricate URLs, archives, or tiers — copy them from the real article frontmatter. **For internal-corpus synthesis from pipeline articles, the provenance copy IS the pipeline article file**, so `archive:` points at that path (e.g. `pipeline/1-incoming/<topic>/<file>.md` or `pipeline/2-curated/...`) or is omitted when the entry already carries `url + date + tier` (per `docs/CONVENTIONS.md` §5.1). A dedicated `pipeline/0-archive/` copy is only expected for research-session web fetches (`source-archive`) — **do not halt ingest just because a collected source lacks a 0-archive copy.**
- **Record ALL distinct sources, not just one.** When the synthesis drew on more than one article/domain, list **every** one as its own `sources:` entry (`url, archive, date, tier`) — not only the first or "best" one. This is what makes downstream multi-source corroboration computable: `scripts/corroborate.py` derives the independent-source count from this list per `docs/CONVENTIONS.md` §16, so an under-recorded `sources:` silently understates the concept's confidence.
- **Preserve the independence signal — never collapse different domains.** Two sources on different registrable domains (eTLD+1) are **two** entries, even when they describe the same story. Do **not** merge or drop different-domain sources at ingest time; collapsing near-duplicate/syndicated texts (the same wire-story reprinted) into one independent source is the **downstream** corroboration step's job (`scripts/dedup.py` + `scripts/corroborate.py`, §16), not this skill's. Ingest records; corroboration counts.
- **Single-source honesty.** If a concept is built from only ONE source — or several reprints of a single story on one domain — record exactly that, and do not phrase the concept as if multiple independent sources confirm it. The digest marks single-source concepts with a caution line ("⚠ Single-source — treat with caution", §16) derived from this `sources:` list, so the accuracy of the list is what keeps that caution honest. An over-stated `sources:` produces a false "confirmed" badge.
- **Every key fact in the body MUST cite one of those sources.** Each bullet in `## Key facts` (and any load-bearing claim elsewhere) carries an inline `Source:` pointing at an entry in `sources:`. For research-session web sources that is URL + the local `pipeline/0-archive/` copy; for collected pipeline articles the provenance copy is the pipeline article file itself, so the source entry's `url + date + tier` (with `archive:` pointing at the article path, or omitted) is sufficient — a missing 0-archive copy is **not** grounds to halt. Where a fact is corroborated by more than one source, cite each. A fact with no traceable source is a hallucination risk → it is **not written**; either source it or drop it.
- **Pre-write check:** every distinct source the synthesis used is present as its own `sources:` entry (no different-domain source dropped or collapsed); every key fact has a `Source:` that resolves to a `sources:` entry; the `related_concept:` graph links are present (subject to the cold-start exception). Missing → halt and return to the author. (Full source-linking / provenance detail: [`references/ingest-rules.md`](references/ingest-rules.md).)

## Author nodes (contributors) — gated byproduct of a concept write

Authors are **first-class vault entities** (Stage 9, model α): a node lives at `brain/authors/<slug>.md` with `type: author`, and the authoritative author↔concept link lives **on the concept** as a `contributors: ["[[authors/<slug>]]"]` frontmatter field (modelled on `related_concept:`). The author's "everything they wrote" view is the Obsidian **backlink** — there is no generated list.

When Phase 3 proposes a concept CREATE/UPDATE, resolve that concept's **cited-source authors** and offer to record them, through the **SAME `AskUserQuestion` gate** as the concept write (one combined confirmation, never a second silent write):

1. **Resolve authors from the sources, never from prose.** For each source the synthesis used, read the `authors: [{name, url?, id?}]` frontmatter of the corresponding pipeline article (`pipeline/1-incoming/…` / `pipeline/2-curated/…`, document order per CONVENTIONS §5). Compute each author's **`identity_key`** with the exact identity ladder (`scripts/source_report/authors.py::identity_key` — `id:` → `url:` → `name:…|pub:…`). **No fuzzy name matching** — a false match credits a stranger's work permanently in a vault the person cannot correct (`scripts/authors/match.py` rationale). An author the feed credits only by a bare name that differs from a known node's is simply not matched — the cheap failure.
2. **Propose, behind the gate:** (a) **CREATE** `brain/authors/<slug>.md` if no node with that `identity_key` exists yet — from `brain/author-template.md`, filling its minimal frontmatter (`title`, `type: author`, `identity_key`, `identifier`/`profile_url` when the source carries them, `tags: [author]`, `created`/`last_updated: <today>`); body is identity + optional prose only, and it does **not** list its concepts; and (b) add `[[authors/<slug>]]` to the concept's `contributors:`. On a match to an existing node, propose only (b).
3. **Terminal + human-approved, never scripted.** The author node is written on the same terminal, gated path as the concept — `brain/` has **no generated indices**, so a script must never emit an author node (a generated `brain/authors/*.md` would break the trust contract; this is why a side-panel variant was rejected). The node's slug is the kebab-case of the author's name (reuse the existing `slugify`).
4. **Best-effort — it never blocks the concept.** A concept whose sources credit no resolvable author still writes normally; author resolution **does not halt** ingest. This step only *adds* provenance, it is never a gate on the knowledge write.
5. **Roster is separate (Q4).** NEVER auto-create an author node from the followed-authors **roster** (`config/authors.yaml`), nor a roster entry from a node — "I want more of them" (roster) ≠ "here is what we know of them" (node). A node may note "followed: yes/no" read-only (slice 4), but the two never write across to each other.

A manual request ("add an author node for X", "record the author of this concept") rides this **same** gated ingest path — there is no separate script and no `author-manage` write (that skill manages the roster, not nodes).

## Hard rules

- **Post-task only.** Activate ONLY after a completed upstream skill — not mid-session, not parallel. Race-condition prevention.
- **Author nodes are gated, terminal, and best-effort.** Author-node CREATE + a concept's `contributors:` edit are proposed through the SAME `AskUserQuestion` gate as the concept write and written on the same terminal path — never by a script (no generated indices). Authors are resolved from the article `authors:` frontmatter via the strict `identity_key` ladder (no fuzzy matching); an unresolvable author never halts the concept write. Never auto-create a node from the roster or vice versa (§ Author nodes).
- **Closed-book tagging.** Concept tags are assigned ONLY from `config/tags.yaml` (nested `domain/topic`, 2–5 per concept, ≥1 domain tag). If nothing fits, propose ≤1 new `domain/topic` into the registry's `pending:` quarantine — never directly into the live `domains:` vocabulary. (See § Tagging.)
- **`related_concept:` graph link.** Every concept carries machine-checkable links in the `related_concept:` frontmatter — the vault graph is built from `related_concept:` + `tags`, not from inline `[[...]]` alone. CREATE/UPDATE without at least one graph link is rejected (subject to the cold-start exception below).
- **Every key fact cites a source.** Each key fact in the body traces to an entry in the structured `sources:` list (url/archive/date/tier), itself derived from the article frontmatter the synthesis used. An unsourced fact is not written (anti-hallucination). (See § Every key fact cites a source.)
- **Record all distinct sources (multi-source provenance).** When synthesis used more than one article/domain, every distinct source is recorded as its own `sources:` entry; different-domain sources are never collapsed into one (that is the downstream corroboration step's job, §16). A single-source concept is recorded honestly as such — the digest's corroboration line is derived from this list. (See § Every key fact cites a source.)
- **Source-link mandatory.** Any new fact without a real source entry → REJECT write. A dedicated `pipeline/0-archive/` path is required only for research-session web fetches; for collected pipeline articles the article file is the provenance copy (`archive:` points at it or is omitted), so a missing 0-archive copy alone is **not** grounds to reject.
- **Provenance tag mandatory.** `[research:{slug}]` / `[lesson:{date}]` required in the body or in the body section "Change history".
- **Verdict gate.** In interactive mode every CREATE / UPDATE requires explicit user confirmation (no-silent-edits invariant). In automatic mode (`INTERACTIVE=false`, scheduled run) the gate is replaced by the recommended-default verdict per the same decision rules — every other hard rule still holds.
- **No fact deletion.** Refuted facts are marked `[REVISED YYYY-MM-DD]`, not deleted.
- **Backlink crosslink — HARD gate (with a cold-start exception).** Any CREATE / UPDATE of a `type: concept` / `type: playbook` / `type: lesson` note MUST contain at least **1 cross-reference** at write time: either a `related_concept:` / `sources:` frontmatter entry (vault-relative path to an existing note), or a markdown body link `[title](relative/path.md)` to an existing file, or an Obsidian `[[wikilink]]` to an existing note. Without at least 1 link the note becomes an orphan (no backlinks, absent from the graph view) → REJECT write, return to the author with a suggested target. Rationale: orphan notes accumulate as unreachable dead weight in the vault. **`type: author` nodes are EXEMPT** — they are backlink-only by design (the link lives on the concept's `contributors:`, so the node carries no outbound link and is never orphan-flagged; see § Author nodes).
  - **Cold-start exception (per `docs/CONVENTIONS.md` §10).** For the **FIRST** concept in an empty / near-empty topic cluster — when no existing *real* sibling note exists to link to (only SEED/EXAMPLE notes, or nothing) — the gate is **relaxed**: write a **self-standing root note** (CREATE *without* an outbound `[[wikilink]]`) rather than forcing BACKLOG or linking to a SEED/EXAMPLE note just to satisfy the gate. A root note is the legitimate seed of a new cluster; it is not orphan debt. As soon as **≥1 real (non-SEED/EXAMPLE) sibling** exists in the cluster, the normal crosslink gate resumes and every later CREATE/UPDATE must carry ≥1 cross-reference. **Cold-start detection:** a real sibling = a `brain/concepts/*.md` whose `tags:` contain neither `seed` nor `example`; if none match the candidate's `domain`/`tags`, treat it as cold-start. This keeps automatic/unattended mode productive — the loop writes the first concepts of a fresh vault instead of BACKLOGging them all waiting for a link target that does not yet exist.
- **All-🔴 confidence halt.** If all confidence markers are 🔴 → halt, return to research-audit (do not write unreliable knowledge).

---

## Stop conditions

- `research-build` / another upstream did not precede → halt "wiki-ingest requires a research artifact (or manual note) as input"
- Upstream closure signal absent → halt "requires a completed upstream task; current state: {detected_state}"
- Diff vs existing concept is empty → skip CREATE/UPDATE, log it
- All confidence markers 🔴 → halt, return to `research-audit`
- Automatic mode (`INTERACTIVE=false`, scheduled run): proceed without AskUserQuestion using the recommended-default verdict (see § Automatic (unattended) mode); halt only on a hard-rule violation (missing source-link / provenance / crosslink, or all-🔴 confidence)
- Source-link missing on any claim → halt "source-link hard-rule violation"

---

## Success criteria

- Phase 1 input contract: upstream skill (research-build, or a finalized manual note) confirmed
- Phase 1 diff: key entities extracted; `brain/INDEX.md` read; for lessons the `related_concept` frontmatter is used
- Phase 2 verdict: exactly one of {UPDATE / CREATE / BACKLOG / IGNORE / RETIRE_LESSON} — via AskUserQuestion (≤4 options) in interactive mode, or the recommended default in automatic mode
- Phase 3 write: for CREATE the concept is built from the template, frontmatter leads with `title` / `type: concept` / `tags` (nested `domain/topic`) / `created` / `last_updated` / `related_concept:` / structured `sources:` (`url, archive, date, tier`) — per `docs/CONVENTIONS.md` §5.1; optional `last_verified` / `ttl_days`
- Closed-book tags: every `tags:` value comes from `config/tags.yaml` (nested `domain/topic`, 2–5, ≥1 domain tag); a non-fitting candidate adds ≤1 tag to the registry's `pending:` quarantine, never to the live `domains:` vocabulary
- `related_concept:` graph: the concept carries ≥1 machine-checkable `related_concept:` link (the graph is built from this + tags), except the cold-start root-note case
- Every key fact cites a source: each key fact in the body traces to an entry in the structured `sources:` list, which is derived from the curated/incoming article frontmatter — an unsourced fact is not written
- All distinct sources recorded: when synthesis used multiple articles/domains, EVERY distinct source is its own `sources:` entry (`url, archive, date, tier`); different-domain sources are not collapsed (corroboration counts downstream per §16); a single-source concept is recorded honestly as single-source so the digest's caution line stays accurate
- Frontmatter stamp: EVERY write (CREATE and UPDATE) stamps `last_updated: <today>` in the YAML frontmatter; CREATE also sets `created: <today>` — the digest reads `last_updated`, not mtime, so an un-stamped write is invisible to the digest
- Source-link mandatory: every new fact has a URL + (if web) an archive path — otherwise REJECT
- Cross-link bidirectional: `[[concepts/related]]` in both notes on cross-reference (powers backlinks + graph view) — **except** the cold-start case (first real concept in an empty/near-empty cluster), where a self-standing root note CREATE without an outbound link is allowed per the § Hard rules cold-start exception; normal crosslink rules resume once ≥1 real sibling exists
- Phase 1.6 dedup: every CREATE candidate is checked against `brain/concepts/` by normalized title + tag overlap; a clear match is downgraded to UPDATE, an ambiguous case is CREATEd with a `possible duplicate of [[X]]` line in the synthesis-run log
- TTL discipline: a re-confirming write stamps `last_verified: <today>`; staleness (`last_verified + ttl_days` past) is left for the digest to flag, not auto-actioned here
- Author nodes (gated byproduct): the concept's cited-source authors are resolved via the `identity_key` ladder (no fuzzy matching) and, behind the SAME `AskUserQuestion` gate, an absent `brain/authors/<slug>.md` (`type: author`) is proposed for CREATE + a `[[authors/<slug>]]` entry added to the concept's `contributors:`; written on the terminal path, never by a script; an unresolvable author never halts the concept write; never auto-created from/into the roster
- Phase 4 sync: `brain/INDEX.md` MOC updated by hand on CREATE; summary reported
- No silent edits / no fact deletion / halt on all-🔴 confidence

---

## Integration with other skills

| Skill | Relationship |
|---|---|
| `wiki-query` | Paired query side (reads `brain/`, does not write) |
| `source-archive` | Creates `pipeline/0-archive/{date}_{host}_{slug}.md` for the double link |
| `research-build` | Upstream source of new knowledge |
