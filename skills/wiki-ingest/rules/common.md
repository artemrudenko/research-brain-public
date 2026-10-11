# wiki-ingest — Vault Paths & Conventions

Last updated: 2026-06-15

The knowledge base is an Obsidian vault under `brain/`. `brain/INDEX.md` is the hand-curated MOC (Map of Content). Navigation relies on Obsidian `[[wikilinks]]` (backlinks) and the graph view — there is no generated index. All paths below are vault-relative from the project root (`{{VAULT_ROOT}}`).

## File paths

| Variable | Path |
|---|---|
| `BRAIN_ROOT` | `brain/` |
| `BRAIN_INDEX` | `brain/INDEX.md` (hand-curated MOC) |
| `CONCEPTS_DIR` | `brain/concepts/` |
| `CONCEPT_TEMPLATE` | `brain/concept-template.md` |
| `PLAYBOOKS_DIR` | `brain/playbooks/` |
| `LESSONS_DIR` | `brain/lessons/` |
| `LESSON_TEMPLATE` | `brain/lesson-template.md` |
| `LESSONS_RETIRED_DIR` | `brain/lessons/retired/` |

## File naming

- Concept: `{slug}.md` where slug = kebab-case topic (e.g., `agent-quality-system`, `agents-md-skill-standard`)
- Playbook: `{slug}-playbook.md` (e.g., `iso-42001-implementation-playbook.md`)
- Lesson: `{YYYY-MM-DD}_{slug}.md` (e.g., `2026-04-30_token-hygiene-lessons.md`)

## Concept note sections (mandatory, in order)

1. Title (`# {Concept}`)
2. Header block (last updated / confidence / domain tags)
3. Sources (Internal artifacts / External — split)
4. What it is (1-2 paragraphs)
5. Why it matters
6. Key facts (with source attribution per bullet)
7. Related concepts (`[[concepts/X]]` cross-links — powers backlinks + graph view)
8. Open questions / gaps
9. Change history (table)

## Confidence levels

| Level | When |
|---|---|
| `high` | ≥3 independent sources + verified, OR confirmed by a real project |
| `medium` | 2 sources, or one authoritative source, not yet verified in practice |
| `low` | 1 source, or a hypothesis, or an unverified extrapolation |

## Domain tags (closed-book from `config/tags.yaml`)

Tags are NOT chosen from a list in this file — pick them **closed-book** from the
controlled vocabulary in `config/tags.yaml` (the FIXED registry). See SKILL.md
§ Tagging and `docs/CONVENTIONS.md` §11.

- Tag format is nested `domain/topic` (e.g. `ai/agents`); a bare `domain` (e.g.
  `ai`) is also a valid tag and natively groups its `domain/*` children.
- **2–5 tags per concept, with ≥1 domain-level tag.**
- If nothing in `config/tags.yaml` fits → propose **≤1** new `domain/topic` into
  the file's `pending:` (quarantine) — NEVER write a new tag straight into
  `domains:`, and do NOT ask via AskUserQuestion. `scripts/validate_brain.py` is
  **advisory** and only *recommends* promotion; the actual promotion of a `pending:`
  tag into `domains:` (after it recurs across ≥3 notes) is applied by
  `scripts/promote_tags.py` in the weekly-run brain-hygiene step.

## When CREATE vs UPDATE vs BACKLOG vs RETIRE_LESSON

| Signal | Decision |
|---|---|
| New facts ≤2 + relate to an existing concept | UPDATE existing |
| New facts ≥3 + a new angle OR a new entity not yet covered | CREATE new |
| Topic mentioned for the first time, but little material (1 source) | BACKLOG |
| Topic is cosmetic / a narrow special case | IGNORE (not in brain) |
| Lesson > 30 days without integration, topic never became a concept | RETIRE_LESSON (move to `lessons/retired/{YYYY-MM}/`) |

## Lesson-specific rules

When processing a lesson source:
- If the lesson has `related_concept: [[concepts/X]]` — it is the first UPDATE candidate; AskUserQuestion confirms
- If the lesson has `related_concept: (none)` — try matching by `domain_tags`; if a match exists → propose UPDATE; if not → CREATE new or BACKLOG
- On UPDATE from a lesson: add facts to the concept's § Key facts, the source to § Sources as `brain/lessons/{file}.md → originally pipeline/0-archive/{path}/{article}.md` (two-level source chain)
- After integration, mark the lesson `related_concept: [[concepts/X]]` (if not already) — for a future audit trail and so the graph view connects them

## Lesson retirement rule

A lesson is considered retired (orphan beyond useful life) if:
- `extracted_at` was > 30 days ago
- `related_concept: (none)` (never integrated)
- The lesson's topic never became a concept in that period
- It is not referenced by any new research artifacts

Action: move it to `brain/lessons/retired/{YYYY-MM}/`. The file is preserved (audit) but is not counted in the main flow.

## When to refuse to run

- The `brain/` directory does not exist
- `brain/concept-template.md` is missing
- `BRAIN_INDEX` is empty or contains a "vault not initialized" marker
- **Mid-session activation**: if the upstream task (research-build) is not yet closed — halt with a recommendation
- **Speculative ingest**: never ingest a "potentially useful" fact without upstream artifact closure

---

## SKIP-table — what NOT to record in brain/concepts/

> Pattern source: [Orchestra-Research/AI-Research-SKILLs](https://github.com/Orchestra-Research/AI-Research-SKILLs) (MIT, clean-room adopted).

Filter pass: in Phase 1 (Diff), for each extracted fact / entity / concept candidate from the upstream artifact — check against the SKIP-table. On a match — drop it without even an AskUserQuestion. This protects `brain/` from bloat with speculative / ephemeral / out-of-scope content.

| # | NOT to record | Why excluded | Where it belongs instead |
|---|---|---|---|
| **S1** | **Ephemeral state** — current session conversation context, todo lists, transient task items, work-in-progress notes | brain/ = post-validated knowledge; ephemeral state belongs in a task list / queue | a task queue or task list |
| **S2** | **Personal opinions without general applicability** — user-specific preferences, single-session reactions, mood / context-of-the-moment | brain/ = domain knowledge, not a personal log | (skip), or a feedback note if it's an actionable rule |
| **S3** | **Narrowly scoped briefs** — research gathered specifically for a single one-off purpose | inherently scoped to the conversation; not general | the relevant `pipeline/3-synthesis/` folder only |
| **S4** | **Numeric specifics with a very high decay rate** — exact prices / quotas / model context windows | TTL <30 days — ingest cost > re-fetch cost. Reference the external source instead | external sources cited in the research artifact only; NOT brain/ |
| **S5** | **Unsourced facts** — claims without a verified upstream URL / archive / lesson reference | brain/ source-link hard rule | re-fetch + cite, or drop |
| **S6** | **Already covered 1:1** — an `pipeline/3-synthesis/` deliverable already covers the topic 1:1 | duplication; an INDEX backlog reference is enough | `brain/INDEX.md` § Backlog with a pointer to pipeline/3-synthesis/ |
| **S7** | **Internal tooling minutiae** — exact command flags / one-time CLI invocations / debug session traces | trivial implementation detail, not durable knowledge | `brain/lessons/{date}_{slug}.md` if recurring + actionable; otherwise drop |
| **S8** | **Speculative "could be useful"** — facts with no current workflow application | YAGNI; brain/ = applied knowledge | `brain/INDEX.md` § Backlog with a trigger condition |
| **S9** | **Private specifics** — confidential configurations / private data / proprietary details | confidentiality + not general | a restricted folder with access control |
| **S10** | **Vendor marketing copy** — overclaim phrases without a verifiable benchmark | brain/ filtered against marketing overclaims | (drop, or filter before re-evaluating) |
| **S11** | **Already-deprecated patterns** — superseded conventions / old names | brain/ = current state of the art, not historical | `archive/superseded/{date}_{topic}/` if worth preserving |
| **S12** | **Pure ASCII art / formatting samples** — templates, mermaid examples, visual demos | non-knowledge; structural assets | `templates/` |

### SKIP-table application timing

- **Phase 1 (Diff):** filter pass first — drop SKIP-matches before mapping to existing concepts. Saves AskUserQuestion overhead.
- **Phase 3 (Apply):** secondary check — even if a concept is selected, pre-write filter each new fact against the SKIP-table. Bonus catch.

### Edge cases

- **Mixed-content artifacts:** if an upstream artifact contains BOTH ingestable AND SKIP-categorized content — extract only the ingestable part, drop SKIP fragments.
- **Borderline ephemeral:** "text mentions current price $X" — drop unless framed as "X-tier pricing as of {date}" with an explicit volatility tag.
- **Recurring SKIP signals:** if SKIP-categorized content recurs across ≥3 sessions with the same theme — flag "maybe the SKIP-table needs a new row".

## Provenance tag enforcement

- Every new fact / concept create / update MUST contain a provenance tag (`[research:slug]` / `[lesson:date]`)
- Pre-write check (Phase 3): missing → halt with the recommendation "add a provenance tag for each new fact"
- A body "Change history" entry is mandatory on UPDATE, with the provenance tag included (history lives in the body, not in frontmatter)

---

## Tool usage detail

### Phase 1 (Diff) — tool usage

```
Read: new_artifact (just created)
Read: brain/INDEX.md  (the MOC)
Read: brain/concepts/*.md (top-3 most likely candidates by domain-tag match)
```

Do not read ALL concepts — that wastes tokens. Use tag matching from `## Key facts` headings or the domain tags in the header.

### Phase 2 (AskUserQuestion) — tool spec

```python
AskUserQuestion(
  questions=[{
    "question": "What do we do with the findings from {artifact_name}?",
    "header": "Vault update",
    "multiSelect": false,
    "options": [
      # Recommended option first, labelled (Recommended)
      {"label": "Update concepts/X.md (Recommended)",
       "description": "{N} new facts, {M} new sources; confidence stays high"},
      {"label": "Create new concepts/Y.md",
       "description": "Topic appears for the first time with critical mass"},
      {"label": "Backlog in brain/INDEX.md",
       "description": "Topic mentioned, but material is still thin"},
      {"label": "Skip / IGNORE",
       "description": "Findings don't warrant a brain-level note"}
    ]
  }]
)
```

Don't ask more than one question at a time. If there are many proposed updates — use a series of independent questions or multiSelect.

### Phase 3 (Apply) — tool usage

#### UPDATE existing

```
Read: brain/concepts/{slug}.md (full)
Edit: add facts to § Key facts, the source to § Sources, a row to § Change history
Edit: brain/INDEX.md if confidence/domain tags changed (hand-curated MOC)
```

Don't use Write for a full rewrite — use targeted Edit.

#### CREATE new

```
Read: brain/concept-template.md
Write: brain/concepts/{slug}.md (filled-in template)
Edit: brain/INDEX.md — add a one-line [[wikilink]] entry under the right thematic cluster by hand
Edit: add a [[wikilink]] to at least one related note so backlinks + the graph view connect it
```

#### BACKLOG

```
Edit: brain/INDEX.md § Backlog — add a row (topic, sources, priority)
```

### Cross-linking on CREATE

If the new concept references existing notes `[[concepts/X]]` — also Edit `concepts/X.md` § Related concepts to add the back-reference. Bidirectional links power Obsidian backlinks and the graph view.

### Verification after Apply

After Edit:
1. `grep -c "Source:" brain/concepts/{slug}.md` — every fact has a source
2. `grep "\[\[concepts/" brain/concepts/{slug}.md` — wikilinks are valid (the target notes exist)
3. Read `brain/INDEX.md` — the concept is listed under a thematic cluster in the MOC

Report a short summary to the user: "Updated concepts/X.md (3 facts, 2 sources). New cross-links: [[concepts/Y]]. INDEX (MOC) synced."

### Token budget

- Diff phase: ≤30K tokens (read ≤3 concepts + the new artifact + INDEX.md)
- Apply phase: ≤10K (only the needed Edits)
- Total per run: ≤50K target

If the budget is exceeded — refuse, and suggest the user run wiki-ingest narrowly: "update concepts/X.md from {artifact}".
