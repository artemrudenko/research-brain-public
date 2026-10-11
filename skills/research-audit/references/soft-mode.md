# research-audit — Soft mode (internal-corpus / no-registry)

> **Lazy-load reference.** SKILL.md § Soft mode holds the pointer. This file is the full
> procedure for the soft-degrade path defined in `docs/CONVENTIONS.md` §10.

## When soft mode activates

Any one of:

1. `SOFT_MODE=true` passed explicitly (the `schedule/weekly-synthesis.md` unattended path passes
   it for `PROFILE=internal-corpus` synthesis).
2. Auto-detect: **both** `sources/trusted-registry.md` and `sources/always-volatile-domains.md`
   are absent.
3. No brief is findable (no `BRIEF_PATH` passed and no sibling brief in `planning/research/`).

If a `sources/` registry **is** present, it is still used for best-effort tier annotation — a
missing registry is what triggers the degrade, never a present one.

## What changes vs FULL mode

| Aspect | FULL mode | SOFT mode |
|---|---|---|
| Missing brief | fail-fast | proceed with defaults + confidence note |
| Missing `sources/` registry | "registry-error", all hosts → T3 | **skip tier-grading**, do NOT mark T3 |
| Phase 3 tier lookup | per claim | skipped (no registry) |
| Phase 4 recency annotation | full | **retained** (relative dates / "recency-unknown") |
| Phase 5b corroboration (factual/news) | gates 🟢/🟡 | **light signal** — annotate publisher proxy + `single`/`multi` + independence-review status, NO block |
| Phase 5.5 citation guard | full | **retained** (PLACEHOLDER for unverified citations) |
| Phase 7 threshold gate | `red_pct > 30%` → block | **disabled** (`gate_status: soft-pass`) |
| Output | verification log + brief update | log + `confidence_note:`; no brief to update |

## Why "no registry" must NOT mean "everything T3"

In FULL mode an unregistered host defaults to T3. If the registry is simply absent (de-branded /
fresh install), grading every host T3 would push `red_pct` to ~100% and falsely trigger the
`>30% 🔴` block — silently killing the unattended synthesis loop. Soft mode breaks that chain:
no registry → **no tier dimension at all** → the block cannot fire on a registry-absence basis.

## Procedure

1. **Detect** (Phase 1) — set the soft flag per the activation rules above.
2. **Extract claims** (Phase 2) — unchanged; the claim list is mode-independent.
3. **Skip Phase 3** (tier lookup) — record `"tier-grading skipped: no registry"`.
4. **Phase 4 recency** — run as usual against `recency_max` (default 12mo if no brief); annotate
   `recency-unknown` where dates are missing. No tier interaction.
5. **Phase 5b coverage and provenance — LIGHT signal only** (§16): derive the publisher-group
   proxy (legacy `independent_sources` field) and `single` / `multi` level. Record
   `independence_review: unknown` unless supporting passages and upstream lineage were
   actually assessed; explain any assessment with source evidence. Do not infer factual
   confirmation from domains or lexical deduplication. Do **NOT** block ingest on this
   coverage signal. Unknown independence stays qualified rather than becoming 🟢.
6. **Phase 5.5 citation guard** — run as usual; insert `[CITATION-UNVERIFIED: …]` PLACEHOLDERs
   for naked citations. The detection is mode-independent; only the Phase-7 *resolution* differs
   (see step 7).
7. **Phase 7** — write the log; set `gate_status: soft-pass`; populate `confidence_note:`. There is
   no operator, so the citation guard does **not** halt: each unresolved PLACEHOLDER is
   **auto-downgraded to its generic, explicitly-unverified phrasing** and recorded in the
   `confidence_note:` (the mode-independent hard rule "a raw PLACEHOLDER never ships" is satisfied by
   the downgrade, not waived). See [`citation-guard.md`](citation-guard.md) § Threshold gate.
   - Log location: `planning/research/{date}_{slug}.verification-log.md` if a brief exists;
     otherwise (internal-corpus, no brief) alongside the draft in
     `pipeline/3-synthesis/{topic}/{date}_{slug}.verification-log.md`. Create `planning/research/`
     only if writing there.

## Confidence-note frontmatter (soft mode)

```yaml
gate_status: soft-pass
soft_mode: true
corroboration:                 # light signal (per §16); downstream reads this, not a stored counter
  - claim: C7
    independent_sources: 3     # historical field: publisher-group proxy, not independence
    level: multi               # multi (>=2 publisher groups) | single (1)
    independence_review: unknown
  - claim: C8
    independent_sources: 1
    level: single
    independence_review: unknown
confidence_note: >
  Tier-grading skipped (no sources/ registry). Citation-guard: N matched, M flagged,
  K placeholders. Recency: annotated, J recency-unknown. Corroboration (light signal):
  P factual/news claims have multiple publisher groups, Q have one. No tier-based 🔴 block applied.
```

## Anti-patterns

- ❌ Marking every host T3 because the registry is absent → inflates `red_pct`, blocks the loop.
- ❌ Fail-fast on a missing brief in soft mode → kills the unattended path.
- ❌ Dropping the citation-guard "because there's no registry" → the guard needs no registry; keep it.
- ❌ Hard-blocking ingest on a `single`-source factual/news claim in soft mode → corroboration is a LIGHT signal here (annotate `independent_sources` + level), not a gate (§16 + §10).
- ❌ Treating distinct domains or dissimilar texts as independent factual confirmation → inspect supporting passages and shared upstream provenance; keep the proxy and review verdict separate.
- ❌ Writing the log into a non-existent `planning/research/` without creating it / without the
  draft-sibling fallback → lost audit trail.
