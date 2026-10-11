---
name: concept-manage
description: "User-facing CRUD over the concept vault (brain/concepts/). One intent per turn: CREATE a new monitored concept via a short interview (name → sources → keywords/tags → run research → fill the note), LIST concepts, UPDATE (re-research) one, or ARCHIVE / RESTORE one (soft-delete, never a hard delete). Mechanical ops (list/backlinks/archive/restore) go through scripts/concept_manage.py; CREATE and UPDATE orchestrate the existing chain (source-manage → research-frame gateway, which routes via wiki-query/research-grep to research-build → wiki-ingest). Distinct from source-manage (monitors a feed, no note) and brain-ask (read-only system state). Triggers: 'new concept', 'create a concept', 'track this as a concept', '/concept new', 'list concepts', 'show my concepts', '/concept list', 'update concept X', 'refresh concept X', '/concept update', 'archive concept X', 'delete concept X', 'restore concept X', '/concept archive', '/concept restore', 'новый концепт', 'создай концепт', 'список концептов', 'обнови концепт', 'заархивируй концепт', 'удали концепт', 'восстанови концепт'."

metainfo:
  category: [knowledge-management]
  type: worker
  domain: brain
  last_updated: 2026-06-28
  predecessor: [setup-wizard, source-manage]
  successor: [research-frame, wiki-ingest]
---

# concept-manage — browse, create, refresh & soft-delete concepts

The synthesis pipeline (`wiki-ingest`) CREATEs and UPDATEs concepts on its own as
a byproduct of the weekly run. This skill gives the **user** direct, single-intent
control over the concept vault between runs:

| Intent | What it does | Backed by |
|---|---|---|
| **new** | Interview → stand up a **monitored** concept and fill its note | `source-manage` + research chain + `wiki-ingest` |
| **list** | Enumerate concepts (title, tags, source count, freshness) | `scripts/concept_manage.py list` |
| **update** | Re-research an existing concept and add what's new | research chain + `wiki-ingest` (UPDATE) |
| **archive** | **Soft-delete** a concept (move out of the vault, restorable) | `scripts/concept_manage.py archive` |
| **restore** | Bring an archived concept back into the live vault | `scripts/concept_manage.py restore` |

> **A concept is a monitored entity, not a one-off snapshot.** `new` adds the
> topic + sources to `config/` (via `source-manage`) so the concept keeps growing
> in the weekly loop — it is not a single search that is then forgotten.

Mechanical reads/moves are **deterministic** and go through
`scripts/concept_manage.py` (atomic writes, never a hand-edit of `brain/`). The
content-bearing flows (`new`, `update`) reuse the research chain and route every
write through `wiki-ingest` — this skill never authors concept markdown directly.

---

## When to Use

**Use when** the user wants ONE concept-vault change:
- "create a concept for **X** / track **X** as a concept" → `new`.
- "list / show my concepts", "what concepts do we have on **X**" → `list`.
- "update / refresh the **X** concept" → `update`.
- "archive / delete the **X** concept" → `archive` (soft-delete).
- "restore / bring back the **X** concept" → `restore`.

**Skip / use the other skill when:**
- The user only wants to **monitor a feed/blog** with no synthesized note →
  `source-manage` (`/add`). A concept's note is the point here; a source's is not.
- A bare **read-only** question about system state ("what are we monitoring", "how
  often", "recent digests") → `brain-ask`, not this skill.
- It is **first-run / bulk** setup → `setup-wizard`.
- The user wants to **research a question** for an answer (not a durable note) →
  `research-frame`.

> **Boundary in one line:** `source-manage` manages **inputs** (feeds), this skill
> manages **outputs** (concept notes) — and the `new` wizard bridges them by
> setting up the inputs *and* producing the first note.

---

## DO / DON'T

**DO:**
- Handle exactly ONE intent per turn.
- **Clarify, don't invent.** For `new`, ask for the missing pieces in plain words
  (name, what to watch, what to look for) — never guess a topic or source URL.
- Route every CREATE/UPDATE **through `wiki-ingest`** (its dedup, cross-linking,
  citation guard, and atomic write are the contract) — never write `brain/` by hand.
- For `archive`, **always surface the backlinks** the script reports: those
  concepts will have a broken `[[concepts/X]]` link. Offer to re-point or proceed.
- Default a "delete a concept" request to **archive (soft-delete)**, which is
  reversible — confirm before doing it, and mention `restore` exists.
- Use relative paths from the project root for every command.

**DON'T:**
- Don't **hard-delete** a concept file. The project never silently breaks the
  graph (ADR 0014) — archive + restore is the only deletion path.
- Don't run the full `setup-wizard` interview for a single concept.
- Don't author or edit concept markdown directly — that is `wiki-ingest`'s job.
- Don't invent sources, tags, or facts. A concept with an uncited fact is a bug.
- Don't treat `new` as a throwaway search — it registers a monitored topic.

---

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `INTENT` | enum | yes | — | new / list / update / archive / restore |
| `NAME` | string | for new/update/archive/restore | — | concept title or slug (e.g. `vector-databases`) |
| `SOURCES` | list[URL] | for new (asked) | — | feeds/pages to monitor for this concept |
| `KEYWORDS` | list[str] | for new (asked) | — | search terms / signals to look for |
| `TAGS` | list[str] | for new | proposed from `config/tags.yaml` | controlled-vocabulary tags (new ones → `pending:`) |
| `TAG_FILTER` | string | for list | — | restrict the listing to a tag or domain |
| `REASON` | string | for archive | `—` | why it's being archived (kept in the marker) |

Ask one focused question at a time (AskUserQuestion-style); confirm, then act.

---

## Steps

### Step 1 — Parse the single intent

Map the user's sentence to one `INTENT`; pull whatever fields are present.
Normalize a free-text name to a slug (`Vector Databases` → `vector-databases`);
if the slug is unclear, propose one and confirm.

### Step 2 — Run the intent

#### `list` — enumerate the vault (read-only)

```bash
python3 scripts/concept_manage.py list                       # human summary
python3 scripts/concept_manage.py list --tag ml              # filter by tag/domain
python3 scripts/concept_manage.py list --json                # machine view
python3 scripts/concept_manage.py list --include-archived    # show soft-deleted too
```

Relay the summary in plain language (title, tags, how fresh). Seed/example demo
notes are hidden by default (`--include-seed` to show them).

#### `new` — interview, then stand up a monitored concept

This is an **orchestration**, in order:

1. **Interview** (ask, don't invent):
   - "What should we call this concept?" → `NAME` (→ slug).
   - "Which sources should I watch for it?" → `SOURCES` (URLs/feeds).
   - "What words or signals should I look for?" → `KEYWORDS`.
   - Propose 2–5 `TAGS` from `config/tags.yaml`; a genuinely new tag goes to
     `pending:` (never invent a domain).
2. **Register the inputs** — for each source, call **source-manage** (it owns
   the active topics+sources config (via `scripts/manage_sources.py`), detects the type, confirms the trust
   level, and re-validates). This is what makes the concept *monitored*.
3. **Gather material** — run the research chain on `NAME` + `KEYWORDS`, entering
   through the **`research-frame` gateway** — frame itself routes onward via
   `wiki-query` / `research-grep` before `research-build` runs (never jump
   straight to `research-build`; `research-build` archives sources via
   `source-archive`).
4. **Create the note** — hand the gathered, cited material to **wiki-ingest**,
   which dedups against the vault, writes `brain/concepts/<slug>.md` atomically
   (via `concept_write.py`), cross-links it, and stamps frontmatter.
5. **Confirm** — show the new concept (`concept_manage.py list --tag …`) and note
   that it will keep updating on the weekly run.

> If the user explicitly wants a **one-off snapshot** (no ongoing monitoring),
> skip step 2 and tell them the concept won't auto-update.

#### `update` — re-research an existing concept

1. Confirm the concept exists (`concept_manage.py list` / `backlinks`).
2. Run the research chain on the concept's topic to gather **what's new**.
3. Route the delta through **wiki-ingest** in UPDATE mode — it appends to
   `Key facts`, refreshes `sources:`, stamps `last_updated` (+ `last_verified`),
   and records a `[REVISED YYYY-MM-DD]` change-log row. Never overwrite history.

#### `archive` — soft-delete (reversible)

```bash
python3 scripts/concept_manage.py backlinks <slug>           # who links to it?
python3 scripts/concept_manage.py archive <slug> --reason "superseded"
```

- Confirm with the user first (it's a deletion, even if reversible).
- The script moves the note to `brain/.archive/concepts/` (a folder Obsidian
  ignores), leaves a dated, restorable marker, and **reports inbound backlinks**.
- Relay those backlinks: "these N concepts will now have a broken link — restore,
  re-point, or leave them?" Don't hide a broken-graph side effect.

#### `restore` — bring an archived concept back

```bash
python3 scripts/concept_manage.py restore <slug>
```

Moves it back into `brain/concepts/`, strips the archive marker, and adds a
change-log row. Refuses (non-zero) if a live concept already claims that slug —
relay that and ask how to resolve.

### Step 3 — Confirm in plain language

Report what changed (and, for `archive`, any links that broke) without exposing
internal jargon. A non-technical user should understand the outcome in one line.

---

## Output

A one-line plain-language confirmation of the single change, plus — for `new` and
`update` — the resulting concept's title/tags, and — for `archive` — the list of
backlinks that now need attention. The backend script's stdout (atomic, idempotent)
is the source of truth; relay its result rather than re-describing the file system.
