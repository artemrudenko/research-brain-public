# ADR 0018 — Deterministic claim-level dedup helper

- **Status:** Accepted (2026-07-01); **wired into synthesis 2026-07-02**
- **Tags:** dedup, synthesis, digest

> **Update (2026-07-02) — now wired (deterministic path only).** The helper grew a
> `main` CLI (JSON array of claim strings, or reader-contract `{claim, attribution}`
> objects → deduped JSON) and the research-build **Phase 2b assembly** now runs the
> accumulated cross-source `key_claims` through `python3 scripts/claim_dedup.py`
> before listing them, so a fact carried by several feeds collapses to one claim
> (URL dedup already handles same-URL). This is a deterministic script step, not
> agent reasoning. The heavier **semantic-dedup *subagent*** over the extract set
> remains deferred (advanced only). The "ships unwired" framing below is the
> original record; the CLI + skill step is the adoption it anticipated.

## Context
The project already dedups at two levels: `scripts/normalize_url.py` collapses
the *same URL* in different shapes (registry key), and `scripts/dedup.py`
collapses near-identical article *bodies* (syndication / reposts) via a hybrid
char-3gram + token Jaccard. Neither collapses at the finest level — the
individual **claim**. When the same assertion is corroborated by several
sources, the digest/synthesis surface can repeat it in slightly different words.

A user asked for **claim-level dedup** as a possible digest refinement. It was
**deliberately deferred**: consistent with the project's no-over-engineering
ethos, we do not build a pipeline stage until a live run shows the duplication
is real and worth folding. Without that signal, wiring an aggressive collapse
into synthesis risks dropping distinct-but-similar claims (a false-merge is
worse than a visible repeat). So the decision here is scoped to the *primitive*,
not its adoption.

## Decision
Add one small, deterministic, **stdlib-only** helper, `scripts/claim_dedup.py`,
exposing a pure function:

```python
dedup_claims(claims: list[str], *, threshold: float = 0.8) -> list[str]
```

- **Normalise** each claim — lowercase, strip punctuation, collapse whitespace,
  drop a small English stopword set so only content words remain.
- **Shingle** the content tokens into unigrams ∪ bigrams; bigrams retain local
  word order so a reorder that keeps the same words still scores lower.
- **Compare** claims pairwise by **Jaccard similarity** over those shingle sets;
  a pair at or above `threshold` (default **0.8**, inclusive `>=`, matching
  `dedup.py`'s convention) is a near-duplicate.
- **Collapse** by keeping the **first** occurrence in input order and dropping
  later near-duplicates; survivors are returned in original order. Fully
  deterministic — no randomness, no reliance on set iteration order in output.

A thin convenience, `dedup_items(items, key, *, threshold=0.8)`, dedups arbitrary
objects by a claim-extracting `key` (delegating to the same shingle/Jaccard
logic), plus a public `similarity(a, b)` for callers and tests.

Crucially, this ships the **helper only**. It is **NOT wired** into
`build_digest.py`, synthesis, curation, or any skill — no existing file is
touched. The threshold default (0.8) is higher than `dedup.py`'s 0.7 body
threshold because a single claim is short, so a looser bar would fold
merely-related claims.

## Consequences
- **Zero runtime impact today.** Nothing imports it, so the digest, synthesis,
  and delivery paths are byte-for-byte unchanged; adding it cannot regress a
  live run. It is opt-in-only until a caller chooses to use it.
- **Deterministic & reproducible.** Pure function of its input list — same input,
  same output — so it composes cleanly into the offline, local pipeline
  and is trivially unit-testable (`tests/test_claim_dedup.py`).
- **Cheap and honest.** Lexical Jaccard has no semantic understanding: it folds
  reworded restatements but will not merge claims that share meaning without
  sharing words, and could over-merge two genuinely distinct claims that happen
  to share most content words. That risk is exactly why adoption waits for a
  live-run signal and stays behind an explicit threshold.
- **A future caller opts in** by importing `dedup_claims` (or `dedup_items`) at
  the point where a claim list is assembled — e.g. de-duplicating the corroborated
  claim lines a synthesis step emits before they reach the digest — passing a
  tuned `threshold`. That wiring is a separate, testable change with its own ADR.

## Limits / failure mode (of the 2026-07-02 wiring)
- **Prose-wired, not code-wired.** The dedup step is invoked by an *instruction*
  in `skills/research-build/` (Phase 2b of the reader contract,
  `references/reader-contract.md`, runs the CLI), not by code inside
  `build_digest.py` or another script. There is therefore no programmatic
  guarantee the step runs — an agent that skips the phase simply produces
  undeduplicated claims.
- **Fail-open on CLI failure.** If `scripts/claim_dedup.py` errors (bad JSON,
  interpreter missing, unexpected crash), the synthesis step continues with the
  **original, undeduplicated** claim list — it never blocks or aborts the run.
- **Deliberate.** Both properties are accepted, not accidental: claim dedup is a
  *quality* refinement, not a safety gate (unlike the S1–S9 sanitize gate, which
  is fail-closed). A visible repeated claim is a cosmetic defect; a synthesis run
  killed by a cosmetic helper — or a false merge silently dropping a distinct
  claim — is worse. If dedup ever becomes load-bearing, wiring it into code with
  fail-closed semantics is a separate ADR.

## Alternatives considered
- **Wire it into synthesis/digest now.** Rejected — no live-run evidence yet that
  claim repetition is common enough to justify the false-merge risk; premature
  per the no-over-engineering ethos. Ship the primitive, defer the adoption.
- **Reuse `dedup.py`'s char-3gram + token hybrid at 0.7.** Rejected for claims —
  that pair is tuned for whole article bodies; on short single sentences the
  char-3gram signal is noisy and 0.7 is too loose. Word-shingle Jaccard at 0.8 is
  a better-matched, simpler bar for sentence-length units. (Kept as a separate
  self-contained module rather than overloading `dedup.py` with a second mode.)
- **Embedding / LLM semantic dedup.** Rejected — violates the stdlib-only runtime
  rule (ADR 0002), adds a dependency and non-determinism, and is unwarranted for
  a feature that has not yet earned pipeline wiring.

## References
- `scripts/claim_dedup.py`, `tests/test_claim_dedup.py`
- [ADR 0002](0002-stdlib-only-runtime.md) — stdlib-only runtime
- `scripts/dedup.py` (article-body hybrid dedup), `scripts/normalize_url.py`
  (URL-level dedup) — the two coarser levels this sits above.
