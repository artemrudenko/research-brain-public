# source-manage — acceptance tests

Given/When/Then scenarios for conversational topic & source edits. Run by reading
the skill and walking each scenario against a scratch copy of `config/`
(`cp config/sources.yaml config/topics.yaml` into a temp dir; never mutate the real
config). The backend assertions match `scripts/manage_sources.py` behavior.

> **Config-format note.** These scenarios use a LEGACY (`.md`) fixture — that path must
> keep working on unmigrated installs. On a YAML install (`config/sources.yaml` +
> `config/topics.yaml` present — the active format, CONVENTIONS §2.3) the SAME commands
> apply the same changes to the YAML twins and never touch the `.md` fallback; that
> behavior is pinned deterministically by `tests/test_manage_sources.py` (YAML-mode
> section). Where a scenario names `sources.md`/`topics.md`, read "the active config".

---

## Scenario 1 — start monitoring a new topic

**Given** `config/topics.yaml` and `config/sources.yaml` have no `ai-agents` section,

**When** the user says "хочу начать мониторить тему ai-agents" (intent
`add-topic`, TOPIC=`ai-agents`),

**Then**
- `config/topics.yaml` gains a `## Topic: ai-agents` section with `Name`,
  `Save folder: pipeline/1-incoming/ai-agents/`, and include/exclude rules,
- `config/sources.yaml` gains a `## Category: ai-agents` block with an empty but
  well-formed 6-column Active-sources table (`| URL | Type | Tier | Priority |
  Filter | Active |`) and a matching `Registry category: ai-agents`,
- `python3 scripts/validate_config.py` still reports `sources.md valid`,
- the skill confirms in plain language and asks which sources to add.

---

## Scenario 2 — watch a blog, type confirmed not invented

**Given** the topic `ai-agents` exists,

**When** the user says "следи за блогом https://simonwillison.net/" with no type
or tier supplied,

**Then**
- the skill **detects** the type (`blog` for a bare index, or proposes the RSS
  feed if one is known) and **confirms it** before writing,
- the skill **asks** for the tier (offering `medium` as default) — it does not
  silently pick one,
- after the user answers, exactly one source row is appended to the `ai-agents`
  Active-sources table with the confirmed type/tier,
- no other row or section is modified.

---

## Scenario 3 — add an RSS feed to an existing topic

**Given** topic `tech-news` exists,

**When** the user says "добавь RSS-фид https://hnrss.org/frontpage в tech-news",

**Then**
- the URL is recognized as `rss` (feed path),
- a row
  `| https://hnrss.org/frontpage | rss | <tier> | <priority> | <note> | yes |`
  is appended to the `tech-news` table,
- the topic name and category name stay identical (`tech-news` in both files).

---

## Scenario 4 — add a source to a topic that doesn't exist yet (auto-sync)

**Given** there is no `ai-rag` topic,

**When** the user says "add this feed https://rag.example/feed to ai-rag",

**Then**
- the skill notes it will create the topic, then `add-source` creates
  `## Topic: ai-rag` + `## Category: ai-rag` **and** appends the row,
- the two files remain name-synced (no orphan source without a topic).

---

## Scenario 5 — pause then resume a source (idempotent)

**Given** `https://hnrss.org/frontpage` is an active row under `tech-news`,

**When** the user says "поставь источник https://hnrss.org/frontpage на паузу",

**Then**
- `pause` flips that row's `Active` cell to `no` (only that row),
- a second "pause" of the same URL reports a **no-op** (already paused),
- a later "включи обратно …" (`resume`) flips it back to `yes`,
- every other source row is unchanged.

---

## Scenario 6 — re-adding the same source is a no-op

**Given** `https://hnrss.org/frontpage` already appears in `sources.md`,

**When** the user asks to add the same URL again,

**Then**
- `add-source` reports "already present" and writes nothing,
- the URL appears exactly once in the file (no duplicate row).

---

## Scenario 6a — pause vs. remove-source (one blog, keep the topic)

**Given** topic `tech-news` has two active sources, one being
`https://oldblog.example/feed`,

**When** the user says "stop watching this one blog:
https://oldblog.example/feed",

**Then**
- the skill recognizes this targets a **single source**, not the topic, and
  **clarifies** whether to *pause* (reversible, keeps the row — the gentle
  default) or *delete* it (`remove-source`),
- on "just delete it", `remove-source https://oldblog.example/feed` removes
  exactly that one row; the `## Category: tech-news` section and the other source
  remain intact,
- on "pause it" (or if intent is unclear), `pause` flips only that row's `Active`
  to `no` and nothing is deleted,
- removing an absent URL is a clean no-op: "not found (already absent)".

---

## Scenario 6b — a commented EXAMPLE row is pausable

**Given** a fresh template `config/sources.yaml` whose EXAMPLE rows carry a trailing
`<!-- # EXAMPLE — replace -->` comment (e.g.
`https://example.com/feed.xml`),

**When** the user says "pause https://example.com/feed.xml",

**Then**
- `pause` finds the row despite the trailing comment (it is parsed as a valid
  6-cell row, matching `brain_status`), flips `Active` to `no`,
- the inline `<!-- … -->` comment **survives** the flip (and a later `resume`
  restores the row verbatim — comment not duplicated),
- `manage_sources.py list` and `brain_status` agree on the count (the commented
  row is counted by both — no contradiction on a fresh install).

---

## Scenario 7 — stop monitoring a topic

**Given** topics `ai-agents` and `tech-news` both exist,

**When** the user says "перестань мониторить тему tech-news" (intent
`remove-topic`),

**Then**
- `## Topic: tech-news` is removed from `topics.md`,
- `## Category: tech-news` (and its sources) is removed from `sources.md`,
- `ai-agents` remains fully intact in both files,
- the skill **confirms first** (it's destructive) and would warn if `tech-news`
  were the **last** topic — removing it would leave zero source rows and make
  `validate_config.py` FAIL — offering to pause its sources instead,
- `validate_config.py` still reports `sources.md valid`,
- removing `tech-news` again is a clean **no-op** (not an error).

---

## Scenario 8 — malformed URL is rejected, not written

**Given** topic `ai-agents` exists,

**When** the user gives "add source medum,com/tag/ai to ai-agents",

**Then**
- the skill (and the script) **reject** the malformed URL — nothing is written,
- the user is told what's wrong and asked for a corrected URL (e.g.
  `https://medium.com/tag/ai/latest`),
- `sources.md` is byte-for-byte unchanged.

---

## Scenario 9 — show what we monitor

**Given** `ai-agents` has 2 sources (1 paused) and `tech-news` has 4 sources,

**When** the user says "покажи что мониторим" (intent `list`),

**Then**
- the skill runs `manage_sources.py list` and reports a plain-language summary:
  "ai-agents: 2 source(s) (1 paused); tech-news: 4 source(s)",
- no raw markdown table is dumped at the user.

---

## Scenario 10 — boundary: full setup hands off to setup-wizard

**Given** a fresh checkout with template config,

**When** the user says "set up everything — topics, delivery, schedule",

**Then**
- `source-manage` recognizes this as bulk first-run setup and **defers** to the
  `setup-wizard` skill (which owns tags / channels / schedule / the rehearsal),
- it does not attempt the multi-step interview itself.
