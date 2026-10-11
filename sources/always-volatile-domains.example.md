# Always-volatile domains (TEMPLATE — opt-in)

> **This file is a starter template.** Copy it to `sources/always-volatile-domains.md`
> (drop the `.example`) and edit it for **your** fast-moving topics. When present,
> `research-frame` (Phase 2) and `research-audit` (Phase 4) match a research question
> against these keywords and, on a hit, **override the recency defaults** so stale
> facts on a volatile subject can't slip through:
>
> - `recency_max` → **3mo** (90 days) — far tighter than the usual 12-month default
> - `sources_mode` → **hybrid** (force a fresh-web cross-check, not vault-only)
> - `min_tier` → **T1** (a volatile fact needs an authoritative source)
>
> Leaving it absent is fully supported — `research-frame` simply skips the check and
> uses the brief's normal defaults (a soft warning, never a halt).

## How to use it

- One row per **keyword / phrase**. The match is on the research question text, so
  prefer the words a user would actually type ("pricing", "model release").
- `recency_max` is the override window for a match (keep it tight — that's the point);
  the other two columns are the forced mode + minimum tier described above.

## Keywords

| keyword | recency_max | sources_mode | min_tier |
|---|---|---|---|
| pricing | 3mo | hybrid | T1 |
| model release | 3mo | hybrid | T1 |
| context window | 3mo | hybrid | T1 |
| rate limit | 3mo | hybrid | T1 |
| api version | 3mo | hybrid | T1 |
| benchmark | 3mo | hybrid | T1 |
| funding round | 3mo | hybrid | T1 |
| acquisition | 3mo | hybrid | T1 |
| regulation update | 3mo | hybrid | T1 |
| security advisory | 3mo | hybrid | T1 |

> These are illustrative. Add the topics whose facts you know go stale fast; remove
> any that are stable in your domain (an over-broad list just forces extra web
> cross-checks).
