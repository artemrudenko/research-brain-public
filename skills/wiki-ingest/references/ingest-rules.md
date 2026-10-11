---
title: "wiki-ingest — Hard-rule enforcement detail (source-linking, provenance, cross-linking, confidence) + AskUserQuestion templates"
type: reference
domain: knowledge-management
last_updated: 2026-06-16
applies_when: "Phase 1.5 cross-link check / Phase 2 AskUserQuestion templates / Phase 3 source-linking + provenance enforcement"
---

# wiki-ingest enforcement detail

> Extracted from `SKILL.md`. SKILL.md keeps the invariants checklist; full enforcement lives here.

## Source-linking (hard rule)

**Every new fact MUST have a source-link.** Without one — **write is rejected** (hallucination protection).

**Double link is mandatory for research-session web fetches** — (1) the original URL, (2) the local archive `pipeline/0-archive/{date}_{host}_{slug}.md` (link-rot protection). This applies to sources captured by the `source-archive` skill, **not** to collected pipeline articles (see below):

```markdown
According to the vendor docs[^1] [(local copy)][^1-local], a skill description is ≤ 500 words.

[^1]: https://example.com/docs/skills
[^1-local]: pipeline/0-archive/2026-05-02_example.com_skills.md
```

If there is no archive (the source is internal — `pipeline/3-synthesis/`) one link is enough. For **collected pipeline articles** (`pipeline/1-incoming/` / `pipeline/2-curated/`) the article file is itself the provenance copy, so the source entry's `url + date + tier` is enough and `archive:` points at the article path (or is omitted, per `docs/CONVENTIONS.md` §5.1) — **ingest does NOT halt when a collected source lacks a 0-archive copy.** Only research-session web fetches need both links; that 0-archive copy is created automatically by the `source-archive` skill.

### Multi-source provenance (record ALL distinct sources)

When the synthesis drew on **more than one** article/domain, record **every** distinct source as its own `sources:` frontmatter entry (`url, archive, date, tier`) — not just the first or "best" one. This is what makes downstream multi-source corroboration computable: `scripts/corroborate.py` derives the independent-source count from the concept's `sources:` list per `docs/CONVENTIONS.md` §16.

- **Preserve independence — never collapse different domains.** Two sources on different registrable domains (eTLD+1) are **two** entries, even when they cover the same story. Collapsing near-duplicate/syndicated texts (one wire-story reprinted on many sites) into one independent source is the **downstream** job of `scripts/dedup.py` + `scripts/corroborate.py`, not this skill. Ingest records; corroboration counts. 10 reprints of one story = 10 raw entries here → collapsed to 1 independent source downstream.
- **Single-source honesty.** A concept built from only ONE source — or several reprints of a single story — is recorded exactly as such. Do not pad `sources:` and do not phrase the concept as if multiple independent sources confirm it. The digest emits a caution line ("⚠ Single-source — treat with caution", §16) derived from this list; an over-stated `sources:` yields a false "✓ Confirmed by N independent sources" badge. Under-recording is the opposite error — it understates real confidence.
- **Cite multi-corroborated facts to each source.** A `## Key facts` bullet confirmed by several sources cites each of them.

Where every fact happens to trace to a single web source, both links on that fact suffice; the rule above only adds entries when **distinct** sources exist.

**Forbidden: unsourced facts.** A fact without a source-link → REJECT write + AskUserQuestion "add URL/path or skip?". If the user insists — mark `unsourced: true` in frontmatter + a body "Change history" entry (date + reason); it queues for re-sourcing. **Legacy facts without a source** are not deleted — mark `unsourced: true` and queue for re-sourcing.

## Provenance tag (hard rule)

**Every new fact / concept create / update MUST contain a provenance tag** — a pointer to the upstream task. Without one — **write is rejected**.

**Format (one of):** `[research:{slug}]` · `[lesson:{date}]`.

**Where:** in the body next to the fact (`Default single-model behaviour [research:2026-05-04_model-comparison]. Source: ...`) OR in the body "Change history" section on UPDATE (`2026-05-10 [research:...] — added §8.1.1 ...`) — history lives in the body, not in frontmatter.

**Why:** trace lineage between `brain/` and upstream records (audit trail) · easy re-fetch on TTL re-validation · prevents orphan facts. **Enforcement:** Phase 3 pre-write check — every new fact has a provenance reference; missing → halt "add a provenance tag for each new fact".

## Frontmatter stamping (hard rule — every write)

Per `docs/CONVENTIONS.md` §5.1, every concept leads with YAML frontmatter (`title, type: concept, tags, created, last_updated`; optional `source_url, last_verified, ttl_days`). On **every** write:

- **UPDATE:** stamp `last_updated: <today>` (leave `created` untouched).
- **CREATE:** set both `created: <today>` and `last_updated: <today>`.

The weekly digest / `build_digest` selects updated concepts by the frontmatter `last_updated` field, **not** file mtime — a write that does not refresh `last_updated` is invisible to the digest. Pre-write check (Phase 3): the write carries `last_updated: <today>`; missing → halt "stamp last_updated for this write". SEED/EXAMPLE notes carry `tags: [seed, example, ...]` so the digest excludes them.

## Cross-linking & confidence

- **Cross-linking:** when a new fact relates to another concept → add `[[concepts/related]]` to the "Related concepts" section of both notes (bidirectional). This is what populates Obsidian backlinks and the graph view.
- **Cold-start crosslink exception (per `docs/CONVENTIONS.md` §10):** the crosslink hard-gate is **relaxed for the FIRST concept in an empty/near-empty cluster** — when no real (non-SEED/EXAMPLE) sibling exists to link to, CREATE a self-standing root note **without** an outbound `[[wikilink]]` (rather than forcing BACKLOG or linking to a SEED/EXAMPLE note). A real sibling = a `brain/concepts/*.md` whose `tags:` contain neither `seed` nor `example` and that matches the candidate's `domain`/`tags`. Once ≥1 real sibling exists, the normal bidirectional crosslink rule resumes. This keeps automatic/unattended mode writing the first concepts of a fresh vault instead of BACKLOGging them all.
- **Confidence:** when new data refutes old data → revise the concept's `confidence:`. Refuted facts are marked `[REVISED 2026-MM-DD]` (not deleted).

## Phase 1.5 — Cross-link presence check

An incoming `type: lesson` with no non-empty `related_concept:` AND no `parent_playbook:` → **soft-flag in the Phase 2 AskUserQuestion** "Lesson has no cross-link → it will be an orphan note (no backlinks, absent from the graph view). Continue / assign crossref / skip?". It does not block automatically (detect-only philosophy) but gives the user an explicit choice. An incoming `type: concept` with no `sources:` → a similar flag (less common — a concept without sources is almost always a bug). The verdict for this case: `ORPHAN_RISK_HOLD`.

## Phase 2 — verdict gate

> **Mode switch (`INTERACTIVE`):** the templates below apply in **interactive mode** (`INTERACTIVE=true`, manual on-demand). In **automatic mode** (`INTERACTIVE=false`, scheduled `weekly-synthesis` — no human present) the AskUserQuestion is NOT fired; instead apply the **recommended-default** verdict (the option marked "(Recommended)") per the same Phase 1 decision rules. ORPHAN_RISK_HOLD auto-resolves (assign `related_concept:` by best `domain`/`topic_tags` match, else BACKLOG — never silently orphan). All hard rules still hold; a hard-rule violation halts and logs even in automatic mode. See SKILL.md § Automatic (unattended) mode.

**Main verdict (≤4 options per AskUserQuestion, interactive mode):**

> What do we do with the findings from {artifact name}?
> - **A.** Update `concepts/X.md` (N new facts, M sources) — recommended
> - **B.** Create a new `concepts/Y.md` (topic not covered)
> - **C.** Backlog in INDEX only, not now
> - **D.** Skip — findings don't warrant a concept-level note

**ORPHAN_RISK_HOLD (if the incoming lesson has no crossref) — a separate AskUserQuestion BEFORE the main one:**

> Lesson `{slug}.md` arrived without `related_concept:` and without `parent_playbook:`. This creates an orphan note in the vault (no backlinks, absent from the graph view). What do we do?
> - **A.** Assign `related_concept:` now — give a concept slug
> - **B.** Assign `parent_playbook:` — if it's an operational pattern, not a conceptual lesson
> - **C.** Create a new concept for this lesson → Phase 2 main flow as CREATE
> - **D.** Accept orphan status deliberately — acceptable for temporary / experimental notes

Default recommendation: A or C (prevents orphan debt). Only after resolution — the main verdict question.

## Verdicts (Phase 1 output)

- `UPDATE existing` — concept exists, needs new facts / sources / confidence change
- `CREATE new` — concept absent; the entity is large enough for its own note
- `IGNORE` — trivial / already in outputs / not knowledge-relevant
- `BACKLOG` — worth creating, but not in this pass (`brain/INDEX.md` § Backlog)
- `RETIRE_LESSON` — lesson > 30 days without integration and the topic never became a concept → `brain/lessons/retired/{YYYY-MM}/`
- `ORPHAN_RISK_HOLD` — incoming lesson with no crossref → hold until the Phase 2 AskUserQuestion

## Activation timing — required upstream closure signal (one of)

- `research-build`: verification-log.md with `gate_status: passed` **or `gate_status: soft-pass`** (the unattended/internal-corpus verdict — threshold gate disabled by design, a valid closure not a block); Format complete; final artifact in `pipeline/3-synthesis/`. Only `gate_status: blocked` is a non-closure.
- manual note: a finalized note in `brain/lessons/{date}_{slug}.md` with substantive content recorded

Closure signal absent → halt "wiki-ingest requires a completed upstream task; current state: {detected_state}. Finish the upstream skill first."
