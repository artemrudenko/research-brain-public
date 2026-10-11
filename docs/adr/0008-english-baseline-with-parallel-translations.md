# ADR 0008 — English is the canonical baseline; RU translations only for onboarding

- **Status:** Accepted (amended 2026-07-03)
- **Tags:** language, docs, i18n

## Context
The project was extracted and de-branded from a personal toolkit that carried RU-hardcoded content.
A distributable, topic-agnostic product needs one canonical content/instruction language, while
still serving Russian-reading users.

The original decision maintained a full set of parallel `*.ru.md` translations alongside every
baseline doc. In practice that translation surface drifted: every change to a baseline doc implied
a matching `*.ru.md` edit, and the deeper reference docs are exactly the ones that change most. The
divergence became concrete — e.g. the Windows scheduling section had silently dropped out of
`docs/scheduling.ru.md`. The maintenance cost was paid on the docs least likely to be a Russian
reader's *first* contact with the project.

## Decision
The content and instruction baseline is **English** for **all** docs. Parallel Russian translations
are maintained **only for the onboarding / first-contact surface** — `README.ru.md` and
`QUICKSTART.ru.md` — where a non-English reader decides whether the project is for them and gets
their first working setup.

**Deeper reference docs are English-only** (no `*.ru.md` sibling): `USER_GUIDE.md`,
`docs/architecture.md`, `docs/scheduling.md`, and the rest of `docs/`. The high-drift translation
surface that had already diverged is removed rather than chased.

The **digest** language stays a runtime parameter — `delivery.language` in `config/channels.yaml` —
not hardcoded. No project- or person-specific branding, consulting tone, or RU hardcoding in the core.

## Consequences
- One authoritative source language; the small onboarding surface still has tracked translations.
- Russian readers get a translated front door (README + QUICKSTART); past that, reference docs are
  English-only.
- The shipped product can still deliver **digests** in the user's language without code changes.
- Net lower maintenance: only two `*.ru.md` files must track their baseline, instead of the whole
  doc tree — eliminating the drift that had already affected `docs/scheduling.ru.md`.
- The deep RU translations (`USER_GUIDE.ru.md`, `docs/architecture.ru.md`, `docs/scheduling.ru.md`)
  are deleted; their EN baselines are now the single source.

## Alternatives considered
- **RU-hardcoded core** (the toolkit's original state) — explicitly rejected ("No … RU hardcoding
  in the core").
- **Full parallel translations of every doc** (the pre-amendment policy) — rejected: the drift cost
  outweighed the value on deep reference docs that few first-time RU readers reach.
- **English-only, no RU at all** — rejected: it loses the translated first-contact experience that
  helps a Russian reader adopt the project; the onboarding surface is cheap enough to keep in sync.

## References
- `docs/CONVENTIONS.md` §6 (Language).
- `AGENTS.md` — Mandatory rules ("Language … baseline is English").
- The maintained onboarding translations: `README.ru.md`, `QUICKSTART.ru.md`.

## Addendum (2026-07-03) — parallel translations retired; RU surface is one minimal quickstart

The "parallel full translations" part of this decision is retired. The Russian surface is now a
**single minimal `QUICKSTART.ru.md`** (what the product is, prerequisites, the shortest install
path, the Telegram bare-word caveat) that points to the English docs for everything else;
`README.ru.md` is deleted. English docs are the single source of truth.

Rationale: manual EN/RU parity was the fastest-rotting maintenance surface in the repo — even
after the 2026-06-29 narrowing to the onboarding pair, the RU quickstart had already diverged in
size from its baseline. A parity gate (CI check keeping translations in sync) would be
over-engineering for a one-maintainer project. One thin RU pointer document keeps the translated
first contact without a tracked translation surface to chase.

Earlier status history, kept for the record: Accepted (backfilled 2026-06-24); amended 2026-06-29
to narrow RU scope to onboarding; amended 2026-07-03 as above.
