---
title: "Research-Audit — Phase 5.5 Citation Hallucination Guard"
type: reference
domain: research-quality
created: 2026-05-23
last_updated: 2026-06-15
applies_when: "Phase 5.5 full procedure — detect / cross-reference / PLACEHOLDER mechanism / threshold gate / anti-patterns"
---

# Phase 5.5 — Citation hallucination guard + PLACEHOLDER

> Guard rail against naked citations (author-year / URL / numbered-ref attribution without a matching source in the raw materials). Lazy-loaded from SKILL.md Phase 5.5.

**Why:** the Phase 5 cross-source check validates extracted claims — but not the *citation form*. An LLM can insert "Per Smith (2024)" or "[5]" into a draft, referencing a source that never existed in the Phase 2b raw materials. This is citation hallucination — a risk distinct from claim hallucination (which Phase 5 catches).

**Why it matters:** an artifact with citation hallucinations is a worse failure than a claim error. A claim error means "we got it wrong"; a citation hallucination means "we fabricated authority".

## Activation

- **Default:** auto-run for all verifiable claims with attribution markers
- **Mandatory:** high-stakes deliverables (decision-grade / leadership / external-facing output)
- **Skip:** internal review AND zero attribution markers in the draft

## Steps

1. **Detect citations** in the draft — 4 attribution patterns:

   | Pattern | Regex (illustrative) | Example |
   |---|---|---|
   | Author-year (English) | `[A-Z][a-z]+\s+et\s+al\.?\s+\(\d{4}\)\|[A-Z][a-z]+\s+\(\d{4}\)` | Smith et al. (2024); Acme (2025) |
   | Author-year (non-Latin script) | locale-specific author-year pattern | configurable per content language |
   | Numbered reference | `\[\d+\]` | [5], [12] |
   | URL inline | `\bhttps?://[^\s\]\)]+` | https://example.com/paper |

2. **Cross-reference each citation** vs the source pool:
   - Raw materials: `materials/raw/{topic}/raw_{date}.md` (Phase 2b output)
   - Brief-supplied sources: `research_brief.materials_used[]`
   - Existing knowledge-base notes: `brain/concepts/*.md` `provenance.url`

3. **Verdict per citation:**
   - 🟢 **MATCHED** — citation maps to a concrete source in the pool. Continue.
   - 🟡 **AMBIGUOUS** — author-year matches multiple potential sources OR partial match. Log in the verification log § "Ambiguous citations" + flag for editorial review.
   - 🔴 **UNVERIFIED** — no matching source found. **Insert a PLACEHOLDER:** replace the citation in the draft with `[CITATION-UNVERIFIED: {original-citation}]` + log in the verification log § "Unverified citations" (mandatory).

4. **PLACEHOLDER resolution** (pre-delivery):
   - **Option A — Verify** — find / archive a matching source, restore the citation
   - **Option B — Drop** — remove the citation if the claim still holds without attribution
   - **Option C — Downgrade** — convert to a generic claim ("Per published research, ...") without specific attribution
   - A PLACEHOLDER **must NOT** appear in the final shipped artifact (the Phase 7 threshold gate enforces this).

## Output (verification-log additions)

```markdown
## Unverified citations (Phase 5.5)

- C1: "Per Smith et al. (2024)" — line 142 — no matching source in raw materials. PLACEHOLDER inserted.
- C2: "[12]" — line 287 — numbered ref orphan (no [12] in the source list). PLACEHOLDER inserted.

## Ambiguous citations (Phase 5.5)

- C3: "Acme (2025)" — matches 3 potential sources (cookbook / announcements / docs). Editorial review required.
```

## Threshold gate (Phase 7 amendment)

- **FULL / interactive mode:** ≥1 PLACEHOLDER remaining in the draft at the hand-off to formatting → halt + AskUserQuestion ("resolve N PLACEHOLDERs first / accept generic downgrade / abort").
- **SOFT / unattended mode (`SOFT_MODE=true`, no operator):** there is no AskUserQuestion to answer, so the guard does **not** halt. Instead each unresolved PLACEHOLDER is **auto-downgraded to its generic, explicitly-unverified phrasing** (the "accept generic downgrade" option, applied deterministically) and recorded in the `confidence_note:`. This keeps the loop moving (`gate_status: soft-pass`) without ever shipping a raw PLACEHOLDER.
- Hard rule (mode-independent): a raw `[CITATION-UNVERIFIED: …]` / `[…PLACEHOLDER…]` token **never** ships in a deliverable. The soft-mode auto-downgrade *satisfies* this rule (it replaces the token); it does not waive it.

## Anti-patterns

- ❌ Resolve a PLACEHOLDER by inventing a matching source — counterproductive (creates a phantom raw material)
- ❌ Skip Phase 5.5 for a quick scan — a quick scan can also have author-year tells; default-on is better than default-off
- ❌ Strip a PLACEHOLDER silently without a log — an audit-trail invariant violation
