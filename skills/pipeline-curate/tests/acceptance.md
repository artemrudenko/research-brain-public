# pipeline-curate — acceptance tests

Given/When/Then scenarios for the curation step. Run by reading the skill and walking each
scenario against a scratch copy of the pipeline.

---

## Scenario 1 — fresh incoming is promoted, indexed, and marked processed

**Given** `pipeline/1-incoming/ai-agents/2026-06-15_multi-agent.md` exists with valid
frontmatter (`title: "Building a multi-agent system"`, `url: https://example.com/ma`), a body
longer than `curate.min_text_chars`, and content matching the topic's Include rules,
**and** its registry row in `pipeline/registry.md` has a blank `status`,

**When** `pipeline-curate` runs,

**Then**
- `pipeline/2-curated/ai-agents/index.md` contains exactly:
  `- [Building a multi-agent system](../../1-incoming/ai-agents/2026-06-15_multi-agent.md) — <one-line summary>`
- the registry row for `https://example.com/ma` now reads `status=processed`,
- the run report lists `ai-agents: 1 kept`.

---

## Scenario 2 — an article excluded by rule is dropped

**Given** `pipeline/1-incoming/ai-agents/2026-06-15_hype.md` exists with valid frontmatter but
either (a) a body shorter than `curate.min_text_chars`, or (b) content matching the topic's
Exclude rules (off-topic / low-signal hype), **and** a blank registry status,

**When** `pipeline-curate` runs,

**Then**
- no line for `2026-06-15_hype.md` appears in `pipeline/2-curated/ai-agents/index.md`,
- its registry row now reads `status=rejected` (a terminal state — NOT `processed`, NOT blank),
- the file remains in `pipeline/1-incoming/ai-agents/`,
- the run report counts it under dropped (too-short or excluded).

---

## Scenario 2b — a rejected article is not re-judged on re-run

**Given** Scenario 2 has already run (the hype article's registry row reads `status=rejected`),
**and** no new articles were collected since,

**When** `pipeline-curate` runs a second time,

**Then**
- the hype article is skipped (not re-evaluated against the rules),
- its registry row stays `rejected` — unchanged,
- it does NOT appear in the digest's "needs attention" list (which surfaces only blank-status
  articles still awaiting a verdict).

---

## Scenario 3 — re-run is idempotent (no double-add, no re-mark)

**Given** Scenario 1 has already run (the multi-agent article is in `index.md` and its
registry row reads `processed`), **and** no new articles were collected since,

**When** `pipeline-curate` runs a second time,

**Then**
- `pipeline/2-curated/ai-agents/index.md` is unchanged — no duplicate line is appended,
- no registry row is rewritten,
- the run report shows `0 kept / 0 marked`.

---

## Scenario 4 — empty incoming is a no-op

**Given** `pipeline/1-incoming/ai-research/` is empty (or contains only articles already in a
terminal status — `processed` or `rejected`),

**When** `pipeline-curate` runs,

**Then**
- no `pipeline/2-curated/ai-research/index.md` is created (or it is left unchanged),
- `pipeline/registry.md` is unchanged,
- the run completes cleanly and reports `ai-research: 0 candidates`.
