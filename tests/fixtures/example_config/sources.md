# config/sources.md — Source registry

Central config for all `collect-*` tasks. To add or change where articles are
collected from, edit **only this file**. Collection tasks read it on every run.

> Filled in during setup (run the `setup-wizard` skill, or edit by hand).
> This file ships as a TEMPLATE — replace the example rows below with your own sources.

**Updated:** YYYY-MM-DD

---

## Record format

| URL | Type | Tier | Priority | Filter | Active |
|-----|------|------|----------|--------|--------|
| full URL | `rss` / `blog` / `medium-tag` / `webpage` | `high` / `medium` / `low` | `high` / `medium` / `low` | short filter note | `yes` / `no` |

- **`Tier`** — *source credibility* (`high` / `medium` / `low`): how much to trust this source. Copied onto each collected article's `tier:` frontmatter and surfaced in the digest. (Distinct from `Priority`, which is collection ordering.)

Supported source types:

- **`rss`** — RSS/Atom feed. Fetched via WebFetch + XML parsing. Most reliable; prefer when a feed exists.
- **`blog`** — a blog index page. Navigated and scraped for article links (browser or RSS discovery).
- **`medium-tag`** — a Medium tag `/latest` page. Navigated in a browser with JS extraction.
- **`webpage`** — any single page. Navigated and scraped for links (fallback for sites without a feed).

---

## Category: example-topic

> `# EXAMPLE — replace`
> Each category maps to a topic in `config/topics.md` (same name).
> The save folder and frontmatter tags are defined there.

**Save folder:** `pipeline/1-incoming/example-topic/`
**Registry category:** `example-topic`

### Active sources

| URL | Type | Tier | Priority | Filter | Active |
|-----|------|------|----------|--------|--------|
| https://example.com/feed.xml | rss | high | high | all articles | yes |  <!-- # EXAMPLE — replace -->
| https://medium.com/tag/example/latest | medium-tag | low | medium | only on-topic posts | no |  <!-- # EXAMPLE — replace -->

### Filter rules
Include: short note on what belongs in this category.
Exclude: short note on what to drop (off-topic, low-signal, duplicates of another category).

### Candidates (not yet automated)

| URL | Type | Note |
|-----|------|------|
| https://example.org/blog | blog | # EXAMPLE — replace; parked idea, enable when ready |

---

## Notes on adding a source

1. Add a row to the **Active sources** table of the relevant category with `Active = yes`.
2. Pick the right **Type** — prefer `rss` when a feed exists (most reliable), otherwise `blog` / `medium-tag` / `webpage`.
2a. Set a **Tier** (`high` / `medium` / `low`) for the source's credibility — it is copied onto each article and shown in the digest.
3. `medium-tag` sources use browser navigation + JS extraction; `rss` uses WebFetch + XML parsing.
4. After adding, check the dedup registry (`pipeline/registry.md`) does not already contain entries from the new source.
5. Keep category names in sync with `config/topics.md`.
