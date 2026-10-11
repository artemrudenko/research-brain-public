# Trusted source registry (TEMPLATE — opt-in)

> **This file is a starter template.** Copy it to `sources/trusted-registry.md`
> (drop the `.example`) and edit the rows for **your** domains. Its mere presence
> turns on **source tier-grading**: `research-audit` runs in FULL mode (the
> `>30% 🔴` verification gate fires on the **manual `/research` chain only** — a
> human is in the loop and can override), and `source-archive` stamps each archived
> source with its tier. **Leaving it absent is fully supported** — every consumer
> degrades to soft mode (no tier-grading, no gate). The **unattended weekly digest
> is soft by design and never blocks**, registry or not.

## How to use it

- One row per **host** (registrable domain, lowercase, no scheme/path), mapped to a
  **tier** plus optional metadata. A host not listed → `unregistered` (treated as
  **T3** + flagged for a question by `research-audit`).
- **Tiers** (see `skills/research-audit/references/tier-rules.md` for edge cases):
  - **T1 — Authoritative.** Vendor primary docs, peer-reviewed venues, standards
    bodies / regulators (RFC, ISO, NIST), a vendor's own announcements about itself.
  - **T2 — Secondary.** Analyst firms, trade press, recognised-expert / corporate
    engineering blogs, high-reputation accepted Q&A answers, vendor marketing.
  - **T3 — Community / opinion.** Generic blogs without a track record, forums,
    aggregator comments, anonymous posts. Signal, not fact.
- Columns: `host` (the key) · `tier` · `topics` (which of your topics it's
  authoritative for, or `*` for any) · `volatility` (`stable` / `3mo` — how fast its
  facts go stale) · `access` (`open` / `paywall` / `login`).

## Registry

| host | tier | topics | volatility | access |
|---|---|---|---|---|
| docs.python.org | T1 | * | stable | open |
| datatracker.ietf.org | T1 | * | stable | open |
| nist.gov | T1 | security | 24mo | open |
| arxiv.org | T1 | ai, ml | stable | open |
| openai.com | T1 | ai | 3mo | open |
| anthropic.com | T1 | ai | 3mo | open |
| <vendor>.com/pricing | T1 | * | 3mo | open |
| gartner.com | T2 | markets | 12mo | paywall |
| techcrunch.com | T2 | markets, ai | stable | open |
| stackoverflow.com | T2 | * | stable | open |
| <some-expert>.dev | T2 | ai | stable | open |
| news.ycombinator.com | T3 | * | stable | open |
| reddit.com | T3 | * | stable | open |
| medium.com | T3 | * | stable | open |

> Replace the `<vendor>` / `<some-expert>` placeholders and add the hosts you
> actually collect from. A tier can be **soft-downgraded per claim** by the audit
> (e.g. a T1 vendor blog making a forward-looking promise → effective T2) — that's
> recorded in the verification log, it does **not** edit this file.
