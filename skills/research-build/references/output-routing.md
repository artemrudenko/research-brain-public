# Output Routing — research-build

Reference file for the `research-build` skill. Used in the Output phase to decide where to save the synthesized document.

---

## Output Location

`{OUTPUT_ROOT}` = `pipeline/3-synthesis/` (defined in `rules/common.md`).

The synthesized research document is written as a single Markdown file directly under
`pipeline/3-synthesis/`. There is no topic-based folder routing and no styled rendering —
the output is a plain, topic-agnostic Markdown document.

If the vault organizes synthesis output by topic, place the file in a per-topic subfolder
that mirrors the raw materials path (`pipeline/3-synthesis/{topic-kebab}/`); otherwise write
it flat under `pipeline/3-synthesis/`.

---

## Filename Convention

| Output | Pattern |
|---|---|
| Synthesized document | `{topic}-research.md` — kebab-case |

Use the raw-materials topic slug as the base name so the document and its raw file
(`pipeline/3-synthesis/{topic}/raw_{YYYY-MM-DD}.md`) stay associated.

---

## Document Structure by Depth

### `overview` (5–8 sources)
1. Executive Summary (3–5 sentences)
2. Key Findings (5–7 bullets with source attribution)
3. Implications (2–3 sentences)
4. Sources

### `deep` (10+ sources)
1. Executive Summary
2. Context and Background
3. [Topic-specific sections — 3–5 based on core questions]
4. Key Conclusions and Recommendations
5. Open Questions / What We Still Don't Know
6. Sources

---

## Sources Section Format

Per source:
`[Author/Organization] — [Title] — [Platform] — [URL] — [Date]`

Minimum: `overview` → 5 sources · `deep` → 10 sources.
