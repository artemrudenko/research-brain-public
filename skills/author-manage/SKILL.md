---
name: author-manage
description: "User-facing CRUD over the author-monitoring roster (config/authors.yaml). One intent per turn: ADD an author the user has decided to follow, LIST the roster, PAUSE / RESUME one, or REMOVE one. Every operation goes through scripts/manage_authors.py — the only write path into the roster. Distinct from source-manage (monitors a feed/site, not a person) and from Source Insights, which SUGGESTS authors but can never add one. Triggers: 'follow this author', 'monitor this author', 'start following X', 'track this person', '/author add', 'list authors', 'who am I following', 'which authors do we monitor', '/author list', 'pause author X', 'stop following X', '/author pause', 'resume author X', 'unfollow X', 'remove author X', '/author remove', 'подписаться на автора', 'следить за автором', 'список авторов', 'кого я читаю', 'отписаться от автора', 'приостановить автора'."

metainfo:
  category: [knowledge-management]
  type: worker
  domain: sources
  last_updated: 2026-07-21
  predecessor: [source-insights, discover-sources]
  successor: [collect]
---

# author-manage — follow, pause & unfollow individual authors

Most monitoring in this system is per-**source**: a feed, a blog, a site. This
skill is the per-**person** equivalent. It owns `config/authors.yaml`
(CONVENTIONS §2.4) and is the only place a person is added to it.

| Intent | What it does | Backed by |
|---|---|---|
| **add** | Start following one author the user has decided to follow | `scripts/manage_authors.py add` |
| **list** | Show the roster (name, variant, handle, paused state) | `scripts/manage_authors.py list` |
| **nodes** | List author **nodes** (`brain/authors/`) each marked `followed: yes/no` — read-only | `scripts/manage_authors.py nodes` |
| **pause** | Stop collecting an author without losing the record | `scripts/manage_authors.py pause` |
| **resume** | Resume a paused author | `scripts/manage_authors.py resume` |
| **remove** | Drop an author from the roster entirely | `scripts/manage_authors.py remove` |

> **`list` vs `nodes` — two different questions.** `list` shows the **roster**
> (`config/authors.yaml`) — "who I follow". `nodes` shows the vault **author nodes**
> (`brain/authors/`) — "what my brain knows of them" — each marked `followed: yes/no`
> by intersecting the node's `identity_key` with the roster (Stage 9, Q4). `nodes`
> is strictly read-only: it NEVER adds a node to the roster or a roster entry to the
> vault. The two intents stay separate on purpose.

> **Nothing here happens on its own.** Source Insights can tell the user that an
> author keeps clearing curation and looks worth following. That is a
> *suggestion*, and it stays one: the report has no route to this skill, and this
> skill has no bulk "accept all". A person starts being followed when the user
> says so, one at a time, and never before. This is the plan's hard rule and it
> is enforced structurally — `scripts/source_report/` does not import
> `manage_authors`, pinned by `tests/test_manage_authors.py`.

---

## When to Use

**Use when** the user wants ONE roster change:
- "follow / monitor **X**", "track this person" → `add`.
- "who am I following", "list authors" → `list`.
- "which authors does my brain know", "who do we have notes on", "author nodes",
  "am I following the people in my vault" → `nodes` (read-only, `followed: yes/no`).
- "pause / stop following **X**" → `pause` (keeps the entry).
- "unfollow / remove **X**" → `remove` (drops the entry).

**Do not use for** a feed, blog or site — that is `source-manage`. If the user
pastes a link, `intake` classifies it first; a *person's* profile or author feed
routes here, a publication routes to `source-manage`.

---

## The three monitoring choices

Adding an author means choosing **how** we can actually reach their work. Each
variant needs a different handle, and the CLI refuses an entry without one.

| `--monitoring` | Use when | Requires | Status |
|---|---|---|---|
| `rss` | they publish an author-specific feed | `--feed URL` | **collected** |
| `publication-filter` | they write for a publication **already in `sources.yaml`** | `--publication HOST` + `--id` or `--url` | **collected** |
| `scholarly` | they publish papers | `--id orcid:… \| openalex:… \| s2:…` | *not collected yet* |

Two refusals are deliberate, and both should be **explained** to the user rather
than worked around:

- **`publication-filter` needs the publication already monitored.** We never
  guess a feed URL for a site the user does not collect. If it is missing, offer
  to add it via `source-manage` first, then retry.
- **`scholarly` needs a prefixed identifier.** `0000-0002-1825-0097` *looks*
  like an ORCID, but acting on that resemblance means querying some registry for
  some person and crediting the result to this one. Ask for the prefix.

> **Honesty at add-time — `scholarly` is not collected yet.** Only `rss` and
> `publication-filter` have an execution path today. `scholarly` is accepted but
> a run collects nothing for it and prints a warning. Say this before writing.
> The retired `search` variant is no longer offered for new authors. An older
> roster row remains readable and removable; `/discover` proposes sources on demand.

---

## Procedure

1. **Identify the intent** (add / list / pause / resume / remove). One per turn.
2. **For `add`, establish the handle before writing.** Ask which variant fits if
   it is not obvious from what the user gave you. Do not invent a feed URL, a
   profile URL, or an identifier prefix — if you do not have it, ask.
3. **Run the CLI.** Never hand-edit `config/authors.yaml`; the file is
   machine-written and its comments are regenerated on every change.

   ```bash
   python3 scripts/manage_authors.py add "Jane Doe" \
       --monitoring rss --feed https://example.com/jane/feed.xml \
       --added 2026-07-21 --note "suggested by source-insights"

   python3 scripts/manage_authors.py list
   python3 scripts/manage_authors.py nodes
   python3 scripts/manage_authors.py pause "Jane Doe"
   python3 scripts/manage_authors.py remove "Jane Doe"
   ```

4. **Report what changed, in the user's words.** The CLI is idempotent: adding
   someone already followed, or pausing someone already paused, prints
   "nothing changed" rather than failing. Pass that through honestly instead of
   claiming a change that did not happen.
5. **On a validation error, relay the reason.** The messages name the missing
   handle and why it is required. They are the explanation the user needs, not
   noise to summarize away.

---

## Notes

- **Identity, not name, is the key.** Re-accepting the same suggestion is a
  no-op; two same-named people with different handles both get a row. If the
  user names someone ambiguous, the CLI says so and asks them to edit the file.
- **Pausing keeps the record.** `pause` is the right answer to "stop following
  X for now" — `remove` throws away the fact that they were ever followed.
- **An emptied roster leaves the file in place.** `authors.yaml` with
  `authors: []` means "asked and answered"; a deleted file means "never
  configured", which is a different thing.
- Collection reads the roster through `scripts/authors/plan.py`, which resolves
  each entry to what would actually be fetched. An entry it cannot resolve is
  reported, never silently skipped.
