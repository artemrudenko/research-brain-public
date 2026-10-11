# config/topics.md — Monitored topics

Defines the topics (categories) this brain tracks. Topics drive **both** collection
(where articles are saved + how they are tagged) and the weekly digest (how items are grouped).

> Filled in during setup (run the `setup-wizard` skill, or edit by hand).
> This file ships as a TEMPLATE — replace the example topic below with your own.

**Updated:** YYYY-MM-DD

---

## Topic format

Each topic is one section. Keep the topic **name** in sync with the matching category in
`config/sources.md`.

- **Name** — the topic / category name (used as the folder name and registry category).
- **Save folder** — where collected articles land: `pipeline/1-incoming/{name}/`.
- **Frontmatter tags** — tags written into each article's frontmatter (`tags:` field).
- **Include rules** — what belongs in this topic.
- **Exclude rules** — what to drop or route elsewhere.

---

## Topic: example-topic

> `# EXAMPLE — replace`

- **Name:** `example-topic`
- **Save folder:** `pipeline/1-incoming/example-topic/`
- **Frontmatter tags:** `[example, replace-me]`
- **Include rules:** Articles directly about the subject you want to track — concrete,
  substantive pieces (deep-dives, announcements, analyses) that match this topic.
- **Exclude rules:** Off-topic content, low-signal/hype with no substance, and items that
  belong to a different topic (route them to that topic's folder instead).
