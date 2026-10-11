---
name: discover-sources
description: Find new sources worth monitoring for a topic. Triggers on "find new sources for X", "who should I read about X", "find alternatives to my sources", "/discover X".
---

# discover-sources

Answers **"who else should I be reading about X?"** — searches, groups what it
finds by site, drops everything already monitored, and proposes at most ten, each
with the reason it is proposed.

## The boundary that matters

This skill **proposes**. It never adds a source. `source-manage` is the only
thing that writes `config/sources.yaml`, and only after the user picks. Say so
when you present results — a list that looks like it was already applied invites
the user to skip reading it.

## Steps

1. Run `python3 scripts/discover.py "<topic>" --json`.
2. If it returns `needs_agent_search: true`, the configured provider is Claude's
   in-agent WebSearch, which the script cannot call. **You** run WebSearch with a
   few phrasings of the topic, write the results as a JSON list of
   `{"url","title","snippet"}`, and re-run with `--results <file>`.
3. Present the proposals in plain language: the site, why it came up, whether it
   has a feed, and an example link or two.
4. Ask which to monitor. Nothing happens until the user answers.
5. For each accepted one, hand off to **source-manage** — it resolves the topic,
   the type, and the trust tier. **Never set `tier` yourself**: trust is the
   user's judgement, and this skill has no basis for it.

## What to tell the user, and what not to

- Lead with what the site *is* and why it surfaced, not with a rank number.
- A site with a feed is easier to monitor than one without — worth saying, since
  it affects what monitoring will actually cost them.
- Roles (`academic`, `aggregator`, `community`, `independent`, …) are a **coarse
  guess from the domain**. Anything unrecognised is labelled `independent`, which
  means "we could not tell", not "verified independent". Do not present a role as
  a fact about the publisher.
- Aggregators (Hacker News, Reddit) are ranked last on purpose: they point *at*
  sources rather than being one, and monitoring them floods the pipeline with
  links to things better monitored directly. If the user wants one anyway, that
  is their call — just make the trade-off explicit.
- If nothing came back, say so plainly. A soft-skip (`provider: none`, missing
  API key) is not a failure and not an empty field — it means search is not
  configured, and the user may want to set it up.

## Related

- `source-manage` — the only path that adds a source.
- `scripts/source_insights.py` — which of the sources they ALREADY have are
  earning their place. Worth mentioning when someone is adding more.
