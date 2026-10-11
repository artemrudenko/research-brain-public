# Knowledge Vault — Map of Content (MOC)

> **Primary front doors:** [`concepts.base`](concepts.base), [`lessons.base`](lessons.base),
> and [`playbooks.base`](playbooks.base). Open them in **Obsidian (>=1.7)** for live,
> auto-updating views over concepts, atomic lessons, and reusable methods. This `INDEX.md`
> is the plain-markdown **fallback** for older Obsidian or non-Obsidian readers.

> A **hand-curated** map of this vault. Not generated — you edit it by hand as the vault
> grows. The Obsidian graph view shows the *live* structure; this MOC is the human-readable
> entry point.

> **Completeness is checked (advisory) by `scripts/validate_brain.py`:** the hygiene pass
> warns when a non-seed concept in `brain/concepts/` is not listed here (by `[[link]]`, stem,
> or title), so this hand-maintained fallback doesn't silently drift behind the vault. It is a
> warning only — `validate_brain` never auto-rewrites this MOC. The one sanctioned automatic
> write: `scripts/concept_write.py` (the wiki-ingest atomic writer) safety-net-lists any
> concept it writes that nothing here references yet, under **“Recently added (file into a
> cluster)”** — move those lines into the right cluster as you curate.

> **Navigation model:** the **front door is the concept / this MOC** — start here. **Tags are
> a secondary filter** (narrow within a domain), and the **graph view is a demo** of how notes
> connect, **not** the way you navigate.

This is the first thing the **`wiki-query`** skill reads on any research-intent query.
The lookup contract:

1. Read this MOC.
2. Open the 1-2 concept notes most relevant to the query (follow the `[[wikilinks]]` below).
3. From an open note, follow its **Related notes** links / backlinks to surface adjacent
   knowledge.
4. If nothing here covers the query → fall back to filename / tag search in
   `brain/concepts/`, then to `research-grep` over the raw corpus.

There is **no generated index** and **no counts tracked here** — Obsidian's graph view,
search, and tag pane are the live index. Don't restate "N concepts" anywhere; open the
graph to see the real structure.

---

## How to use this MOC

- Each cluster below groups related concepts. Links are `[[wikilinks]]` — click them in
  Obsidian to jump to the note.
- Some links below are **placeholders / examples** until real notes exist. Replace them as
  you add concepts.
- When you create a concept, add a one-line entry under the right cluster (or start a new
  cluster). Keep entries to a single descriptive sentence.

---

## Thematic clusters

### Example cluster (seed — replace)
Two linked example notes ship with the vault so the graph has at least one edge:
- [[example-concept-a]] — first seed concept (links to the second).
- [[example-concept-b]] — second seed concept (links back to the first).

### {Your cluster A}
- [[concept-name]] — one-line description.
- [[another-concept]] — one-line description.

### {Your cluster B}
- [[yet-another-concept]] — one-line description.

### Playbooks (reusable methods)
- [[playbooks/method-name]] — when and how to run a repeatable method.

---

## Backlog

Topics seen but not yet worth a full concept (thin material, or already covered 1:1
by a `pipeline/3-synthesis/` deliverable). `wiki-ingest` parks rows here; promote one
to a cluster above once it reaches critical mass. Format: `topic — sources — priority`.

- _(none yet)_

---

## Live structure

The clusters above are a *curated summary* grouped by **domain tag**. They can lag behind the
real vault. For the live set:

- **Browse concepts:** open [`concepts.base`](concepts.base) in Obsidian (>=1.7) - the
  **By domain** cards group concepts by their top-level domain tag automatically.
- **Browse lessons:** open [`lessons.base`](lessons.base) for atomic facts and watchlist
  items that still need integration.
- **Browse playbooks:** open [`playbooks.base`](playbooks.base) for reusable methods and
  procedural knowledge.
- **See connections:** open this folder in Obsidian and use the **graph view** (the search
  filter is pre-tuned to hide infrastructure files and show only knowledge notes).

Note **counts are not tracked here** — Obsidian Bases show the live set. Don't
restate "N concepts" anywhere.
