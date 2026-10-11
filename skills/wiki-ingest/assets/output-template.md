---
title: "{Concept slug — human-readable name}"
type: concept
tags: [domain/topic, domain/other]   # nested, ONLY from config/tags.yaml; 2-5 tags, ≥1 domain-level tag
created: {YYYY-MM-DD}                 # set once on CREATE — never changed afterwards
last_updated: {YYYY-MM-DD}           # stamped on EVERY write; the digest reads this, NOT mtime
related_concept:                      # machine-checkable links — the graph is built from this + tags
  - "[[concepts/related-one]]"
# contributors:                       # optional — [[authors/<slug>]] of the cited-source authors (wiki-ingest proposes these behind the same gate; omit when no author resolves)
#   - "[[authors/some-author]]"
sources:                              # anti-hallucination: every key fact below cites one of these.
                                      # Record ALL distinct sources the synthesis used — one entry per
                                      # source/domain. NEVER collapse different domains (corroboration is
                                      # counted downstream by scripts/corroborate.py, CONVENTIONS §16).
                                      # Single source → list exactly one (single-source honesty).
  - url: "https://{host}/{path}"
    archive: pipeline/0-archive/{YYYY-MM-DD}_{host}_{slug}.md   # flat source-archive convention (rules/common.md)
    date: {YYYY-MM-DD}
    tier: high                        # high | medium | low — shown in the digest
  - url: "https://{other-host}/{path}"   # a SECOND distinct domain → its own entry (independence signal)
    archive: pipeline/0-archive/{YYYY-MM-DD}_{other-host}_{other-slug}.md
    date: {YYYY-MM-DD}
    tier: medium
# Optional: last_verified: {YYYY-MM-DD}   ·   ttl_days: 180 (90 high-volatility / 180 default / 365 stable)
generated_by: wiki-ingest
---

# {Concept Title}

> A short 1-2 sentence definition.

## Key facts

- **Fact 1** — description [research:{slug}]. Source: [URL]({url}) ([local copy](pipeline/0-archive/...))
- **Fact 2** — description [research:{slug}]. Source: ...
- ...

## Context / Application

{Where it applies, which problems it solves.}

## Lessons

Atomic facts for `scripts/extract_vault_notes.py`. Include this section only when the
upstream artifact contains durable, source-backed facts useful outside this concept. Do not bury
lesson candidates only in prose or under Context / Application.

- {One source-backed atomic fact worth extracting as a lesson.}

## Playbook: {Reusable method name}

Draft procedure for `scripts/extract_vault_notes.py`. Include this section only when the upstream
artifact contains a reusable method, checklist, review loop, or decision procedure.

Use this when {trigger condition or recurring situation}.

1. {First concrete step.}
2. {Second concrete step or decision point.}
3. {Record the result back in the relevant concept or lesson.}

## Related concepts

- [[concepts/related-one]] — how it relates
- [[concepts/related-two]] — ...

> Cross-links here power Obsidian backlinks and the graph view. Always link at least one related note so this concept is not an orphan.

## Open questions / gaps

- {What is unknown or needs clarification}

## Change history

- {YYYY-MM-DD} — initial create from {upstream artifact} [research:{slug}]
- ...

## Sources

- {URL} ({tier}, fetched {date}) — [local archive](pipeline/0-archive/...)
- ...
