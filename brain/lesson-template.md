---
schema_version: 1   # frontmatter contract version (CONVENTIONS §5.4); leave as-is
type: lesson
source: pipeline/0-archive/{YYYY-MM}/{category}/{YYYY-MM-DD}_{slug}.md
url: https://...
extracted_at: YYYY-MM-DD
tags: [topic-a, topic-b]
related_concept: [[some-concept]]   # >=1 link REQUIRED (related_concept OR parent_playbook) — keeps the note in the graph; an empty value creates an orphan
# parent_playbook: [[playbooks/some-method]]   # alternative to related_concept when the lesson is operational
confidence: high | medium | low
---

# Lesson: {Title} — {N} key facts

## Facts

- **Fact 1.** {1-2 concrete sentences}.
- **Fact 2.** ...
- **Fact 3.** ...

(No more than 5 atomic facts per lesson; otherwise split, or promote the article to a full concept.)

## Why kept

{Why this fact was worth extracting — which decision it informs, which open question it
closes, or which hypothesis it confirms or contradicts.}

For example:
- Closes open question Q1 in [[some-concept]]
- Confirms / contradicts a claim in [[another-concept]]
- Useful when the topic "{scenario}" comes up

## Suggested integration

Where this knowledge should land:
- **UPDATE concept [[some-concept]]** — add fact 1 under § Key facts
- **CREATE concept** — if no note covers this topic yet
- **Playbook [[playbooks/some-method]]** — if the fact is operational, not theoretical
- **(Forward-ref)** — if no suitable concept exists yet, set `related_concept: [[new-concept]]` as a forward-ref and mark it CREATE (wiki-ingest will create the note). A lesson with no `related_concept`/`parent_playbook` is an orphan — if no link is possible, archive the article instead of adding it to `brain/lessons/`.

## Context (optional)

Extra context from the source: what made this fact stand out; what in the article was
noise and ignored; what (if anything) in the article contradicts existing notes.

---

**Frontmatter fields:**
- `source` — path to the archived article (in `pipeline/0-archive/` after triage)
- `url` — original link
- `extracted_at` — when the extract was made (= the triage decision date)
- `tags` — free-form topic tags; Obsidian indexes them (tag pane + search)
- `related_concept` / `parent_playbook` — **>=1 required** (keeps the note linked in the graph). Use `[[concept]]` to cross-link, or a forward-ref to a not-yet-created concept (CREATE via wiki-ingest). An empty value leaves a dangling note disconnected from the graph.
- `confidence` — high/medium/low confidence in the facts (separate from a concept's confidence)
