---
title: "Acceptance tests — capabilities"
type: acceptance-test
status: active
related_skill: skills/capabilities/SKILL.md
generated_by: ai-then-human-edited
---

# Acceptance tests — capabilities

> Living spec for the friendly "what can you do?" orientation skill. Covers the
> open-ended menu request, routing a concrete "how do I…" to one capability instead
> of the whole menu, the Russian trigger answered in the conversation language, and
> the boundary where a concrete task should route rather than dump everything. The
> menu mirrors the skill trigger table in `AGENTS.md` (the source of truth).

## Scope

- **Skill:** `capabilities` (named to avoid the built-in `/help` CLI command, but its
  triggers include help-style phrasing).
- **SKILL.md:** [`../SKILL.md`](../SKILL.md)
- **Coverage:** 4 scenarios — 1 full menu + 1 concrete-task route + 1 RU trigger +
  1 ambiguous "help with X" route.

---

## Scenarios

### Scenario 1: "what can you do?" -> the grouped menu

**Given:**
- A normal conversation, no specific task in flight.

**When:**
- User: "what can you do?" (or "help", "what can I say?", "what commands are there?").

**Then:**
- The skill presents the capability menu **grouped by user goal**, not by internal
  skill name — the six groups: Set things up, Manage what I monitor, Ask about my
  brain, Get a digest, Research a topic deeply, Explore the knowledge base.
- Each group has 2–3 concrete example sentences in quotes the user could copy.
- Skill names appear only lightly (in parentheses), never as the headline.
- It closes by inviting the user to just say what they want.
- It does **not** perform any action (no config edit, no digest build/send, no
  research) — orientation only.

---

### Scenario 2: "how do I add a source?" -> route, don't dump

**Given:**
- A normal conversation.

**When:**
- User: "how do I add a source?" (a concrete task framed as a help question).

**Then:**
- The skill does **not** print the whole menu.
- It points to the **Manage what I monitor** capability (source-manage) and quotes a
  ready-to-use example sentence, e.g. *"watch this blog: https://example.com/"* or
  *"add this RSS feed to tech-news"*.
- It notes the change is made by just saying it in plain words (the system confirms
  the topic/type, never guesses).

---

### Scenario 3: Russian trigger «что ты умеешь» -> same menu, RU

**Given:**
- The conversation is in Russian.

**When:**
- User: "что ты умеешь?" (or "помощь", "какие команды?").

**Then:**
- The skill presents the **same six-group menu**, written in Russian (the
  conversation's language), with the example sentences in the user's language.
- The grouping and routing logic are identical to the English path — only the
  presentation language changes.
- It closes by inviting the user to just say what they need.

---

### Scenario 4: ambiguous "help with X" -> route or ask one question

**Given:**
- A normal conversation.

**When:**
- User: "help with the digest" (concrete area, but ambiguous between building and
  sending).

**Then:**
- The skill recognizes this is a concrete-task help request, so it does **not** dump
  the full menu.
- Because "the digest" is ambiguous (build vs send vs run the whole cycle), it asks
  ONE clarifying question (clarify, don't invent) — e.g. "do you want to build one
  now, send a built one, or run the whole cycle?" — then points at the right
  capability (digest-build / digest-deliver / run-now) with its example sentence.
- It never invents which one the user meant.
