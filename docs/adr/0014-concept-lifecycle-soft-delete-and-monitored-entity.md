# ADR 0014 — Concepts are soft-deleted (archive + restore), never hard-deleted; a user-created concept is a monitored entity

- **Status:** Accepted (2026-06-28)
- **Tags:** concepts, vault, lifecycle, deletion, concept-manage

## Context
The synthesis pipeline CREATEs and UPDATEs concepts on its own (`wiki-ingest`), but users
had no deterministic way to **browse, delete, or restore** a concept by hand between runs.
The `concept-manage` skill (+ `scripts/concept_manage.py`) adds that user-facing CRUD —
`/concept new | list | update | archive | restore`. Two design questions it answers are
load-bearing and non-obvious, so they belong in an ADR rather than living only in code:

1. **What does "delete a concept" mean?** Concepts form a graph: each note links to others
   via `related_concept:` and `[[concepts/X]]` wikilinks. A hard `rm` of one note silently
   turns every inbound link into a broken link. The advisory brain-hygiene pass (CONVENTIONS
   §13) already establishes that the system **flags, never deletes** — but §13 governs
   *hygiene*, not a user-invoked deletion path; it does not by itself define one.
2. **What is a user-created concept — a one-off snapshot, or a standing entity?**

## Decision
**1 — Soft-delete only.** `archive` MOVES a concept out of the live vault to
`brain/.archive/concepts/` (a dot-folder Obsidian ignores, so the note leaves the graph view,
yet git still tracks it so it stays recoverable), wraps it in a dated, sentinel-marked
restorable callout, and **reports the inbound backlinks** that the move turns into broken
links so the caller can re-point or accept them knowingly. `restore` reverses the move and
strips the marker; it refuses to clobber a live concept that has claimed the same slug. The
move is atomic (`registry.atomic_write_text` + unlink). There is **no hard-delete path** for
concepts — `wiki-ingest` already forbids deleting facts, and this extends the same "never
silently break the graph" principle to whole notes.

**2 — A user-created concept is a monitored entity.** `/concept new` interviews the user
(name → sources → keywords/tags) and **registers the sources via `source-manage`** so the
concept keeps growing in the weekly loop, then runs the research chain and routes the first
note through `wiki-ingest`. A one-off snapshot (no ongoing monitoring) is the explicit
opt-out, not the default.

## Consequences
- **The graph never breaks silently.** A deletion always surfaces its blast radius
  (backlinks) and is always reversible.
- **Archived notes are invisible to Obsidian, hygiene, and `list`** (non-recursive `*.md`
  glob over `brain/concepts/`), but remain in git history and restorable.
- **`new` deliberately couples to `source-manage` + the research chain + `wiki-ingest`** —
  an orchestration across skills that is unusual in the architecture and intentional.
- The deletion semantics are now anchored to a real decision instead of an over-broad reading
  of CONVENTIONS §13 (which is about hygiene, not deletion).

## Alternatives considered
- **Hard-delete with a confirmation prompt.** Rejected — even confirmed, it leaves dangling
  `[[concepts/X]]` links across the vault and is irreversible; soft-delete + restore gives the
  same outcome safely.
- **Tombstone in place (mark `[DEPRECATED]` but keep the file in `brain/concepts/`).**
  Rejected — the note stays in the graph view and in `list`/hygiene, defeating the point of
  removing it; moving it out of the vault is cleaner and still reversible.
- **Treat `/concept new` as a one-off research snapshot.** Rejected as the default — it
  reduces a durable, compounding asset to a throwaway search; monitoring is the differentiator.
  Kept as an explicit opt-out.

## References
- `skills/concept-manage/SKILL.md` (the user-facing contract; `new`/`update`/`archive`/`restore`).
- `scripts/concept_manage.py` (`archive_concept`, `restore_concept`, `find_backlinks`; the
  `brain/.archive/concepts/` location + sentinel marker).
- `docs/CONVENTIONS.md` §13 (brain-hygiene: flags, never deletes — the principle this extends).
- ADR 0005 (controlled-vocabulary tagging) and the `wiki-ingest` "never delete facts" rule.
