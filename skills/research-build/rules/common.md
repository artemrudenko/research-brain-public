# Common Rules — research-build

Last updated: 2026-06-15

Project-specific paths and defaults. Override the inline references in `SKILL.md`.

## File Paths (variables used in SKILL.md)

| Variable | Path |
|---|---|
| `OUTPUT_ROOT` | `pipeline/3-synthesis/` |
| `RAW_ROOT` | `pipeline/3-synthesis/` |

The synthesized research document and its raw materials both live under
`pipeline/3-synthesis/`. The output is a plain Markdown research document — the
engine does no styled rendering.

## Minimum Source Counts
- `overview`: 5 sources minimum
- `deep`: 10 sources minimum

**`PROFILE=internal-corpus` exception:** the minimum web-source count does NOT apply. The
curated corpus (`pipeline/2-curated/{topic}/index.md` + the linked `pipeline/1-incoming/{topic}/`
articles) is the source set. Eligibility is gated upstream by `weekly-synthesis` against
`synthesis.min_sources_per_topic` (default 3), not by this minimum.

## Profiles (`PROFILE` input)

Per `docs/CONVENTIONS.md` §10:

- **`standard`** (default) — manual deep-dive; requires an upstream `research-frame` brief in
  `planning/research/` and a `research-grep` inventory; downstream `research-audit` uses the
  `sources/` tier-registry if present and applies the 30% gate.
- **`internal-corpus`** (unattended auto path, invoked by `schedule/weekly-synthesis.md`) —
  synthesize from `pipeline/2-curated/{topic}/` + `pipeline/1-incoming/{topic}/`; the brief
  (`planning/research/`), the `research-grep` inventory, and the `sources/` tier-registry are all
  OPTIONAL (absence → soft warning, never a halt). `research-audit` runs in soft mode (no >30%
  block; citation-guard + recency annotation retained). Dedup defaults + citation-guard stay on.

## Output Format
Research artifacts are plain Markdown documents (scrollable, single file).

## Existing-Knowledge Baseline

If the research topic is already partially covered by the knowledge base, **before
collecting sources** consult the vault:

- Run `wiki-query` against `brain/concepts/` to find existing concept pages.
- Run `research-grep` over the local corpus (`pipeline/`, `brain/`) for prior material.

Use any matches as:
- **Baseline** — what is already documented, to avoid duplication.
- **Gap analysis** — what the current material does not yet cover.
- **Context** — the existing structure of the topic in the vault.

---

## Raw File Write (Phase 2b — mandatory)

- Path pattern: `{RAW_ROOT}/{topic-kebab}/raw_{YYYY-MM-DD}.md`
- Tool: `Write` — overwrite if it already exists (re-run case)
- Timing: write BEFORE any synthesis step — even for `overview` depth

## WebSearch Pattern (Phase 2)

```
Search query: "{topic} {angle} site:arxiv.org OR site:..."
Max results per query: 10
Queries per research run: 5–10 (from Phase 1 plan)
```

## WebFetch Pattern (Phase 2)

```
Fetch full page: WebFetch(url="{source_url}", format="text")
Extract: title, author, date, key claims, statistics, verbatim quotes
```

If WebFetch fails (paywall/403): note the URL as inaccessible, find an alternative source.

## Bash Path Check (Phase 0)

```bash
ls pipeline/3-synthesis/
```
Run to confirm `RAW_ROOT` exists before the first write.
