---
title: "Research-Build — Phase 5.5 Anti-AI Audit + Phase 6.5 Critique"
type: reference
applies_when: "Phase 5.5 anti-AI audit watchlist + Phase 6.5 Critique pass detail (critical-hat review, subagent dispatch, 5-item checklist)"
last_updated: 2026-06-15
---

# Phase 5.5 — Anti-AI Audit Pass

> Audit finds — editorial fixes (deliberate separation of concerns).

After Phase 5 (Sources) and **before** Phase 6 (Editorial Review) — a short audit pass over
stylistic AI-tells. **Audit ≠ Critique.** Phase 6.5 Critique works on content (weak claims,
counter-arguments); Phase 5.5 Audit works on phrasing/style.

**Mandatory when:** `audience: external` / `leadership`, `depth: deep`.
**Skip when:** `audience: internal` AND `depth: quick-scan`; chat-answer downgrade; artifact <300 words.

## Step 1 — Detect

Self-prompt against a watchlist of common AI-tells (adapt to the output language):

1. "It's worth noting / it's important to note" — filler connector with no content
2. "plays a key role / is a key factor / marks a turning point" — significance inflation
3. "not just X, but Y" / "not only X, but also Y" — negative parallelism
4. Em-dash overuse — 5+ per paragraph, or 3+ in a single sentence. _Exception:_ source attributions "[Author] — [Title] — [URL] — [Date]" are functional and do not count.
5. Gratuitous rule-of-three with synonyms ("innovation, creativity, and ingenuity")
6. "experts believe / the industry notes / observers say" — vague attribution with no concrete source
7. "possibly, potentially", "may turn out to be", "it cannot be ruled out" — excessive hedging. _Exception:_ honest uncertainty when sources disagree is allowed.
8. "reflecting / underscoring / contributing to / demonstrating" — superficial -ing analyses
9. "in today's landscape / in the era of X / amid rapid development" — inflated context
10. "represents / serves as / acts as" instead of plain "is" — copula avoidance

## Step 2 — Hand-off to Editorial

The list of flagged tells is passed into Phase 6 as explicit input — editorial revises them in one pass.

## Output

`audit_pass` field in the research-brief frontmatter or critique-log:
- `audit_pass: applied (N tells flagged: pattern1, ...)` — if detection found tells
- `audit_pass: skipped ({reason})` — if skipped
- `audit_pass: clean` — 0 tells

---

# Phase 6.5 — Critique Pass

After Editorial Review (Phase 6) and **before** handoff downstream — a short "red-team" /
"critical hat" pass over the draft. At least 5 minutes of deliberate critique of your own theses.

## When mandatory

- When `audience: external` or `leadership` (per the research-brief)
- When `depth: deep`, regardless of audience

## When optional

- When `audience: internal` AND `depth: quick-scan`
- When `format: chat-answer`

## Subagent dispatch

**The Critique pass is the one stage where subagent dispatch is recommended** (for external /
leadership artifacts). Reason: an independent adversarial perspective beats self-review.

**Pattern:** dispatch **one** subagent (`general-purpose`) with an adversarial brief. Pass it: the
draft md path, the research-brief path, and the verification-log path. The subagent returns a
critique-log with adversarial findings (weak claims, missed counter-arguments, generalizations,
bias flags).

The main agent integrates the findings: adds confidence tags to 🟡/🔴 claims, reformulates weak
theses, adds a "Known unknowns" section, and saves the critique-log to
`pipeline/3-synthesis/{topic}/{date}_{slug}.critique-log.md`.

When `audience: internal` or `format: chat-answer` — subagent dispatch is optional; self-review is fine.

## Sonar cross-check (optional, key-gated — CONVENTIONS §15a)

An **independent second synthesis** that strengthens the adversarial pass without touching the
collection pipeline. It is OPT-IN: it runs only when `PERPLEXITY_API_KEY` is set in `config/.env`
(and `config/research.yaml` does not set `cross_check.provider: none`). No key → this step is
silently skipped and the Critique proceeds exactly as before.

**How to run:** call the dispatcher with the research question (the brief's TOPIC + ANGLE):

```bash
python3 scripts/search/cross_check.py "<research question>"
```

It returns `{answer, citations}` — Sonar's own synthesized answer plus the sources it used.

**How to use it (adversarial input ONLY — never a synthesis input):** treat Sonar's answer as a
hostile reviewer, not as material to copy. Ask three questions and fold the results into the
critique-log:

1. **Coverage gap** — does Sonar assert a claim (X/Y/Z) the draft never addresses? → add it or note why it was excluded.
2. **Missed source** — did Sonar cite a URL not in the draft's Sources? → if relevant, fetch it via `source-archive` (instruction-stripping) and re-enter Gather; do NOT cite it from Sonar's summary.
3. **Contradiction** — does Sonar contradict a draft thesis? → surface both in the body ("According to [A]… whereas Sonar's synthesis suggests…") and downgrade the confidence tag.

**Trust boundary (non-negotiable):** Sonar's prose is NEVER pasted into the artifact and its
citations are NEVER cited second-hand. Any source it surfaces must go through the normal fetch →
`source-archive` → Phase 2b → verification path before it can support a claim. This is what keeps
instruction-stripping (§12), verbatim-raw, and claim traceability intact.

## Checklist

1. **Weakest thesis** — name it out loud, decide keep or cut. If keeping, add a hedge or confidence tag (`🟡 Medium` / `🔴 Low`).
2. **Counter-argument check** — which alternative interpretations were not addressed; include at least one counter-argument in the body where it is strongest.
3. **Generalization audit** — where a broad conclusion is drawn from 1–2 examples; either find more examples or reframe as a narrow claim.
4. **Known unknowns section** — what could NOT be verified goes explicitly into the final artifact (a new "Open Questions" section).
5. **Bias check** — is there a slant toward one vendor / one school of thought; if so, find a counter-example or hedge.

## Output

1. **A "Known unknowns" section** — embedded in the final artifact. The Phase 3 `deep` structure already includes it; for `overview` add it if there is material worth recording.

2. **Critique log** — a separate file `pipeline/3-synthesis/{topic}/{date}_{slug}.critique-log.md`. Frontmatter `type: log`. Contains:
   - Which theses were cut and why
   - Which were reformulated (with before/after)
   - Which counter-arguments were considered, which were discarded and why
   - Bias flags, if any were found

   **NOT** in the research-brief — the brief keeps its role as the Frame-stage input contract.

## Verification

- If `research-audit` (Phase 5) ran before Critique — the critique leans on the verification-log markers: 🔴 unverified claims must be either removed or explicitly tagged `🔴 Low`; 🟡 single-source claims must be tagged `🟡 Medium`.
- If `research-audit` was skipped (chat-answer downgrade) — Critique works on a best-effort basis.
