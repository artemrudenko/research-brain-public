# config/sources.example-starter.md — Starter source pack

> **This is a STARTER PACK.** Copy the rows you want into `config/sources.md`
> (and the matching topics into `config/topics.md`), then run
> `python3 scripts/schema.py migrate-config --force` to land them in the active YAML
> config (`config/sources.yaml` + `config/topics.yaml`) — or just run the
> `setup-wizard` skill, which does all of this for you. It exists so a new user can
> get a first digest fast without hunting for feeds.
>
> **Verify each feed still resolves before relying on it** — public feed URLs change
> and break over time.

**Updated:** YYYY-MM-DD

---

## Record format

| URL | Type | Tier | Priority | Filter | Active |
|-----|------|------|----------|--------|--------|
| full URL | `rss` / `blog` / `medium-tag` / `webpage` | `high` / `medium` / `low` | `high` / `medium` / `low` | short filter note | `yes` / `no` |

- **`Tier`** = source credibility (`high` / `medium` / `low`), copied onto each article and shown in the digest. **`Priority`** = collection ordering. They are independent.

---

## Category: tech-news

> Maps to topic `tech-news` in `config/topics.md` (same name).

**Save folder:** `pipeline/1-incoming/tech-news/`
**Registry category:** `tech-news`

### Active sources

| URL | Type | Tier | Priority | Filter | Active |
|-----|------|------|----------|--------|--------|
| https://hnrss.org/frontpage | rss | medium | high | Hacker News front page | yes |
| https://techcrunch.com/feed/ | rss | medium | medium | TechCrunch | yes |
| https://www.theverge.com/rss/index.xml | rss | medium | medium | The Verge | yes |
| https://feeds.arstechnica.com/arstechnica/index | rss | high | medium | Ars Technica | yes |
| https://dev.to/feed | rss | low | low | dev.to community (dev/webdev, UGC — mixed quality) | yes |

### Filter rules
Include: substantive tech industry news, launches, and analyses.
Exclude: pure marketing/PR, low-signal hype, and AI/ML-specific items (route to `ai-ml`).

---

## Category: ai-ml

> Maps to topic `ai-ml` in `config/topics.md` (same name).

**Save folder:** `pipeline/1-incoming/ai-ml/`
**Registry category:** `ai-ml`

### Active sources

| URL | Type | Tier | Priority | Filter | Active |
|-----|------|------|----------|--------|--------|
| https://huggingface.co/blog/feed.xml | rss | high | high | Hugging Face blog | yes |
| https://medium.com/feed/tag/artificial-intelligence | rss | low | low | Medium AI tag (UGC — mixed quality) | yes |
| https://dev.to/feed/tag/ai | rss | low | low | dev.to AI tag (UGC) | yes |

### Filter rules
Include: AI/ML research, model releases, tooling, and applied technique deep-dives.
Exclude: general tech news with no AI/ML substance (route to `tech-news`).

---

## Verified feed patterns (copy + adapt)

> These are the **feed URL shapes** that reliably resolve to RSS/Atom. Swap in your
> own channel id / query / tag / subreddit, then **verify the URL resolves** before
> relying on it (public feeds change and break). Tiers below are starting suggestions —
> set the real credibility for the specific channel/feed you point at.

| URL pattern | Type | Tier | Note |
|-----|------|------|------|
| https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID | rss | medium | YouTube channel uploads — `CHANNEL_ID` from the channel page source. verify resolves |
| https://export.arxiv.org/rss/cs.AI | rss | high | arXiv category feed (swap `cs.AI` for any category). verify resolves |
| https://news.google.com/rss/search?q=YOUR+QUERY | rss | low | Google News keyword search (aggregator — low credibility). verify resolves |
| https://EXAMPLE.substack.com/feed | rss | medium | any Substack newsletter (`/feed`). verify resolves |
| https://medium.com/feed/tag/TAG_SLUG | rss | low | Medium per-tag feed. verify resolves |
| https://hnrss.org/frontpage | rss | medium | Hacker News (also `/newest`, `/best`, `/jobs`). verify resolves |
| https://www.reddit.com/r/SUBREDDIT/.rss | rss | low | any subreddit feed (`/.rss`). verify resolves |

---

## Notes on adding a source

1. Add a row to the **Active sources** table of the relevant category with `Active = yes`.
2. Prefer `rss` when a feed exists (most reliable), otherwise `blog` / `medium-tag` / `webpage`.
2a. Set a **Tier** (`high` / `medium` / `low`) for the source's credibility — copied onto each article and shown in the digest.
3. After adding, check the dedup registry (`pipeline/registry.md`) for existing entries from the source.
4. Keep category names in sync with `config/topics.md`.
