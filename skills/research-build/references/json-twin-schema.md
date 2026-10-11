---
title: "JSON-twin synthesis schema"
type: reference
status: active
created: 2026-05-10
last_updated: 2026-06-15
parent_skill: research-build
---

# JSON-twin synthesis schema

> A structured companion file `{slug}.json` alongside `{slug}.md`, for programmatic chaining
> (external orchestration, downstream tools that consume claims/sources without parsing Markdown).

**Activation:** opt-in via the brief frontmatter `emit_json_twin: true` OR
`audience: programmatic-chain` (research-build Phase 4.7).

---

## Top-level schema (v1.0)

```json
{
  "schema_version": "1.0",
  "generated_by": "research-build",
  "generated_at": "2026-05-10T12:00:00Z",
  "research_brief_path": "pipeline/3-synthesis/topic-slug/2026-05-10_topic-slug.brief.md",

  "research_question": "Full text of research_question from the brief frontmatter",
  "audience": "leadership | external | internal",
  "depth": "quick | standard | deep",
  "source_modality": "mixed | research-tier | social-pulse | regulatory",

  "claims": [
    {
      "id": "C1",
      "text": "A single-sentence conceptual assertion",
      "section": "Where this claim appears in the md (anchor / heading)",
      "evidence_grading": "🟢🟢 Definitive | 🟢 High | 🟢- Moderate | 🟡 Low | 🔴 Very-Low | ⚫ Insufficient",
      "evidence_type": "official-doc | peer-reviewed-equivalent | vendor-attested | aggregator-attested | expert-opinion | community-discussions | self-attested",
      "sources": ["S1", "S3"],
      "misinfo_flag": "none | fabrication | distortion | outdated | conflation"
    }
  ],

  "sources": [
    {
      "id": "S1",
      "title": "Source title",
      "url": "https://...",
      "host": "example.com",
      "tier": "T1 | T2 | T3 | unregistered",
      "fetched_at": "2026-05-10T11:30:00Z",
      "hash": "sha256:abc123...",
      "archive_path": "pipeline/3-synthesis/topic-slug/raw_2026-05-10.md"
    }
  ],

  "structured_findings": {
    "key_takeaways": [
      "Top 3–5 takeaways in order of importance"
    ],
    "open_questions": [
      "Unresolved questions / known unknowns"
    ],
    "counter_arguments": [
      "Counter-arguments or contrary evidence found in the Critique pass"
    ]
  },

  "verification_summary": {
    "phase": "verify | critique | both",
    "claims_total": 25,
    "green_count": 18,
    "yellow_count": 5,
    "red_count": 2,
    "red_threshold": 0.30,
    "red_ratio": 0.08,
    "threshold_met": true
  },

  "rigor_score": {
    "applied": true,
    "score_pct": 100.0,
    "verdict": "🟢🟢 Strong (exemplary) | 🟢 Strong | 🟡 Adequate | 🔴 Marginal | ⚫ Insufficient",
    "dim_scores": {
      "clarity": 4,
      "accuracy": 4,
      "completeness": 4,
      "objectivity": 4,
      "actionability": 4,
      "source_quality": 4
    }
  },

  "downstream_hints": {
    "wiki_ingest_targets": ["concept-slug-1", "concept-slug-2"],
    "format_recommendations": "md"
  }
}
```

---

## Field semantics

### `claims[]`

Each claim is an atomic synthesizable assertion. **Granularity rule:** one claim = one falsifiable
statement. Compound claims should be split.

**`evidence_grading` enum** (6-level taxonomy):
- `🟢🟢 Definitive` — direct primary-source quote / official authoritative
- `🟢 High` — ≥2 T1 sources cross-confirmed
- `🟢- Moderate` — single T1 + ≥1 T2 cross-confirmed
- `🟡 Low` — single T2 OR ≥2 T3 only
- `🔴 Very-Low` — single T3 OR contradicted by a primary source
- `⚫ Insufficient` — no sources OR speculation

`evidence_type` and `misinfo_flag` enums mirror the `research-audit` taxonomy.

### `sources[]`

Each source is a single addressable artifact. `hash` is required for drift detection downstream.

### `verification_summary`

Mirror of the `research-audit` verify-gate output. `threshold_met` = (red_ratio ≤ red_threshold) —
the gate-pass criterion.

### `rigor_score`

Only present if `research-audit` ran in extended mode. Captures the 6-dimension rigor reviewer
output for leadership artifacts.

### `downstream_hints`

Optional advisory fields for skill orchestration:
- `wiki_ingest_targets` — candidate concept slugs for `wiki-ingest` (post-task)
- `format_recommendations` — suggested format if the artifact gets re-rendered

---

## Validation

The JSON-twin should be valid against JSON Schema 2020-12.

**Hard rules:**
- `schema_version: "1.0"` mandatory (forward compat)
- `claims[*].sources[*]` IDs must reference existing `sources[*].id` entries (referential integrity)
- `verification_summary.threshold_met` must match the `red_ratio ≤ red_threshold` calculation
- All datetime fields ISO 8601 UTC

---

## Downstream consumers

| Consumer | Use case |
|---|---|
| `wiki-ingest` | Uses `downstream_hints.wiki_ingest_targets` to gate concept updates |
| External skill chains | Programmatic ingestion without Markdown parsing overhead |
