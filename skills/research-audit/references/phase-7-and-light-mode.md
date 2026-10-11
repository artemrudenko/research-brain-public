---
title: "Research-Audit — Phase 7 (Verification Log) + Light Mode Detail"
type: reference
domain: research-quality
created: 2026-05-23
last_updated: 2026-06-15
applies_when: "Phase 7 generate verification log + threshold gate (7a-7e detail) AND chat-answer light mode procedure"
---

# Phase 7 — Generate verification log + Threshold gate

> Lazy-loaded from SKILL.md. SKILL.md holds a summary; details here.

## 7a. Compute aggregate stats

```
total = len(claims_list)
green = count(claims, marker == 🟢)
yellow = count(claims, marker == 🟡)
red = count(claims, marker == 🔴)
red_pct = red / total * 100
```

## 7b. Threshold gate

**Hard rule:** if `red_pct > 30%` → **block the transition to formatting**. Return to Gather:

- Create the verification log anyway (for the audit trail)
- Set `gate_status: blocked` in the frontmatter
- Return to the caller with the instruction: "> 30% of claims unverified — formatting is blocked. Returning to Gather. Weak claims (see the log) need better sources or a revised draft."
- Do not hand control to Critique / formatting

If `red_pct ≤ 30%` → `gate_status: passed`, proceed to Critique → formatting.

**Tunable note:** 30% is the starting threshold. After the first 5-10 research-audit runs, revisit it based on the actual distribution. Changing the threshold → edit the `RED_THRESHOLD_PCT` field in `rules/common.md` (single point of change).

## 7c. Write the verification log

Path: `planning/research/{date}_{slug}.verification-log.md` (where `{date}_{slug}` matches the brief).

**Full template (frontmatter + body):** [`log-template.md`](log-template.md). It contains:
- Mandatory frontmatter (`type`, `skill`, `mode`, `severity_summary`, `gate_status`)
- Granular aggregate fields (`total_claims`, `green/yellow/red_count`, `red_pct`)
- Extended-mode framing (`grading_mode`, `levels_distribution`, `evidence_type_distribution`)
- Body sections: Summary table, Claim-by-claim, Contradictions, Unregistered hosts, Recommended confidence tags, Recommendations (for a blocked gate)

## 7d. Unregistered hosts handling (INTERACTIVE-gated)

After writing the log — for each `unregistered` host (if ≥1):

**If `INTERACTIVE=true`:**
AskUserQuestion: "New host `{host}` appears in {n} claims. Tier?"
Options: T1 / T2 / T3 / Skip (leave unregistered)

On a T1/T2/T3 choice — `source-archive` (or a manual call) adds a row to `sources/trusted-registry.md`.

**If `INTERACTIVE=false` (default):**
Write a line into verification-log.md under the `## Recommendations` section for each host:
`- Register host \`{host}\` (appears in {n} claims) in \`sources/trusted-registry.md\` with tier T1/T2/T3.`

Do not ask the question; do not block the flow. Automated/headless runs prefer this mode (silent dispatch).

## 7e. Update the brief lifecycle

Edit `BRIEF_PATH`:
- `verification_log: planning/research/{date}_{slug}.verification-log.md`
- `last_updated: {today}` (mandatory frontmatter stamp)
- Lifecycle checkbox: `- [x] **Verify** — verification_log.md ({gate_status})`

---

# "Chat answer" Light mode (Phase 7 alternative)

Activated when `format == chat-answer` in the brief (or `MODE=chat-answer-light`).

## Procedure

1. **Skip Phases 2-6.** Do not extract all claims, do not do cross-source.
2. **Tier-check citations only:** for each explicit URL in the draft (footnotes / inline links) — look up the tier. If any is T3-only or unregistered — flag.
3. **Recency-check citations only:** if a claim explicitly cites a `published` date — compare with `recency_max`. Without a published date — do not block (a chat answer is not a deliverable).
4. **No cross-source enforcement.** A single source is OK, T3 is OK with a warning in chat.
5. **No verification-log file.** Inline summary in chat:
   ```
   Tier audit: 3 links — 2× T1 (vendor docs, repo), 1× T3 (forum thread).
   Recency: all < 6 mo.
   Verdict: safe to answer. The T3 link is used to illustrate an opinion, not as fact.
   ```
6. **Threshold gate disabled.** A chat-answer format is not blocked — only a tier warning surfaces in chat.

Light mode keeps the friction low for informational queries while still catching obvious source failures.
