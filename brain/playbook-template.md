---
schema_version: 1   # frontmatter contract version (CONVENTIONS §5.4); leave as-is
title: "{Method name}"
type: playbook
status: draft        # draft | reviewed | retired
tags: [domain/topic]
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
related_concept:
  - "[[concepts/some-concept]]"
source_concepts:
  - brain/concepts/some-concept.md
sources:
  - url: "https://..."
    archive: pipeline/2-curated/{topic}/{file}.md
    date: YYYY-MM-DD
    tier: high|medium|low
---

# {Method name}

## When to use

Use this playbook when {trigger condition or recurring situation}.

## Inputs

- {Input 1}
- {Input 2}

## Steps

1. {Do the first concrete action.}
2. {Check the result or decision point.}
3. {Record the output in the relevant concept or lesson.}

## Outputs

- {Expected artifact, decision, or update}

## Checks

- [ ] Every claim or decision rule links back to a concept or source.
- [ ] The playbook has at least one `related_concept`.
- [ ] The result is reusable, not a one-off task note.

## Related notes

- [[concepts/some-concept]]

## Change history

| Date | Change | Source |
|---|---|---|
| YYYY-MM-DD | Created playbook draft | wiki-ingest / manual |
