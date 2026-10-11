---
name: brain-ask
description: "Answer READ-ONLY status, findings & HEALTH questions about THIS system's own state — what it monitors, on what cadence, what digests it has produced, and whether everything is healthy and correctly set up (config valid, feeds alive, delivery wired, digest fresh) — using scripts/brain_status.py, scripts/health.py and scripts/doctor.py (the deep setup+health check). NOT a research skill: it never fetches anything new and never reads brain/concepts/ for external topics (that is wiki-query). Boundary — brain-ask = OUR monitored state/schedule/digests/health; wiki-query = EXTERNAL topic knowledge from the vault. Triggers: «what are we monitoring», «list our sources», «how often do we collect», «show last digest», «top 5 digests», «key findings this week», «is everything ok», «system health», «is anything broken», «are the feeds alive», «что мониторим», «как часто собираем», «покажи последний дайджест», «ключевые находки за неделю», «всё ли в порядке», «состояние системы», «здоровье системы», «что-нибудь сломалось»."
metainfo:
  type: lookup
  domain: meta-process
  last_updated: 2026-06-16
  relation: "Sibling of wiki-query. brain-ask answers about OUR own state (sources, schedule, produced digests); wiki-query answers about EXTERNAL topics from brain/concepts/. They never overlap."
---

# brain-ask — status & findings over our own state

Answers a user's questions about **this system itself**: which sources it
monitors and how often, what digests it has produced, and the key findings from
the most recent one. It reads only the project's own config and produced digests
— it never fetches anything new and never browses the knowledge vault for an
external topic.

Everything it reports comes from one deterministic, read-only helper —
`scripts/brain_status.py` — so the answers are exact, not invented.

---

## Boundary — brain-ask vs wiki-query (read this first)

| Question is about… | Skill | Reads |
|---|---|---|
| **Our own state** — "what do we monitor?", "how often do we collect?", "show the last digest", "key findings this week" | **brain-ask** (this skill) | the sources config (`config/sources.yaml`), `config/schedule.yaml`, `pipeline/3-synthesis/digest_*.md` |
| **An external topic** — "what do we know about RAG?", "research transformers", "topic overview of X" | **wiki-query** | `brain/concepts/` (the Obsidian vault) via `brain/INDEX.md` |

- If the user is asking about **the machine** (its sources, its schedule, its
  digests / findings) → **brain-ask**.
- If the user is asking about **a subject the machine has studied** → that is a
  research-intent query: route through `research-frame` → `wiki-query`.
- When genuinely ambiguous, ask ONE clarifying question (clarify, don't invent —
  see AGENTS.md mandatory rules), then proceed.

---

## When to Use

**Use when the user asks (EN or RU):**
- "what are we monitoring", "list our sources", "what feeds do we watch",
  "что мониторим", "какие источники"
- "how often do we collect", "what's the schedule", "when does the digest run",
  "как часто собираем", "какое расписание"
- "show the last digest", "give me the latest digest", "top 5 digests",
  "покажи последний дайджест", "топ-5 дайджестов"
- "key findings this week", "highlights from the last digest",
  "ключевые находки за неделю"
- "is everything ok", "system health", "is anything broken", "are the feeds
  alive", "did the digest go out", "всё ли в порядке", "состояние системы",
  "здоровье системы", "что-нибудь сломалось"

**Skip / don't use for:**
- Any question about an external **topic** ("what do we know about X") → that is
  research intent → `research-frame` → `wiki-query`. This skill never reads
  `brain/concepts/`.
- **"What's new?" / "что нового"** → that is `whats-new` (it FETCHES fresh items and
  answers inline); brain-ask only reads the already-produced digests. "Key findings
  this week" / "highlights from the LAST digest" stay here (read-only, nothing fetched).
- Building or sending a digest (that is the `digest-build` / `digest-deliver` skills).
- Changing config. To **change what we monitor** (add/pause/remove a source or
  topic) that is `source-manage`; broader setup (channels, schedule, tags) is
  `setup-wizard`. brain-ask is strictly read-only.

---

## Inputs

| Input | Source | Notes |
|-------|--------|-------|
| The question | user request | Used only to classify which query to run |
| `config/sources.yaml` | repo config | Source registry (read-only, via `scripts/brain_status.py`) |
| `config/schedule.yaml` | repo config | Cadence + timezone + lookback (read-only) |
| `pipeline/3-synthesis/digest_*.md` | produced digests | Newest-first listing + findings (read-only) |
| `pipeline/.health/events.jsonl` | run-history log | Operational roll-up: feed liveness, delivery, run history (read-only) |
| `scripts/doctor.py` | deep composite check | Read-only setup+health verdict — config schema, sources, delivery wiring, health, locks (for broad "is anything broken" questions) |
| `config/channels.yaml` → `delivery.technical_level` | repo config | Audience level for the answer: `technical` \| `balanced` \| `non-technical` (default `balanced`, read-only) — see [`docs/audience-levels.md`](../../docs/audience-levels.md) |

---

## Steps

1. **Classify the question** into exactly one of five intents:
   - *sources* — what we monitor / our feeds / how many sources.
   - *cadence* — how often / the schedule / when things run.
   - *digests* — list / show recent digests (latest, last N, top 5).
   - *findings* — key findings / highlights from the last digest (not "what's
     new?" — that fetches fresh and belongs to `whats-new`).
   - *health* — is everything OK / system status / are the feeds alive / did the
     last digest go out / "is anything broken".

   If it is actually about an **external topic**, stop and route to
   `wiki-query` instead (see Boundary). If ambiguous, ask ONE question.

2. **Call the matching read-only query.** Prefer the CLI; the module is also
   importable if you are already in Python.

   ```
   python3 scripts/brain_status.py sources          # active sources only
   python3 scripts/brain_status.py sources --all     # include parked rows
   python3 scripts/brain_status.py cadence
   python3 scripts/brain_status.py digests           # all, newest first
   python3 scripts/brain_status.py digests -n 5       # top 5
   python3 scripts/brain_status.py findings           # latest digest highlights
   python3 scripts/health.py report                    # operational run-history roll-up
   python3 scripts/doctor.py                            # deep setup+health verdict (config, sources, delivery, health, locks)
   ```

   These commands only read files — they never write anything (`doctor.py` is
   read-only too: it sends nothing, writes nothing, resolves no secret values).

3. **Present the result at the configured audience level**, with concrete dates
   and cadence words (never raw cron strings unless asked). Read
   `config/channels.yaml` → `delivery.technical_level` (default `balanced`):
   `non-technical` → plain language, expand acronyms, lead with what it means;
   `balanced` → plain language but keep useful specifics, define terms on first use;
   `technical` → concise, may keep jargon and raw identifiers. The grounding is
   identical at every level — only the wording changes ([`docs/audience-levels.md`](../../docs/audience-levels.md)):
   - *sources*: group by category; for each source give the URL, its type, and
     its credibility tier; say how many are active. Mention parked ones only if
     the user asked for "all". **Empty-state branch:** if there are **no** real
     (non-example) sources yet (`brain_status.py sources` skips the shipped EXAMPLE
     placeholders, so it prints "No monitored sources configured." on the un-set-up template),
     do **not** claim we monitor the example feed. Say plainly: "Nothing is set up
     yet — tell me a topic to start watching (e.g. *\"start monitoring AI news\"*)
     or I can run the setup wizard," and offer to hand off to `source-manage` /
     `setup-wizard`. To **change** what we monitor, that is `source-manage` (this
     skill is read-only).
   - *cadence*: state the timezone once, then one friendly line per step
     ("Collects new articles every 3 days at 09:00", "Builds the digest every
     Monday at 09:00"), plus the digest lookback window in days.
   - *digests*: a newest-first list — each line a date plus its one-line summary
     ("3 new sources across 2 topics, 1 updated concept") or "Quiet week" for a
     quiet one. For "the last digest", show just the newest.
   - *findings*: the highlight bullets from the latest digest, prefixed with its
     date. **Handle the empty cases explicitly** (the query returns a clear
     message, not a crash): a **quiet week** → say "the latest digest
     (<date>) was a quiet week — nothing new"; **no digests yet** → say "no
     digests have been produced yet" and suggest building one.
   - *health*: pick the tool by breadth of the question.
     - **Broad "is everything OK / is anything broken / is it set up right"** →
       run `python3 scripts/doctor.py` — the deep composite that checks config
       schema, monitored sources, delivery wiring (secret SET/MISSING, never
       values), the operational health verdict, and the run/delivery locks in one
       pass. Lead with its final verdict line, then relay only the `[FAIL]` /
       `[WARN]` sections that matter to the user, and relay `Next action:` lines
       verbatim. Doctor catches **setup** problems (a broken `channels.yaml`, no
       active RSS source, a missing secret) that the operational log alone cannot.
       On a brand-new install its WARNs mean *"setup is unfinished"*, not
       *"broken"* — say that plainly and offer the setup wizard rather than
       implying a fault.
     - **Narrowly operational — "did the digest go out", "are the feeds alive",
       "did delivery succeed"** → relay `health.py report`: lead with the overall
       verdict (✅ OK / ⚠️ needs attention), then only the lines that matter — a
       stale digest, a failed delivery channel, or a source gone quiet for several
       runs. Relay `Next action:` lines verbatim. If nothing is wrong, say so in
       one line ("Everything looks healthy — last digest N days ago, delivery
       succeeded, all sources active"). The log is empty on a brand-new system →
       say "no runs recorded yet" rather than implying a problem. (`doctor.py`
       already embeds this verdict as its Health section, so a broad check needs
       only doctor; don't run both unless the user asks for the run-history
       detail.)
       Never advise manual edits to `pipeline/registry.md`, `.synthesis-meta.json`,
       or delivery receipt JSON files; status recovery must go through the printed
       commands/intents instead.

4. **Stay read-only.** Never edit config, never write a file, never fetch a URL.
   If the user actually wants to *change* what we monitor (a source or topic), hand
   off to `source-manage`; for broader setup (schedule, channels, tags), hand off to
   `setup-wizard`.

---

## Output

- A concise answer at the configured `technical_level` (default plain-language), grounded entirely in `brain_status.py` output.
- Dates are shown as `YYYY-MM-DD`; cadence as human phrases.
- The empty / quiet / no-digests cases are stated clearly, never as an error.
- Nothing is written; no URL is fetched.

---

## Verification

- *sources*: active-only by default; parked (`Active: no`) and Candidate rows are
  excluded unless the user asked for "all".
- *cadence*: timezone and digest lookback reported; one friendly line per
  scheduled block; no raw cron unless requested.
- *digests*: newest-first; "top N" truncates correctly; quiet digests are
  labelled as such.
- *findings*: highlights come from the **latest** digest; a quiet week and a
  no-digests state each produce a clear plain-language message, not a crash.
- *health*: a broad "is anything broken / set up right" question runs `doctor.py`
  (its verdict leads); a narrowly operational one uses `health.py report`. A
  fresh, unfinished install reads as *"setup incomplete"*, never as a fault.
- Boundary: an external-topic question is routed to `wiki-query`, not answered here.
- Read-only: no file written, no fetch performed.

---

## Examples

**Example 1 — sources (RU):**
> User: "что мы мониторим и с какой периодичностью?"
> Runs `brain_status.py sources` and `brain_status.py cadence`; replies with the
> active sources grouped by topic and one friendly cadence line per step
> (collect every 3 days, digest every Monday), plus the timezone.

**Example 2 — top digests:**
> User: "show me the last 5 digests"
> Runs `brain_status.py digests -n 5`; replies with a newest-first list, each
> line a date + one-line summary (quiet weeks labelled "Quiet week").

**Example 3 — findings, quiet week:**
> User: "ключевые находки за последнюю неделю"
> Runs `brain_status.py findings`; the latest digest was quiet, so it replies
> "the latest digest (2026-06-08) was a quiet week — nothing new to report",
> not an error.

**Example 4 — boundary (route away):**
> User: "what do we know about retrieval-augmented generation?"
> That is an external-topic question → brain-ask declines and routes to
> `research-frame` → `wiki-query`; it does NOT read `brain/concepts/` itself.

**Example 5 — health, broad check (RU):**
> User: "всё ли в порядке / что-нибудь сломалось?"
> Runs `python3 scripts/doctor.py`; leads with its verdict and relays only the
> `[FAIL]`/`[WARN]` sections — e.g. "почти всё в порядке; одна проблема: секрет
> Telegram не задан (MISSING)". On a brand-new install it says setup is
> unfinished and offers the wizard, never "broken".
