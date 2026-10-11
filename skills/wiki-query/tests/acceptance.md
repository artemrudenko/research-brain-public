# wiki-query — Acceptance Tests

Given/When/Then scenarios for regression coverage of the **read-only vault lookup** (the
Inventory step). wiki-query reads `brain/concepts/` via the `brain/INDEX.md` MOC; a hit yields
a compiled answer. A research-chain miss forwards to `research-grep`; an explicit
brain/vault query reports the miss and offers research without starting it. It NEVER
writes to `brain/`.

---

## Test cases — Vault state gates

### Test WQ-1.A — Vault not initialized

**Given:** `brain/INDEX.md` does not exist
**When:** wiki-query is invoked
**Then:**
- It halts with "Knowledge vault not initialized — no brain/INDEX.md MOC found"
- `VAULT_ONLY=false`: control is handed to `research-grep`; no answer is fabricated
- `VAULT_ONLY=true`: the empty state is reported and research is offered, not started

### Test WQ-1.B — Vault too thin

**Given:** `brain/concepts/` has fewer than 2 concepts
**When:** wiki-query is invoked
**Then:**
- It declines ("vault not populated")
- It goes to `research-grep` only when `VAULT_ONLY=false`; a vault-only request stops
  after reporting the empty state and offering research

---

## Test cases — Matching & answering

### Test WQ-2.A — MATCH high

**Given:** the MOC lists a concept covering the query keywords
**When:** wiki-query runs the Match step
**Then:**
- Result is `MATCH high`
- It reads only `brain/INDEX.md` + the matched concept (≤2 concepts total; ≤3 with peer expansion) — the raw corpus is NOT opened (token-economy invariant)
- The answer uses the `Vault answer` template
- The answer carries **mandatory source attribution** (`Source: `brain/concepts/<slug>.md` § <section>; underlying source: <url-or-path>`), an explicit `Confidence:`, and surfaces the concept's gaps

### Test WQ-2.B — NO MATCH

**Given:** no concept covers the query
**When:** the Match step returns `NO MATCH`
**Then:**
- Control is forwarded to `research-grep` with pre-loaded brain context (+ topic filter if set)
- After the research run, `wiki-ingest` is offered

### Test WQ-2.B2 — VAULT_ONLY miss does not broaden scope

**Given:** the user asks "what does my brain know about X?" / "что моя база знает о X"
and no concept covers X
**When:** the Match step returns `NO MATCH`
**Then:**
- `VAULT_ONLY=true` is inferred from the explicit brain/vault phrase
- The answer uses the `Vault-only miss` template
- The answer states what was checked and that no matching concept exists
- research-grep, the raw corpus, and the web are not opened
- Do not start research-grep, web search, or raw-corpus inventory for VAULT_ONLY=true.
- External research is offered as a separate next action

### Test WQ-2.C — MATCH partial

**Given:** the query partially matches a concept
**When:** the concept is read
**Then:**
- For a forwarded research request (`VAULT_ONLY=false`), the concept, provenance, confidence,
  freshness, and gaps are passed to `research-grep`; its local inventory runs before any
  external-research choice
- For a direct vault-only request, an `AskUserQuestion` gate offers "enough / deep dive via
  research-grep / cancel" (interactive mode)

### Test WQ-2.D — Category-peer expansion

**Given:** a `MATCH high` concept has sibling notes in the same MOC cluster
**When:** Step 1.7 runs
**Then:**
- Up to 2 sibling concepts are surfaced via the matched note's `[[wikilinks]]`/backlinks
- Total opened ≤3 (1 anchor + ≤2 peers)

---

## Test cases — Topic filter & disambiguation

### Test WQ-3.A — Topic filter, empty candidate set

**Given:** `DOMAIN_FILTER=security` is set and no security-tagged concept matches
**When:** the topic pre-filter runs
**Then:**
- Result is `NO MATCH (topic-constrained)` — **not** a silent degrade to an unfiltered search

### Test WQ-3.B — Multi-topic ambiguity

**Given:** the query matches ≥2 topics and the secondary cluster is substantial
**When:** the disambiguation gate fires
**Then:**
- Interactive (`INTERACTIVE=true`): one `AskUserQuestion` disambiguation question before answering — never invent which topic the user meant
- Subagent (`INTERACTIVE=false`): halt with the recommendation in the report (a flag, not a guess)

---

## Test cases — Freshness & invariants

### Test WQ-4.A — Stale concept, soft note

**Given:** a matched concept's `last_verified` is past its `ttl_days`, or verification is unknown
**When:** the optional freshness check runs
**Then:**
- The answer distinguishes `review due` from `freshness unknown`; neither state is treated as
  proof the concept is wrong
- A research-chain request forwards the note, sources, and gaps to `research-grep`; a direct
  vault-only answer carries the caveat and offers a separate research step

### Test WQ-4.B — Always-volatile topic

**Given:** the matched concept's topic is listed always-volatile in `rules/common.md`
**When:** wiki-query answers
**Then:**
- Current-source research is recommended regardless of `last_verified`; local inventory still
  precedes the research-grep external-choice gate

### Test WQ-4.C — Read-only invariant

**Given:** any wiki-query run
**When:** it completes
**Then:**
- No `Edit`/`Write` touches `brain/` (writing is `wiki-ingest`'s job)
- The raw corpus (`pipeline/`, collected sources, prior outputs) is never opened

### Test WQ-4.D — Confidence transparency

**Given:** a matched concept is marked `Confidence: medium`/`low`
**When:** the answer is composed
**Then:**
- The medium/low confidence is stated explicitly — never presented as a sure fact

### Test WQ-4.E — Not a cold-start responder

**Given:** the user sends a cold-start research phrase ("research X", "deep dive", "what do we know about X")
**When:** routing is decided
**Then:**
- wiki-query does **not** pick it up directly — those are owned by `research-frame`, which forwards control here for the Inventory step

---

## Acceptance criteria

- [x] `brain/INDEX.md` missing / vault <2 concepts → halt; forward only when not vault-only
- [x] Token-economy: only the MOC + ≤2 concepts (≤3 with peer) opened; raw corpus never read
- [x] Source attribution mandatory on every answer
- [x] Topic filter → `NO MATCH (topic-constrained)`, never a silent degrade
- [x] Multi-topic ambiguity → disambiguation gate (AskUserQuestion / flag)
- [x] `last_verified` + `ttl_days` drive freshness notes; `last_updated` alone is not re-verification
- [x] Research-chain partial/stale/unknown context goes to local inventory; web remains behind its choice gate
- [x] Always-volatile topics recommend current-source research regardless of recorded verification date
- [x] Read-only — never writes to brain/
- [x] Confidence transparency on medium/low concepts
- [x] Explicit brain/vault queries stay vault-only until the user opts into research
- [ ] Dogfood: lookup against a populated live vault (deferred to a live run)

---

## Change log

| Date | What | Trigger |
|---|---|---|
| 2026-06-24 | Created acceptance tests for wiki-query. WQ-1 vault gates · WQ-2 match/answer · WQ-3 topic filter & disambiguation · WQ-4 freshness & read-only/confidence invariants. | Review found wiki-query had no acceptance contract. |
