# AGENTS.md — agent baseline for research-brain

> Universal, tool-agnostic instructions for any coding/agent runtime (Claude Code,
> Copilot CLI, Codex CLI — all read this file natively). Claude-Code/Cowork-specific
> extensions live in [`CLAUDE.md`](CLAUDE.md), which builds on top of this baseline.

## What this project is

**research-brain** is a distributable, topic-agnostic knowledge & research pipeline that
runs inside an agent runtime and stores everything as an **Obsidian vault** (`brain/`).
There is no always-on server and no database — the knowledge store is plain Markdown plus
a small Python delivery module. An optional local MCP stdio adapter exposes read-only
retrieval from `brain/concepts/` to MCP-compatible agents; its SDK is isolated from the
core runtime. The agent itself executes the skills and scheduled tasks.

**The core loop:** **collect** sources on configured topics (`collect-topic`, RSS-first) →
**sanitize** untrusted incoming content (`sanitize_incoming.py`) →
**curate** the sanitized material into the curated stage (`pipeline-curate`,
`1-incoming/` → `2-curated/`) →
**synthesize** curated material into durable knowledge in `brain/` automatically
(`weekly-synthesis`: `research-build` → `research-audit` (SOFT_MODE) → `wiki-ingest`, no manual gate) →
**extract** lessons/playbooks from the new concepts (`extract_vault_notes.py`, additive) → run a **brain-hygiene**
pass (`validate_brain.py`) → build a **weekly digest** of what's new → **deliver** it to the
user's channels (email / Telegram / Rocket.Chat). `weekly-run.md` is the recommended single
orchestrator that chains these steps in order, each gated on the previous finishing. The
Obsidian graph view, backlinks, and the `concepts.base` Bases front door are how the user
browses the accumulated knowledge.

See [`docs/architecture.md`](docs/architecture.md) for the component/data-flow view and
[`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) for the authoritative path/schema contract.

## Mandatory rules (always-on)

- **Ambiguity → clarify, never invent.** If a research or factual request is ambiguous in
  intent / scope / entity, ask ONE targeted clarifying question before answering or
  researching. Never infer or invent the intended topic/entity/scope. One question only —
  do not interrogate the user.
- **Relative paths only.** The project opens from its root; every path in a skill, task,
  or instruction is relative to that root (e.g. `pipeline/1-incoming/`, `config/sources.yaml`,
  `brain/concepts/`). Never write absolute machine paths. (CONVENTIONS §1)
- **Language.** The content and instruction baseline is **English**. The digest language
  is a runtime parameter — `delivery.language` in `config/channels.yaml` — not hardcoded.
  No project- or person-specific branding in the core. (CONVENTIONS §6)
- **Secrets only in `config/.env`.** Secrets are referenced from YAML by env-var name
  (e.g. `password_env: SMTP_PASSWORD`), never written inline in YAML, and never committed.
  `config/.env.example` documents the keys; the real `config/.env` is gitignored.
  (CONVENTIONS §2.1, §8)
- **Pipeline articles are frontmatter-strict.** Every file in `pipeline/1-incoming/`
  begins with `---` and carries `source, url, title, author, date_published, collected,
  category, tags`. `scripts/validate-pipeline-frontmatter.py` is the **advisory** gate —
  it reports files with missing/empty/malformed frontmatter (exit 2 under `--strict`); the
  collect step is expected to drop or fix flagged files. The validator itself does **not**
  delete anything. (CONVENTIONS §5)
- **Knowledge lives in `brain/` as an Obsidian vault.** Concepts link via `related_concept:`
  frontmatter + shared tags (the graph is built from these, not only inline `[[wikilinks]]`)
  and **must carry `sources:`** — every key fact cites where it came from (anti-hallucination).
  The Obsidian graph + backlinks + `concepts.base` (Bases front door) + the `brain/INDEX.md` MOC
  fallback *are* the index — do **not** generate auxiliary indices, knowledge-graph files, or
  AUTO_INDEX artifacts. Knowledge mutation flows through `wiki-ingest` (write) and `wiki-query`
  (read). (CONVENTIONS §5.1, §14)
- **Tags are a controlled vocabulary.** Concept tags are nested `domain/topic`, chosen
  **closed-book** from `config/tags.yaml` only (2–5 per note, ≥1 domain-level tag). If nothing
  fits, propose ≤1 new tag into the `pending:` quarantine — never write a new tag straight into
  the live vocabulary. `validate_brain.py` (advisory) normalizes, merges synonyms, and
  *recommends* promoting a pending tag once it recurs across ≥3 notes; `scripts/promote_tags.py`
  *applies* that promotion in the weekly brain-hygiene step (and `source-manage` seeds a new
  topic's tag on add-topic). (CONVENTIONS §11)
- **Collection is multi-stage and RSS-first.** Per topic, gather candidates from three
  parallel **source roles** — **RSS** feeds, the tool's **Official** news/docs pages, and
  **Search** platforms (Medium/dev.to/Habr tags) — into a wide pool
  (`collect.candidate_pool_per_topic`, default 25), rank them by relevance × recency × tier,
  then read the best (`collect.max_articles_per_topic`, default 10) in full. Within each role
  climb the cheap→expensive ladder (RSS body → WebFetch top-up → static fetch → browser only
  per a per-source allow-list); the browser is not the default. The persistent cross-run dedup
  key is the canonical URL (`scripts/normalize_url.py`); the RSS `<guid>`/`<id>` is used only for
  in-run feed-item dedup (there is no guid column in `registry.md`). Near-dup syndication is
  collapsed by `scripts/dedup.py`. Seed tags come from RSS `<category>`, normalized through
  `config/tags.yaml`. (CONVENTIONS §12)
- **Dedup before save.** Collection checks the key against `pipeline/registry.md` before
  saving and appends a row the moment an article lands in `1-incoming/`.
- **Brain hygiene is one advisory pass.** `scripts/validate_brain.py` (run by `weekly-run`)
  flags orphans, broken `[[concepts/...]]` links, concepts missing `sources:`, uncited
  `## Key facts` bullets, tag issues, and stale notes, and emits one health line into the
  digest. It never edits or deletes the vault. (CONVENTIONS §13)
- **Schedule config is the source of truth.** `config/schedule.yaml` holds the cadence
  (collect / curate / synthesis / digest + `timezone`); any cron string is just a trigger and
  must be kept in sync with it by hand. Prefer the gated single `weekly-run.md` orchestrator
  over four independent timers.
- **The runtime stays stdlib-only.** Shipped `scripts/` code imports only the Python stdlib
  plus `pyyaml`; never add a third-party runtime dependency or import the dev toolchain
  (`uv` / `ruff` / `mypy` / `bandit` / `pytest`) from a `scripts/` module — it breaks the
  headless/cron install. (Contributors changing the code: the test-driven workflow, the
  `make` gate, and the coverage floor live in `DEVELOPING.md` — present only in the dev
  checkout; it is excluded from the shipped archive, so don't look for it there.)

## Skills

Skills are the engine. Each lives at `skills/{name}/SKILL.md` as a Markdown instruction
set the agent reads, then executes. When a request matches a trigger below, read that
skill's `SKILL.md` first and follow it.

> **Agents without a Skill tool (Codex CLI, Copilot, plain editors).** There is no
> auto-firing mechanism: when a request matches a trigger phrase below, **`Read
> skills/{name}/SKILL.md` and follow it manually** — that is the whole mechanic. Features
> that need MCP (Gmail/Telegram MCP delivery, inbound Telegram) won't be available; use the
> headless path instead — set `config/channels.yaml` to `provider: smtp` / `transport:
> bot-api` and drive `scripts/build_digest.py` + `scripts/delivery/deliver.py` directly.
> (Claude Code / Cowork auto-invoke skills via the Skill tool and have the MCP path — see
> [`CLAUDE.md`](CLAUDE.md), which those runtimes also read.)

SKILL.md files come in two tiers by design: a heavy template for the research-cluster
skills (plus `source-archive` and `wiki-ingest`) — Phases, `rules/`, `references/`, and
explicit Stop conditions — and a lighter operational shape for the rest (`brain-ask`,
`brain-review`, `capabilities`, `concept-manage`, `digest-build`/`-deliver`, `digest-review`,
`digest-feedback`, `author-manage`, `discover-sources`, `intake`, `pipeline-curate`, `run-now`,
`setup-wizard`, `source-manage`, `source-capture`, `trends`, `whats-new`) — When to Use /
Skip / Steps / Output. This split is intentional, so
don't expect every skill to follow the same structure.

| Skill | When to use | Trigger phrases |
|---|---|---|
| **setup-wizard** | First-run onboarding or reconfigure: heavy interview that stands up the whole `config/` (topics, sources, tags, channels, schedule) — incl. the conversational cadence toggles for the optional `daily_digest` / `weekly_trends` blocks. | "set up sources", "configure", "let's set up", "first-time setup", "онбординг", "starter pack", "add a daily digest", "remove the daily digest", "добавь ежедневный дайджест", "включи отчёт по трендам" |
| **intake** | The PRIMARY "add this" verb: the user just sends a link and this skill classifies it — feed → monitor (source-manage), one-off article → inbox (source-capture), ambiguous → exactly one question. Also previews/applies OPML subscription imports. The explicit expert shortcuts (`/add <url>`, `/save <url>`) skip it and stay direct. | "add this", "add this link", "here is a URL", bare `https://...`, "добавь это", "добавь эту ссылку", "вот ссылка", "забери эту ссылку", "что делать с этой ссылкой", "import OPML", "import subscriptions", "migrate feeds" |
| **source-manage** | Quick single-intent edits to monitored **topics & sources only** (add/pause/resume/remove a topic or source). Mutates the topics+sources config (`config/topics.yaml` + `config/sources.yaml`) in sync via `scripts/manage_sources.py`; defers to setup-wizard for bulk/tags/channels/schedule. A bare/unclassified link belongs to **intake** — `/add <url>` is the expert shortcut that skips it. | "/add <url>" (expert shortcut), "start monitoring X", "watch this blog", "add this feed", "stop monitoring X", "pause this source", "начни мониторить", "следи за блогом", "перестань мониторить" |
| **discover-sources** | Proposes NEW sources for a topic: searches, groups results by site, drops what is already monitored, and returns at most ten with the reason each surfaced. Strictly read-only — it never adds anything; accepted candidates are handed to **source-manage**, which is also where the trust tier is set. Roles (`academic`/`aggregator`/…) are a coarse guess from the domain, not a claim about the publisher. | "/discover <topic>", "find new sources for X", "who should I read about X", "find alternatives to my sources", "найди новые источники по X", "кого стоит читать по теме X" |
| **author-manage** | User-facing CRUD over the author-monitoring roster (`config/authors.yaml`), one intent per turn: ADD an author the user decided to follow, LIST the roster, list author NODES in `brain/authors/` with `followed: yes/no` (read-only), PAUSE / RESUME one, or REMOVE one. Backed by `scripts/manage_authors.py` — the ONLY write path in. Distinct from `source-manage` (a feed/site, not a person); Source Insights **suggests** authors but can never add one (`source_report/` cannot import the write path, pinned by test). | "follow this author", "monitor this author", "start following X", "/author add", "list authors", "who am I following", "/author list", "/author nodes", "pause author X", "stop following X", "unfollow X", "remove author X", "подписаться на автора", "следить за автором", "список авторов", "кого я читаю", "отписаться от автора" |
| **source-capture** | Capture a **single** article the user sends (read-it-later URL) into the inbox queue, then **batch-process** the queue into concepts (fan-out readers → route to topic → curate→synthesis→ingest). Hybrid: instant capture, batched processing (threshold / `/process` / weekly-run). Distinct from source-manage (recurring **feed**) and research-frame (answer a question). A bare/unclassified link belongs to **intake** — `/save <url>` is the expert shortcut that skips it. Backed by `scripts/inbox.py`. | "save this article", "read this and save it", "/save <url>" (expert shortcut), "process the inbox", "/process", "сохрани эту статью", "прочитай и сохрани", "разбери инбокс", "обработай накопленное" |
| **brain-ask** | READ-ONLY status, findings & HEALTH about OUR own state: what we monitor + cadence, recent digests, key findings this week, and whether everything is healthy (feeds alive, delivery succeeded, digest fresh — via `scripts/health.py`). Reads `config/` + `pipeline/3-synthesis/digest_*.md` + `pipeline/.health/`. NOT external knowledge (that is `wiki-query`/`research-frame`). | "what are we monitoring", "list our sources", "how often do we collect", "show last digest", "top 5 digests", "key findings this week", "is everything ok", "system health", "is anything broken", "что мониторим", "ключевые находки за неделю", "всё ли в порядке", "состояние системы" |
| **research-frame** | GATEWAY — run FIRST on any research-intent request; routes onward (forwards to `wiki-query`). | "research X", "investigate", "deep dive", "topic overview", "what do we know about X" |
| **wiki-query** | After `research-frame`, or directly for an explicit vault-only question: look up the existing vault via `brain/INDEX.md` before fetching anything new. Vault-only misses offer research but do not start it silently. | (forwarded) "research X"; direct "/know <topic>", "what does my brain know about X", "что моя база знает о X", "search the vault", "concepts on topic=X" |
| **research-grep** | After `wiki-query` on a vault miss: grep the local corpus for material, then ask the user. | "look into", "gather material", "what do we have on", "is there anything local about X", "inventory the topic" |
| **research-build** | Compile multi-source material into a structured Markdown research document. Never the first responder. | (post-frame) "synthesize from the brief", "build a research document from these materials" |
| **research-audit** | Verify factual claims in a draft against source tier & recency; emits 🟢/🟡/🔴 log. | "check facts", "verify claims", "run research-audit", "is this ready to ship?", "check the sources in this draft", "check the citations" |
| **brain-review** | Adversarial multi-agent CONTENT-TRUST audit of the standing vault — re-verify `brain/concepts/` against their `sources:` for hallucination, single-source illusion, staleness, contradiction, overconfidence, tag drift. Agent-runtime only (degrades to `validate_brain.py` headless); proposes/routes changes via `wiki-ingest`, never silent edits. Distinct from `validate_brain` (mechanical), `brain-ask` (operational), `research-audit` (fresh draft). | "review the brain", "audit the knowledge base", "is the vault accurate", "re-verify concepts", "trust audit", "проверь базу знаний", "аудит достоверности", "перепроверь концепты", "нет ли выдумок в базе" |
| **pipeline-curate** | Promote collected articles from `pipeline/1-incoming/` into `pipeline/2-curated/` — the link between collection and synthesis. Applies topic include/exclude rules + a min-length floor; idempotent. | "curate", "curate pipeline", "promote incoming", "отбери в curated", "курируй" |
| **source-archive** | Persist any web fetch into `pipeline/0-archive/` with frontmatter + sha256 + double-link. Auto-hooks on fetches. | "archive this URL", "save this fetched page to the archive", "persist to the archive" |
| **wiki-ingest** | After `research-build` (or manual new knowledge): propose vault updates under `brain/concepts/`. POST-task only. | "update the vault", "sync brain", "ingest into concepts", "add this fact to a concept" |
| **concept-manage** | User-facing CRUD over the concept vault, one intent per turn: CREATE a **monitored** concept via a short interview (name → sources → keywords/tags → research → note), LIST concepts, UPDATE (re-research) one, or ARCHIVE / RESTORE one (soft-delete, never hard delete). Mechanical ops via `scripts/concept_manage.py`; CREATE/UPDATE orchestrate `source-manage` + the research chain + `wiki-ingest`. Distinct from `source-manage` (feeds, no note) and `brain-ask` (read-only state). | "new concept", "create a concept", "track this as a concept", "/concept new", "list concepts", "show my concepts", "/concept list", "update concept X", "refresh concept X", "/concept update", "archive concept X", "delete concept X", "restore concept X", "/concept archive", "/concept restore", "новый концепт", "создай концепт", "список концептов", "обнови концепт", "заархивируй концепт", "удали концепт", "восстанови концепт" |
| **whats-new** | The ONE casual verb for "what's new?": quick bootstrap collect (RSS/Atom + static article-page top-up, capped) → sanitize → light inflow snapshot to a TEMP file → answer INLINE in the chat with the top items. Persists no digest, sends nothing; offers `digest-build`/`digest-deliver`/`run-now` only as follow-ups. | "what's new", "anything new?", "/new", "news?", "что нового", "что новенького", "есть что-то новое", "новости есть?" |
| **trends** | "How is it changing over time?" answered INLINE: render the deterministic trends signals (ADR 0017 — topic volume this week vs last, rising tags, activity, knowledge growth) from `pipeline/registry.md` + `brain/concepts/` to a TEMP file and reply with the top movers. Read-only: collects nothing, persists no report, sends nothing. (The weekly digest embeds the same section by default.) | "/trends", "trends", "what's trending", "how are my topics changing", "what's rising", "тренды", "что растёт", "динамика тем" |
| **digest-build** | On-demand build of the weekly digest (local, no side-effects): rich agent-authored path or the deterministic `scripts/build_digest.py` fallback. Writes `pipeline/3-synthesis/digest_*.md`; does NOT send — hands off to `digest-deliver`. | "build digest", "build the weekly digest", "make a digest", "give me a digest", "I want a digest", "make me a digest", "собери дайджест", "сформируй дайджест", "собери дайджест сейчас" |
| **digest-deliver** | Deliver a built weekly digest to the channels in `config/channels.yaml`, picking the transport per channel. | "deliver digest", "send digest", "send the weekly digest", "push the digest", "разошли дайджест", "отправь дайджест" |
| **digest-review** | Opt-in adversarial PRE-SEND gate over a built digest (after the deliver rehearsal, before the real send): claims grounded in cited sources, trust markers justified, no injection leaked into the delivered text, links resolve. Advisory by design; agent-runtime multi-agent, degrades to `scripts/presend_review.py` headless. Gated on `delivery.pre_send_review`. Distinct from `brain-review` (standing vault) / `research-audit` (fresh draft). | "review the digest before sending", "pre-send check", "is the digest safe to send", "vet the digest", "проверь дайджест перед отправкой", "безопасно ли отправлять дайджест" |
| **digest-feedback** | Turn a reader's reaction to a delivered digest into ONE reversible tuning change via existing surfaces (audience-level step, or `source-manage` pause with confirm-first) + ALWAYS record the event via `scripts/feedback.py`. At most one change per reaction; states the undo. | "too technical", "simpler please", "more technical", "less of X", "mute X", "not useful", "useful", 👍/👎 sent as messages (tap-reactions never reach the agent), «слишком технично», «попроще», «потехничнее», «поменьше X», «замьють X», «не полезно» |
| **run-now** | On-demand trigger for the WHOLE gated loop (collect→sanitize→curate→synthesis→hygiene→digest→deliver). Thin wrapper that invokes `schedule/weekly-run.md` immediately; stops on a failed step. Whole loop — vs `digest-build` (build only) / `digest-deliver` (send only). | "run now", "run the pipeline now", "do a full run", "collect and send me a digest now", "update now", "прогони цикл сейчас", "собери всё сейчас", "обнови базу и пришли дайджест" |
| **capabilities** | Friendly, plain-language menu of what the system can do, grouped by user goal, with example phrases. Orientation/routing only — does no work itself. (Named `capabilities`, not `help`, to avoid the built-in `/help` command.) | "what can you do", "help", "what can I say", "what commands", "что ты умеешь", "помощь", "какие команды" |

Typical research chain: `research-frame → wiki-query → research-grep → research-build →
research-audit → wiki-ingest`, with `source-archive` hooking on any fetch.

> **Source tier-grading is opt-in / advanced.** The T1/T2/T3 tier subsystem (and the
> `>30%-red` hard gate in `research-audit` FULL mode — which fires on the **manual `/research`
> chain only**) activates **only** if you create `sources/trusted-registry.md`. Ready-to-copy
> starter templates ship as `sources/trusted-registry.example.md` +
> `sources/always-volatile-domains.example.md` (`setup-wizard` offers to copy them); copy one,
> drop the `.example`, and edit. On a default install those live files are absent, so
> `research-audit` runs in **soft mode**: tier-grading is skipped (a missing registry is never
> treated as "everything T3"), the 30% gate is disabled, but the citation-guard and recency
> annotation still run. The **unattended weekly digest is soft by design** — it never blocks,
> registry or not.

## Config map (`config/`)

> **Sources/topics config:** read `config/topics.yaml` + `config/sources.yaml` — the
> only formats the runtime reads (CONVENTIONS §2.3). The legacy `config/topics.md` +
> `config/sources.md` tables were retired before public `0.1.0`: an install that still has only the
> `.md` files imports them once via `python3 scripts/schema.py migrate-config` (a
> sidecar import — the `.md` files are left untouched as the rollback). Wherever an
> older instruction says "read `config/topics.md`", read the YAML twin instead.

| File | Format | Purpose |
|---|---|---|
| `config/sources.yaml` | YAML | **The** source config (CONVENTIONS §2.3): collection sources by category (url, type, `tier`, priority, filter, active). |
| `config/topics.yaml` | YAML | **The** topics config: tracked topics + tags + include/exclude rules. |
| `config/sources.md` / `config/topics.md` | Markdown | **Retired before public 0.1.0** — the runtime no longer reads the legacy `.md` tables; an old install imports them once via `python3 scripts/schema.py migrate-config` (the `.md` files stay untouched as rollback). |
| `config/sources.example-starter.md` | Markdown | Ready-to-use starter source list the setup-wizard copies in (the "starter pack" fast lane), then lands in the active format via `scripts/schema.py migrate-config --force`. |
| `config/topics.example-starter.md` | Markdown | Matching starter topic set for the setup-wizard's starter pack. |
| `config/authors.yaml` | YAML | Optional: the followed-authors roster (CONVENTIONS §2.4) — people the user explicitly chose to follow, with a `monitoring:` variant each. Absent until the first `/author add`; `scripts/manage_authors.py` is the only write path. |
| `config/tags.yaml` | YAML | The FIXED controlled tag vocabulary: `domains:` (domain → topics), `synonyms:` (alias → canonical), `pending:` quarantine. Machine-owned. |
| `config/channels.yaml` | YAML | Delivery channels (email / Telegram / Rocket.Chat), digest language, transport selection. Secrets via `*_env` refs. |
| `config/schedule.yaml` | YAML | Cadence for collection and digest (cron + caps); optional `daily_digest` (ADR 0016) and `weekly_trends` (ADR 0017) blocks. |
| `config/glossary.yaml` | YAML | Optional term→explanation map; a `📖 Glossary` of the jargon a digest uses is appended (only matching terms). |
| `config/search.yaml` | YAML | Web-search provider (optional, config-gated — CONVENTIONS §15; staged). |
| `config/research.yaml` | YAML | Sonar cross-check for `research-build` Phase 6.5 (optional, key-gated — CONVENTIONS §15a). |
| `config/.env.example` | env | Template of required secret keys. The real `config/.env` is gitignored. |
| `config/agents.yaml` | YAML | Single source of truth for the pipeline **role agents** (model tier per runtime + tool allowlist + prompt). `scripts/gen_agents.py` renders it into `.claude/agents/*.md` + `config/codex-profiles.example.toml`. See ADR 0015. |
| `config/codex-profiles.example.toml` | TOML | **Generated** Codex per-role profiles (model + reasoning-effort tier) for the headless Codex scheduling path — merge into `~/.codex/config.toml`. Edit `config/agents.yaml`, not this file. See `docs/scheduling.md` "C. Codex". |
| `config/README.md` | Markdown | Notes on editing the config files. |

Fixed schemas for `channels.yaml`, `schedule.yaml` and `tags.yaml` are in
[`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) §2/§11 — edit the values, not the keys.

## Workspace map

| Path | Purpose |
|---|---|
| `config/` | All user configuration (sources, topics, `tags.yaml`, channels, schedule, `.env`). |
| `skills/` | The agent skills (`skills/{name}/SKILL.md`) — the engine. The trigger table above is the authoritative list. |
| `integrations/mcp_server/` | Optional local read-only stdio MCP adapter for querying source-backed concepts from other projects; isolated SDK environment and setup instructions in its README. |
| `schedule/` | Scheduled-task definitions: `collect-base.md`, `collect-topic.md`, `weekly-curate.md`, `weekly-synthesis.md`, `weekly-digest.md`, and the `weekly-run.md` orchestrator; `health-watchdog.md`, the opt-in daily health check decoupled from the run it reports on (`scripts/health_alert.py`); plus the two thin cron wrappers that run `weekly-run.md` agentically on a LOCAL install — `codex-run.sh` (via `codex exec`) and `claude-run.sh` (via `claude -p`, least-privilege `--tools`/`--permission-mode dontAsk`, for when a `/schedule` cloud routine can't reach the install) — sharing one sourced preamble, `_agentic-run.sh` (see `docs/scheduling.md` "C. Codex" / "D. Claude Code via OS cron"). |
| `pipeline/` | Article pipeline: `1-incoming/` → `2-curated/` → `3-synthesis/`, plus `0-archive/` and the dedup `registry.md`. Per-topic sidecars under `3-synthesis/{topic}/`: `.synthesis-meta.json` (freshness hash) + the agent-authored `digest-lead.md` (one-line digest lead). Delivery state under `3-synthesis/.delivered/` (receipts + `.delivery.lock`); the run lock is `pipeline/.run.lock`. |
| `planning/research/` | Manual research-chain artifacts: the `{date}_{slug}.md` briefs (written by `research-frame`) and the sibling `{date}_{slug}.verification-log.md` (written by `research-audit`). Created on demand by the research chain; absent on a default install. |
| `sources/` | Optional source tier-registry: `sources/trusted-registry.md` (host → T1/T2/T3) + `sources/always-volatile-domains.md` (recency override), used by `research-audit` / `research-build` / `source-archive` in FULL mode. Ships `*.example.md` starter templates (tracked); the live files are user-created (copy + edit, offered by `setup-wizard`). Absent on a default install — their absence puts `research-audit` in soft mode (tier-grading skipped). |
| `brain/` | The Obsidian knowledge vault: `concepts/`, `lessons/`, `playbooks/`, `authors/` (backlink-only author nodes, `type: author` — the author↔concept link lives on the concept's `contributors:` field; no `.base` view, surfaced via Obsidian backlinks), the `concepts.base` Bases front door, and the `INDEX.md` MOC fallback. |
| `scripts/` | Helpers: frontmatter validators + `frontmatter_lint.py` (SKILL.md frontmatter gate), `validate_config.py` (config schema facade; implementation split into `scripts/config_validation/` per ADR 0021) + `validate_brain.py` (brain hygiene; implementation in the `scripts/hygiene/` package) + `doctor.py` (one read-only plain-language "is everything OK?" check composing config/sources/delivery/health/lock/version and showing the agentic-vs-headless collection boundary), `configure.py` (interactive no-agent config installer — the scriptable alternative to the `setup-wizard` skill), `collect.py` (deterministic stdlib RSS collector facade for the headless path — RSS/Atom full bodies plus static article-page top-up, no agent; implementation split into `scripts/collection/` per ADR 0021), `normalize_url.py` + `dedup.py` (collection dedup) + `claim_dedup.py` (deterministic claim-level dedup over reader extracts — ADR 0018), `registry.py` (single source of truth for the `pipeline/registry.md` table schema), `purge_rejected.py` (evicts curation-rejected articles from `pipeline/1-incoming`), `rotate_pipeline.py` (age-based housekeeping of old pipeline artifacts — `weekly-run` Step 7.7), `corroborate.py` (§16 trust line), `promote_tags.py` (pending→domains), `build_digest.py` (headless digest; implementation in the `scripts/digest/` package — also `--html` report output, `--daily` inflow digest (ADR 0016), and the inline trends embed, ON by default for non-quiet weekly digests (`--no-trends` opts out; `--report` for the browser page — ADR 0017)), `glossary.py` (appends the `📖 Glossary` section to a digest from `config/glossary.yaml`), `trends.py` (deterministic weekly trends report facade from registry + concepts — trend models/concept scanning/metrics/rendering split into `scripts/trend_report/` per ADR 0021), `brain_status.py` (read-only status / empty-state guard facade; status models/source/cadence/digest parsing split into `scripts/status/` per ADR 0021), `health.py` (operational health facade; CLI parser, model, roll-up, renderer, event-log storage, and event/artifact-derived signals split into `scripts/health_checks/` per ADR 0021), `value_metrics.py` (read-only recurring-value report — delivery-receipt retention, registry yield, synthesis reuse, feedback counts; cost-per-digest stays a manual PILOT field), `manage_sources.py` (source edits facade; implementation split into `scripts/sources/` per ADR 0021), `manage_authors.py` (the ONLY write path into `config/authors.yaml` — roster CRUD backing `author-manage`) + `scripts/authors/` (author roster store, identity ladder, per-variant collection plan + the honest "not built yet" warnings), `discover.py` + `scripts/discovery/` (read-only source *proposals* for a topic backing `discover-sources`; never writes config), `source_insights.py` + `scripts/source_report/` (Source Insights: which existing sources earn their place — the static HTML report + decision journal, CONVENTIONS §9.1–§9.2; it may *suggest* an author but can never add one), `import_opml.py` (OPML subscription preview/apply facade; model/parsing/preview/CLI helpers split into `scripts/opml_import/` per ADR 0021, config writes still route through `manage_sources`), `intake.py` (read-only plain URL classifier facade for unified intake; classification/topic/CLI/rendering internals split into `scripts/intake_flow/` per ADR 0021), `content_metadata/` (the single title/author/publication/date/feed extractor over untrusted remote documents — shared by intake and collection, and the only HTML metadata parser in the tree; absorbed the former `intake_flow/evidence.py`, so intake's classification signals and the metadata values now come from one pass), `inbox.py` (ad-hoc article-capture queue facade for `source-capture`; queue/registry/path/frontmatter/CLI internals split into `scripts/inbox_flow/` per ADR 0021), `concept_write.py` (atomic write-time concept write — invoked by `wiki-ingest`; also safety-net-lists the new concept in `brain/INDEX.md` § Recently added when nothing there references it, so a missed MOC edit can't hide it from `wiki-query`), `concept_manage.py` (user-facing concept-vault CRUD — `list`/`backlinks`/`archive`/`restore`, backing the `concept-manage` skill; soft-delete only, never hard-deletes), `extract_vault_notes.py` (additive lesson/playbook extraction from concept notes — `weekly-run` Step 3.5; writes only missing notes, never rewrites or deletes), `gen_agents.py` (renders `config/agents.yaml` → `.claude/agents/*.md` + `config/codex-profiles.example.toml`; `--check` drift guard — ADR 0015), `schema.py` (flat `schema_version` stamps + additive-only drift check — ADR 0020), `version.py` (reads/compares the `pyproject.toml` version for the shipped `update.sh` — refuses a silent downgrade), `setup_check.py` (the activation verdict the `setup-wizard` ends on: `complete` / `ready_schedule_not_registered` / `needs_attention`), `install_schedule.py` (the other half of that verdict: renders this install's crontab block from `config/schedule.yaml` for the chosen run path — `claude` / `codex` / `headless` — writes `crontab-research-brain.txt`, and with `--apply` merges it in without disturbing unrelated entries), `state.py` (state-dir relocation via `RESEARCH_BRAIN_STATE_DIR` — imported by `health.py`/`synthesis_freshness.py`/`delivery/deliver.py`), `health_alert.py` (opt-in DEGRADED push — invoked by `weekly-run` Step 7.5 and the decoupled `schedule/health-watchdog.md`), `feedback.py` (append-only reader-feedback event log backing the `digest-feedback` skill — docs/feedback.md), the headless `delivery/` module (`deliver.py` facade + CLI/runtime/channel/config/quiet/receipt/MCP/health/path internals + per-channel adapters), `search/` (staged web-search dispatcher — §15), and the unattended-safety trio: `run_lock.py` (single-run lock), `sanitize_incoming.py` (S1–S9 injection-gate facade; CLI/rules/model/frontmatter/companion/operations internals in `scripts/sanitizer/`), `synthesis_freshness.py` (content-hash re-synthesis trigger), and `presend_review.py` (deterministic pre-send review backbone — injection-leak scan + link resolution, backing the `digest-review` skill). |
| `templates/` | Copy-me templates (e.g. an article template). |
| `tests/` | `pytest` suite mirroring `scripts/` *(dev checkout only — excluded from the shipped archive)*. |
| `docs/` | Project docs (`architecture.md`, `scheduling.md`, `OPERATIONS.md` (operator runbook: migration / troubleshooting / recovery / durable state), `CONVENTIONS.md`, `telegram-commands.md` (the command-menu source of truth) + `telegram-multiproject.md`, `updating.md`, `SUPPORT.md` (supported vs best-effort), `PILOT.md` (the two-cycle full-product validation), `WALKTHROUGH.md`, `audience-levels.md`, `feedback.md`, `adr/` (architecture decision records)). |
| `brain/.obsidian/` | Obsidian vault configuration (the vault root is `brain/`; do not edit — see below). |

## Don't touch

- **`config/.env`** — never read its secret values aloud, print them, or commit them.
  Work only with `config/.env.example` and `*_env` references.
- **`brain/`** — treat this as the **user's** knowledge. Append and update notes; never
  bulk-delete or rewrite the vault. Knowledge changes go through `wiki-ingest` with the
  user's approval gate, never as a silent mass edit.
- **`brain/.obsidian/`** — Obsidian's own vault config (the vault root is `brain/`); leave it to Obsidian.
