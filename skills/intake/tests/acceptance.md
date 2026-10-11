# intake — Acceptance Tests

Given/When/Then scenarios for unified OPML and plain-URL intake. The skill previews or proposes before persistence, except for explicit expert overrides.

---

## Scenario 1 — interactive OPML preview, selection, and confirmation

**Given** a valid OPML file with three ready feeds,
**When** the user asks to import subscriptions,
**Then** the skill runs `python3 scripts/import_opml.py PATH --json`, summarizes proposed topics and feeds, accepts deselection/reassignment, asks one final confirmation, and only then runs `--apply --confirmed --json`.

## Scenario 2 — automatic OPML import

**Given** a valid OPML file,
**When** the user explicitly requests automatic import,
**Then** the skill runs `python3 scripts/import_opml.py PATH --automatic --json` and reports the same result fields as interactive apply.

## Scenario 3 — partial invalid OPML import

**Given** an OPML file with valid feeds plus invalid or unsupported entries,
**When** the preview is shown,
**Then** invalid/unsupported items are reported per item, valid ready feeds remain selectable, and selected valid feeds can still be applied.

## Scenario 4 — repeated OPML import

**Given** an OPML file was already imported,
**When** the same file is imported again,
**Then** existing feeds are reported as already existing and no duplicate topic or source rows are created.

## Scenario 5 — confident recurring plain URL

**Given** `scripts/intake.py URL --json` returns `kind=recurring_source`,
**When** the user sees the proposal,
**Then** the skill displays `source_url`, `source_type`, `topic_mode`, `proposed_topic`, reason, `tier`, `priority=medium`, `filter_note="all posts"`, and `active=yes`, asks for required trust and approval, then hands off to `source-manage`.

## Scenario 6 — confident article plain URL

**Given** `scripts/intake.py URL --json` returns `kind=one_off_article`,
**When** the user sees the proposal,
**Then** the skill displays the input URL, reason, and one-off capture action, asks for approval, then hands off to `source-capture` with no topic required.

## Scenario 7 — ambiguous one-question path

**Given** `scripts/intake.py URL --json` returns `kind=ambiguous`,
**When** the skill needs user input,
**Then** it asks exactly `Should I save this one article, or monitor this site for future updates?` and asks no second generic ambiguity question.

## Scenario 8 — ambiguous→monitor with no matching topic

**Given** an ambiguous URL and the user chooses monitor,
**When** the classifier has no existing matching topic,
**Then** choosing monitor removes only generic action approval; the skill still asks for trust, still asks approval to create the proposed topic, and performs no persistence until those gates are resolved.

## Scenario 9 — topic match

**Given** a recurring URL whose tokens uniquely match an existing topic,
**When** the proposal is shown,
**Then** `topic_mode=existing` and `proposed_topic` are displayed, and the handoff may proceed after required trust and approval.

## Scenario 10 — topic no-match

**Given** a recurring URL with no unique existing topic match,
**When** the proposal is shown,
**Then** `topic_mode=create` and the proposed topic are displayed, but no topic is created until the user approves that new topic.

## Scenario 11 — explicit `/add <url>`

**Given** the user sends `/add https://example.com/feed.xml`,
**When** routing selects a skill,
**Then** it routes directly to `source-manage`, does not run `scripts/intake.py`, and adds no generic plain-URL approval gate.

## Scenario 12 — explicit `/save <url>`

**Given** the user sends `/save https://example.com/post`,
**When** routing selects a skill,
**Then** it routes directly to `source-capture`, does not run `scripts/intake.py`, and adds no generic plain-URL approval gate.

## Scenario 13 — repeated plain URL

**Given** the proposed URL has already been persisted by the target backend,
**When** the user approves the same plain URL again,
**Then** the target backend reports already present/already known and no duplicate source or inbox state is created.

## Scenario 14 — automatic one-off

**Given** automatic mode is explicitly requested and classification returns `one_off_article`,
**When** the action runs,
**Then** the generic action approval is bypassed and the existing `source-capture` backend handles dedup and capture.

## Scenario 15 — automatic existing-topic recurring

**Given** automatic mode is explicitly requested and classification returns `recurring_source` with `topic_mode=existing`,
**When** required default fields are available,
**Then** the generic action approval is bypassed and `source-manage` handles idempotent persistence.

## Scenario 16 — automatic recurring no-topic

**Given** automatic mode is explicitly requested and classification returns `recurring_source` with `topic_mode=create`,
**When** there is no approved existing topic,
**Then** the skill returns `needs_topic_approval`, performs no `add-topic` call, and performs no `add-source` call.

---

## Acceptance criteria

- [x] OPML preview and apply use `scripts/import_opml.py`.
- [x] Plain URL classification uses `scripts/intake.py`.
- [x] Confident plain classifications require approval before persistence.
- [x] Ambiguous URLs ask exactly one generic question.
- [x] Ambiguous→monitor preserves trust and new-topic approval gates.
- [x] Explicit `/add <url>` and `/save <url>` bypass classification.
- [x] Automatic recurring no-topic returns `needs_topic_approval` without persistence.
