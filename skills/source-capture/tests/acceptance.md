# source-capture — Acceptance Tests

Given/When/Then scenarios for regression coverage of the two intents — **CAPTURE**
(`/save <url>`) and **PROCESS** (drain the inbox → concepts). All queue mutations go through
`scripts/inbox.py`; the skill never hand-writes frontmatter or moves files.

---

## Test cases — CAPTURE (`/save <url>`)

### Test SC-1.A — Fresh URL, cache miss

**Given:** the inbox queue has no entry for `https://example.com/post`
**When:** the user sends «save this — https://example.com/post»
**Then:**
- The page is fetched via **`source-archive` with `MODE=instruction-stripping`** (never a raw fetch — a pasted link is untrusted web text, CONVENTIONS §12)
- `scripts/inbox.py add --url … --title … --body-file <tmp> --source web` writes a frontmatter-strict file under `pipeline/1-incoming/_inbox/`
- The script prints `OK: captured` and `queued: 1`
- The user is **acked immediately** with the queued count — no waiting for processing

### Test SC-1.B — Same URL still pending (dedup)

**Given:** `https://example.com/post` is already queued and unprocessed
**When:** the user sends the same URL again
**Then:**
- `inbox.py add` prints `OK: already queued` — no duplicate file, no re-fetch
- The ack reflects the unchanged queue; no error

### Test SC-1.C — URL already collected/curated (registry hit)

**Given:** `https://example.com/post` already has a registry row (collected earlier)
**When:** the user sends it via `/save`
**Then:**
- `inbox.py add` prints `SKIP: already known (in registry)` — nothing queued
- The user is told it's already known; no duplicate

### Test SC-1.D — Below-threshold ack mentions the brain

**Given:** the queue holds 1–2 articles (below `inbox.DEFAULT_PROCESS_THRESHOLD` = 5)
**When:** a capture succeeds
**Then:**
- The ack adds a brief, conversational line that captured articles become concepts once a few more accumulate (or on `/process`)
- It does **not** recite the threshold number unless asked

### Test SC-1.E — Threshold reached

**Given:** a capture brings the queue to 5
**When:** `inbox.py add` returns
**Then:**
- The script prints `READY`
- The skill tells the user and **offers to run PROCESS now** (or notes it drains on the next weekly-run); an outward `brain/`-writing run is confirmed unless the user already said go

### Test SC-1.F — Fetch failure

**Given:** the URL is a dead link / paywalled and all fetch fallbacks fail
**When:** the user sends it
**Then:**
- The skill says so plainly and **skips that URL**
- **No** empty/placeholder article is queued

---

## Test cases — PROCESS (drain the queue)

### Test SC-2.A — Standalone `/process`, lock acquired

**Given:** no run is in progress and the queue has ≥1 article
**When:** the user sends `/process`
**Then:**
- `run_lock.py acquire --note "source-capture"` exits 0; the printed `lock-token:` is captured
- The body runs (sanitize → fan-out read → route → curate → synthesis)
- The lock is released with `run_lock.py release --token <token>` on **every** exit path

### Test SC-2.B — Invoked by weekly-run (Step 1.5), lock NOT re-acquired

**Given:** `weekly-run` already holds the single run lock and invokes PROCESS
**When:** PROCESS runs
**Then:**
- It **skips** `run_lock.py acquire` (re-acquiring would refuse against the orchestrator's own lock)
- It **does not** release the lock on any exit path — `weekly-run` owns and releases it

### Test SC-2.C — Lock already held (standalone)

**Given:** another run holds the lock
**When:** the user sends `/process`
**Then:**
- `run_lock.py acquire` exits 1 (`REFUSED: a run is already in progress`)
- The skill **stops**, does nothing else — this is **not** a failure

### Test SC-2.D — Empty queue

**Given:** `inbox.py count` returns `queued: 0`
**When:** PROCESS runs
**Then:**
- It reports "inbox empty" and stops
- The lock is released **only if this task acquired it** (standalone path)

### Test SC-2.E — Readers use the sanitized companion

**Given:** the queue has articles and `sanitize_incoming.py sanitize` has written stripped companions
**When:** the fan-out readers run (one subagent per article)
**Then:**
- Each reader reads the **sanitized companion**, never the raw file
- Each returns a best-fit **topic** (closed-book from `config/topics.yaml`), 2–4 takeaways, and tags closed-book from `config/tags.yaml` (genuinely new tags → `pending:` only, CONVENTIONS §11)

### Test SC-2.F — Routing + normal chain

**Given:** a reader chose topic `ai/agents` for an article
**When:** routing runs
**Then:**
- `inbox.py route "<path>" "ai/agents"` moves it out of `_inbox/` and retargets `category:`
- The routed material then flows through **`pipeline-curate`** → **`weekly-synthesis`** (not reimplemented)
- A topic still below `synthesis.min_sources_per_topic` simply waits — **expected, not a failure**

### Test SC-2.G — Unprocessed captures never pollute the digest

**Given:** an article is queued in `_inbox/` but not yet routed
**When:** a digest is built
**Then:**
- The builder skips `_inbox/` — the queued link never appears as a junk topic

---

## Acceptance criteria

- [x] CAPTURE fetches via `source-archive` instruction-stripping (never raw)
- [x] All queue state goes through `scripts/inbox.py` (add/count/pending/route)
- [x] Dedup outcomes distinguished: captured / already queued / already known
- [x] Instant ack on capture; processing is batched (threshold / manual / weekly-run)
- [x] PROCESS serialized under the single run lock, with the weekly-run skip-acquire rule
- [x] Readers consume the sanitized companion only
- [x] Below-threshold topics wait without erroring
- [x] `_inbox/` excluded from the digest until routed
- [ ] Dogfood: full capture→process→concept on a real batch (deferred to a live run)

---

## Change log

| Date | What | Trigger |
|---|---|---|
| 2026-06-24 | Created acceptance tests for source-capture. SC-1 CAPTURE (fetch/dedup/threshold/failure) · SC-2 PROCESS (lock semantics/sanitize/route/chain/digest-isolation). | Review found source-capture had no acceptance contract. |
