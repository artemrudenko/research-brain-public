---
title: "Reader-subagent contract — extract, don't dump (context-bounded fan-out)"
type: reference
applies_when: "Any multi-source build (research-build Phase 2/2b/3, weekly-synthesis Step 3) where ≥5 synthesis-bound sources would otherwise be read full-text into the main agent's context"
last_updated: 2026-06-26
---

# Reader-subagent contract

> **The rule that prevents context exhaustion:** the **main agent never loads full
> article bodies into its own context**. Reader subagents read full text; they return
> only a compact **structured extract**. The main agent synthesises from extracts, not
> from raw bodies. This is the single biggest context win — fetching in parallel saves
> wall-clock, but *extracting* is what saves the main window.

Shared by `research-build` (Phase 2 Collect → 2b Raw → 3 Synthesise) and
`schedule/weekly-synthesis.md` (Step 3, internal-corpus). Both paths use one contract so a
change lands in one place (DRY).

---

## When to dispatch

| Sources to read (synthesis-bound) | Action |
|---|---|
| **< 5** | Read inline in the main agent — subagent overhead isn't worth it |
| **5 – ~12** | **One reader subagent per source/article** (the "1 agent per article" pattern) |
| **> ~12** | Group into **clusters of 2–4** by kind (vendor docs / analyst / community / regulatory / collected-corpus topic) → **one subagent per cluster**, keep the parallel count ≤ ~6 |

This **replaces** the old `depth: deep` AND `>10 sources` threshold — dispatch is now the
default for any build that would read ≥5 sources, regardless of `depth`. Synthesis
(holistic) still runs **sequentially in the main agent** — it cannot be decoupled — but on
the bounded set of extracts, so the preventive-pause budget rarely fires.

Dispatch all subagents of a wave in **one message with multiple Agent calls** so they run
concurrently.

---

## Return schema (each subagent returns exactly this — no prose body, no "mini-synthesis")

A reader subagent does **not** return a partial draft or a written summary. It returns a
compact structured extract and **writes the verbatim body to disk** (audit trail), so the
load-bearing detail is preserved without flowing into the main context:

```yaml
source_meta:  { title, url, author, org, date_published, tier? }
key_claims:   [ { claim: "<one sentence>", attribution: "<url / section> " } ]   # 3–8
quotes:       [ { text: "<verbatim, ≤40 words>", attribution } ]                 # load-bearing only
data_points:  [ { value, unit, context, attribution } ]
contradicts:  [ { other_source_hint, on_what } ]    # flags only — main agent resolves in Phase 3
dedup_key:    "<canonical-url>"                      # from scripts/normalize_url.py
raw_path:     "pipeline/3-synthesis/{topic}/raw/{n}_{host}.md"   # the verbatim fragment it wrote
notes:        "<paywall | manual-handoff | empty-fetch | clean>"
```

Verbatim quotes are carried **in the extract** so a later claim never needs the main agent
to re-open the body. If a subagent could not fetch (login wall / paywall / empty) it returns
`notes: manual-handoff` with the placeholder path and an empty `key_claims` — it never guesses.

---

## Boundaries — keep deterministic work OUT of the agents

These are scripts, not agent reasoning. Running them as agents adds variance and burns
context for no gain:

- **Sanitize (security).** Reader subagents read the **`sanitized/` companion only**, never
  the raw original. `scripts/sanitize_incoming.py` (S1–S9) runs as a **batch script BEFORE
  dispatch** — no agent ever ingests untrusted raw text. (research-build standard mode: the
  `source-archive` `MODE=instruction-stripping` companion; internal-corpus: the
  `pipeline/1-incoming/{topic}/sanitized/` companion.)
- **URL dedup.** The persistent cross-source key is the canonical URL
  (`scripts/normalize_url.py`); near-dup syndication is collapsed by `scripts/dedup.py`. Both
  run as scripts (before dispatch for the source list, after collection for the fragments) —
  the subagent only **reports** its `dedup_key`, it does not decide merges.
- **Claim-level dedup across extracts.** After URL dedup, the same fact sourced from
  several feeds still appears as a near-duplicate **claim** across extracts. Collapse it
  deterministically — `scripts/claim_dedup.py` (word-shingle Jaccard, stdlib, ADR 0018),
  run by the main agent in Phase 2b — not as agent reasoning. The heavier **semantic-dedup
  subagent** over the extract set stays deferred (advanced only); the script covers the
  common case without added variance or context cost.

---

## Phase 2b assembly (main agent)

The main agent assembles `raw_{YYYY-MM-DD}.md` as an **index of fragment paths + the returned
extracts** — it lists each `raw_path` and its `key_claims`/`quotes`. It does **not** re-read
the fragment bodies into context; the verbatim bodies stay on disk for the audit trail. The
non-negotiable "a raw file must exist before synthesis" rule is satisfied by this index plus
the on-disk fragments.

**Claim dedup before listing.** Pass the accumulated `key_claims` across all extracts through
`python3 scripts/claim_dedup.py` (JSON array of `{claim, attribution}` on stdin → deduped
array on stdout) so a fact carried by several sources collapses to one claim — URL dedup has
already handled same-URL duplicates; this handles the same claim from *different* URLs. Keep
each survivor's `attribution` (the CLI preserves the first object of a near-dup group), then
list the deduped claims. Deterministic, no LLM.

## Phase 3 synthesis (main agent, on extracts)

Synthesis reads the set of extracts (bounded, small), groups `contradicts` flags and resolves
them explicitly ("According to [A]… whereas [B]…"), picks the 3–5 findings, and writes the
document. Holistic view preserved; context bounded.

---

## Failure handling

- A subagent returns `null` / empty → log the cluster in the notes
  ("Reader fan-out: cluster {k} failed"), continue with the rest. **Do not** re-read that
  cluster's sources inline — that re-introduces the full bodies the contract exists to keep
  out (unless fewer than 5 sources remain total, in which case inline is fine).
- Audit-trail completeness is mandatory: every dispatched subagent must return either a
  `raw_path` (fetched) or a `manual-handoff` placeholder path.
- **`internal-corpus` path (no fetch):** the sources are already-collected local files, so a reader
  subagent reads the `sanitized/` companion directly and its `raw_path` is that companion — there is
  no fetch fallback and no `manual-handoff` (a missing/stale companion is the upstream sanitize
  gate's job, not the reader's).

## Cost note

Parallel reader subagents cost **more total tokens** than a sequential read, but they protect
the **main context window** — which is the actual failure users hit ("running out of context
mid-research"). The trade is deliberate and only taken at ≥5 sources, where the main-window
risk is real.
