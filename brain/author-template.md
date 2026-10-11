---
schema_version: 1   # frontmatter contract version (CONVENTIONS §5.4); leave as-is
title: "{Author — full name as they publish it}"
type: author
identity_key: "{id:… | url:… | name:…|pub:…}"   # the shared identity ladder key (scripts/source_report/authors.py::identity_key); the collision-safe join used everywhere
identifier: ""        # ORCID / DOI author id / stable handle when known — else leave ""
profile_url: ""       # canonical profile / homepage when known — else leave ""
tags: [author]
created: YYYY-MM-DD    # set once, on CREATE — never changed afterwards
last_updated: YYYY-MM-DD   # stamped by wiki-ingest on EVERY write
---

# {Author}

<!--
  An author node is a FIRST-CLASS vault entity (Stage 9, model α) — "here is what we
  know of this person". It is BACKLINK-ONLY: the authoritative author↔concept link
  lives ON the concept, in its contributors frontmatter (`[[authors/<slug>]]`).
  So this node MUST NOT list its own concepts — the "everything they wrote" view is
  the Obsidian BACKLINK panel of the concepts that cite them. There is no generated
  list here, and no contributors field on the node itself.

  Keep the body minimal: identity, and optional human prose (affiliation, focus,
  why we track them). A script must NEVER emit this file — author nodes are written
  only through wiki-ingest's AskUserQuestion gate, like every other brain/ note.
-->

Optional one-paragraph note on who this is and why the vault tracks them.

## Identity

- **Name:** {full name}
- **Identity key:** `{identity_key}` — how this person is matched across the pipeline.
- **Identifier / profile:** {ORCID/handle/homepage, when known}

---

**Followed?** Whether we actively collect this author's new work is a separate
question — it lives in the roster (`config/authors.yaml`, managed by `/author`), not
here. `/author nodes` shows this node's `followed: yes/no` by cross-referencing the
roster read-only. A node is *never* auto-added to the roster, nor the reverse (Q4).
