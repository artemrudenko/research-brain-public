# Walkthrough — what compounds after four weeks

> **Every name, number, and quote below is illustrative sample data**, invented to
> show the *shape* of what the system produces. Your topics, sources, and counts
> will differ. Nothing here is a benchmark or a promise.

An RSS reader shows you a river: this week's items, then next week's items, and
nothing connects them. research-brain reads the same river — but it **keeps what
it learned**. This page shows the difference on one topic, one month apart.

---

## Week 1 — the digest looks like a smart RSS reader

You monitor the (sample) topic `ai-agents` with three feeds. Monday 09:00, the
first digest arrives:

```markdown
# Weekly digest — 2026-06-01

_4 new sources across 1 topic, 1 updated concept._

## ⚡ TL;DR
- 📰 Most active: **ai-agents** (4 of 4 new sources)
- 🔎 Worth a look: [Sandboxing patterns for tool-using agents](https://example.com/a) ⭐
- 💡 1 concept updated: Agent Sandboxing

## 📰 New sources (last 7 days)
### 🏷 ai-agents (4)
- "Sandboxing patterns for tool-using agents" ⭐ — isolate side-effectful tools
  behind per-call scopes (feeds: Agent Sandboxing)
- "A2A protocol draft v0.3" — agent-to-agent handshake spec update
- …

## 💡 Updated concepts (last 7 days)
- **Agent Sandboxing** — restricting what a tool-using agent can touch per call.
  - 🟡 Single-source — treat with caution
```

So far, an RSS reader with taste: grouped, capped, one ⭐ credibility marker, and
one honest trust line. The one structural difference is easy to miss: that last
line. The article didn't just get listed — it became a **concept note** in
`brain/concepts/agent-sandboxing.md`, with the source cited in its frontmatter.

## Week 4 — the same topic, compounded

Three weekly runs later, the digest for the same topic reads differently:

```markdown
# Weekly digest — 2026-06-22

_6 new sources across 2 topics, 3 updated concepts._

**🟢 Knowledge base:** 9 concepts · 0 orphans · 0 broken links · 0 missing-sources · 0 uncited-facts · 1 stale
**🧠 Knowledge base changes:** 1 concept created, 2 updated this run.
**🔁 Reused existing knowledge:** 2 existing concepts reused during synthesis.

## 💡 Updated concepts (last 7 days)
- **Agent Sandboxing** ⭐ — restricting what a tool-using agent can touch per call.
  - 🔵 Reported by 3 sources
- **A2A Protocol** — the emerging agent-to-agent interop handshake.
  - 🟢 Confirmed by 2 independent sources

## 📈 Trends — 2026-06-22
### 🧠 Knowledge growth
- Concepts created: 1 this week (↓ -1 vs last)
- Created per week (last 8w): ▁▁▁▁▂▅█▃ (0 → 1)
- Most connected: Agent Sandboxing (4), A2A Protocol (3)
```

And the concept note itself — `brain/concepts/agent-sandboxing.md` in Obsidian —
now carries the month, not the week:

```markdown
---
title: Agent Sandboxing
type: concept
tags: [ai/agents, security/isolation]
created: 2026-06-01
last_updated: 2026-06-22
related_concept: [a2a-protocol, tool-permissioning]
sources:
  - {url: https://example.com/a, archive: pipeline/0-archive/…, date: 2026-06-01, tier: high}
  - {url: https://example.org/b, archive: pipeline/0-archive/…, date: 2026-06-12}
  - {url: https://example.net/c, archive: pipeline/0-archive/…, date: 2026-06-21}
---

## What it is
Restricting what a tool-using agent can touch per call…

## Key facts
- Per-call scopes beat session scopes for side-effectful tools (Source: example.com/a)
- The A2A draft punts sandboxing to the runtime (Source: example.net/c)  ← added week 4
```

## The difference, named

| | RSS reader | research-brain, week 4 |
|---|---|---|
| This week's articles | ✅ a list | ✅ a list, curated + sanitized |
| Last month's articles | scroll back and re-read | already distilled into 9 concept notes |
| "How well-supported is this claim?" | you check manually | 🟢/🔵/🟡 corroboration per concept, from cited domains |
| "What do I already know about X?" | search your memory | `/know X` answers from the vault, with sources |
| Direction over time | none | 📈 trends + the created-per-week sparkline |
| Reader preference | none | reply "too technical" / "mute X" — it tunes itself |

The loop that produces this is the same every week — collect → sanitize → curate →
synthesize → digest → deliver — so the vault is a **by-product of reading you were
doing anyway**. Week 1 you get a digest; week 4 you also have a brain.

## Try the loop yourself (10 minutes)

1. `./install.sh` installs the dependencies; then say **"let's set up sources"** in
   Cowork / Claude Code — the wizard sets topics/sources/channels/schedule
   ([QUICKSTART](../QUICKSTART.md)).
2. Ask **"run the pipeline now"** (`/run`) — one full gated cycle.
3. Open `brain/` in Obsidian: your first concepts, each citing its sources.
4. Ask **"what does my brain know about \<your topic\>?"** (`/know`) — the answer
   comes from the vault, not the web.
5. Let the weekly schedule run. Around week 4, open this page again next to your
   own digest — the before/after above should now be yours.
