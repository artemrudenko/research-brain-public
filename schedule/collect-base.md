# collect-base — Shared article-collection logic

**Purpose:** Common logic for every `collect-*.md` task. Not run directly — it is invoked from a thin-wrapper task that supplies the parameters below.

**Parameters (substituted by the calling task):**
- `{CATEGORY}` — topic / category name (from the topics config `config/topics.yaml` — AGENTS.md config map)
- `{OUTPUT_FOLDER}` — relative folder where articles are saved: always `pipeline/1-incoming/{CATEGORY}/` (derived from the topic name, never stored)
- `{SOURCE_URLS}` — list of active source URLs (with their `type` **and `tier`**) for this category, read from the sources config (`config/sources.yaml`). Each saved article copies its originating source's `tier` into the `tier:` frontmatter field (credibility, surfaced in the digest).
- `{TAGS_FRONTMATTER}` — frontmatter tags for saved files (from the topics config)
- `{REGISTRY_CATEGORY}` — value written to the `category` column of the registry (usually = `{CATEGORY}`)
- `{FILTER_CRITERIA}` — include/exclude rules (from the active topics config)
- `{CANDIDATE_POOL}` — how many candidates to gather per topic *before* selection, read from `config/schedule.yaml` → `collect.candidate_pool_per_topic` (default 25). Gather wide, then rank.
- `{MAX_ARTICLES}` — per-topic cap on how many of the ranked candidates to actually read & save, read from `config/schedule.yaml` → `collect.max_articles_per_topic` (default 10). Saved cap, raisable per deployment.

All paths are relative to the project root (`{{VAULT_ROOT}}`), the folder the product is opened from.

---

## Step 0: Run lock (held by the caller — usually skip here)

Collection writes shared state (`pipeline/registry.md`, the dedup ledger that
`synthesis_freshness.combined_hash` and the weekly run read), so a collect pass must run
**under the single run lock**. This base file is never run directly — its caller owns the
lock, so by the time you reach Step 1 the lock is **already held** and you **skip acquiring
it here**:

- called from **`collect-topic`** standalone — the wrapper took the lock in its Step 0a;
- called from **`weekly-run`** (Step 1, per topic) — the orchestrator already holds it.

Either way, **do not acquire or release the lock in this file** — that is the caller's
job (the wrapper's Step 0a/0b, or `weekly-run`'s Step 0/8). Only if you are running these
steps **directly with no wrapper** (unusual) must you bracket them yourself, exactly like
`collect-topic` does:

```bash
python3 scripts/run_lock.py acquire --note "collect-base"   # exit 1 → a run is in progress; stop cleanly
# … Steps 1–8 …
python3 scripts/run_lock.py release --token <lock-token>    # only if you acquired it here
```

---

## Step 1: Get a browser tab

For browser-driven sources (`medium-tag`, `blog`, `webpage`), open or reuse a browser tab via the available browser MCP (Playwright or the Chrome extension). Remember the tab/page handle. RSS sources do not need a browser — they are fetched via WebFetch.

---

## Step 2: Load the registry (URL dedup)

Read `pipeline/registry.md`.

Extract every URL from the table rows (rows look like `| collected | category | status | https://... | title |`). **Build the known-URL set as canonical dedup keys**, not raw URLs: pass each registry URL through `scripts/normalize_url.py` → `normalize(url)`. This folds http/https, `www.`/`m.` prefixes, trailing slashes, `#fragments` and tracking queries onto one key, so a candidate that differs only in those ways is still recognised as already-collected. You may run the script (`python3 scripts/normalize_url.py <url>`) or apply the same rules inline. Keep this set of canonical keys — it is checked against each candidate article.

---

## Step 3: Build the candidate list

**Collect from every role the topic defines (multi-stage).** A topic's sources in
the sources config play one of three **roles** (a source's role is read from its
`Filter`/note column or its `Type`); gather candidates from *all* of them, then rank
(Step 4c):

1. **RSS** — any `Type: rss` (and `medium-tag` via its per-tag feed). Cheapest, first.
2. **Official** — the product/tool's own news or docs page (`Type: webpage`/`blog`,
   noted `official`). **Rule — a topic about a specific tool MUST include its official
   source** (e.g. `claude` → `https://www.anthropic.com/news`, `codex` →
   `https://openai.com/news/`). Fetch the page and extract its recent item links.
3. **Search platforms** — fresh-article search on Medium / dev.to / Habr for the
   topic (`medium-tag`, a `dev.to` tag feed, a Habr hub). For **Medium member-only**
   articles use the **logged-in browser** (the deployment's own Chrome session via the
   browser MCP) so the paywall is bypassed; `dev.to`/Habr are open (full text via RSS
   or WebFetch).

**RSS-first acquisition ladder (cheap → expensive — CONVENTIONS §12).** Within each
role, always start at the top rung and only descend when the one above fails (missing
feed, error, empty, or no usable body):

1. **RSS with full body** — fetch the feed; if `<content:encoded>` / full
   `<description>` carries the whole article, use it as-is. No browser, no
   second fetch.
2. **RSS + WebFetch body-completion** — feed gives the link + metadata but only a
   summary; WebFetch the article URL to complete the body.
3. **Static-page fetch** — no feed at all: WebFetch the page (or index) and
   scrape links / body from the HTML.
4. **Playwright / Chrome (browser)** — JS-heavy pages only, and **only for
   sources on a per-source allow-list** (`medium-tag`, or a source explicitly
   typed `blog`/`webpage` that needs JS). The browser is **not** the default.

For each source in `{SOURCE_URLS}`, branch on its `Type` (each maps onto a rung):

- **`rss`** — fetch the feed with WebFetch and parse the XML `<item>` / `<entry>` elements. Preferred: most reliable, no browser needed. For each item capture, when present:
  - `<link>` + `<title>` — the article URL and title;
  - **`<guid>` / `<id>`** — the feed's own stable identifier; keep it for *in-run* de-dup of feed items only (collapsing the same item appearing twice within this fetch). The persistent, cross-run dedup key is the normalized URL, not the guid (see Step 4a);
  - full body from `<content:encoded>` / `<description>` (rung 1 above) — if it is the complete article, no per-article fetch is needed;
  - **`<category>` terms** — keep them as **seed tags**; normalise each through the registry `config/tags.yaml` (synonyms → canon, drop anything unknown) per CONVENTIONS §11/§12. These become the article's `tags:` (in addition to `{TAGS_FRONTMATTER}` from the topic).
- **`blog` / `webpage`** — navigate to the index page; if it exposes an RSS/Atom feed, prefer that. Otherwise scrape article links from the HTML.
- **`medium-tag`** — **try Medium's per-tag RSS feed first**: `https://medium.com/feed/tag/{tag}`
  (where `{tag}` is the tag slug from the source URL, e.g. `https://medium.com/tag/ai-agents/latest`
  → `https://medium.com/feed/tag/ai-agents`). Fetch it with WebFetch and parse `<item>` elements
  for `<link>` + `<title>`, exactly as for an `rss` source. **Only if the feed fails** (blocked,
  empty, or no items) fall back to navigating the tag `/latest` page and extracting links with a
  browser JS call, for example:

```javascript
Array.from(document.querySelectorAll('h2, h3')).slice(0, 25).map(h => {
  let el = h;
  while (el && el.tagName !== 'A') el = el.parentElement;
  return { title: h.innerText.trim(), url: el?.href || '' };
}).filter(i => i.url.includes('medium.com') && i.title.length > 10
  && !i.url.includes('/tag/') && !i.url.includes('/membership'))
```

**Positive Medium article-URL check:** a real Medium article URL ends with a slug whose
last segment is a 12-hex-digit id, e.g. `…/some-title-1a2b3c4d5e6f`. Keep a candidate only
if it matches this pattern (regex: `-[0-9a-f]{12}(\?|#|/?$)`). This positive check is more
reliable than the negative `/tag/` / `/membership` filters alone — apply it in addition to
them (works for both the RSS and the browser path).

Apply `{FILTER_CRITERIA}` when judging the relevance of each candidate.

Gather up to **`{CANDIDATE_POOL}`** (~25) unique candidate links per topic across all
roles — deliberately **wider than you will read**. A single rich source (e.g. one Medium
tag) can supply many; cap any one source's share so the pool stays diverse across roles.
Selection happens in Step 4c — gather wide here, read the best later.

---

## Step 4: Filter out duplicates

Two layers — exact normalized-URL match against the registry first (cheap), then
near-duplicate text (only for survivors that we actually fetched).

**4a — Exact dedup against the registry (CONVENTIONS §12):** the persistent,
cross-run dedup key is the **normalized URL** — the *same* value Step 7 stores in
`pipeline/registry.md` (there is no guid column in the registry). For each candidate
compute `scripts/normalize_url.py` → `normalize(url)` (lowercase host, strip
`www.`/`m.`, force https, drop trailing slash, `#fragment` and query) and check it
against the registry key-set (Step 2, which normalizes the stored URLs the same way).
If **present** → skip. If **absent** → add to the collect list (carry the original
URL through; the key is only for the comparison). Because the compare key and the
stored key are the same normalized URL, an item collected on a previous run is
reliably recognised and not re-collected.

A feed's **`<guid>` / `<id>`**, when present, may be used only as an *in-run* de-dup
of feed items (collapsing the same item appearing twice within this one fetch) — it
is **not** a persistent key, since the registry does not store it. Near-duplicate /
syndicated stories that live at a *different* URL are handled by **Step 4b** (near-dup
on body text), not here.

**4b — Near-duplicate / syndication (`scripts/dedup.py`):** the same story is
often republished at a *different* URL/guid (syndication, mirror, reworded
repost), which 4a cannot catch. After fetching bodies (Step 5), compare each
new article's cleaned body against the others collected **this run** (and,
cheaply, against recent same-category bodies if at hand) using the hybrid
lexical check:

```bash
python3 scripts/dedup.py <fileA> <fileB> [more...]   # prints duplicate clusters
```

or programmatically `from scripts.dedup import is_duplicate, find_duplicates`.
It scores `max(char-3gram-jaccard, token-jaccard) >= 0.7` (CONVENTIONS §12).
Within a duplicate cluster, **keep one** (prefer the higher-`tier` source, then
the longer body) and skip the rest — do not write a file or a registry row for
the dropped near-dups. Log: `NEAR-DUP: <url> — duplicate of <kept-url>. Skipped.`

**4c — Rank the pool, keep the best `{MAX_ARTICLES}`.** The pool from Step 3 is
wider (`{CANDIDATE_POOL}`, ~25) than what you read. **Before** fetching full bodies,
score every deduped candidate and keep the top `{MAX_ARTICLES}` (~10):

- **Relevance** to the topic — title/summary match against `{FILTER_CRITERIA}` and the
  topic's keywords (strongest signal; drop off-topic candidates outright).
- **Recency** — newer is better (prefer the lookback window; heavily discount stale items).
- **Source tier** — `high` > `medium` > `low` as a tie-breaker, and keep the pool
  **diverse across roles** (don't let one Medium tag crowd out the official source).

Read & save only this ranked top `{MAX_ARTICLES}`; the rest of the pool is dropped
(not parked). Log one line: `SELECTED {MAX_ARTICLES}/{pool} for <topic> (dropped N off-topic/stale)`.
This is "gather 25, read the best 10" — quality of the saved set over raw recency.

---

## Step 5: Fetch full text (up to `{MAX_ARTICLES}` selected articles)

For each article in the collect list:

1. Fetch the article. Prefer WebFetch for plain pages; use the browser for JS-heavy pages (e.g. Medium). If WebFetch is blocked or returns no usable body, fall back to the browser (Playwright / Chrome extension).
2. For browser fetches, **scroll to the bottom** to load lazy content — two sequential JS calls:
```javascript
window.scrollTo(0, document.body.scrollHeight); true;
```
then again:
```javascript
window.scrollTo(0, document.body.scrollHeight); true;
```
3. Extract the fields (browser example):
```javascript
({
  title: document.querySelector('h1')?.innerText?.trim() || '',
  author: document.querySelector('[data-testid="authorName"], [rel="author"]')?.innerText?.trim() || '',
  date: document.querySelector('time')?.getAttribute('datetime') || document.querySelector('time')?.innerText || '',
  url: window.location.href.split('?')[0],
  text: document.body.innerText
})
```
4. If `text.length < 500` or `title` is empty → skip.
5. Clean the text: site chrome / navigation (menus, "Home", "Sign in", footers, etc.) usually sits at the start of `body.innerText` — drop it and keep the article body starting from the title.
6. **Content-sanity / grounding gate (do this on the *cleaned* body, before writing anything or generating "Key takeaways"):**
   - **Junk-wall reject** — if the cleaned body looks like a paywall / consent / login wall rather than an article, **skip the article** (do not save a file). Markers (case-insensitive) include: `subscribe to continue`, `create a free account`, `sign in to read`, `members only`, `accept cookies` / `manage cookies` / `cookie preferences`, `you have N free` (N free articles/stories), `register to read`, `enable javascript`. Treat the body as a wall if such markers dominate it (i.e. there is little real prose around them).
   - **Too-little-prose reject** — if the cleaned body has too little actual prose to summarise (e.g. fewer than ~3 sentences, or essentially no paragraph text after chrome removal), **skip the article**.
   - On reject: do **not** write a junk file, do **not** generate "Key takeaways", and **do not** update the registry (skip Steps 6–7 for this article). Log to stdout: `JUNK/WALL: <url> — looks like paywall/consent/login or too little prose. Article skipped.`
   - These checks are *in addition to* the existing `text.length < 500` rule (step 4) and the strict-frontmatter verification (Step 6.5) — a body can clear 500 chars and still be a wall.

---

## Step 6: Save article files

**Final exact-dedup gate before every write.** Before writing a file, re-check the
article's normalized URL against the current `pipeline/registry.md` (or the live
known-URL set if you have kept it current). This is the last guard against a duplicate
introduced after Step 2's snapshot by another source in the same run, a parallel reader
subagent, or a concurrent capture flow. If the key is now present, skip the article:
do **not** write a file and do **not** append a registry row. Log:
`DUP: <url> — already registered before save. Skipped.`

For each collected article, save a file at:
`{OUTPUT_FOLDER}/YYYY-MM-DD_<slug>.md`

Where `slug` is the first 5 words of the title, lowercased and hyphen-joined.

File format (strict frontmatter — see `docs/CONVENTIONS.md` §5):
```
---
source: <source name, e.g. medium / rss feed name / blog>
url: <NORMALIZED URL>
title: <TITLE>
author: <AUTHOR>
date_published: <PUBLISH DATE>
collected: <TODAY'S DATE>
category: {CATEGORY}
tags: {TAGS_FRONTMATTER}        # + RSS <category> seed tags, normalised via config/tags.yaml (Step 3)
tier: <high|medium|low>         # optional — copied from the source's tier in the sources config
---

# <TITLE>

*By <AUTHOR> · <DATE>*

---

## Key takeaways

<3–5 bullet points — the most important things from the article: the core idea, practical implications, and why it matters for the topic being tracked>

---

<ARTICLE BODY>

---
*Source: <URL>*
```

---

## Step 6.5: Post-write verification (mandatory)

**Guard against frontmatter-less drops:** after writing each article, verify it.

For each just-saved file:
1. Read the first 2 lines (`Read` or `head -2`).
2. **Hard rule:** the first line must be exactly `---` (open YAML frontmatter).
3. If not:
   - **Delete the file** (`rm`) — do not leave a frontmatter-less artifact in `1-incoming/`.
   - **Log the error** to stdout: `FRONTMATTER MISSING: <path> — discarded. Article skipped.`
   - **Do not** update the registry for this article (skip Step 7).

**Why:** the collect pipeline must be reliably frontmatter-strict so downstream steps (digest, ingest) can trust the metadata. Manual paste / external import is a separate flow and should not land in `1-incoming/` via collect.

**Verification helper:** `scripts/validate-pipeline-frontmatter.py` can be run over `pipeline/1-incoming/` to catch frontmatter-less files that entered the pipeline by other means (manual paste, external script).

---

## Step 7: Update the registry

After saving each article, append a row to the registry table in `pipeline/registry.md`:
```
| YYYY-MM-DD | {REGISTRY_CATEGORY} |  | <NORMALIZED URL> | <TITLE> |
```
(The `status` column is left blank on collection.)

Read the current file, find the last table row, and append the new row.

Writing to the registry is the **mandatory final step** for every saved article.

---

## Step 8: Record source health (observability)

After finishing each source, append one health event per source so feed liveness
is traceable over time (CONVENTIONS — operational observability; the log is the
gitignored `pipeline/.health/events.jsonl`). Use the item count **after dedup**:

```bash
python3 scripts/health.py record --kind collect --source "<source URL>" --items <N>
# on a fetch error (feed unreachable / blocked / empty), use --status error --items 0
```

This is best-effort and read-mostly: a logging failure never aborts collection.
`brain-ask` health and the weekly health line read these events to surface a
source that has gone quiet for several runs (a likely dead feed).

---

## Success criteria
- Up to `{MAX_ARTICLES}` new files in `{OUTPUT_FOLDER}` (as many as found after dedup).
- Each file contains a `## Key takeaways` section with 3–5 bullets and the full article text.
- Each candidate was checked against the registry by its normalized URL before saving (`scripts/normalize_url.py`) — the same value the registry stores (Step 7); http/https, www/m, trailing-slash and tracking-query variants do not produce duplicates, and items collected on a previous run are not re-collected.
- Near-duplicate / syndicated stories (different URL, same content) were collapsed via `scripts/dedup.py` (hybrid `max(char-3gram, token) >= 0.7`) — one kept per cluster, the rest skipped.
- Each saved article carries seed tags from the RSS `<category>` (normalised via `config/tags.yaml`) and the source's `tier` (when the source declares one).
- Each saved article was appended to `pipeline/registry.md`.
- Files with body text shorter than 500 characters are not saved.
- Articles whose body is a paywall / consent / login wall, or has too little prose to summarise, are not saved (R5 grounding gate, Step 5.6).
