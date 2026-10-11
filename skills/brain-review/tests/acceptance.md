# Acceptance — brain-review

> Given/When/Then for the content-trust audit skill. brain-review judges whether the
> accumulated knowledge is **accurate** (vs validate_brain's mechanical integrity); these
> scenarios pin the batch selection, the adversarial verify, the no-silent-edit gate, and the
> headless degrade path.

- **SKILL.md:** [`../SKILL.md`](../SKILL.md)
- **Reuses:** `validate_brain.py` (mechanical pre-pass), `research-audit`'s verify discipline.
- **Coverage:** 6 scenarios — full audit happy path + single-source-illusion catch + refute-pass
  survival + headless degrade + no-silent-edit gate + empty/clean vault.

---

## Scenario 1: On-demand audit, mixed findings (agent runtime)

**Given:** a vault with several `brain/concepts/*.md`, some `last_verified + ttl_days` in the past,
one changed since the last `brain-review_*.md` report.

**When:** user says "audit the knowledge base for accuracy".

**Then:**
- Phase 0 runs `validate_brain.py` first, then scopes the batch to stale + never-verified +
  changed-since-last; the batch cap is honored and any deferred concepts are `log`ged (not dropped
  silently).
- Phase 1 fans out one verifier per concept; each cites evidence for its verdict.
- A graded report is written to `pipeline/3-synthesis/brain-review_YYYY-MM-DD.md` with a headline
  `Trust: N concepts · X stale · Y resynth · Z hallucination-risk` and a worklist.
- Nothing in `brain/` is rewritten without the wiki-ingest gate.

## Scenario 2: Single-source illusion is caught

**Given:** a concept whose `sources:` has three entries that are the same registrable domain
(or one story re-syndicated), but the concept claims a 🟢 "confirmed by multiple sources" trust.

**When:** that concept is in the audited batch.

**Then:** the verifier counts **distinct independent domains** (per §16), finds one, and returns
`DOWNGRADE-TRUST` with the domain evidence. The worklist suggests re-collecting an independent
corroborating source.

## Scenario 3: A flagged finding must survive the refute pass

**Given:** Phase 1 returns a `HALLUCINATION-RISK` verdict on a concept.

**When:** Phase 2 runs.

**Then:** a second agent attempts to **refute** the finding; the concept is reported as a problem
only if the finding survives. A finding the refuter overturns is dropped (not reported), so a
single agent's misread cannot condemn a concept.

## Scenario 4: Headless / cron — graceful degrade

**Given:** the skill is invoked with no agent runtime (headless cron path).

**When:** brain-review runs.

**Then:** it does **not** attempt a multi-agent audit; it runs `python3 scripts/validate_brain.py`
(mechanical) and reports plainly: "content-trust audit needs the agent runtime; ran mechanical
hygiene only — N concepts, X orphans, Y stale." No crash, no silent no-op.

## Scenario 5: No silent vault edit

**Given:** Phase 1 returns `NEEDS-RESYNTHESIS` for a concept (a content change).

**When:** Phase 4 applies.

**Then:** in interactive mode the content change is **proposed and routed to wiki-ingest** (its
approval gate), never written directly. `last_verified:` may be stamped only on `VERIFIED-OK`
concepts. In unattended mode, no content is auto-rewritten — the change goes to the worklist; a
mass-failure halts and reports rather than mass-mutating.

## Scenario 6: Empty / freshly-clean vault

**Given:** a vault with no real concepts yet (only SEED/EXAMPLE notes), or every concept recently
verified.

**When:** user asks to review the brain.

**Then:** brain-review reports a clear, non-error message ("nothing to re-verify — all concepts
verified within ttl" or "no real concepts yet"), writes no spurious findings, and suggests when the
next sweep would be useful. It never fabricates a problem to look busy.
