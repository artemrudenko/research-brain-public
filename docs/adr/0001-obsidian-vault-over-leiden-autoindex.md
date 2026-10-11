# ADR 0001 — Use an Obsidian vault instead of Leiden/AUTO_INDEX/kb generated indices

- **Status:** Accepted (backfilled 2026-06-24)
- **Tags:** knowledge-store, obsidian, indexing

## Context
The system stores durable knowledge as plain Markdown and needs a navigation/graph layer
over it. The personal toolkit this was extracted from used generated artifacts — a Leiden
community-detection pass, `AUTO_INDEX` files, and a `kb` index. Those are derived data the
system must build and keep in sync, i.e. gardening cost and drift.

## Decision
Store knowledge in `brain/` as an **Obsidian vault** and let Obsidian's native primitives be
the index: the graph + backlinks, the `concepts.base` (Bases) front door, and the `brain/INDEX.md`
MOC as a fallback. Concepts link via `related_concept:` frontmatter + shared tags (not only inline
`[[wikilinks]]`). Do **not** generate auxiliary indices, knowledge-graph files, or AUTO_INDEX
artifacts.

## Consequences
- Zero index-gardening: the front door updates itself as notes appear; no rebuild step to drift.
- No server/DB — just Markdown the user can open in Obsidian directly.
- The graph is a demo, not navigation; the concept/MOC is the real front door (CONVENTIONS §14).
- Cost: edges live in Obsidian-native form, so a plain Markdown reader (e.g. an OKF consumer) does
  not see them; this is an interoperability limitation.

## Alternatives considered
The replaced approach itself: Leiden / AUTO_INDEX / a generated `kb` index. Rejected because the
Obsidian graph + backlinks + tags provide the same navigation natively, without generated indices
to build and keep healthy.

## References
- `docs/CONVENTIONS.md` §14 (Obsidian reading layer), §5.1 (concept frontmatter).
- `AGENTS.md` — Mandatory rules ("Knowledge lives in `brain/` as an Obsidian vault").
