# extract-patterns — patterns for extracting verifiable claims from a draft md

Reference material. Loaded from SKILL.md in Phase 0 Step 2 when working with non-standard drafts (structured tables, footnote-heavy, multi-paragraph claims). Base triggers are in `rules/common.md` § "Verifiable claim patterns".

---

## Markdown structure → claim mapping

### Inline citation pattern (footnote-style)

```markdown
According to the vendor docs[^1], product X supports a 200K-token context window.

[^1]: https://docs.example.com/about/models
```

**Extraction:**
- Claim text: "product X supports a 200K-token context window"
- Source: `docs.example.com` (T1 vendor docs)
- Type: vendor-claim (own product) → single T1 sufficient → 🟢

### Inline link pattern

```markdown
Tool Y [released](https://example.com/changelog/v2.0) version 2.0 in Q3 2026.
```

**Extraction:**
- Claim text: "Tool Y released version 2.0 in Q3 2026"
- Source: `example.com`
- Type: vendor-claim, numeric (version + date)

### Quote-with-attribution pattern

```markdown
The author states: "the right prompt is worth 10× more than the right fine-tune".
```

**Extraction:**
- Quote-attribution — an opinion, not verifiable factual unless the supporting claim is numeric
- Numeric claim ("10×") → flag as verifiable; attribution → the author's site (T2)

### Statistic-without-attribution pattern (anti-pattern in a draft)

```markdown
70% of companies are piloting LLM tools in 2026.
```

**Extraction:**
- A numeric statistic with no footnote → flag as "unsupported" immediately
- Marker → 🔴 (no source — cannot verify)
- Recommendation: add a footnote or remove from the draft

---

## Table-based claims

### Pricing comparison table

```markdown
| Tool | Price | Context |
|---|---|---|
| Tool A | $15/M tokens | 200K |
| Tool B | $20/M tokens | 256K |
```

**Extraction approach:**
- Treat each cell with a number as a separate claim
- Source: the header row or a footnote under the table
- If no source → the entire table is flagged 🔴 ("table without a source citation")

**Best practice (recorded in the verification-log recommendations):** every table with numeric values should have a footnote beneath it with links to per-vendor docs.

### Feature matrix

```markdown
| Feature | Tool A | Tool B |
|---|---|---|
| Plugin support | ✅ | ❌ |
| Hooks | ✅ | ❌ |
```

**Extraction:**
- Each ✅/❌ → vendor-claim (presence/absence of a feature)
- If the feature claim is about a competitor (Tool B ❌) — requires cross-source (a vendor describing a competitor is biased)
- Verify via `docs.{vendor}.com` for each cell

---

## Multi-paragraph claim patterns

### Cumulative claim (spread across paragraphs)

```markdown
In 2024 the company launched its product. By early 2026 it already had N enterprise customers,
including Fortune 500 firms. Its growth was 10× year-over-year.
```

**Extraction:**
- 3 separate claims: "launched in 2024", "N customers", "10× YoY growth"
- Each → a separate entry in `claims_list`
- The shared attribution may be at the bottom: "Per a CEO interview" — applies to multiple claims

### Conditional claim

```markdown
If the regulation comes into force as planned in Q3 2027, vendors with GPAI obligations
will have to disclose training-data summaries.
```

**Extraction:**
- Conditional ("if X then Y") — verifiable parts:
  - "the regulation is planned for Q3 2027" — verifiable factual
  - "vendors with GPAI obligations must disclose training-data summaries" — verifiable from the regulation text
- The logical link ("if-then") is not verifiable — it's inference, marked non-verifiable

### Forward-looking statements

```markdown
The vendor plans to release version 5 by the end of 2026.
```

**Extraction:**
- A forward-looking promise — flag specifically: "forward-looking statement, not yet delivered"
- Verify only the attribution and the date in the plan (if announced — current) — do not verify delivery (hasn't happened yet)
- Tier: T1 (announcement page) sufficient → 🟢, but add a hedge "as announced" / "planned" to the claim text

---

## Sources section in a draft

### Standard pattern

Most drafts end with a "## Sources" section. Footnote refs ([^1], [^2]) → a list of URLs.

**Extraction:**
- Immediate map: footnote ID → URL → host → tier
- Cross-check: every footnote ID mentioned in the body must have an entry in Sources; otherwise → broken footnote (warning)

### Inline-only (no Sources section)

- Older drafts may have only inline links without a Sources section
- Extraction: regex on `\[.*\]\(https?://...\)` + footnote-style `\[\^\d+\]`
- Build the host list manually

### Mixed style

Combine both + dedup. If one URL is cited N times — count it as one source with N claims attached.

---

## Edge cases

### Footnote with a local archive (dual link)

```markdown
According to the vendor docs[^1] [(local copy)][^1-local], skills require minimal frontmatter.

[^1]: https://docs.example.com/agents-and-tools/skills
[^1-local]: materials/raw/2026-05-02_docs.example.com_skills.md
```

**Handling:** treat as a single source; the primary URL is for the tier lookup, the local archive for the recency lookup (read the frontmatter `published` / `fetched_at`).

### Citation chain (X cites Y cites Z)

```markdown
An analysis (Q2 2026)[^1] cites an analyst report[^2]: 60% adoption.

[^1]: https://analysis.example.com/...
[^2]: https://analyst.example.com/...
```

**Handling:**
- Primary source — the analyst report (T2, original)
- Secondary chain (the analysis citing it) — additional context, not a replacement
- Verify the analyst report's availability; if behind a paywall → manual hand-off
- Tier for the claim — T2 (the analyst)

### Self-citation (vendor citing its own past blog)

```markdown
In a blog post last year[^1] the vendor announced a 200K context window. Since then → 1M.
```

- First claim ("200K declared in 2024") — T1 vendor blog, single sufficient
- Second claim ("200K → 1M") — needs confirmation from current `docs.{vendor}.com`, otherwise 🟡

### Code blocks with verifiable values

```markdown
\`\`\`yaml
context_window: 200000
\`\`\`
```

- Code block content → if it looks like a config/spec, treat the values as verifiable
- Source — usually the adjacent prose; if none — flag

---

## Output: claims_list schema

```yaml
claims:
  - id: C1
    text: "Product X supports a 200K-token context window"
    type: vendor-claim
    source_refs:
      - footnote_id: 1
        url: https://docs.example.com/about/models
        host: docs.example.com
        tier: T1
        published: 2026-04-15  # from materials/raw/ frontmatter
        local_archive: materials/raw/2026-05-02_docs.example.com_models.md
    cross_source: single-authoritative
    recency_check: ok
    marker: 🟢
    reason: "Vendor primary docs, single T1 sufficient for an own-product claim"

  - id: C2
    text: "70% of companies are piloting LLM tools in 2026"
    type: numeric
    source_refs: []  # no footnote
    cross_source: unsupported
    recency_check: n/a
    marker: 🔴
    reason: "Numeric statistic without a citation — impossible to verify"
```

This schema is used internally in Phase 6/7 for structured tracking; the final verification log is rendered from this dict.

---

## Anti-patterns during extraction

- ❌ Treating subjective claims ("better", "more convenient") as verifiable — skip them
- ❌ Treating recommendations ("better to pick X") as factual claims — that's inference, not fact
- ❌ Splitting one factual claim into multiple — "Product X supports a 200K context window" is one claim, not two
- ❌ Combining several claims into one — "the vendor shipped A in 2024 and B in 2025" is two claims with different verifications
- ❌ Skipping extraction from tables — tables are often densely packed with verifiable claims; always process them
