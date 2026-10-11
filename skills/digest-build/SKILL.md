---
name: digest-build
description: "Build a weekly digest on demand — scan recently collected sources (pipeline/1-incoming) and recently updated concepts (brain/concepts) over the configured lookback window and write pipeline/3-synthesis/digest_YYYY-MM-DD.md. Prefers the rich agent-authored build (prose lead + source→concept links) when running in Cowork/Claude Code with vault access; falls back to the deterministic scripts/build_digest.py for headless/quick builds. Builds locally and reports the path; it does NOT send anything — it offers to hand off to digest-deliver. Triggers: «build digest», «build the weekly digest», «make a digest», «give me a digest», «I want a digest», «make me a digest», «собери дайджест», «сформируй дайджест», «собери дайджест сейчас». To RE-SHOW an already-built digest, that is brain-ask ('show last digest'); to SEND one, digest-deliver; for the whole collect→…→deliver loop, run-now."
metainfo:
  type: worker
  domain: research-methodology
  last_updated: 2026-07-12
  successor: [digest-deliver]
---

# digest-build — build the weekly digest on demand (local, no sends)

Builds a weekly digest **now**, in conversation, from what is already in the
vault: recently collected sources in `pipeline/1-incoming/` and recently updated
concepts in `brain/concepts/`, scoped to the lookback window. It writes one file —
`pipeline/3-synthesis/digest_YYYY-MM-DD.md` — and stops there.

This skill is the **build** half of the build/deliver pair; `digest-deliver` is the
other. The separation is deliberate: **build is local and has no side effects**
(it only writes a file you can inspect), while **deliver has external side effects**
(it sends to email / Telegram / Rocket.Chat). This skill never sends — it ends by
telling you the digest is built and offering to hand off to `digest-deliver`.

It does **not** reimplement digest building. It **orchestrates** the two existing
build paths — the agent-authored richer build (`schedule/weekly-digest.md`) and the
deterministic headless builder (`scripts/build_digest.py`) — and picks between them.

---

## When to Use

**Use when:**
- The user says: "build digest", "build the weekly digest", "make a digest",
  "give me a digest", "I want a digest", "make me a digest",
  "собери дайджест", "сформируй дайджест", "собери дайджест сейчас".
- They want a digest produced **right now**, on demand, without waiting for the
  scheduled weekly run.

> **CREATE-intent owner.** "give me a digest" / "I want a digest" / "make me a
> digest" mean *produce a new digest now* — that is this skill. To **RE-SHOW** an
> already-built digest, that is `brain-ask` ("show last digest"); to **SEND** one,
> `digest-deliver`; for the whole collect→…→deliver loop, `run-now`.
>
> **RU near-collision.** «собери дайджест сейчас» = just the digest (this skill);
> «собери всё сейчас» = the whole loop (`run-now`).

**Skip / don't use for:**
- **Re-showing** an already-built digest — that is `brain-ask` ("show last
  digest"); this skill builds a fresh one.
- **Sending** a digest — that is `digest-deliver` (this skill only builds, then
  hands off).
- The **scheduled** weekly build — that is the `schedule/weekly-digest.md` task,
  driven by `digest.cron`; it builds and then hands off to delivery on a timer.
- The full gated weekly pipeline (collect → sanitize-incoming → curate → synthesis → hygiene →
  digest → deliver) — that is `schedule/weekly-run.md`. This skill is just the digest-build
  step, run by itself on request.
- Configuring channels, secrets, or schedule — that is `setup-wizard`.

---

## Inputs

| Input | Source | Notes |
|-------|--------|-------|
| Lookback window | `config/schedule.yaml` → `digest.lookback_days` | Default 7; the `--lookback N` flag overrides it |
| Recent sources | `pipeline/1-incoming/**/*.md` | In-window by frontmatter `collected:` (not mtime), grouped by `category`. Read title/takeaway from the `sanitized/` companion when one exists (the S1–S9-stripped view — that text ships to the reader); raw file is the fallback only |
| Recent concepts | `brain/concepts/*.md` | In-window by `last_updated`; SEED/EXAMPLE excluded (CONVENTIONS §5.1) |
| Synthesis / health | `pipeline/3-synthesis/synthesis-run_*.md`, `brain-health_*.md` | Latest of each, best-effort (omitted when absent) |
| Value evidence | `pipeline/3-synthesis/synthesis-run_*.md` → `## Totals` | Exact fields: `concepts created`, `concepts updated`, `existing concepts reused` |
| Digest language | `config/channels.yaml` → `delivery.language` | The language the digest is written in (default `en`) |
| Audience level | `config/channels.yaml` → `delivery.technical_level` | How much is explained vs assumed: `technical` \| `balanced` \| `non-technical` (default `balanced`). Render-time only — see [`docs/audience-levels.md`](../../docs/audience-levels.md) |
| Glossary | `config/glossary.yaml` → `terms:` | Optional term→explanation map. The deterministic builder appends a `📖 Glossary` section listing only the terms that appear in the digest (no-op if the file is absent or nothing matches) |

---

## Decision: rich agent-authored build vs deterministic builder

Both paths produce the **same file and the same section structure** (CONVENTIONS
§3 digest format) at `pipeline/3-synthesis/digest_YYYY-MM-DD.md`. They differ only
in how the body is written. Pick by capability:

- **RICH (preferred — agent-authored).** Use this whenever you are running **as an
  agent with vault/MCP access** (Cowork / Claude Code). Follow the build steps of
  [`schedule/weekly-digest.md`](../../schedule/weekly-digest.md) (its Steps 1–5).
  This produces everything the deterministic builder cannot: a **"this week in one
  line" prose lead** written for a non-technical reader, the week rendered as short
  **prose with inline `[title](url)` citations**, **source→concept links** (e.g.
  `"title" ⭐ — takeaway (feeds: <Concept Name>)`), and cross-topic synthesis —
  while still keeping the section structure, the high-tier ⭐ markers, the corroboration
  trust lines (CONVENTIONS §16), and the **Knowledge base** health line. A good
  shortcut: **run the deterministic builder first to lay down the skeleton, then
  enrich it** (see the cookbook below). Persist each topic's one-line lead into
  `pipeline/3-synthesis/{topic}/digest-lead.md` as you go (`weekly-digest.md`
  Step 4a) so the next deterministic build renders it too.
  Preserve the per-run value-evidence lines exactly: **Knowledge base changes**
  renders `concepts created` / `concepts updated`, and **Reused existing knowledge**
  renders only an explicit positive `existing concepts reused` count. Do not infer
  reuse from recent concept volume or source volume; raw source count is not reuse.

- **DETERMINISTIC (fallback — `scripts/build_digest.py`).** Use this when you are
  **headless** (no agent / cron), when the user explicitly wants the plain
  build, or when you just need a quick, reproducible skeleton. Per topic it shows a
  **curated** view — the top `DIGEST_LINKS_PER_TOPIC` (3) sources by credibility with a
  `+N more` note, not every article — over **de-duplicated** counts (re-collected URLs
  collapse). It stays LLM-free, so it generates **no** prose lead and no inline
  citations itself — but it **renders every topic's one-line prose lead** that the agentic
  `weekly-synthesis` (or the RICH path's Step 4a) writes to
  `pipeline/3-synthesis/{topic}/digest-lead.md`, freshness-gated per topic (a sidecar whose
  synthesis no longer matches the curated corpus is auto-suppressed; graceful when absent).
  With no sidecar only the busiest topic gets a derived one-line lead, and the daily inflow
  digest renders no leads. It applies every rule deterministically,
  renders **Knowledge base changes** from `concepts created` / `concepts updated`,
  renders **Reused existing knowledge** only from `existing concepts reused`, is fully
  tested, and is the exact path the external-cron flow runs before `deliver.py`.

**Default in this runtime:** RICH. You are in Cowork / Claude Code with vault
access, so author the richer digest. Drop to DETERMINISTIC only when headless or
when the user asks for the plain build.

> **KISS / DRY.** Do not re-derive the scan logic. The deterministic path **is**
> `scripts/build_digest.py`; the rich path **is** `schedule/weekly-digest.md`. This
> skill only chooses between them, supplies the lookback, and reports the result —
> it adds no new building logic of its own.

---

## Steps

1. **Read the lookback window — and first guard the un-set-up template.** Read
   `config/schedule.yaml` → `digest.lookback_days` (default 7). If the user named an
   explicit window ("build a digest for the last 14 days"), use that as the
   `--lookback N` override instead.

   **Empty-state guard (do this BEFORE building).** If the config still has only the
   shipped EXAMPLE topic/sources (no real source added yet —
   `scripts/brain_status.py sources` skips EXAMPLE placeholders, so it prints
   "No monitored sources configured." on the un-set-up template), do **not** build. Tell the user they
   haven't added real sources yet (building now would only fetch the placeholder
   `example.com` and return a confusing empty "quiet week") and hand off to
   `source-manage` ("start monitoring …") or `setup-wizard`.

2. **Read the digest language and audience level.** Read `config/channels.yaml` →
   `delivery.language` (default `en`) and write the digest in that language. Also read
   `delivery.technical_level` (default `balanced`) and render the body at that level —
   `technical` (terse, keeps jargon, raw specifics), `balanced` (defines non-obvious terms,
   one plain-language takeaway each), or `non-technical` (leads with "why it matters", expands
   acronyms, analogies, fewer raw IDs). This is a **render-time** choice — it changes wording
   only, never the underlying sources, counts, ⭐ tier markers, or section structure. Full
   semantics: [`docs/audience-levels.md`](../../docs/audience-levels.md). (Note: the RICH path's
   one-line prose lead is already written for a non-technical reader; at `technical` you may keep
   it crisp, at `non-technical` lean further into plain language.)

   **Glossary (both paths).** A `📖 Glossary` section explaining the jargon a digest
   uses is appended automatically by the DETERMINISTIC builder from
   `config/glossary.yaml` (only terms that appear; no-op if the file is absent). On
   the RICH path, lay the deterministic skeleton down first (Step 4) so the same
   section is inherited, and keep it when enriching — don't drop the glossary block.
   The curated list is a starting point, so on the RICH path also **augment it**:
   scan the digest for any acronym or specialist term a non-technical reader
   wouldn't know that is **not** already in `config/glossary.yaml`, and add a
   one-line plain-language entry for it (matching the existing `- **TERM** — …`
   style). At `non-technical` audience level be generous; at `technical`, minimal.
   Skip when nothing qualifies. (Consider offering to persist genuinely recurring
   terms into `config/glossary.yaml` so the deterministic path picks them up too.)

3. **Pick the path** per the decision above — RICH when running as an agent with
   vault access (default here), DETERMINISTIC when headless or on explicit request.

4. **Build.**
   - **RICH:** Follow `schedule/weekly-digest.md` Steps 1–5 with the lookback from
     Step 1. Recommended: lay down the deterministic skeleton first, then enrich it
     (prose lead, inline citations, source→concept links) — see the cookbook. Persist
     each topic's one-line lead to `pipeline/3-synthesis/{topic}/digest-lead.md`
     (weekly-digest.md Step 4a) so the next deterministic build renders it too.
   - **DETERMINISTIC:** first make sure the incoming tree is sanitized — the builder's
     anti-injection gate is fail-closed by default and refuses to build otherwise
     (idempotent, cheap, safe to re-run):

     ```
     python3 scripts/sanitize_incoming.py sanitize
     ```

     then run

     ```
     python3 scripts/build_digest.py
     ```

     to write the default path, or pass an explicit out path and/or lookback:

     ```
     python3 scripts/build_digest.py pipeline/3-synthesis/digest_<date>.md --lookback 14
     ```

     With no out path it writes `pipeline/3-synthesis/digest_YYYY-MM-DD.md` (date =
     today). It prints `wrote <path>` on success.

     Add `--html` to also write a self-contained, styled HTML report next to the
     markdown (`digest_YYYY-MM-DD.html`, same renderer the email transport uses).
     The markdown stays canonical; the HTML is a derived view for opening/sharing.

5. **Handle a quiet week.** When there are **no** new sources, **no** updated
   concepts, **and no** pending "Needs attention" items in the window, the digest is a
   one-line quiet note (the deterministic builder writes "Quiet week — nothing new
   surfaced in the last N days. Everything's running fine; I'll have more for you in
   the next digest."). (A stale-incoming backlog keeps the digest **non-quiet** so it still renders
   and surfaces that backlog — zero new sources/concepts alone is not enough.) A quiet
   digest MUST carry the structural marker line `<!-- research-brain: quiet-digest -->`
   (the deterministic builder writes it; if you compose or localize the quiet text
   yourself, keep that line — it is what `deliver.py --skip-quiet` detects, in any
   language). The deterministic builder also
   prints a `QUIET_WEEK` marker on stdout. This is **not** an error — report the
   quiet digest as built, and note that the user may want to skip delivery so they
   are not pinged with a "nothing new" digest (CONVENTIONS §10 / D7; in headless
   delivery this is `deliver.py <digest.md> --skip-quiet`).

6. **Report — do NOT deliver.** Tell the user the digest is built and **where**:
   `pipeline/3-synthesis/digest_YYYY-MM-DD.md`. Give a one-line summary (e.g. "N new
   sources across M topics, K updated concepts" — or "quiet week"). Then **offer the
   hand-off**: ask whether to send it via `digest-deliver`. This skill sends
   nothing on its own.

---

## Output

- A digest markdown file at `pipeline/3-synthesis/digest_YYYY-MM-DD.md` (today's
  date), or at the explicit out path the user gave.
- A concise report: the output path, a one-line volume summary (or "quiet week"),
  which path was used (rich / deterministic), and an offer to hand off to
  `digest-deliver`.
- **No external side effects** — nothing is sent; `config/` is read-only here.

---

## Verification

- A digest file exists at `pipeline/3-synthesis/digest_YYYY-MM-DD.md` (or the given
  out path) and follows the CONVENTIONS §3 section structure.
- The lookback came from `config/schedule.yaml` → `digest.lookback_days`, unless a
  `--lookback N` override was supplied.
- Both `pipeline/1-incoming/` and `brain/concepts/` are reflected, scoped by
  `collected:` / `last_updated` frontmatter (not mtime); SEED/EXAMPLE concepts are
  excluded (CONVENTIONS §5.1).
- A quiet week (no new sources, no updated concepts, **and** no pending attention
  items) produces the one-line quiet digest, is reported as success (exit 0,
  no error), and is flagged as "skip delivery?".
- **Nothing is sent** — no MCP delivery tool call, no webhook POST, no SMTP/Bot-API
  send. The skill ends by offering the `digest-deliver` hand-off.
- The digest is written in `delivery.language` from `config/channels.yaml`.

---

## Cookbook — skeleton then enrich (RICH path)

Lay down the deterministic skeleton, then rewrite the body as a brief:

```
python3 scripts/sanitize_incoming.py sanitize   # gate is fail-closed
python3 scripts/build_digest.py        # writes pipeline/3-synthesis/digest_<today>.md
```

Then open that file and enrich it per `schedule/weekly-digest.md`: add the
"this week in one line" lead, rewrite the week as short prose with inline
`[title](url)` citations, and add the `(feeds: <Concept Name>)` source→concept
links — preserving the sections, the ⭐ tier markers, the trust lines, the
**Knowledge base health** line, the **Knowledge base changes** line, and any
**Reused existing knowledge** line the skeleton already produced. Finally, persist
each topic's one-line lead into `pipeline/3-synthesis/{topic}/digest-lead.md`
(weekly-digest.md Step 4a — only for topics whose synthesis is current; never stamp
freshness from the digest path).

---

## Examples

**Example 1 — default build (rich, in conversation):**
> User: "собери дайджест сейчас"
> Reads `digest.lookback_days` (7) and `delivery.language` (en). Builds the rich,
> agent-authored digest for the last 7 days (prose lead + inline citations +
> source→concept links), writes `pipeline/3-synthesis/digest_2026-06-16.md`,
> reports "Built: 3 new sources across 2 topics, 1 updated concept →
> pipeline/3-synthesis/digest_2026-06-16.md", and offers to deliver it.

**Example 2 — explicit lookback (deterministic):**
> User: "build a plain digest for the last 14 days"
> Runs `python3 scripts/build_digest.py pipeline/3-synthesis/digest_2026-06-16.md
> --lookback 14`, reports the written path and the volume summary, and offers the
> `digest-deliver` hand-off.

**Example 3 — quiet week:**
> User: "build the weekly digest"
> No new sources and no concept updates in the window. The digest is the one-line
> "Quiet week …" note; the skill reports it as built (success), notes it is a quiet
> week, and suggests skipping delivery so the user is not pinged with nothing new.

**Example 4 — build then deliver:**
> User: "make a digest and send it"
> This skill builds the digest and reports the path, then hands off to
> `digest-deliver` (the build/deliver boundary is preserved — two skills, one for
> the local build, one for the external send).
