# CONVENTIONS — the shared contract for all contributors (humans and agents)

> The single source of truth for paths, configs, and naming. Every skill/script/doc follows it.

## 1. Paths

- The product opens in Cowork / Claude Code **from the project root folder**.
- All paths in skills/tasks are **relative to the project root**. No absolute
  `/Users/...`. Example: `pipeline/1-incoming/`, `config/sources.yaml`, `brain/concepts/`.
- Where an instruction needs a "root", use the placeholder `{{VAULT_ROOT}}` = the current folder.

## 2. Configuration files (`config/`)

| File | Format | Purpose |
|---|---|---|
| `config/sources.yaml` | YAML | **The** source config (schema §2.3): collection sources by category (url, type, tier, priority, filter, active) |
| `config/topics.yaml` | YAML | **The** topics config (schema §2.3): tracked topics + tags + include/exclude rules |
| `config/sources.md` / `config/topics.md` | markdown | **Retired (0.8.0)** — the runtime no longer reads the legacy `.md` tables; imported once via `python3 scripts/schema.py migrate-config` (§2.3) |
| `config/channels.yaml` | YAML | Digest delivery channels |
| `config/schedule.yaml` | YAML | Collection and digest cadence |
| `config/tags.yaml` | YAML | Controlled vocabulary of tags (schema — §11) |
| `config/glossary.yaml` | YAML | Optional plain-language glossary of terms/acronyms, appended to the digest when its terms appear (delete the file to turn the glossary off) |
| `config/search.yaml` | YAML | Web-search provider (optional, see §15) |
| `config/research.yaml` | YAML | Sonar cross-check for research-build Phase 6.5 (optional, key-gated, see §15a) |
| `config/agents.yaml` | YAML | Single source of truth for the pipeline role agents — `scripts/gen_agents.py` renders it into `.claude/agents/*.md` and `config/codex-profiles.example.toml` (`--check` guards drift) |
| `config/codex-profiles.example.toml` | TOML | GENERATED from `agents.yaml` — Codex per-role model/reasoning-effort profiles; do not hand-edit |
| `config/.env.example` | env | Secrets template (the real `.env` is in .gitignore) |
| `config/README.md` | markdown | Operator-facing index of the config files above |

The sources config carries a per-source **`tier`** field (credibility: `high`/`medium`/`low`) —
it is the source of the `tier` value copied into the pipeline frontmatter and shown in the
digest (§5, §12).

### 2.1 `config/channels.yaml` — schema (fixed)

```yaml
# Delivery channels. enabled=false → the channel is skipped.
# Secrets are NOT here — they live in .env (referenced via *_env).
delivery:
  language: en              # digest language: en | ru | ...
  technical_level: balanced # OPTIONAL audience knob: technical | balanced | non-technical
  email:
    enabled: false
    provider: gmail-mcp     # gmail-mcp (in Cowork/Claude Code) | smtp (headless/cron)
    to: []                  # recipient list
    smtp:                   # used only when provider: smtp
      host: ""
      port: 587
      user: ""
      password_env: SMTP_PASSWORD
  telegram:
    enabled: false
    transport: mcp          # mcp (telegram MCP) | bot-api (headless/cron)
    chat_id: ""
    token_env: TELEGRAM_BOT_TOKEN   # only when transport: bot-api
  rocketchat:
    enabled: false
    webhook_url_env: ROCKETCHAT_WEBHOOK_URL   # incoming webhook (no OAuth)
```

**Optional `delivery.technical_level`** (default `balanced` when absent — backward
compatible). A **render-time** presentation level — `technical` / `balanced` / `non-technical` —
that controls how much is explained vs assumed in the digest and interactive answers. It does
**not** change stored knowledge in `brain/` (so switching levels needs no re-processing), and it is
**orthogonal** to `research-frame`'s `audience` question (which is a formality/stakes axis, not a
reader-literacy axis). `validate_config.py` rejects an off-enum value. Full semantics + the
who-reads-it table: [audience-levels.md](audience-levels.md).

**Optional `delivery.alerts` block** (OFF by default — shipped commented out in
`config/channels.yaml`). A PUSH alert that `scripts/health_alert.py` sends when the
health verdict is `DEGRADED`. Two fields: `enabled` (the opt-in flag) and `channel` (one of
the channels above — `email` / `telegram` / `rocketchat` — to alert through). A missing
block or `enabled: false` = no-op (existing users are never suddenly messaged).
Details — in [scheduling.md](scheduling.md) "Health alerts".

```yaml
delivery:
  alerts:
    enabled: false           # default OFF — opt-in
    channel: telegram        # which of the configured channels above to use for the alert
  # ... email / telegram / rocketchat as above
```

**Optional `delivery.pre_send_review` key** (OFF by default — shipped commented out in
`config/channels.yaml`). A boolean opt-in for the pre-send review gate: when `true`, the
`digest-review` skill vets a built digest (claims grounded in the cited sources, trust
markers earned, injection-leak scan, link resolution) between the `digest-deliver`
rehearsal and the real send (`weekly-run.md` Step 5.5). Advisory by design — it surfaces
findings rather than silently blocking the unattended digest. A missing key or `false` =
today's behavior. `validate_config.py` rejects a non-boolean value.

### 2.2 `config/schedule.yaml` — schema (fixed)

```yaml
collect:
  cron: "0 9 */3 * *"          # every 3 days at 09:00 (cron syntax)
  candidate_pool_per_topic: 25 # how many candidates to gather per topic before ranking
  max_articles_per_topic: 10   # how many of the best to read and save per topic per run
curate:
  cron: "0 8 * * 1"         # Monday 08:00 — before synthesis and digest
  min_text_chars: 500       # candidate relevance threshold
synthesis:
  cron: "30 8 * * 1"        # Monday 08:30 — after curate
  min_sources_per_topic: 3  # how many curated sources per topic are needed for auto-synthesis
digest:
  cron: "0 9 * * 1"         # Monday 09:00
  lookback_days: 7
daily_digest:               # OPTIONAL second cadence (ADR 0016) — absent → no daily digest
  cron: "0 8 * * *"         # every day 08:00
  lookback_days: 1          # one day's arrivals
weekly_trends:              # OPTIONAL trends report (ADR 0017) — absent → no trends report
  cron: "0 10 * * 1"        # Monday 10:00 (after the digest)
timezone: "UTC"             # timezone for all cron times (e.g. Europe/Minsk)
```

> **Sequential weekly run:** instead of a timing race between curate/synthesis/digest,
> a single sequential run of `schedule/weekly-run.md` is recommended
> (collect→sanitize→curate→synthesis→extract lessons/playbooks→brain-hygiene→digest→deliver, each gated on the previous step
> finishing). Separate crons remain an option for headless/split execution.

> **Optional daily "inflow" digest:** the `daily_digest` block (default-absent, backward
> compatible) enables a light daily digest — only `New sources` + `Needs attention`, no
> synthesis — built by `build_digest.py --daily` to `digest_daily_YYYY-MM-DD.md` (a distinct
> filename, so it never collides with the weekly digest on the same date). See ADR 0016.

> **Weekly trends:** `build_digest.py` embeds the trends section — topic volume this week
> vs last, rising tags, activity, and knowledge growth — inline in every **non-quiet**
> weekly digest by **default** (`--no-trends` disables; `--report` adds the dynamic,
> browser-grade HTML viewing page). It reads only the installation's durable local sources
> (registry + concepts), so it is fully reproducible. The `weekly_trends` block
> (default-absent) additionally enables the standalone `trends.py` report, written to
> `trends_YYYY-MM-DD.md`. See ADR 0017.

### 2.3 `config/sources.yaml` + `config/topics.yaml` — schema (the source/topic config)

`config/sources.yaml` + `config/topics.yaml` are **the only sources/topics config the
runtime reads** (every reader goes through `scripts/sources/store.py`). The legacy
markdown tables (`config/sources.md` / `config/topics.md`) were **retired before public 0.1.0** —
no code path reads them anymore; they survive only as **migration input**. An unmigrated
legacy install (real `.md` content, no YAML twin) fails **loudly** everywhere — collect,
`validate_config.py`, `configure.py`, `manage_sources.py` — each pointing at the one-time
import: `python3 scripts/schema.py migrate-config` (offered by `update.sh`/`update.ps1`,
never auto-applied). The migration is a **sidecar**: it writes the YAML twins and leaves
the `.md` files untouched — they remain the rollback copy, and the validator WARNs while
such a stale leftover drifts from the YAML. Fresh installs get the YAML files from the
setup-wizard / `configure.py` (the shipped archive contains empty twins). Both files carry
`schema_version: 2` (schema 1 *is* the retired `.md` format; see §5.5). The files are
machine-written by `scripts/manage_sources.py`: the **values** are the user's to edit;
comments/formatting are regenerated on each change (same contract as `tags.yaml`).

```yaml
# config/sources.yaml
schema_version: 2
categories:
  - name: ai-agents            # lowercase slug; = the topics.yaml topic name and the
    sources:                   #   pipeline/1-incoming/<name>/ save folder
      - url: "https://blog.example/feed.xml"   # required, http(s) only
        type: rss              # rss | blog | medium-tag | webpage   (default rss)
        tier: high             # high | medium | low — source credibility (default medium)
        priority: medium       # high | medium | low — collection ordering (default medium)
        filter: "all posts"    # short filter note (default "—")
        active: true           # true | false (default true); paused sources stay listed
```

```yaml
# config/topics.yaml
schema_version: 2
topics:
  - name: ai-agents            # slug, = the sources.yaml category (same name)
    tags: [ai, agents]         # frontmatter tags for collected articles (default [<name>])
    include: "Substantive pieces directly about agents."   # what belongs (prose)
    exclude: "Hype with no substance."                     # what to drop / route elsewhere
```

Semantics are 1:1 with the retired legacy tables (`migrate-config` maps the 6-column
`URL | Type | Tier | Priority | Filter | Active` rows onto `categories[].sources[]` and the
`## Topic:` sections onto `topics[]`); the save folder stays **derived** as
`pipeline/1-incoming/<name>/`, never stored, and `min_text_chars` stays a global curate
knob in `schedule.yaml` §2.2. `validate_config.py` validates the YAML twins, ERRORs on an
unmigrated legacy install (with the `migrate-config` pointer), and WARNs when a leftover
`.md` no longer matches the YAML (edits to the retired `.md` are ignored) or when exactly
one twin exists (half-migrated). `manage_sources.py` / `import_opml.py` write only the
YAML twins.

### 2.4 `config/authors.yaml` — schema (optional; the author-monitoring roster)

`config/authors.yaml` records the people the user has **explicitly chosen** to follow.
The file is **optional and absent by default** — no file means nobody is monitored. That
default is deliberate: `scripts/source_report/authors.py` may *suggest* an author worth
following (`monitoring_suggestions`), and the `discover-sources` / `author-manage` skills
may *offer* one, but **nothing in the system ever starts monitoring an author on its own**.
A suggestion becomes an entry here only after the user accepts it; the write is
`author-manage`'s, never the collector's, and never a report's.

Each entry names a person **and** a handle the chosen variant can actually act on. The
required companion field differs per variant, and `validate_config.py` rejects an entry
that lacks it — an entry naming a person with no way to find them would have to be
resolved by *guessing*, and a wrong guess credits one person's work to another (the same
refusal the identity ladder in `authors.py` makes when it declines to merge two same-named
authors; see §9).

```yaml
# config/authors.yaml
schema_version: 1
authors:
  - name: Jane Doe             # required — display name, used in reports
    monitoring: rss            # rss | publication-filter | scholarly
    topic: ai-agents           # required by every new variant
    feed: "https://example.com/jane/feed.xml"   # required by `rss`, http(s) only
    id: "orcid:0000-0002-1825-0097"   # stable identifier; required by `scholarly`
    url: "https://example.com/author/jane"   # canonical profile URL, http(s) only
    publication: example.com   # required by `publication-filter` — the feed to narrow
    active: true               # true | false (default true); paused entries stay listed
    added: "2026-07-21"        # free text — when the user accepted the suggestion
    note: "suggested by source-insights"       # free text
```

| `monitoring` | how it works | requires |
|---|---|---|
| `rss` | an author-specific feed, collected as an ordinary RSS source | `topic` + `feed` |
| `publication-filter` | a **paused** publication feed, narrowed to one identity | `topic` + `publication` + (`id` or `url`) |
| `scholarly` | OpenAlex / Semantic Scholar / ORCID, queried **by identifier** | `topic` + `id` |

Legacy `search` rows remain valid for reading and removal, but new entries are refused.
They never collected work; use `/discover` for on-demand source proposals.

`topic` is required by every variant that COLLECTS: the article lands in
`pipeline/1-incoming/<topic>/` and is judged by that topic's curate rules, so an author
without one has nowhere to go — and where a person's work belongs is knowledge only the
user has. Legacy `search` rows are exempt so they remain readable. An `rss` author is
merged into their topic's category as an **ordinary source** at collect time
(`scripts/authors/collect.py`), so dedup, ordering, the per-source budget and journal
provenance all apply with no author-specific branch; a feed already monitored is not added
twice. A `publication-filter` author is merged too, but only when the referenced publication
source is **paused**. That is the variant's whole shape: the feed URL is the user's own
(we never invent one), it is not being collected whole, and polling it filtered collects
that publication *only* for the people they follow. If the publication source is **active**
it is already collected whole — their articles already arrive — so the entry is reported as
redundant rather than silently filtering a feed other readers depend on. The merged source
always travels with its per-item predicate (`author_item_filters`); without it the whole
publication would be collected under one author's name. Non-matching items are journalled
as `off_topic`/`author_mismatch`, so "we read the feed and none of it was theirs" stays
distinguishable from a dead feed.

Matching uses the identity ladder read outward (`scripts/authors/match.py`): the author's
identifier, their canonical profile URL, or their name **scoped to that publication**. No
fuzzy names — a miss costs one mention, a false match credits someone with a stranger's
work. *Known limit:* two followed authors on the same paused publication but different
topics get the feed under both topics with an OR-ed predicate, so cross-run URL dedup
decides which topic an article lands in.

`scholarly` is still withheld from the merge — it returns JSON the feed parser would read
as zero items, indistinguishable from an author who stopped publishing. `scholarly` and
`search` therefore have **no collection path** (headless *or* agent-mode). New
`search` rows are refused because the variant was retired; older rows remain
readable and removable. The CLI accepts `scholarly` as a staged choice, but a run
collects nothing for it. That withholding is **never silent**: `withheld_author_warnings`
(`scripts/authors/collect.py`) emits a `WARN: author monitoring: …` naming
each such author and whether the path is staged or retired, so "not collected yet" never reads as "published nothing lately"
(the guardrail from the 2026-07-22 review).

`scholarly` insists on `id` rather than accepting a profile `url`, because those APIs are
queried by identifier: accepting a URL would leave the lookup to fall back on the display
name, which is precisely the collision this schema exists to prevent. The enum is owned by
`scripts/config_schema.py` (`AUTHOR_MONITORING_VARIANTS`) and pinned to this block by
`tests/test_config_schema_drift.py`.

## 3. Delivery: two transports (both covered)

- **MCP mode** (the primary path, in Cowork/Claude Code): the `digest-deliver` skill calls the
  Telegram / Gmail MCP tools directly. Rocket.Chat — through the **same guarded module** the
  headless path uses, via its CLI (`python3 scripts/delivery/rocketchat_webhook.py
  --text-file <digest.md>`), never a raw `curl`/WebFetch POST: that would bypass the SSRF
  guards and put the secret-bearing webhook URL into argv (`ps`, shell history, the agent
  transcript). One hardened transport, two callers.
- **Headless mode** (cron, no agent): the Python module `scripts/delivery/` —
  `email_smtp.py`, `telegram_botapi.py`, `rocketchat_webhook.py`. Testable, no MCP.

The skill picks the transport from `channels.yaml` (`provider` / `transport`). Known values:
email `provider: gmail-mcp | smtp`, telegram `transport: mcp | bot-api`. The headless path
**skips** the **MCP values** (`gmail-mcp` / `mcp`) — those are sent by the agent skill. **Any other
value is a config error** (`DeliveryError`, rc=1, `CONFIG ERROR` in dry-run), not a silent skip — a
typo like `stmp` no longer drops a channel silently. SMTP: `587` (STARTTLS) and `465` (implicit TLS /
`SMTP_SSL`), both with certificate verification (`ssl.create_default_context()`).

## 4. Skill naming

`{entity}-{action}` kebab-case, ≤3 words. Each skill = `skills/{name}/SKILL.md`
(+ optional `tests/acceptance.md` with Given/When/Then).

## 5. Article frontmatter (pipeline) — strict

Every file in `pipeline/1-incoming/` begins with exactly `---` and contains:
`source, url, title, author, date_published, collected, category, tags`.
Optional: `tier` (`high`/`medium`/`low`) — source credibility, copied from
`config/sources.yaml` at collection and shown in the digest (§12).

**Optional metadata enrichment** (all default-absent, written by the collector when
`scripts/content_metadata/` could establish them; an article without them is valid and
unchanged, so no `schema_version` bump):

| Key | Shape | Meaning |
|---|---|---|
| `authors` | list of `{name, url?, id?}` | Everyone credited, in document order. `author` stays the required single display string (the first extracted name, else the feed's, else `unknown`). |
| `publication` | scalar | The publisher — schema.org `publisher`, else `og:site_name`, else the hostname. |
| `source_url` | scalar | The feed/index the article arrived through. `url` remains the ARTICLE's own URL and the dedup key. |
| `content_type` | scalar | `article` when the page declared itself one. |
| `metadata_source` | scalar | Where the authors came from: `jsonld` / `rss` / `rel-author` / `meta` / `byline`. Provenance, so a wrong byline is debuggable. |

`authors` is the only nested structure in this block. It is emitted through PyYAML
exactly like every scalar field, so an author named `- name: evil` is written as a
quoted string and cannot become a second entry — the structure is the writer's, only
the leaf values come from the document. Never hand-assemble these lines.
`scripts/validate-pipeline-frontmatter.py` is an **advisory** check: it flags files
with missing / empty / broken frontmatter (`yaml.safe_load`, required-field check,
URL, dates, `tags` list; exit 2 with `--strict`). The script itself **deletes nothing** —
the collect step must drop or repair the flagged files.

### 5.1 Concept frontmatter (`brain/concepts/`) — strict

Every concept node begins with YAML frontmatter:
```yaml
title: ...
type: concept
tags: [domain/topic, ...]        # nested, from the config/tags.yaml registry; 2–5 of them; ≥1 domain tag
created: YYYY-MM-DD
last_updated: YYYY-MM-DD          # wiki-ingest stamps this on every write (NOT mtime)
related_concept:                  # machine-checkable links (the graph is built from here + tags)
  - "[[concepts/other-note]]"
sources:                          # anti-hallucination: every key fact cites a source
  - url: "https://..."
    archive: pipeline/1-incoming/<topic>/<file>.md   # see below: for collected sources this is the path to the pipeline article (optional)
    date: YYYY-MM-DD
    tier: high|medium|low         # credibility (visible in the digest)
# opt.: last_verified, ttl_days
```

> **`archive:` for collected sources.** For gathered pipeline sources, the value of
> `archive:` is the path to the article itself in the pipeline (`pipeline/1-incoming/<topic>/<file>.md`
> or `pipeline/2-curated/...`) — the article file IS the local provenance copy. For such a
> source `archive:` is **optional** if the entry carries `url + date + tier`. A dedicated
> copy under `pipeline/0-archive/...` + sha256 remains the rule for web-fetches in a research
> session (the `source-archive` skill), not for the collection path.
`weekly-digest`/`build_digest` read `last_updated`. Nodes tagged `seed`/`example` are excluded from the digest.
**Links are generated via `related_concept:` (frontmatter) + tags**, not only inline `[[...]]`.

### 5.2 Lesson frontmatter (`brain/lessons/`)

A lesson note must carry **at least one** of `related_concept:` OR `parent_playbook:` — otherwise
it is an orphan (a lesson detached from both the concept graph and any playbook is unreachable from
the reading layer and gets flagged by brain hygiene, §13). The canonical shape lives in
`brain/lesson-template.md`; this is the contract home for the rule. New lessons carry
`type: lesson` so `brain/lessons.base` can show them as a live Obsidian Bases view.

The unattended generator is deliberately conservative: `scripts/extract_vault_notes.py` creates
lesson notes only from explicit `## Lessons`, `## Key lessons`, or `## Extracted lessons` sections
already present in `brain/concepts/*.md`. Each bullet becomes one lesson, linked back with a
quoted block-list `related_concept` (matching the §5.1/§5.3 samples — an unquoted inline
`[[...]]` is YAML flow syntax and would parse as a nested list, corrupting the link):

```yaml
related_concept:
  - "[[concepts/<source-concept>]]"
```

plus `source: brain/concepts/<source-concept>.md` and the first cited source URL when available.
The generator is additive/idempotent and never rewrites or deletes existing vault notes.

The upstream write path is responsible for producing those explicit sections: `research-build`
emits "Downstream extraction hints" when it sees candidate lessons, and `wiki-ingest` turns accepted
candidates into `## Lessons` in the concept body. Do not rely on the extractor to infer lessons
from generic prose such as `## How to apply it`.

### 5.3 Playbook frontmatter (`brain/playbooks/`)

Playbooks are reusable methods derived from concepts, lessons, and cited sources. They are
not concepts: a concept says "what we know"; a playbook says "how to act next time".
The canonical shape lives in `brain/playbook-template.md`:

```yaml
title: ...
type: playbook
status: draft|reviewed|retired
tags: [domain/topic, ...]
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
related_concept:
  - "[[concepts/other-note]]"
source_concepts:
  - brain/concepts/other-note.md
sources:
  - url: "https://..."
    archive: pipeline/2-curated/<topic>/<file>.md
    date: YYYY-MM-DD
    tier: high|medium|low
```

Every playbook must have at least one `related_concept` or other vault link at write time.
Drafts are allowed; unreviewed generated playbooks should stay `status: draft`. `brain/playbooks.base`
is the live Obsidian Bases view for browsing them.

`scripts/extract_vault_notes.py` also creates draft playbooks from explicit concept sections named
`## Playbook: <title>` or `## Playbook draft: <title>`. Ordered or unordered list items in that
section become the draft steps; the source concept path and its structured `sources:` block are
carried into the playbook frontmatter for provenance.

As with lessons, `wiki-ingest` writes these sections only when the synthesis contains a real
reusable method, checklist, review loop, or decision procedure. Empty playbook boilerplate is worse
than no playbook because it makes the front door noisy.

### 5.4 Author-node frontmatter (`brain/authors/`)

Author nodes are first-class vault entities — "here is what we know of this person" —
distinct from the followed-authors roster (`config/authors.yaml`, §2.4), which is "I
want more of their work". The canonical shape lives in `brain/author-template.md`:

```yaml
title: ...
type: author
identity_key: "id:… | url:… | name:…|pub:…"   # the shared identity ladder key (§2.4)
identifier: ""        # ORCID / stable handle when known — else ""
profile_url: ""       # canonical profile when known — else ""
tags: [author]
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
```

Author nodes are **backlink-only**: the authoritative author↔concept link lives ON the
concept, in its `contributors: ["[[authors/<slug>]]"]` frontmatter — so a node lists NO
concepts, and the author's "everything they wrote" view is the Obsidian backlink panel.
Because `type != concept`, author nodes are exempt from the concept `sources:` rule (§5.1)
and are never flagged as orphans by `validate_brain.py`.

Author nodes are written ONLY through `wiki-ingest`'s gated path (there are no generated
indices in `brain/`): as a best-effort byproduct of a concept write, the cited-source
authors are resolved from the article `authors:` frontmatter via the identity ladder (no
fuzzy matching) and proposed for creation + a `contributors:` edit behind the same
`AskUserQuestion` gate. A node is never auto-created from the roster, nor vice versa;
`/author nodes` cross-references the two read-only (`followed: yes/no`).

### 5.5 Schema versioning & the additive-only rule

Frontmatter and config shapes evolve; these two rules keep that from breaking already-deployed
installs (they are shipped without an auto-migrator today — see [ADR 0019](adr/0019-assisted-in-place-update.md)
and [ADR 0020](adr/0020-frontmatter-schema-versioning.md)).

**Additive-only (the default).** A schema change should ADD an OPTIONAL key with a safe code
default, never make a new key required and never repurpose an existing key's meaning. Readers must
tolerate its absence (an old file still parses). Config readers already do this (`*.get(k, default)`).
An additive change needs **no** version bump and **no** migration — this is how most changes should
land.

**`schema_version` (for the rare breaking change).** Newly written frontmatter-bearing artifacts
carry a single **flat top-level** `schema_version: N` integer — concept/lesson notes from their
templates, pipeline articles stamped by `collect.py`/`inbox.py` — as do the fixed-schema configs
(`channels.yaml`, `schedule.yaml`). Files predating the stamp read as the baseline (see below), so it
is not required on existing files. Rules:

- **Flat, never nested.** It is a column-0 key, not a sub-key of a `meta:` block — several readers on
  the headless (no-PyYAML) path are line-based (`build_digest._split_frontmatter`, the audit reader in
  `sanitize_incoming`, the tag reader in `validate_brain`) and would miss or misread a nested stamp.
- **Missing == baseline (1).** Every file predating the stamp is treated as version 1, so introducing
  it is a no-op for existing installs.
- The single source of truth is `scripts/schema.py` (`CURRENT` per artifact class); `validate_config`
  and `validate_brain` emit an **advisory** warning when a file is stamped NEWER than the running code
  (the one risky direction — old code silently misreading a new-schema file).
- **On a breaking change:** bump `CURRENT[kind]` in `scripts/schema.py`, update the template/writer to
  stamp the new number, and register the migration step in `scripts/schema.py`'s
  `MIGRATIONS[(kind, N)]` — the migrator machinery (`migrate_text`/`migrate_file` +
  the `schema.py migrate` CLI) ships and is rehearsed end-to-end in tests. The first
  real entries are `(sources, 1)→2` and `(topics, 1)→2` — the config-format move from
  the `.md` pipe tables to the YAML twins (§2.3). These are **sidecar** migrations: the
  migrated text lands in the sibling `.yaml` file (via `schema.py migrate-config`) and
  the original `.md` is never rewritten or deleted (it stays as the rollback copy; since
  0.8.0 the runtime no longer reads it).

## 6. Language

The content and instruction baseline is **EN**. The digest language is the `delivery.language` parameter.
No internal/source branding, consulting tone, or RU hardcoding in the core.

## 7. Tests

> **Dev checkout only.** The test suite (`tests/`, `pytest.ini`,
> `requirements-dev.txt`) is stripped from the shipped archive — in an install
> this section describes how the product was verified, not files present on disk.

- Python scripts → pytest in `tests/` (mirrors `scripts/`).
- Skills → `skills/{name}/tests/acceptance.md` (Given/When/Then).
- **Toolchain (not a bare `pytest`).** The canonical command is `make test`
  (= `uv run pytest --cov`); a bare `pytest tests/` **bypasses the coverage gate**
  (`pytest.ini` has no `--cov`). `make gate` runs the full local CI mirror —
  `ruff` + `mypy` + `bandit` + `pytest-cov`. The blocking floor is `fail_under` in
  `pyproject.toml` (currently **88%**) — it only ratchets up, so treat that value as
  the source of truth rather than any number quoted here.
- **TDD for `scripts/`:** new/changed `scripts/` code is test-driven — the failing test comes first.
- **Runtime stays stdlib-only except `pyyaml`.** `uv` / `ruff` / `mypy` / `bandit` / `pytest`
  are dev-only and are never imported by a `scripts/` module.
- The `Makefile` + `pyproject.toml` define the gate locally; `.github/workflows/ci.yml`
  runs the identical gate in CI.

## 8. Secrets

Only through env. `config/.env.example` documents the keys. `.env`, `config/.env` are in `.gitignore`.
Headless delivery (`scripts/delivery/deliver.py`) auto-loads `config/.env` if the file exists.
`validate_config.py` catches inline secrets but allows the sanctioned form `*_env: NAME` for a variable
NAME of any case (`password_env: my_smtp_password` is valid) — it must be an **unquoted**
bare identifier; a quoted/token-like value is treated as a leak.

## 9. Pipeline stages and owners (fixed chain)

```
collect-topic     →  1-incoming/{topic}/     (collect-base writes; frontmatter-strict)
pipeline-curate   →  2-curated/{topic}/       (filter by the topics config; writes index.md; marks registry status=processed)
weekly-synthesis  →  3-synthesis/ + brain/    (research-build → wiki-ingest; auto, no manual gates)
weekly-digest     →  digest_*.md + digest_*.audit.json (scans 1-incoming + brain/concepts over lookback_days)
digest-deliver    →  channels                 (email/telegram/rocketchat)
source-archive    →  0-archive/               (verbatim copies of fetched sources; default ARCHIVE_ROOT)
```

- **`2-curated/{topic}/index.md`** — the list of a topic's selected sources: one line per source
  (`- [title](relative-path-to-1-incoming-file) — 1-line summary`). Created/updated by `pipeline-curate`.
- **registry `status`**: empty at collection; `processed` is set by `pipeline-curate` after promotion into `2-curated/`; `rejected` — discarded by the curate rules (no longer re-judged, excluded from the digest's "needs attention").
- **Concept dedup (anti-sprawl):** before a CREATE, `wiki-ingest` looks for a similar existing concept (normalized title + tag overlap); on a match it does an UPDATE, not a CREATE. A possible duplicate is logged in the synthesis-run for periodic manual merge. No embeddings — a simple comparison.
- The verbatim-source archive is **only** `pipeline/0-archive/` (NOT `materials/raw/`, NOT `sources/`).

### 9.1 Collection decision journal (runtime)

`pipeline/.source-insights/events.jsonl` — append-only, one JSON row per candidate
the collector **considered**, not just the ones it kept. The registry answers "what
did we collect?"; this answers "what did we look at, and why did most of it not make
it?" — without which a feed yielding fifty candidates and one keeper is
indistinguishable from one yielding two candidates and one keeper.

- **Written by** `scripts/collect.py` (opt-in: `collect_category(journal_root=...)`,
  which `main()` passes and nothing else does). A **dry run records nothing** —
  `setup_check.py` probes collection on every health check, and those are not runs.
- **Never load-bearing.** A journal failure is swallowed whole; losing a row is
  acceptable, losing a collected article is not.
- **Concurrency-safe under rotation, without stalling collect.** The append
  (`record_decision`) and the rotation compaction (`rotate_pipeline._compact_journal`)
  share a `journal_lock` (mirroring the event log's `events_lock`, §10), so an append that
  lands *during* compaction's read-filter-replace survives instead of being rewritten away
  from a stale snapshot. The **compactor blocks** on the lock (it must not skip work); the
  **writer takes it with a bounded try** (`registry.try_advisory_lock`) and drops the row
  rather than block the collect loop behind a long/stuck compaction — consistent with
  "never load-bearing" above.
- **Relocatable + rotated.** Same `RESEARCH_BRAIN_STATE_DIR` resolver as the delivery
  receipts, health log and feedback log (§10). Pruned by `rotate_pipeline.py` at
  `JOURNAL_KEEP_DAYS` (180) — deliberately longer than the 90 used for digests and
  the health log, because source usefulness is only readable over many runs.
- **`decision` is a closed vocabulary; `reason_codes` are open slugs.** Metrics group
  on `decision`, so a typo there would silently open a new bucket. The headless
  collector emits `selected`, `duplicate_url`, `too_short`, `junk_wall`,
  `unsupported`, `below_topic_cap`, `fetch_failed`; the agentic `collect-base` path
  additionally owns `off_topic`, `stale`, `role_balance`, `duplicate_story`,
  `saved_one_off`.
- **Read it** with `python3 scripts/source_insights.py summary` (read-only facade;
  counts are not verdicts, and thin evidence is labelled as such).

### 9.2 Source Insights report (artifact)

`python3 scripts/source_insights.py report` writes
`pipeline/3-synthesis/source-insights_YYYY-MM-DD.report.html` — a **standalone
sibling** of the digest report, deliberately NOT a sixth tab inside it: that report
holds at five tabs because five fit a phone (§ the 2026-07-14 Trends/Stats/Audit
merge into Pulse), and source intelligence serves a different audience on a
different cadence.

It joins the journal with the registry: the journal knows what a source offered and
what the collector did; the registry knows whether curation kept the survivors. The
join is on the NORMALIZED url, since the journal stores the link as published and
the registry stores the canonical key.

Three deliberate refusals, each pinned by test:

- **No single blended score.** One number would hide which signal moved it, which
  defeats the point of recording reason codes.
- **No automatic `tier` changes.** `tier` in `config/sources.yaml` is the user's
  stated trust; this artifact measures and never edits config (§2.3).
- **No false precision.** Every row carries a confidence band —
  `insufficient` (<5 observations) / `low` (5–19) / `established` (20+) — rather
  than a percentage computed from three data points.

Theme, escaping and the http(s) link allowlist are reused from the digest report
rather than reimplemented; everything rendered came from a remote document. The
render takes its date as an INPUT and is deterministic (no clock, no randomness),
so the same data yields byte-identical HTML. Rotated by `rotate_pipeline.py` and
gitignored like the other dated artifacts.

**Author identity (`scripts/source_report/authors.py`).** The report's Authors tab
resolves credited names with a conservative ladder — same identifier → same
canonical profile URL → same name *within one publication* → otherwise different
people. It never merges names fuzzily, never merges one name across publications,
and never invents an identity from a single article. Misattributing one person's
work silently poisons every count built on it, so the rules refuse to guess.

An author is suggested for monitoring only when ALL of these hold: ≥3 collected
articles, across ≥2 collection runs, ≥60% of judged articles passed curation, and a
**stable profile URL or identifier**. The last is not negotiable — without a handle
there is no way to follow the person, and offering it would be an empty promise.
Suggestions are read-only proposals — accepting one only *stages* a follow, and nothing
is ever enabled automatically. Author *collection* itself does run: `rss` /
`publication-filter` authors are collected headlessly (the followed-authors roster and the
`brain/authors/` nodes exist since 0.10.0), while `scholarly` is staged only,
with no collection path yet (headless *or* agent-mode). Legacy `search` is
retired — see §2.4 for the withheld-author
warning that keeps that honest.

**Where a followable author comes from.** The collector reads the article page's
metadata whenever it fetched that page anyway — i.e. when a short RSS body triggered
the top-up. That is where multiple authors and profile URLs appear, so those articles
can produce suggestable authors. A full-text feed is never re-fetched (doing so would
change the collector's cost profile for no body gain), so its authors stay the bare
`dc:creator` name and remain unfollowable. The coverage is complementary rather than
arbitrary: the feeds with the poorest metadata are exactly the ones whose pages get
read.

## 10. Auto modes (unattended)

- **Internal-corpus synthesis profile** — the mode for the auto cycle (`weekly-synthesis`): `research-build`
  synthesizes from the already-gathered local corpus (`2-curated/` + `1-incoming/`) WITHOUT a mandatory
  research-brief, WITHOUT an external `sources/`-tier registry, and WITHOUT the fail-fast/">30% 🔴" gate.
  The dedup defaults and the citation guard stay. The full chain (frame→grep→build→audit with a registry)
  is available for **manual** deep-dives; dependencies on `sources/` and `planning/research/` are
  **optional/soft** there (absence → warning, not halt). No hardcoded paths to `sources/` as mandatory.
- **Cold-start crosslink** — `wiki-ingest`: for the FIRST concept in an empty topic cluster the
  crosslink gate is relaxed (a self-standing root node is allowed); afterward — the normal rules.
- **Delivery receipt** — `scripts/delivery/deliver.py` writes `pipeline/3-synthesis/.delivered/{digest-stem}.json`
  (channel → status + time + content-hash). On a re-run the already-delivered channels are skipped
  (unless `--force`); changed content (a different hash) is re-sent. A failure of the **final** receipt
  write is no longer swallowed — it prints the error and returns a non-zero code (otherwise a lost receipt
  would silently re-send the channels on the next run).
- **Delivery lock (concurrency)** — a real (not `--dry-run`) delivery takes a short-lived lock
  `pipeline/3-synthesis/.delivered/.delivery.lock` (reuses `run_lock`, `steal_dead` — a crashed
  delivery self-recovers immediately via **same-host** dead-pid detection, lease 1 h; a holder on
  another host is freed by its lease only, since a pid means nothing across machines). Two
  simultaneous `deliver.py` cannot both send the same digest: the second refuses (`exit 1`,
  "another delivery is already in progress"). Dry-run does not lock.
- **MCP reservation (agent path)** — the agent's sequence is `--mcp-status` → **`--reserve-mcp
  CHANNEL`** → send → `--record-mcp CHANNEL`. The reservation writes `status: sending` under the
  same `.delivery.lock` **before** the external send, so two agents that both read `PENDING`
  cannot both proceed: exactly one gets exit 0, the other is refused (`3` already delivered, `4`
  another sender in flight, `1` lock busy) and must not send. `--mcp-status` reports a live claim
  as `IN-FLIGHT`. An abandoned reservation expires after `RESERVATION_LEASE` (1 h) so a crashed
  sender doesn't block the channel forever — which is also the honest limit: an external send is
  not transactional, so this converts a silent double-send into a refusal rather than making one
  impossible.
- **Health / run-history log** — `pipeline/.health/events.jsonl` (gitignored, append-only JSONL). Written
  by both modes: headless `deliver.py` (per-channel outcome) and the agent skills/tasks
  (`collect-base` — items per source; `digest-deliver` — MCP sends; `weekly-run` — run heartbeat)
  via `python3 scripts/health.py record …`. Read by `scripts/health.py report` and by the *health*
  intent of the `brain-ask` skill for a summary (feed liveness, delivery, digest freshness). The write is
  best-effort and never crashes a real run. **Note:** collect/run events are written only by the agent
  path; a pure headless cron (`build_digest.py`) does not collect, so feed liveness is observable
  specifically in the agent mode.
- **Deterministic digest builder** — `scripts/build_digest.py <out.md>`: scans `1-incoming/` by
  `collected:` over `digest.lookback_days`, groups by topic, adds concepts updated by
  `last_updated`, and a "Synthesis this week" section from the latest `synthesis-run_*.md`. The headless
  path (cron) first builds the file with this script, then `deliver.py` delivers it. Each build also
  writes a JSON audit sidecar next to the digest (`digest_YYYY-MM-DD.audit.json`): a derived,
  machine-readable explanation of the digest selection (counts, per-topic shown/hidden source
  decisions, digest hash). It is not a delivery receipt and not a health log.
- **Deterministic lesson/playbook extractor** — `scripts/extract_vault_notes.py`: scans explicit
  lesson/playbook sections in concept notes and writes additive notes into `brain/lessons/` and
  `brain/playbooks/`. It runs after synthesis and before brain hygiene in `weekly-run`, so generated
  notes are checked and surfaced by the same digest/front-door path as manual notes.

## 11. Tagging (controlled vocabulary, non-technical, auto)

- **Frontmatter `tags:` only** (not inline `#tag`). Format is **nested `domain/topic`** (`ai/agents`, `ai/rag`).
- **Super-tag = the nested parent**: `#ai` aggregates `#ai/*` natively. There is NO separate super-tag feature.
- **Registry `config/tags.yaml`** is the single source of allowed tags: `domain → [topics]` + `synonyms`
  (aliases → canonical). Seeded from `config/topics.yaml` + RSS `<category>`.
- **Tagging rule (closed-book):** the LLM picks tags ONLY from the registry; when none fits —
  ≤1 new one in `domain/topic` form → lands in the registry's `pending:` (quarantine), NOT straight into the vocabulary.
- **Cap/floor:** 2–5 tags per note, ≥1 domain tag. Tags live on **concepts** (knowledge); articles carry
  seed tags from RSS categories, normalized through the registry.
- **Promotion/merge:** `validate_brain.py` is **advisory**: it normalizes (lowercase/singular/hyphen),
  merges synonyms, and *recommends* promotion, but it does NOT edit the vocabulary itself. The actual promotion
  of a `pending` tag into `domains:` (on a recurrence of ≥3 concepts) is done by `scripts/promote_tags.py` in
  the brain-hygiene step of `weekly-run`; one-offs stay in quarantine. A new topic does not get stuck in
  `pending:`: `source-manage` (add-topic) seeds the new topic's tag into `config/tags.yaml` right away.

## 12. Collection — multi-stage, RSS-first

- **Three source roles (gather wide → rank → read best):** for each topic, candidates are gathered
  in parallel from three roles —
  - **RSS** — feeds (full/partial body);
  - **Official** — the tool's own news/docs/blog pages (marked as
    official in the sources config);
  - **Search** — tag-based aggregator platforms (Medium/dev.to/Habr);
  
  everything flows into a wide pool `collect.candidate_pool_per_topic` (default 25), is ranked by
  **relevance × freshness × tier**, and the best `collect.max_articles_per_topic` (default 10) are
  read in full. Both numbers are in `config/schedule.yaml` (§2.2); ranking details — in
  `schedule/collect-base.md`.
- **Ladder (cheap → expensive), within each role:** RSS with full body → RSS + WebFetch body top-up → static-page fetch →
  Playwright/Chrome (per-source allow-list only). The browser is not the default.
- **Dedup:** the **persistent, cross-run dedup key is the canonical/normalized URL**
  (`scripts/normalize_url.py`: https + lower-host + strip `www.`/`m.` + drop fragment; it strips
  only **tracking parameters** (`utm_*`, `fbclid`, `gclid`, `mc_eid`, `igshid`, `ref`, …) and keeps
  significant query params, re-serializing them **sorted** — so `watch?v=AAA` and `watch?v=BBB`
  remain distinct keys). The RSS `<guid>`/`<id>`, when present, is used **only for in-run feed-item
  dedup** — it does NOT persist across runs (there is no `guid` column in `registry.md`). Near-dup /
  syndication — `scripts/dedup.py` (hybrid `max(char-3gram-jaccard, token-jaccard) ≥ 0.7`).
- **Seed tags:** RSS `<category>` → normalization through `config/tags.yaml`.
- **Source credibility:** the `tier` field (high/medium/low) in `config/sources.yaml`, carried into the digest items.
- **Anti-injection:** a source whose content goes into the synthesis context (Phase 3 of `research-build`)
  is archived by `source-archive` with `MODE=instruction-stripping`, and the synthesis is compiled from
  the **sanitized copy** (`{{ARCHIVE_ROOT}}/sanitized/{file}.md`), not from the raw original (the original
  is kept untouched as provenance). 9 rule classes S1–S9 — content-vs-instruction separation:
  a command like "ignore previous instructions…" inside an article is stripped before it reaches the prompt.
  Inventory fetches that do not go into synthesis may stay on the default `auto-archive`.
  - **The auto path (internal-corpus) is enforced in code.** RSS-collected articles in
    `pipeline/1-incoming/` are untrusted external text. Before auto-synthesis
    (`weekly-synthesis`), `scripts/sanitize_incoming.py sanitize` writes a sanitized companion
    `pipeline/1-incoming/{topic}/sanitized/{file}.md` for each article (a deterministic
    strip of classes S1–S9: critical — cut out, medium/info — flagged into the audit). Stripped
    are not only the body but also the **frontmatter values** (single-line scalars, block-sequence
    items, flow collections like `tags: [a, b]`, and multi-line block scalars —
    `title`/`source`/`author`/`summary`): an injection in an untrusted title no longer passes as
    `clean` (findings raise `stripping_severity`). A flow collection is sanitized **item-by-item**,
    so it keeps its list type — only the offending item becomes a quoted placeholder scalar
    (`tags: [ai, "[STRIPPED:S1]"]`), never the whole value collapsed into one re-quoted string. Before
    synthesis, `sanitize_incoming.py gate --topic {topic}` is checked **per topic**
    separately (fails with `exit 1` if a topic's article has no fresh companion — drift is caught
    by `source_hash`, and companion tampering by `sanitized_hash` over the **whole** file, not just
    the body). A topic that fails the gate is **skipped and recorded in the log**, the other topics
    are synthesized — one bad article does not block the whole run. Synthesis reads only the
    sanitized companions, not the originals. This is defense-in-depth (a pattern strip is not a guarantee),
    but synthesis can no longer silently swallow an unsanitized article. The zero-width/bidi
    normalization (S9) runs **before** the instruction-pattern rules, so an invisible char hidden
    inside a trigger phrase can't defeat the match and then be cleaned away into a readable injection.
- Good feeds: YouTube `feeds/videos.xml?channel_id=`, arXiv `export.arxiv.org/rss/{cat}`,
  Google News `news.google.com/rss/search?q=`, Substack `/feed`, Medium `/feed/tag/`, HN `hnrss.org`, Reddit `/.rss`.

## 13. Brain hygiene — a single pass

`scripts/validate_brain.py` (WITHOUT a KG engine), run in `weekly-run`, is **advisory** (it only
reports/recommends, does NOT edit the vocabulary or the notes, exit 0), 1 health line into the digest:
- orphan concept (no `related_concept` AND no shared tags) → warn;
- broken `[[link]]` → warn; a concept without `sources:` → warn;
- uncited key fact under `## Key facts` (no inline `Source:`, wikilink, or URL) → warn;
- orphan lesson/playbook (no concept, parent playbook, source concept, or body wikilink) → warn;
- tag normalization/merge/cap + a *recommendation* to promote a `pending` tag at ≥3 concepts (see §11) —
  the promotion itself is done by `scripts/promote_tags.py` (the same brain-hygiene step), which edits
  `config/tags.yaml`; `source-manage` add-topic seeds the new topic's tag ahead of time;
- stale: `last_verified + ttl_days` in the past → "needs re-verification".

Beyond this default **advisory** pass, `weekly-synthesis` additionally runs a scoped write-time gate —
`validate_brain.py --strict --paths <just-written files>` — which exits non-zero / quarantines only the
files that run just produced (so a malformed fresh write never lands in `brain/`); `weekly-synthesis` is
the owner of that strict invocation. The default standalone pass remains advisory.

## 14. Obsidian reading layer (front door)

- **`concepts.base` / `lessons.base` / `playbooks.base`** (Obsidian Bases) — live dynamic
  front doors for concepts, atomic lessons, and reusable methods. They update as notes appear
  (zero gardening). Requires Obsidian ≥1.7.
- **`brain/INDEX.md` (MOC)** — a simple markdown fallback if Bases is unavailable.
- The front door = Bases + the curated MOC fallback; tags are a secondary filter; the graph is a
  demo of structure, not the primary navigation.

## 15. Search providers (config-gated, OPT-IN)

> **Status: wired to corroboration.** `scripts/corroborate.corroborate_with_search()`
> calls `scripts/search/search.web_search()` — this is the first live consumer of the subsystem
> (CLI: `python3 scripts/corroborate.py enrich "<claim>" --source URL …`; used by
> `research-audit` for single-source claims). Synthesis still prefers the
> built-in Claude WebSearch within the agent loop. With the default `claude-websearch`, a headless call
> returns a sentinel → soft-skip (the base verdict is unchanged); real enrichment turns on with the
> `tavily` or `perplexity` provider (Search API, raw results) with a key in `config/.env`
> (`TAVILY_API_KEY` / `PERPLEXITY_API_KEY`). For corroboration we take raw results, NOT Sonar-chat.

Web search is **optional and config-gated**, on the same model as delivery (§3/§8/§10).
The default experience in Cowork / Claude Code **requires nothing**: the agent uses the built-in
**Claude WebSearch** tool right in its loop. An external provider turns on only
for the headless path (cron, no agent) and the future fact-check corroboration.

- **Config `config/search.yaml`** (`search.provider`):
  - `claude-websearch` — the **default**, in-agent. A headless process cannot call
    the Claude WebSearch tool, so the dispatcher returns a sentinel note
    ("use the in-agent WebSearch tool") rather than results.
  - `tavily` — turns on Tavily for headless / corroboration. Requires a key in `config/.env`
    (`TAVILY_API_KEY`, name via `search.tavily.api_key_env`). LLM-oriented search.
  - `perplexity` — turns on Perplexity's raw `/search` endpoint for headless / corroboration.
    Requires a key in `config/.env` (`PERPLEXITY_API_KEY`, name via `search.perplexity.api_key_env`).
    This is the §15 raw-search slot (`{title,url,snippet}` for counting domains), **separate** from
    the §15a Sonar-chat — the same key but a different endpoint (`/search`, not `/chat/completions`).
  - `none` — web search fully off (soft-skip everywhere).
- **Headless dispatcher** — `scripts/search/search.py` (`web_search(query) -> list[{title,url,snippet}]`),
  the Tavily adapter — `scripts/search/tavily.py` (stdlib `urllib` only, no SDK). CLI:
  `python3 scripts/search/search.py "<query>"`.
- **Soft-skip-on-missing:** a missing key or `provider: none` → an empty list + a clear
  message, **never an exception** (mirrors `scripts/delivery/deliver.py`).
- **Secrets — only in `.env`** via the `*_env` reference (§8); `config/search.yaml` stores only
  the variable NAME, not the value.
- **Brave** — an independent alternative (its own search index, not dependent on Bing/Google);
  it can be added as another `provider` with the same config-gated pattern, should a
  second source with independently established support be needed.

### 15a. Sonar cross-check (agent-research, Phase 6.5 — config-gated, OPT-IN)

> **This is a DIFFERENT slot than §15/§16.** §15 web_search and §16 corroboration take **raw results**
> (`{title,url,snippet}`) to find additional publisher domains. Cross-check, by contrast, asks
> **Sonar-chat** the same research question and gets a **synthesized answer + citations**.

- **Purpose:** an independent second opinion as an **adversarial input into research-build Phase 6.5
  (Critique)** — "Sonar independently claims X, Y, Z: did we cover that? did it cite a source
  we missed? does it contradict us?". Sonar's answer does **NOT** go into synthesis — only into the critique
  of the synthesis. So the collection pipeline (instruction-stripping §12, verbatim-raw Phase 2b,
  dedup, claim→citation traceability) **does not change** whether or not cross-check ran;
  the trust model is not inverted.
- **Gating — "have a key → run, otherwise as before":** `config/research.yaml`
  (`research.cross_check.provider`, default `sonar`) → the mere presence of `PERPLEXITY_API_KEY`
  in `config/.env` activates cross-check; no key or `provider: none` → soft-skip to an empty
  `{answer:"", citations:[]}` + a message, **never an exception**.
- **Dispatcher** — `scripts/search/cross_check.py`
  (`cross_check(question) -> {answer, citations}`); the Sonar adapter — `scripts/search/sonar.py`
  (`/chat/completions`, stdlib `urllib` only, no SDK; default model `sonar` — cheap;
  cross-check takes only answer+citations and discards reasoning, so reasoning models
  (~8× more expensive on output, requiring `max_tokens`≥3000) are not needed).
  CLI: `python3 scripts/search/cross_check.py "<question>"`.
- **Same key, different endpoint:** `PERPLEXITY_API_KEY` is shared with §16 (raw `/search`); cross-check
  hits `/chat/completions`. Secrets — only in `.env` via `api_key_env` (§8).

### 15b. Search-trail — durable provenance log of a session's search queries (OFF by default)

> **Purpose — auditable grounding (§12).** A manual research session (`research-frame` →
> `research-build`) does several web searches across different providers. The search-trail is
> a machine-readable JSONL log: *which query went to which provider, how many results came back,
> and from which registrable domains*. It is the provenance companion of the verification-log (§ research-audit):
> the verification-log records *which claims were verified*, the search-trail records *what was searched to
> find them*.

- **Artifact — a sibling of the brief, the same `{date}_{slug}` prefix** as the verification-log/critique-log:
  `planning/research/{date}_{slug}.search-trail.jsonl` (one JSON object per line). Line schema:
  `{"ts": ISO-8601 UTC, "query": str, "provider": str, "n_results": int, "domains": [eTLD+1, …]}`.
  `domains` are extracted by `corroborate.registrable_domain` (DRY — §16), deduplicated, empties
  dropped.
- **Helper** — `scripts/search/search_trail.py`: `append_search_entry(trail_path, *, query, provider,
  n_results, urls)` (append-safe, line-atomic via `O_APPEND` — concurrent writes do not tear a line),
  `read_trail(path) -> list[SearchEntry]` (frozen dataclass), `summarize_trail(entries)`,
  `trail_path_for_brief(brief)` (the sibling path), `slug_for_query` / `resolve_trail_target`.
  CLI: `python3 scripts/search/search_trail.py <trail.jsonl>` (prints a summary).
- **Two paths feed the trail, both via `append_search_entry`:**
  - **(a) API providers — auto-injected** in `search.py` (tavily/perplexity) and `cross_check.py` (sonar):
    after a successful provider call the entry is written automatically.
  - **(b) the agent's own `claude-websearch`** — the default provider returns a sentinel, its
    results do NOT pass through the scripts, so the scripts don't see them. `research-frame` / `research-build`
    append the entry with the helper themselves after each of their WebSearches — this is what makes the trail complete.
- **Gating — OFF by default:** nothing is written until a target is set — the env variable
  `RESEARCH_TRAIL_DIR` (the trail directory) or an explicit path from the caller. So unit tests and the
  headless cron path create no trail files. `resolve_trail_target(slug)` returns `None` for an
  empty/unset variable.
- **Soft-skip (§8/§10):** a trail write error **never fails** — it is swallowed with a printed note,
  because a logging failure must not interrupt the search that produced it. `read_trail` skips
  a broken line rather than crashing (observability is never load-bearing).
- **Limitation:** the trail for `claude-websearch` depends on the agent following the skill instructions
  (path (b)) — there is no auto-injection here by design (there are no sentinel results to record).

## 16. Publisher diversity and claim corroboration

Goal: show source coverage without turning publication counts into factual confirmation.

- **Publisher-count proxy:** distinct approximate registrable domains (eTLD+1), with
  per-subdomain identities on selected hosting platforms. The helper has a small suffix
  list, not the full public-suffix registry. Optional lexical near-duplicate collapse groups
  similar texts first. Dissimilar texts can still repeat a shared upstream assertion.
- **Coverage level:** `multi` (at least 2 retained publisher groups), `single` (1), `none` (0).
  `scripts/corroborate.py` derives this from the concept's `sources:`. Historical API names
  `independent_sources()` and the `independent` result key are retained for compatibility;
  their numeric values do not establish independence. `collapsed` only records that a text
  map was supplied; missing bodies are possible and it is not a claim-verification verdict.
- **Digest:** `trust_line()` renders publisher diversity, whether or not a text map is used:
  - `🔵 N retained publisher domains — check the claim` — at least 2 retained groups;
  - `🟡 One retained publisher domain — check the claim` — exactly 1;
  - empty — no usable URLs.
  Derive the count; do not keep a separate concept counter. The headless builder supplies
  URLs without bodies. An agent-authored digest uses the same bounded marker and may add a
  separately cited factual review, but must not infer confirmation from the count.
- **research-audit:** inspect the exact supporting passages and shared upstream provenance.
  For factual/news 🟢 eligibility, at least two independently supporting sources must be
  established by that review, with applicable recency and contradiction checks. Distinct
  domains and low lexical similarity alone do not meet the gate. When independence is
  unknown or all reports trace to one source, retain a 🟡 qualification rather than claiming
  confirmation. Zero supporting evidence or a material contradiction follows the usual 🔴
  rule. Numeric/vendor checks are unchanged. Soft mode annotates; it never blocks on this
  coverage signal.
- **Search enrichment (§15):** `corroborate_with_search(query, sources)` returns additional
  publisher-domain candidates and recomputes coverage. It does not verify their content,
  provenance or support for a claim. Inspect discovered passages before adding their URLs
  to a concept; search-disabled/unavailable results soft-skip to the base count.

## 17. Digest format (`scripts/build_digest.py`)

The deterministic headless builder assembles a single Markdown digest that renders into two views:
plain-text for Telegram and premium HTML for email. Structure (section order):

- **Volume summary header** — one line with pluralization: "N new sources across M topics, K updated concept(s)".
- **TL;DR** (when there is activity) — up to three highlight lines: 📰 the most active topic + its share;
  🔎 one standout source (highest tier / first in order); 💡 **all** updated concepts as
  sub-bullets (not "…and N more" — TL;DR shows the full list).
- **Knowledge base health** — one line from the latest `brain-health_*.md`: `🟢` only when
  **every** issue counter (orphan/broken/missing/uncited-facts/stale) parses exactly as `0`
  (exact numeric parse, not a substring — otherwise "10 orphans" would falsely read as clean),
  otherwise `⚠️`.
- **New sources** (always, even when empty) — grouped by topic with a `🏷 {topic} (N)` badge, where `N` is the number
  of **unique** sources (articles re-written with the same URL across several incoming files are
  deduplicated in `scan_incoming` — all counters, including the header and the TL;DR shares, count unique).
  The digest is a **curated slice, not an archive**: per topic only the top `DIGEST_LINKS_PER_TOPIC`
  (=3) sources **by credibility** (high→medium→low→unknown) are shown, as a card (bold clickable title +
  `⭐` for high-tier + the takeaway in a blockquote), and the remainder is folded into a line
  `_+N more — top 3 shown by source credibility_`. The full raw set stays in `pipeline/1-incoming/`.
  Under the topic badge, in italics, a **one-line prose lead** renders (if present), which the agent
  `weekly-synthesis` writes into the sidecar `pipeline/3-synthesis/{topic}/digest-lead.md`; the deterministic
  builder only **reads** it (the first non-empty line, capped at `LEAD_MAX_CHARS`=240) and stays LLM-free —
  no sidecar → no lead (graceful).
- **Updated concepts** (always, even when empty) — a card: bold name + `⭐` for high-tier + a badge line
  (the §16 trust line + a link to the source) + the definition in a blockquote.
- **Synthesis this week** (when a log exists) — `## 🧪`, the first paragraph of the latest `synthesis-run_*.md`.
- **Needs attention** (when present) — stale incoming (>14 days, empty `status` in the registry).

The scan window is exactly `digest.lookback_days` calendar dates ending today
(`[today − (N−1), today]`), so a boundary day does not land in two adjacent digests.

Render specifics:
- **Telegram** (`scripts/delivery/telegram_botapi.py`): markdown → Telegram-HTML; headings → bold,
  lists → `•`/`◦`, separators `──────────`. TL;DR — a **plain** blockquote (always visible),
  long concept definitions — an **expandable** blockquote. Splitting at 4096 chars: it prefers
  a boundary before `##`/a divider, then a blank line, then `\n`, then a hard cut; the `_is_header_only`
  guard prevents tearing a section heading off its body; on a break inside a `<blockquote>` the tag is closed at the end
  of the chunk and reopened at the start of the next (tag balance — otherwise Telegram 400). Reserve 12 chars
  for the `(i/N)` marker. Chunks are sent one at a time with per-chunk retry (resume, not restart — no duplicates).
  Links: only the `http`/`https`/`mailto` schemes are allowed; others (`javascript:`/`data:`) render
  as plain text without an href (protection against injection from untrusted article content).
- **Email** (`scripts/delivery/email_html.py`): inline styles (Gmail/Outlook-safe), a centered
  640px card, an accent header, a TL;DR callout, topic pill badges, a blockquote with a left border
  (in email everything is expanded — no collapse), a dark-mode hint + a mobile breakpoint.
- **Quiet week** — zero new sources AND zero concepts AND zero stale backlog: a one-line digest;
  `build_digest.py` prints the marker `QUIET_WEEK` to stdout so cron can skip delivery
  (`deliver.py --skip-quiet`).
- **Vault front doors** — the weekly Markdown digest includes a compact `Vault front doors`
  section for `brain/lessons.base` and `brain/playbooks.base` so non-concept note types are
  visible even when the run mostly updated concepts. The light daily digest omits it.
- **Audit sidecar** — every deterministic build writes `digest_YYYY-MM-DD.audit.json` (or
  `digest_daily_YYYY-MM-DD.audit.json`) next to the Markdown. Schema version `digest_audit.v1`
  includes `built_on`, `lookback_days`, `digest_path`, `digest_sha256`, `daily`, `quiet`, `totals`,
  and per-topic `decisions` with `included`, `rank`, and `reason` (`selected_by_source_credibility`
  or `hidden_topic_cap`). `totals` also carries derived vault counts for `lessons` and
  `playbooks`. It is an additive provenance artifact derived from the Markdown inputs; old digests
  without a sidecar remain valid.
- **Browser report** — `build_digest.py --report` writes `digest_YYYY-MM-DD.report.html`, a local
  static operator view of the same digest plus stats, an Audit tab with the full per-topic
  source drilldown and shown/hidden reasons, a Vault tab for lessons/playbooks,
  glossary/concept snapshots, and a link to the audit sidecar. It is not a SPA, not a service,
  and not a new source of truth.

## 18. Health / observability (`scripts/health.py`)

A lightweight operational layer over the pipeline (does NOT replace brain hygiene §13 — that is about knowledge
quality, this is about "is the pipe working").

- **Event log:** `pipeline/.health/events.jsonl` — append-only JSONL, **gitignored**. One line per
  event: `{ts, kind, status, ...details}`.
- **Who writes events:** headless `deliver.py` (per-channel after sending, best-effort — never
  blocks delivery) and the skills `collect-base` / `digest-deliver` / `weekly-run` — via the CLI
  `python3 scripts/health.py record --kind <collect|deliver|hygiene|run|research> --status <...>`.
- **Who reads:** the `brain-ask` skill (the *health* intent) via `health.py report` — produces a plain-language report.
- **Verdict signals:**
  - *feed liveness (by events)* — a feed is "dead" if the last N runs (default 2) are empty/errored
    (`collect` events — written only by the agent path);
  - *feed liveness (by registry)* — `stale_feeds()` reads `pipeline/registry.md` (columns
    `collected | category | status | url | title`) and takes the **most recent `collected` date per category**;
    a monitored category counts as a "dead feed" if its last collection is older than the `STALE_FEED_DAYS` window
    (= `STALE_DIGEST_DAYS` = 8 days). This works on the **pure headless cron path**: the registry is updated
    at collection regardless of agent/headless (unlike `collect` events), so a dead feed is visible
    even without an agent. No false alarms: a flag is raised only if a category is both monitored and **has already
    been collected** (there is a row with a recognizable date) and then went stale — a never-collected category, an empty or
    old-format registry (without dates) is treated as "unknown, not dead" → a fresh/unconfigured vault
    stays `UNCONFIGURED`/`UNKNOWN`, not `DEGRADED`.
  - *delivery* — the last status per channel (`failed`/`error` → failure);
  - *digest freshness* — the age of the latest `digest_*.md`; *stale* at >8 days (a week + slack);
  - *brain health note* — one line from the latest `brain-health_*.md`.
- **Bottom line:** `ok = True` only when there are no dead feeds, no failed delivery, and the digest is not stale.


## Project problem-solution profile (concept schema 1)

The optional `knowledge_kind: problem_solution` concept profile is defined in
[problem-solutions.md](problem-solutions.md) and validated by
`scripts/problem_solutions/profile.py`. It adds language/problem facets, applicability,
verification and explicit evidence scope without changing generic concept metadata.
A structurally valid profile may cite retained project synthesis evidence rather than an
external URL; every key fact must still cite a declared source, and the evidence must exist.
The hygiene pass and write-time gate share this check. Save these records only through
interactive exact-package approval with `scripts/problem_solution.py`; unattended synthesis
holds these changes for review. MCP filters are exact metadata matches, not an evidence
certificate, privacy boundary or factual audit.
