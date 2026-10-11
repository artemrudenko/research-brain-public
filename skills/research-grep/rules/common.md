# Research-Grep — Project Paths & Conventions

## File paths (variables used in SKILL.md)

| Variable | Path (relative to `{{VAULT_ROOT}}`) |
|---|---|
| `BRAIN_DIR` | `brain/` |
| `BRAIN_INDEX` | `brain/INDEX.md` |

`{{VAULT_ROOT}}` is the project root — the folder opened in Cowork / Claude Code. All paths below are relative to it.

## Search domains (priority order for Phase 2)

| Order | Domain | Path | Type | When to skip |
|---|---|---|---|---|
| 1 | Index (MOC) | `brain/INDEX.md` | hand-curated map of contents | Never skip — read first |
| 2 | Knowledge notes | `brain/` | concepts / lessons / playbooks | Never skip |
| 3 | Curated sources | `pipeline/2-curated/{topic}/index.md` | external links, indexed (written by `pipeline-curate`) | Skip if topic not in mapping |
| 4 | Synthesis drafts | `pipeline/3-synthesis/` | pre-artifact drafts | Never skip |
| 5 | Incoming | `pipeline/1-incoming/` | untriaged articles | **Only at `DEPTH=deep`** — noisy |
| 6 | Verbatim archive | `pipeline/0-archive/` | verbatim source captures | **Only at `DEPTH=deep`** OR explicit request |

## ⚠ Hard rule — knowledge ↔ telemetry boundary

**Top-level scope:** the research inventory scans ONLY the following top-level directories:

| Top-level dir | In scope? | Type |
|---|---|---|
| `brain/` | ✅ YES | Knowledge vault (concepts/lessons/playbooks) — an Obsidian vault |
| `pipeline/` | ✅ YES | Research pipeline (incoming, curated, synthesis, verbatim archive, registry) |
| `archive/` | ❌ NO (default) | Inactive/superseded project artifacts (distinct from `pipeline/0-archive/`) |
| `planning/` | ❌ NO | Operational queues / research briefs |
| `config/` | ❌ NO | Project configuration (sources, topics, channels, schedule) |
| `skills/` | ❌ NO | Project skill definitions |

**Top-level exclusion (most important):** simply do not glob `archive/`, `planning/`, `config/`, or `skills/`. They are not in the search-domains list (Phase 2 priority order above). This is a hard rule for confidence — do not pull them in via an explicit Glob or Grep.

**Why:** a research query about a standard should not return planning queues, configuration, or the skill definitions themselves. Those are project plumbing, not knowledge. The "knowledge vs system" boundary is enforced at the skill level via the explicit scope-dir list.

**Counter-example (correct):** "what do we know about ISO 42001" → greps `brain/` notes and `pipeline/` (curated/synthesis/archive) for knowledge, does not touch `planning/` or `config/` (plumbing).

## Search domain → folder mapping

The knowledge vault uses the topic categories defined in `config/topics.yaml`. Notes in `brain/` and curated indexes in `pipeline/2-curated/{topic}/` are organized by those same categories. To route a search:

1. Match the request's keywords against the categories in `config/topics.yaml`.
2. Grep `brain/` for notes tagged with the matching `domain:` / `tags:` in their frontmatter.
3. Grep the corresponding `pipeline/2-curated/{topic}/index.md` for curated external links.
4. For untriaged or verbatim material (at `DEPTH=deep`), grep `pipeline/1-incoming/{topic}/` and `pipeline/0-archive/`.

If the request crosses several categories — search all of them.

## Keyword extraction rules

1. **Preserve exact-form** — if the user wrote `MCP server`, search `MCP server`, not `Model Context Protocol` (but add it as a synonym).
2. **Cross-language expansion** — for a term in one language, add its translation to `SEARCH_TERMS` if the corpus is multilingual.
3. **Acronyms first** — short terms (`MCP`, `RAG`) give more relevant hits than long paraphrases.
4. **Project-specific aliases** — check `brain/INDEX.md` and `config/topics.yaml` for project terminology.
5. **Stop-words** — drop common filler words.

## Coverage thresholds

| Threshold | Criteria | Recommended Phase 4 option |
|---|---|---|
| **none** | 0 hits across all domains | Web from scratch + save raw |
| **partial** | 1-3 hits, or only raw with no synthesized notes | Local + a full web research pass |
| **substantial** | 1+ synthesized note + curated/verbatim captures on the topic | Local + targeted web for an update |
| **saturated** | 2+ synthesized notes from different angles + raw + curated | Use local |

## Skip conditions (restated — for a quick check)

- Request about "what came out today / latest news / today's release"
- A narrow factual one-sentence question
- A research-build workflow already in progress this session
- Context already contains a raw file and the user asks for synthesis from it
- A conversational meta-question about how the project is set up
- An action request (send / update / rename)

## Time budget

- Phase 1 (extract): < 5 seconds (no tools)
- Phase 2 (search): < 30 seconds for standard depth (~8-12 grep/glob calls)
- Phase 3 (inventory): < 10 seconds (in-memory aggregation)
- Phase 4 (ask): pending user response
- Total to Phase 4: target < 60 seconds

If Phase 2 exceeds 30 seconds with no useful hits — fall back to coverage=`none`, move to Phase 4.

## Output handover format

When handing control to another skill — add this to its context:

```
## Research-Grep Context

**Topic:** {TOPIC}
**Coverage:** {none / partial / substantial / saturated}
**User decision:** {chosen option}

**Pre-loaded inventory:**
{markdown list from Phase 3 — compact}

**Identified gaps (if web chosen):**
- {gap 1}
- {gap 2}
```

The receiving skill must read this context and not duplicate the search.
