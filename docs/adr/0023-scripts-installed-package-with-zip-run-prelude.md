# ADR 0023 — `scripts` installs as a real package; the zip-run contract survives via one canonical prelude

- **Status:** accepted (2026-07-14)
- **Relates to:** [ADR 0002](0002-stdlib-only-runtime.md) (runtime dependency floor),
  [ADR 0004](0004-zip-handoff-not-marketplace.md) (zip distribution),
  [ADR 0021](0021-stable-script-facades-over-domain-packages.md) (facade layout)

## Context

Until 0.8.0 the project declared `[tool.uv] package = false` — "an application run
in-place, not a distributable library". The cost of that stance grew with the tree:
`scripts` was importable only through `sys.path` mutation, so the idiom metastasized
into ~80 copies — one per test file, one per CLI, plus 13 `try: from .x import …
except ImportError: import x` fallback dances so delivery/search modules survived
being run as bare files. Every dance meant a module could load as TWO copies
(`scripts.delivery.quiet` *and* top-level `quiet`), which is exactly how
monkeypatching and isinstance checks go subtly wrong.

Two contracts had to survive any change:

1. **The zip-run contract (ADR 0004):** every documented `python3 scripts/X.py`
   invocation — including bare `/usr/bin/python3` for the stdlib-only tools
   (`version.py` in update.sh's preflight, `schema.py migrate-config`) — works on an
   unpacked archive with ZERO installation.
2. **The documented CLI surface is frozen:** cron lines, skills, and docs all spell
   `python3 scripts/…` paths; nothing may require retraining users onto `-m` forms.

## Decision

1. **The project installs itself.** `pyproject.toml` gains a hatchling build backend
   and `packages = ["scripts"]`; `uv sync` (already run by `install.sh` and CI)
   installs the project **editable** into the venv. Any venv interpreter imports
   `scripts.*` from any cwd — tests, subprocesses, tools, no path help.
2. **One canonical prelude, only in directly-runnable CLIs:**

   ```python
   if not __package__:  # direct script run (zip-run, no install)
       sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
   ```

   It fires only when the file is executed as a bare script (`python3 scripts/X.py`
   on an uninstalled tree) and is skipped on every import (venv, console scripts,
   tests). Internal modules carry **no** path logic and **no** import dances — plain
   relative/absolute imports, one module identity.
3. **Console scripts are additive.** `rb-collect`, `rb-digest`, `rb-deliver`,
   `rb-doctor`, `rb-health`, `rb-setup-check`, `rb-sanitize`, `rb-trends` appear on
   the venv PATH. The `python3 scripts/X.py` spelling stays canonical in docs.

## Consequences

- ~80 path-mutation sites collapse to 33 uniform guarded preludes (CLIs only);
  the 13 fallback dances are gone; each module has exactly one import identity.
- `uv sync` now needs the hatchling backend at install time (fetched like any
  locked dependency; requirements exports keep `--no-emit-project`).
- The drift guards live in `tests/test_packaging.py`: venv-wide import from a
  neutral cwd, the console-script table, no path hacks in tests (AST-based), and
  every runtime `sys.path.insert` confined to the canonical prelude shape.
- Bare-interpreter support still means the **documented floor** (Python 3.11+):
  e.g. macOS's Xcode python3.9 runs `version.py`/`schema.py` but not the
  collect→health import chain (`datetime.UTC`) — unchanged by this ADR.
