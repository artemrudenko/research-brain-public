# brain/ — your knowledge vault (Obsidian)

This folder **is an Obsidian vault**. Open it in [Obsidian](https://obsidian.md) to browse
the graph, follow backlinks, and search. Everything is plain Markdown, so it also reads
fine in any editor or in Cowork / Claude Code — Obsidian just adds the graph view, backlink
panel, and tag pane on top.

The vault is the durable memory of the research pipeline: collected sources get distilled
into the notes here, and the `wiki-query` / `wiki-ingest` skills read and write them.

## How to browse (non-technical)

You don't need to maintain anything — pick whichever fits:

1. **Open [`concepts.base`](concepts.base) in Obsidian** (version >=1.7). It is a live
   database of every concept: use the **All concepts** table, or the **By domain** cards to
   browse by topic. It updates itself as notes are added - no upkeep.
2. **Open [`lessons.base`](lessons.base) or [`playbooks.base`](playbooks.base)** when you
   want atomic facts/watchlists or reusable methods instead of synthesized concepts.
3. **Use the tag pane** (left sidebar in Obsidian). Click a domain like `#ai` and it expands
   to every `#ai/topic` underneath it. Tags are a *secondary* filter for narrowing down.
4. **No Bases?** On older Obsidian or outside Obsidian, open **[`INDEX.md`](INDEX.md)** - the
   hand-curated map of the same concepts. It's the fallback front door.

## What lives where

| Folder | Holds | Lifespan |
|---|---|---|
| `concepts/` | **Durable distilled knowledge** — synthesized answers to recurring questions. One topic per note. | Long-lived; updated over time. |
| `lessons/` | **Atomic facts / watchlists** — small, single-fact extracts from individual sources that aren't (yet) a full concept. | Promoted into a concept, or kept as a standing fact. |
| `playbooks/` | **Reusable methods** — step-by-step procedures you re-run (a research routine, a triage method, etc.). | Long-lived; refined as you learn. |

Templates: `concept-template.md`, `lesson-template.md`, and `playbook-template.md` (copy
them when creating notes).

## How linking and the graph work

- **Wikilinks** — write `[[note-name]]` to link one note to another. Obsidian turns it into
  a clickable link and records a **backlink** on the target note (see the Backlinks panel).
- **Graph view** — every wikilink is an edge. The graph view visualizes the whole vault so
  you can see clusters and orphans at a glance. This **replaces** any generated index or
  knowledge-graph build — the links *are* the index.
- **Tags** — `#tag` in a note (or `tags:` in frontmatter) groups notes by topic in the tag
  pane and search.
- **MOC** — `INDEX.md` is a hand-curated Map of Content: the human entry point and the first
  file `wiki-query` reads. It is not generated and does not track counts.

## Entry points

- `INDEX.md` — start here (the curated MOC).
- `concepts.base`, `lessons.base`, `playbooks.base` — live Obsidian Bases front doors.
- Obsidian graph view — start here to see the live structure.
- To hide the `INDEX` / `README` scaffolding files so the graph shows knowledge, not
  machinery, paste `-file:INDEX -file:README` into the graph view's search filter once
  (Obsidian keeps it as local per-vault state — the vault ships no `.obsidian/` settings).
  The vault root is `brain/`, so only `brain/` notes (concepts / lessons / playbooks)
  appear in the graph.
