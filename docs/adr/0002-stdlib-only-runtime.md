# ADR 0002 — Runtime scripts/ import only the stdlib + pyyaml

- **Status:** Accepted (backfilled 2026-06-24; amended 2026-07-12)
- **Tags:** runtime, dependencies, headless

## Context
The product ships as an unpacked archive a non-technical recipient sets up locally, and the
headless path runs from OS cron with no agent present. Any third-party runtime dependency, or a
leak of the dev toolchain into shipped code, would make that install fragile or fail outright.

## Decision
Shipped `scripts/` code imports **only the Python stdlib plus `pyyaml`**. The dev toolchain
(`uv` / `ruff` / `mypy` / `bandit` / `pytest`) is dev-only and must **never** be imported by a
runtime module. The test-driven workflow, the `make` gate, and the coverage floor are contributor
concerns and live in `DEVELOPING.md` (excluded from the shipped archive).

## Consequences
- The headless/cron install works with a stock Python — no dependency resolution at the recipient.
- Keeps the runtime/dev boundary crisp: a runtime import of a dev tool is a defect by definition.
- Constrains implementation: features that would want a third-party library must be built on the
  stdlib (or `pyyaml`) or deferred.

## Alternatives considered
Not recorded explicitly as rejected options at decision time; the rationale documented is the
positive one — a third-party runtime dependency "breaks the headless/cron install."

## References
- `AGENTS.md` — Mandatory rules ("The runtime stays stdlib-only").
- `DEVELOPING.md` — Toolchain, Test-driven workflow ("runtime-stays-stdlib-only invariant").
- `docs/CONVENTIONS.md` §7 (Tests — "Runtime stays stdlib-only except `pyyaml`").

## Addendum (2026-07-12) — "stdlib-only" retired as shorthand; the factual claim is "stdlib + PyYAML (hard)"

The "stdlib-only" shorthand (this file's name, kept for link stability, and older prose that
called PyYAML optional) is retired. The factual runtime claim — which the Decision above
already makes — is: shipped `scripts/` code imports the Python stdlib **plus PyYAML**, and
PyYAML is a **hard runtime dependency**, not an optional extra. Precisely:

- `pyproject.toml` declares it as the **only** third-party runtime dependency —
  `dependencies = ["pyyaml>=6,<7"]`, capped below the next major — declared 2026-06-22 and
  first shipped in v0.2.0. The 0.5.x releases completed the shift in practice: v0.4.1
  (2026-07-04) was the last release to describe PyYAML as staying optional; since then the
  installers create `.venv` and install it (`uv sync --no-dev`), `doctor.py` runs at install
  and treats a missing PyYAML as a wrong-interpreter fault, and `scripts/delivery/deliver.py`
  refuses to run without it — which is why every documented cron line calls
  `.venv/bin/python3` (drift-guarded by `tests/test_docs_examples.py`).
- The first Consequence above ("works with a stock Python — no dependency resolution at the
  recipient") no longer holds as written: the recipient needs Python ≥3.11 **plus PyYAML**,
  which the shipped installers resolve once, at install time, via the project venv. The
  spirit survives: exactly one small, ubiquitous dependency — never resolved at run time,
  and never a dev tool.
- Unchanged core rule: no **other** third-party runtime import, and the dev toolchain
  (`uv` / `ruff` / `mypy` / `bandit` / `pytest`) is never imported by a runtime module.
- Some modules still carry graceful no-PyYAML fallbacks (lazy `import yaml` sites),
  although the dependency is now required.

Earlier status history, kept for the record: Accepted (backfilled 2026-06-24); amended
2026-07-12 as above.
