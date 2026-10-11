# ADR 0011 — Native Windows support via cross-platform concurrency primitives

- **Status:** Accepted (2026-06-24)
- **Tags:** platform, windows, concurrency, distribution

## Context
The product targets **non-technical** users, but the runtime was POSIX-only: the registry
serialised concurrent writes with `fcntl.flock` (Unix-only, imported by ~12 scripts), and the
run-lock's stale-owner check used `os.kill(pid, 0)` — which on Windows *terminates* the target
process instead of probing it. The documented answer was "use WSL", but installing WSL is a real
barrier for a non-technical Windows user, conflicting with the day-one-value goal.

## Decision
Support **native Windows** by making the two concurrency primitives platform-dispatched, while
keeping the runtime stdlib-only (see [ADR 0002](0002-stdlib-only-runtime.md)):
- **Registry lock** (`registry._select_flock`) — `fcntl.flock` on POSIX, `msvcrt.locking` on
  Windows. The platform-specific import lives inside the chosen branch so `import registry`
  works on every OS.
- **Process liveness** (`run_lock.is_pid_alive`) — `os.kill(pid, 0)` on POSIX; a non-destructive
  `OpenProcess`/`GetExitCodeProcess` ctypes probe on Windows.
- Ship `install.ps1` (PowerShell counterpart of `install.sh`) and document Task Scheduler as the
  cron equivalent (`docs/scheduling.md`).

## Consequences
- Windows users run the product natively (`.\install.ps1`); WSL remains an option, not a
  requirement.
- The POSIX code paths are **unchanged** — zero regression risk for existing macOS/Linux users.
- The Windows code paths are **best-effort**: CI runs on POSIX only, so they are unit-tested by
  dispatch/mock here and must be smoke-tested on a real Windows box before relying on them.
- A small ongoing cost: any future OS-specific syscall must be added behind the same dispatch.

## Alternatives considered
- **WSL-only (status quo).** Rejected — the WSL install/copy dance is a barrier for the
  non-technical Windows audience the product is built for.
- **Replace `flock` with an `O_CREAT|O_EXCL` lockfile everywhere** (one code path, like
  `run_lock.py`). Rejected — it would change the proven POSIX behavior and reintroduce stale-lock
  handling that `flock` gives for free (auto-release on fd close / process death).

## References
- `scripts/registry.py` — `_select_flock` (fcntl/msvcrt dispatch).
- `scripts/run_lock.py` — `is_pid_alive` / `_win_pid_alive`.
- `install.ps1`; `docs/scheduling.md` § "B (Windows). Task Scheduler".
- `README.md` → "Platform"; builds on [ADR 0002](0002-stdlib-only-runtime.md).
