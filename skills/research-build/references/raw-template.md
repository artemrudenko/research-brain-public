# Raw Materials Template — research-build

Reference file for the `research-build` skill. Used in Phase 2b when saving collected sources.

---

## Save Location

```
{RAW_ROOT}/{topic}/raw_{YYYY-MM-DD}.md
```

`{RAW_ROOT}` = `pipeline/3-synthesis/` (defined in `rules/common.md`).

---

## File Format

The file starts with a **mandatory frontmatter block**, then the Markdown body.

```markdown
---
title: "Raw Materials — {TOPIC} — {YYYY-MM-DD}"
type: source
status: active
created: {YYYY-MM-DD}
last_updated: {YYYY-MM-DD}
topic_tags: [{tags from the brief topic_tags if present, else omit field}]
---

# Raw Materials — {TOPIC} — {DATE}

**Sources collected:** N
**Search queries used:** [list from Phase 1]

---

## SOURCE 1 — {Title}
**URL:** {url}
**Author/Org:** {author}
**Date:** {date}
**Relevance:** {which core question this addresses}

{Full extracted text — copy as close to verbatim as possible. Do not paraphrase.
Include: statistics, quotes, definitions, examples, code snippets, tables.
Preserve original formatting where possible.}

---

## SOURCE 2 — {Title}
...
```

### Frontmatter fields (mandatory unless marked optional)

| Field | Source | Rule |
|---|---|---|
| `title` | derived: `"Raw Materials — {TOPIC} — {YYYY-MM-DD}"` | descriptive, not a generic "Raw note" — TOPIC matches the `{topic}` slug in the path |
| `type` | constant: `source` | raw research inputs feeding synthesis |
| `status` | constant: `active` | lifecycle (becomes `archived` when synthesis closes and the raw file moves to `pipeline/0-archive/`) |
| `created` | today's date | YYYY-MM-DD, matches `{YYYY-MM-DD}` in the filename |
| `last_updated` | today's date | identical to `created` at write; updated when the raw file is patched (e.g. additional sources appended) |
| `topic_tags` | optional — copy from the brief `topic_tags:` if present | open free-form list. Omit the field entirely if empty (don't write `topic_tags: []`). |

---

## Rules for Raw Save

- Copy text as close to the original as possible — do not rephrase or summarize yet
- Include ALL data points, statistics, quotes — even if they seem redundant
- Mark contradictions between sources inline: `⚡ CONFLICTS WITH SOURCE N`
- If a source has more content than needed, include the relevant sections in full
- This file is the ground truth — the synthesis in Phase 3 builds from it

**This phase is non-negotiable:** even for `overview` depth, a raw file must exist.
Without a raw file, there is no verifiable audit trail for claims in the final document.
