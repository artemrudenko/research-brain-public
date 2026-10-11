# Research-Grep — Search Recipes

Ready-made grep/glob commands for common topic families. Each recipe follows the scheme: **TERMS → DOMAINS → COMMANDS** (what to search → where → how).

Usage: after Phase 1 (extract keywords), check whether the topic matches one of the recipe families below. If so — run the recipe's commands in parallel. Otherwise — the generic search from `rules/common.md` (grep everything).

> **Topic-agnostic note.** The categories below (policy, security, metrics, tooling, …) are illustrative families, not a fixed enum. The real categories live in `config/topics.yaml`; substitute `{topic}` with whatever categories that file defines. Knowledge is stored as notes in `brain/`, curated links in `pipeline/2-curated/{topic}/index.md`, and verbatim captures in `pipeline/0-archive/`.

---

## Recipe 1 — Policy / Governance / Standards

**Topic triggers:** policy, governance, transparency, compliance, ISO, IEEE, OECD, EU AI Act, regulation

**Search terms (examples):** `policy`, `governance`, `transparency`, `compliance`, `ISO`, `IEEE`, `OECD`, `regulation`

**Domains:**
- `brain/` — synthesized notes tagged with the policy/governance topic
- `pipeline/0-archive/` — verbatim captures (standards documents, `DEPTH=deep`)
- `pipeline/2-curated/{policy-topic}/index.md` — external links
- `pipeline/3-synthesis/` — pre-artifact drafts

**Commands:**
```
Glob: brain/**/*.md
Glob: pipeline/0-archive/**/*.md
Read: pipeline/2-curated/{policy-topic}/index.md
Grep: pattern="ISO|IEEE|OECD|policy|governance" path="brain/" output_mode="files_with_matches"
```

---

## Recipe 2 — Security / Guardrails / Risk

**Topic triggers:** security, guardrails, risk, OWASP, MITRE ATLAS, SLSA, NIST AI RMF, vulnerability, supply chain

**Search terms:** `security`, `guardrails`, `OWASP`, `MITRE`, `SLSA`, `risk`, `NIST`, `vulnerability`, `prompt injection`, `RCE`

**Domains:**
- `brain/` — synthesized security notes
- `pipeline/0-archive/` — verbatim OWASP/MITRE/SLSA + standards captures (NIST AI RMF, ISO; `DEPTH=deep`)
- `pipeline/2-curated/{security-topic}/index.md` — curated sources
- `pipeline/3-synthesis/` — pre-artifact drafts

**Commands:**
```
Glob: brain/**/*.md
Glob: pipeline/0-archive/**/*.md
Read: pipeline/2-curated/{security-topic}/index.md
Grep: pattern="OWASP|MITRE|SLSA|guardrail|injection" path="brain/" output_mode="files_with_matches"
```

---

## Recipe 3 — Metrics / Dashboards / Usage Tracking

**Topic triggers:** metrics, dashboard, usage, tracking, monitoring, KPI, baseline, ROI

**Search terms:** `metrics`, `usage`, `tracking`, `dashboard`, `KPI`, `baseline`, `monitoring`

**Domains:**
- `brain/` — synthesized notes on the metrics topic
- `pipeline/2-curated/{metrics-topic}/index.md` — curated sources
- `pipeline/0-archive/` — verbatim captures (`DEPTH=deep`)

**Commands:**
```
Glob: brain/**/*.md
Read: pipeline/2-curated/{metrics-topic}/index.md
Grep: pattern="metric|baseline|KPI|usage" path="brain/" output_mode="files_with_matches"
```

---

## Recipe 4 — Tooling / Agents / Plugins / MCP

**Topic triggers:** MCP, plugin, skill, agent, AGENTS.md, portability, tooling, IDE

**Search terms:** `MCP`, `plugin`, `skill`, `agent`, `AGENTS.md`, `portability`, `tooling`

**Domains:**
- `brain/` — synthesized tooling notes
- `pipeline/3-synthesis/` — pre-artifact drafts
- `pipeline/0-archive/` — verbatim captures (`DEPTH=deep`)

**Commands:**
```
Glob: brain/**/*.md
Glob: pipeline/3-synthesis/**/*.md
Grep: pattern="MCP|AGENTS\\.md|plugin|portab" path="brain/" output_mode="files_with_matches"
```

---

## Recipe 5 — Pipeline material (untriaged + curated)

**When to use:** the user explicitly wants "what we recently collected" / "what's in the pipeline" / "what's in raw"

**Search terms:** keywords from the request + temporal markers

**Domains:**
- `pipeline/1-incoming/{topic}/` — untriaged (categories from `config/topics.yaml`)
- `pipeline/2-curated/{topic}/` — curated
- `pipeline/3-synthesis/` — pre-artifact drafts
- `pipeline/registry.md` — dedup registry (URL-level)

**Commands:**
```
Glob: pipeline/1-incoming/**/*.md
Glob: pipeline/2-curated/**/index.md
Glob: pipeline/3-synthesis/**/*.md
Read: pipeline/registry.md
Grep: pattern="{keywords}" path="pipeline/" output_mode="files_with_matches"
```

**Note:** `pipeline/1-incoming/` is noisy. Use it only when `DEPTH=deep` or the user specifically asked about incoming.

---

## Generic recipe (fallback when topic doesn't match above)

**When to use:** the request doesn't fit any category above

**Commands (run in parallel):**
```
Read: brain/INDEX.md  (if not already in context)
Grep: pattern="{primary keyword}" path="brain/" output_mode="files_with_matches" head_limit=20
Grep: pattern="{primary keyword}" path="pipeline/2-curated/" output_mode="files_with_matches" head_limit=10
Grep: pattern="{primary keyword}" path="pipeline/3-synthesis/" output_mode="files_with_matches" head_limit=10
Grep: pattern="{primary keyword}" path="pipeline/0-archive/" output_mode="files_with_matches" head_limit=10
```

If the primary keyword gave > 5 hits — narrow with a second keyword by grepping the already-found files. If it gave 0 hits — try synonyms / a translation.

---

## Index shortcut

`brain/INDEX.md` is the hand-curated map of contents (a Map-of-Content note in the Obsidian vault). If it has an entry on the topic, that is the **fastest path** to the key material. Before grepping, read the descriptions in `brain/INDEX.md` first.

In an Obsidian vault you can also lean on backlinks and the graph view to traverse from one note to related notes — `brain/INDEX.md` plus backlinks replace any generated index file.
