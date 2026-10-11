# Bypass Heuristics — Edge Cases & Examples

Extended examples for the Phase 1 bypass-evaluator. Read only on unclear cases (uncertainty 60-40 split).

See also `rules/common.md` section "Bypass triggers — specific patterns" for the base rules.

---

## Edge case 1 — Mixed signals (factual + research keyword)

**Query:** "research what the latest version of tool X is"

**Analysis:**
- Contains the trigger keyword "research" → leans toward Frame mandatory
- BUT: the actual subject is a version lookup (Pattern 1: specific entity + attribute)
- Conflict: the trigger word implies research, but the content is a quick lookup

**Decision:** **Frame mandatory.** Trigger keywords always win, even if the question is factual. Reason: the user explicitly signalled research intent. If they chose "research", they want the full Frame, not a quick answer.

**Counter-rule:** if after Frame Q1 "Depth" the user picks "quick scan" with a single lookup in the research_question — that's fine, the brief is still created.

---

## Edge case 2 — Factual question with research depth signals

**Query:** "explain the MCP server protocol in detail"

**Analysis:**
- NO trigger keyword (no "research", "investigate", etc.)
- Contains a depth signal "in detail" → leans toward Frame
- Contains a factual subject — protocol description

**Decision:** **Frame mandatory.** A depth signal ("in detail") = "not a quick lookup". This is equivalent to a research request.

**Default depth pre-selection:** `standard` (depth signal "in detail" → not `quick`, but not necessarily `deep`).

---

## Edge case 3 — Compare/contrast questions

**Query:** "which is better — tool A or tool B for a development team?"

**Analysis:**
- NO trigger keyword
- BUT: a comparison (which is better — X or Y?) is **always research** per `rules/common.md` (Frame mandatory for "compare", "which approach is better")

**Decision:** **Frame mandatory.** A comparison requires cross-source verification, mandatory min_tier T1+T2.

---

## Edge case 4 — Yes/no with hidden depth

**Query:** "can we use this tool in production for the financial sector?"

**Analysis:**
- On the surface yes/no → leans toward bypass
- BUT: "financial sector" + "production" = compliance / risk / regulatory → requires careful analysis with T1 sources (regulatory, vendor docs)

**Decision:** **Frame mandatory.** Compliance / regulatory implications are always full research. A quick yes/no bypass would be irresponsible.

---

## Edge case 5 — Feature listing

**Query:** "what features does tool X 2.x have?"

**Analysis:**
- Specific entity (tool X) + attribute (features) → Pattern 1 bypass
- BUT: features are always-volatile (updates weekly)

**Decision:** **Bypass OK, but with a mandatory always-volatile check on forward.** The forward to `wiki-query` flags the query as always-volatile → wiki-query enforces a web supplement regardless of local TTL.

**Net result:** bypass UX (no AskUserQuestion friction), but downstream stages know a fresh fetch is needed.

---

## Edge case 6 — User explicitly skips Frame

**Query:** "no brief — just find out whether tool X supports MCP"

**Analysis:**
- Explicit skip request ("no brief")
- Content is factual → bypass-able

**Decision:** **Force bypass** (via MODE=force-bypass or explicit skip). Forward to `wiki-query` without AskUserQuestion.

**Note:** an explicit skip overrides trigger keywords. If the user said "no brief", even "research with a trigger" → bypass.

---

## Edge case 7 — Continuation of existing research

**Query:** "continue the research on tool-a-vs-tool-b — add a section on pricing"

**Analysis:**
- The phrase "continue the research" → references an existing brief
- Not new research, not a lookup — an extension of existing work

**Decision:** **Skip Phase 1-2, read the existing brief**, forward to the next stage.

Implementation:
1. Find `planning/research/*_tool-a-vs-tool-b-*.md` (slug match)
2. Read the brief Lifecycle status
3. Forward to the next stage per the Lifecycle

---

## Edge case 8 — Conversational meta vs. research

**Query:** "how is our research chain set up?"

**Analysis:**
- Conversational meta-question about project structure
- NOT a research request (not searching the outside world)
- Matches skip condition #2

**Decision:** **Skip the skill entirely.** Answer directly from project knowledge, without Frame.

---

## Phase 0.5 worked examples

> 3 worked examples for Phase 0.5 pre-flight resolution (Step 0.45 keyword-trap + Step 0.5 entity resolution + Step 0.55 confidence scoring).

### Example A — "tool A or tool B for our team?" (K1 + K3 trapped)

**Surface analysis:** short query (8 words), looks like a simple A-or-B question. Without Phase 0.5, the bypass-evaluator was likely to forward to wiki-query as a "specific entity comparison".

**Phase 0.5 application:**

- **Step 0.45 keyword-trap:** matches K1 (Comparative-disguised-as-lookup — "X or Y" pattern) + K3 (Strategic-disguised-as-tactical — "for our team" implies a decision context with ROI / alternatives)
- **Step 0.5 entity resolution:** "tool A" known tool ✓; "tool B" known tool ✓. No unresolved entities.
- **Step 0.55 confidence scoring:** base 1.0 − 0.30 (K1 + K3 = 2 classes × 0.15) − 0.0 (no entity issues) = **0.70**

**Routing:** **Refine** — use defaults, **Frame mandatory** regardless of bypass-evaluator outcome.

**Why valuable:** without Phase 0.5, this query would bypass to wiki-query → a quick answer without cross-source comparison + ROI analysis. With Phase 0.5 — full Frame proceeds, output = research brief with audience: strategic, sources_mode: hybrid, depth: standard. Avoids the "answer was technically correct but missed strategic context" failure mode.

### Example B — "MCP servers" (K4 trapped + low confidence)

**Surface analysis:** 2-word query. On the surface it looks like a quick lookup.

**Phase 0.5 application:**

- **Step 0.45 keyword-trap:** matches K4 (Topic-explosive-disguised-as-narrow — "MCP" single-noun query touching a big domain). Single class match.
- **Step 0.5 entity resolution:** "MCP" — ambiguous (Model Context Protocol vs. other meanings); known tool ✓ but query intent unclear (overview? specific server? troubleshooting? security?). 1 unresolved scope question.
- **Step 0.55 confidence scoring:** base 1.0 − 0.15 (K4) − 0.10 (unresolved scope intent) + 0.10 (query <15 words boost) = **0.85**, just above the 0.80 threshold

**Routing:** **Proceed** — confidence sufficient. The Phase 1 bypass-evaluator can decide. It will likely also flag "too short for a research-grade query" — and either force Frame mandatory or bypass with a Frame fallback if the user is dissatisfied.

**Edge case:** if the user follows up with "explain in detail" after seeing the bypass response — re-trigger Phase 0.5 with the refined query, and confidence drops below 0.80 → Refine routing.

### Example C — "tell me about the latest pricing changes" (K2 + entity issue)

**Surface analysis:** a query about vendor pricing, sounds like a factual lookup.

**Phase 0.5 application:**

- **Step 0.45 keyword-trap:** matches K2 (Stateful-disguised-as-static — pricing changes are implicitly volatile, require a recency check). Single class match.
- **Step 0.5 entity resolution:** "pricing changes" — vendor unspecified! Which vendor? Multiple possible. **Unresolved entity** flag triggered.
- **Step 0.55 confidence scoring:** base 1.0 − 0.15 (K2) − 0.10 (unresolved entity vendor) + 0.10 (short query boost) = **0.85**, but the flag "K2 + unresolved entity" combination → **mandatory clarification regardless of score**

**Routing:** **Clarify** (override score-based routing because of the K2 + entity combination — pricing data without a vendor name is unanswerable). AskUserQuestion: "Which vendor?". Single clarification, then proceed.

**Why valuable:** without Phase 0.5, the bypass would forward to wiki-query → the answer would be either a "which vendor?" chat question (rude UX), or a multi-vendor sweep (wasteful), or an assumption-based answer (possibly the wrong vendor). Phase 0.5 catches the missing entity and asks 1 clean question.

### Decision summary table

| Example | Confidence | Decision | Outcome |
|---|:-:|---|---|
| A — "tool A or tool B" | 0.70 | Refine | Frame mandatory + defaults |
| B — "MCP servers" | 0.85 | Proceed | Phase 1 bypass-evaluator decides; likely needs follow-up |
| C — "pricing changes" | 0.85 (overridden) | Clarify | 1 question for vendor disambiguation, then proceed |

---

## Edge case 9 — Multi-question request

**Query:** "research: (1) features of tool A, (2) pricing comparison of IDE agents, (3) MCP support in tool A vs tool B"

**Analysis:**
- Trigger "research" → Frame mandatory
- 3 sub-questions → need to decide: one brief or three

**Decision:** **One brief.** Phase 2 Q9 (focus) is written as "Compare tool A vs tool B: features, pricing, MCP support". Multi-question is merged into one research_question. If one of the sub-questions needs a radically different approach (e.g., one about regulation, another about tech), AskUserQuestion at Phase 2: "Is this one research task or three separate ones?"

---

## Decision matrix — when uncertain

If the bypass-evaluator is unsure after applying patterns 1-4:

| Signal → | Trigger keyword | Specific entity+attr | Resource lookup | Yes/no | Short query | Compare/contrast | Compliance signals |
|---|---|---|---|---|---|---|---|
| **Decision** | Frame | Bypass | Bypass | Bypass | Bypass | Frame | Frame |

**Tie-breaker rules:**

1. **Trigger keyword wins everything** — even if the query is factual.
2. **Compliance / regulatory / safety signals** beat bypass — even if the query is simple.
3. **Compare / contrast** beats bypass — multi-source verification is mandatory.
4. **Always-volatile topic** does not change the bypass decision, but adds a forward-tag for downstream.
5. **On full uncertainty** — Frame (cost of FP: 1 AskUserQuestion; cost of FN: research drift, wrong scope).

---

## Anti-patterns

- ❌ Bypass for a query with a trigger keyword "because the question is simple"
- ❌ Frame for a conversational "hi, how are you" (skip the skill entirely instead)
- ❌ Ignoring compliance/regulatory signals in the bypass decision
- ❌ A single-question research_question for a multi-faceted request (scope is lost)
