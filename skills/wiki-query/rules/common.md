# wiki-query — Project Paths & Conventions

Last updated: 2026-06-15

All paths are relative to the project root (`{{VAULT_ROOT}}`).

## File paths

| Variable | Path |
|---|---|
| `BRAIN_ROOT` | `brain/` |
| `BRAIN_INDEX` | `brain/INDEX.md` (the hand-curated Map of Content / MOC) |
| `CONCEPTS_DIR` | `brain/concepts/` |

`brain/` is an Obsidian vault. Discovery uses the `brain/INDEX.md` MOC plus Obsidian
`[[wikilinks]]` / backlinks and file/tag search — there is no generated index.

## Token budget per run

- Read INDEX (MOC): ~3-5K tokens
- Read 1 concept: ~5-7K tokens
- Read 2 concepts (max): ~10-14K tokens
- **Cap per run: 25K tokens** before moving to the Answer step

If the budget is exceeded, the question is too broad. Forward to `research-grep` when
`VAULT_ONLY=false`; otherwise report the vault lookup limit and offer deeper research.

## Match criteria — keyword to concept

### Hard match

Match query keywords against the concept titles and the query-guide entries in
`brain/INDEX.md`. The MOC is the lookup table; do not maintain a duplicate keyword
table here (it would drift). When a concept is not yet listed in the MOC, fall back
to a filename or tag search in `brain/concepts/`.

### Tag match

If a query keyword matches a concept's topic tags (≥2 hits), that is a strong match signal.

### Soft match

Match via semantic relation (e.g. 'AI quality' → a quality-related concept). Use with
care — prefer to confirm via AskUserQuestion on a partial match.

## When to decline running

- `brain/INDEX.md` does not exist → the vault is not initialized
- `brain/concepts/` has fewer than 2 concepts → not enough of a base

In these cases, hand control to `research-grep` immediately with the note 'vault empty /
not initialized' unless `VAULT_ONLY=true`. A vault-only request reports the empty state
and offers research without starting it.

## Confidence in the answer to the user

| Concept confidence | What to tell the user |
|---|---|
| `high` | Direct answer with the source, no caveats |
| `medium` | 'Based on our current data, X. This is medium confidence — worth confirming via {gap from Open questions}.' |
| `low` | 'Hypothesis: X. Confidence is low — recommend research-build to widen the base.' |

## Logging

After each run, print a short summary to the console:
- `wiki-query → match=high, concepts_read=[<name>], answered_from_vault`
- `wiki-query → match=partial, concepts_read=[<name>], forwarded_to_research-grep`
- `wiki-query → no_match, vault_only=true, offered_research`
- `wiki-query → no_match, vault_only=false, forwarded_to_research-grep`

Useful for tracking the vault-cache-hit rate (≥30% is the target).

## Always-volatile topics

Fast-moving topics where a compiled note can go stale quickly (recommend current-source
research regardless of `last_verified`): model/API pricing and capabilities, tool/IDE
features, regulation and policy, security advisories. Local inventory still comes first;
the `research-grep` choice gate controls external research. Maintain the project's list in a
project config note if you want it enforced consistently; otherwise apply judgement.

---

## Tool usage detail

### Match step — tool usage

```
Read: brain/INDEX.md (full)
```

One Read per run. Parse it by keyword-matching against the query guide and the concept
table in the MOC.

**Do not use Grep / Glob** at this step — unnecessary overhead; the MOC is compact and
parses directly. (Grep/Glob over `brain/concepts/` is an acceptable fallback only when the
MOC does not list a likely concept.)

### Read step — tool usage

```
Read: brain/concepts/{matched}.md
[If the concept references [[related-concept]] via wikilinks / backlinks]
Read: brain/concepts/{related}.md  # max 1 additional
```

### Read step alternative (partial match) — AskUserQuestion for vault-only requests

When a forwarded research request (`VAULT_ONLY=false`) is already underway, hand an uncovered
partial concept to `research-grep` as context instead of asking again whether to continue. The
skill's local inventory runs first and its existing choice gate still controls external research.
Use the interactive choice below for a direct vault-only lookup.

```python
AskUserQuestion(
  questions=[{
    "question": "Found concept {name} (Confidence: {level}). It looks close but not an exact match. What do we do?",
    "header": "Vault match",
    "multiSelect": false,
    "options": [
      {"label": "Enough — answer from this concept",
       "description": "Source: brain/concepts/{name}.md. Answer relies only on the compiled facts."},
      {"label": "Supplement via research-grep (Recommended)",
       "description": "Use the concept as a baseline + grep the raw corpus to fill gaps. Costs more tokens, more complete."},
      {"label": "Full research from scratch",
       "description": "Ignore the vault, run a full research-build. Most expensive option."}
    ]
  }]
)
```

### Answer step — format

```
From {concept_name} (Confidence: {level}):

{1-2 paragraphs answering the query}

**Key facts:**
- {fact 1} — Source: `concepts/{name}.md` § Key facts; underlying: <path or URL>
- {fact 2} — Source: ...

**Open questions** (not fully covered):
- {gap from § Open questions, if relevant to the query}

Enough, or dig deeper via research-build?
```

### Forward step — pattern

```
Not in the vault yet. Switching to research-grep to grep the raw corpus.
[Hand control over by activating the research-grep skill]
```

After research-grep finishes — do NOT run wiki-ingest automatically. The user decides via a
direct trigger if the result is worth compiling into the vault.

For `VAULT_ONLY=true`, replace the forward with:

```
Not in the vault yet. I checked {keywords/topic} and found no matching concept.
I can research it next if you want.
```

Do not open the raw corpus or web until the user explicitly opts in.

### Verification

After Answer:
1. Does every claim have a source link? If not — rephrase.
2. Is confidence stated? If medium/low — is there a caveat?
3. Are Open questions mentioned when present in the concept?

After Forward:
1. Was research-grep activated?
2. Was context passed (which keyword was searched, what was not found in the vault)?

### Anti-patterns

- Reading the raw corpus (collected sources / prior outputs) in the Match/Read steps — that is research-grep's job
- Reading >2 concepts — token waste; prefer partial match → AskUserQuestion → forward
- Grep over brain/ as the primary lookup — the `brain/INDEX.md` MOC exists precisely so Grep is not needed (Grep is a fallback only)
- Omitting the source — even a correct fact without attribution looks like a hallucination
