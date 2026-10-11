---
title: "Research-Frame — Research-brief output template"
type: asset
last_updated: 2026-06-15
applies_when: "Phase 3 — Generate research-brief"
---

# Research-brief output template

Canonical skeleton written to `planning/research/{YYYY-MM-DD}_{slug}.md` in Phase 3.

```yaml
---
title: "Research brief — {slug}"
type: brief
status: active
created: 2026-05-02
last_updated: 2026-05-02
topic: agent-tooling                  # primary topic tag (see config/topics.yaml)
topic_tags: [...]                     # open free-form list

research_question: "{question 9}"
depth: standard | quick | deep
audience: internal-review | strategic-leadership | ...
format: research-artifact-md | chat-answer | ...
sources_mode: hybrid | internal-only | web-from-scratch
source_modality: mixed | research-tier | social-pulse | regulatory  # auto-adjusted per always-volatile keywords
recency_max: 12mo
min_tier: T1+T2

grading_mode: standard | extended  # auto-set: extended when audience=strategic-leadership
critique_log:
final_artifact:
materials_used: []

generated_by: ai-then-human-edited
---

# Research brief — {slug}

**Research question:** {question 9}

## Frame contract
| Field | Value |
| ... | ... |

## Lifecycle
- [x] **Frame** — this file (✓ created {date})
- [ ] **Inventory** — `wiki-query` → `research-grep`
- [ ] **Gather**
- [ ] **Synthesize**
- [ ] **Verify**
- [ ] **Critique**
- [ ] **Format**
- [ ] **Archive**
```

**Slug generation:** kebab-case of the first 3-5 key words of research_question (e.g., "Where does tool A win over tool B in enterprise?" → `tool-a-vs-tool-b-enterprise`).

---

## Schema check

A research brief should satisfy these rules before being handed downstream:

- **R1 (required):** all mandatory frontmatter fields present + non-empty (research_question / depth / audience / format / sources_mode / source_modality / recency_max / min_tier / grading_mode)
- **R2 (required):** `grading_mode: extended` when `audience` is `strategic-leadership` (or variants like `founders` / `c-level` / `board`)
- **R3-R7:** filename pattern `{date}_{slug}.md` / slug constraints (kebab-case 6-60 chars, 3-5 words) / enums (recency_max / min_tier / format)
- **R8:** `source_modality` enum-conformance (mixed / research-tier / social-pulse / regulatory)

**On violations:** rerun `research-frame` Phase 3 to regenerate the brief with the full schema, OR edit the frontmatter manually (add a missing field / fix an enum / rename the file).
