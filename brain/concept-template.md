---
schema_version: 1                     # frontmatter contract version (CONVENTIONS §5.4); leave as-is
title: "{Concept — human-readable name}"
type: concept
tags: [domain/topic, domain/other]   # nested, ONLY from config/tags.yaml; 2-5 tags, ≥1 domain-level tag (a SEED/EXAMPLE note adds `seed`, `example` so the digest excludes it)
created: YYYY-MM-DD                   # set once, on CREATE — never changed afterwards
last_updated: YYYY-MM-DD             # stamped by wiki-ingest on EVERY write; the digest reads this, NOT file mtime
related_concept:                      # machine-checkable links — the graph is built from this + tags, not only inline [[...]]
  - "[[concepts/other-note]]"
# contributors:                       # optional — [[authors/<slug>]] of the cited-source authors (proposed by wiki-ingest behind the same gate); backlink is the author's "everything they wrote" view
#   - "[[authors/some-author]]"
sources:                              # anti-hallucination: EVERY key fact below must cite one of these entries
  - url: "https://{host}/{path}"
    archive: pipeline/0-archive/{YYYY-MM}/{category}/{slug}.md
    date: YYYY-MM-DD
    tier: high                        # high | medium | low — source trustworthiness (shown in the digest)
# Optional (recommended for sourced/volatile concepts):
# last_verified: YYYY-MM-DD          # last time the facts were re-checked against the source
# ttl_days: 180                      # 90 high-volatility · 180 default · 365 stable
---

# {Concept}

> **Confidence:** high / medium / low

---

## Sources

The basis for this note. **Hard rule — every key fact in the body below MUST cite one of
these sources** (or an internal note). This is the anti-hallucination guard: a fact with no
traceable source does not belong in the note. These entries mirror the `sources:` frontmatter
(url / archive / date / tier).

### Internal notes
- `[[some-other-concept]]` — what was reused
- `[[lessons/some-lesson]]` — what was reused

### Collected material
- `pipeline/0-archive/{YYYY-MM}/{category}/{slug}.md` — verbatim capture (fetched YYYY-MM-DD)

### External sources
- [Title — Author](URL) — fetched YYYY-MM-DD

---

## What it is

1-2 paragraphs of plain-language definition. No jargon. If you had to explain it to
someone new to the topic, how would you put it?

## Why it matters

Why this concept is worth a durable note: what recurring question it answers, what
decisions it informs, what gap in your knowledge base it closes.

## Key facts

- Fact 1 — {one sentence}. Source: `pipeline/0-archive/.../X.md` / [Title](URL)
- Fact 2 — {one sentence}. Source: …
- Fact 3 — {one sentence}. Source: …

(5-10 key facts; if more, split into themed subsections.)

## How to apply it

Concrete ways this knowledge gets used — formulations, numbers, analogies, checks:
- When question "{typical question}" comes up → answer "{response}"
- Things to verify before relying on it: "{check 1}", "{check 2}"
- Anti-pattern: "{what not to conclude}"

## Lessons

Atomic, reusable facts that should become `brain/lessons/` notes through
`scripts/extract_vault_notes.py`. Include only facts that are useful on their own and already
source-backed above; leave this section empty or omit it when there are no good candidates.

- {One concrete sourced fact worth keeping as an atomic note.}

## Playbook: {Reusable method name}

A repeatable procedure that should become a draft `brain/playbooks/` note through
`scripts/extract_vault_notes.py`. Include this section only when the concept contains a reusable
method, checklist, review loop, or decision procedure; otherwise omit it.

Use this when {trigger condition or recurring situation}.

1. {First concrete step.}
2. {Second concrete step or decision point.}
3. {Record the result back in the relevant concept or lesson.}

## Related notes

Use Obsidian `[[wikilinks]]` so the graph view shows the connections:
- [[related-concept-a]] — how it relates
- [[related-concept-b]] — how it relates
- [[playbooks/usage-pattern]] — a method that builds on this concept

## Open questions / gaps

What you still **don't** know or know only partially. These gaps prioritize the next
round of research.

- Q1: ?
- Q2: ?

## Change log

| Date | What changed | Trigger |
|---|---|---|
| YYYY-MM-DD | Created note | Initial synthesis from {sources} |
| YYYY-MM-DD | Updated section X | wiki-ingest after research on {topic} |
