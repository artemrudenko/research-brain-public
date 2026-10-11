# ADR 0013 — `technical_level` as a render-time presentation knob (not stored variants)

- **Status:** Accepted (2026-06-26)
- **Tags:** audience, delivery, digest, presentation

## Context
Readers vary in technical literacy: an engineer wants terse output with raw specifics, a
non-technical reader wants explanation, expanded acronyms, and "why it matters". The existing
`research-frame` `audience` question (internal / external / strategic-leadership) is a
**formality / stakes** axis — it governs verification rigor (Anti-AI audit, Critique, tiering) —
**not** a reader-literacy axis. There was no way to set, once, how much the system explains versus
assumes across the digest and interactive answers.

## Decision
Add **one config knob** — `delivery.technical_level: technical | balanced | non-technical` in
`config/channels.yaml`, default **`balanced`** when absent (backward compatible) — applied as a
**render-time transform** at the moment of delivery / answering. It changes wording only; it does
**not** change what is stored. `brain/` concepts and `pipeline/3-synthesis/` documents stay
full-fidelity and technical (every fact still cites its `sources:`). Only **delivery / answer
surfaces** read the knob and adjust phrasing — `digest-build` (the RICH agent-authored path),
`brain-ask`, and conversational/Telegram answers; the surfaces that *write stored artifacts*
(`research-build` synthesis docs, `wiki-ingest` concepts) do **not** consult it. The enum is
validated by `validate_config.py`; semantics live once in
[`docs/audience-levels.md`](../audience-levels.md). Set it in `setup-wizard` (Step e.5) /
`configure.py`, or change it later via the `/audience` Telegram alias.

## Consequences
- **Single source of truth preserved.** No "simplified copy" of knowledge exists to drift from the
  real one; the same vault renders three ways.
- **Switching levels is instant and free** — no re-collection, no re-synthesis.
- **Orthogonal to `audience`.** The two axes compose (a leadership deliverable can render
  non-technical); they must not be collapsed into one parameter.
- Every user-facing surface must read the knob to honor it; `brain-ask`, which previously hardcoded
  "plain, non-technical language", now reads `technical_level` instead.
- Adds one optional key to the channels schema (absent → `balanced`, so existing installs are
  unaffected).

## Alternatives considered
- **Store per-level variants of each concept/digest.** Rejected — duplicates the source of truth,
  invites drift, and forces re-processing on every level change.
- **Overload the existing `audience` parameter.** Rejected — conflates stakes with literacy; a
  leadership artifact is not necessarily for a non-technical reader and vice-versa.
- **Per-message/per-request only (no persisted default).** Rejected — the common case is a stable
  audience for a given install; a persisted default is the better fit. A user can still ask for a
  one-off answer at a different level in conversation, but the install-wide default is the knob.

## References
- `docs/audience-levels.md` (the three-level semantics + who-reads-it table).
- `docs/CONVENTIONS.md` §2.1 (`delivery.technical_level` schema note).
- `config/channels.yaml`; `scripts/validate_config.py` (`TECHNICAL_LEVELS`); `scripts/configure.py`.
- `skills/digest-build`, `skills/brain-ask`, `skills/setup-wizard` (Step e.5).
- `docs/telegram-commands.md` + `CLAUDE.md` (`/audience` alias).
