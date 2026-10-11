#!/usr/bin/env python3
"""
run_lock.py — a single mutual-exclusion lock for the whole gated pipeline.

Why: the weekly pipeline (`schedule/weekly-run.md`) and the on-demand `run-now`
skill both drive collect → curate → synthesis → digest → deliver, and they write
the same shared state (the dedup `registry.md`, the curated `index.md` files, the
`brain/` vault). Nothing else serialises them — so a manual `run-now` fired while
the scheduled `weekly-run` is mid-flight could double-collect an article or
interleave two `brain/` writers. This lock makes "a run is already in progress" an
explicit, cheap refusal instead of a silent race.

Ownership model — important, because the real consumer is a markdown skill calling
this as a CLI: the lock is *acquired* at the start of a run and *released* at the
end, and on the CLI path those are **two separate python processes** (the agent
runs `run_lock.py acquire` … then `run_lock.py release` minutes later). So:
  - ownership is keyed on a **token** the acquirer emits (`lock-token: …`), which
    the skill threads to `release --token …` — NOT on the ephemeral python pid;
  - staleness is **time-based** (a lease), because the acquiring process exits
    immediately while the logical run keeps going — pid-liveness is the wrong
    signal here. Dead-pid stealing is an opt-in extra (`steal_dead=True`) used
    only by the in-process `run_lock(...)` context manager, where one long-lived
    process holds the lock for its lifetime and a dead pid really means a crash.
    It applies **only to a holder on our own host**: a pid means nothing on
    another machine, so on a shared `RESEARCH_BRAIN_STATE_DIR` a foreign holder
    is freed by its lease alone (`_holder_pid_is_dead_here`).

Design (stdlib only, best-effort, tolerant — matching health.py's spirit):
  - the lock is a single JSON file (default `pipeline/.run.lock`, gitignored);
  - `acquire` creates it atomically AND with its payload already in place
    (`_exclusive_create`: stage a temp file, publish with `os.link`), so the
    lockfile is never observable as an empty — and therefore "corrupt",
    therefore stealable — file; an existing lock is stolen only when dead (lease
    expired, opt-in same-host dead-pid, or corrupt file), otherwise acquisition
    is refused and the caller stops;
  - `release` removes the lock when the token (or owner pid, or `force`) matches.

`acquire` takes injectable `now`, `pid`, `host`, `token`, and `is_alive` so callers
and tests stay deterministic.

Reclaim (steal) race-safety — reclaiming a dead/stale/corrupt lock runs under a short-lived
`O_EXCL` reclaim-mutex sentinel and swaps the lockfile with `os.replace`, which is atomic
and NEVER leaves the path absent. So a reclaim is: (1) take the `.reclaiming` mutex via
`O_CREAT | O_EXCL` (only one reclaimer wins; the rest concede); (2) re-read the lock under
the mutex and confirm it is still the EXACT one we judged stale (same token+ts, or
still-corrupt) — if a competitor changed it first, concede without touching it; (3)
`os.replace` our fresh lock over it. Because `path` always holds a file (stale, then ours,
via the atomic swap), a concurrent fast-path create always sees a file and fails —
so a fast-path acquirer and a reclaimer can't both win. This closes both the original CAS
hole (two reclaimers re-reading their own writes) and the empty-window hole (a rename-based
reclaim briefly leaving `path` absent for a fast-path acquirer to slip into). A leaked mutex
(only possible if a holder is hard-killed inside the microsecond critical section) is
self-healed by a 60s staleness check.

Residual, honestly: on a filesystem without hardlink support the fast path falls back to
`O_EXCL`-then-write, which restores the (microsecond) empty-file window — the atomic form
is simply unavailable there. Everything else above still holds.

`release` is no-clobber: a release we do NOT own is a pure no-op (we read first and never
touch the file), and a release we DO own renames the lockfile aside (atomic snapshot) and
re-verifies ownership before unlinking — so the old read-check-unlink window is gone. In the
rare case our lease expired and a successor reclaimed in the read→rename gap, we restore that
successor with `O_CREAT | O_EXCL`, so a brand-new acquirer that grabbed the freed slot is
never overwritten.

Residual caveats (honest about what this lock does NOT do):
  - **The lease needs an explicit heartbeat for very long runs.** Staleness is a
    fixed time window; a run that exceeds `stale_after` without refreshing can have
    its lock reclaimed mid-flight. `renew(token=…)` (CLI `renew`) pushes the lease
    forward, so a long agentic run should heartbeat between stages (see
    `schedule/weekly-run.md`). A crashed run still holds the lock only until the
    lease expires.
  - **Only the orchestrators take this lock.** `weekly-run` and `run-now` acquire it;
    the standalone `collect` / `curate` / `synthesis` steps do NOT, so running one of
    those directly is not serialised against an orchestrated run.

CLI (weekly-run Step 0 / run-now — exit 1 from `acquire` means "refused, a run is
in progress", so the skill stops on a non-zero exit):
    python3 scripts/run_lock.py acquire            # exit 0 (prints lock-token:), exit 1 held
    python3 scripts/run_lock.py release --token T   # release the run we acquired
    python3 scripts/run_lock.py status
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# The durable-state resolver — same one deliver.py routes its `.delivery.lock`
# through. The run lock is runtime state (gitignored, like the health log and the
# delivery receipts), so on a persistent-volume deployment it must follow that
# state onto the volume; otherwise the lock and the registry/state it guards could
# land on DIFFERENT filesystems, where os.replace/os.rename are no longer atomic
# (the lock's whole correctness model depends on same-FS atomic swaps). Package /
# standalone import dance mirrors the sibling scripts.
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.state import state_root as _state_root  # noqa: E402 — after the direct-run prelude

# Default lock location — runtime state, gitignored like the health log / receipts.
# This is the env-UNSET (in-repo) default; live callers should prefer
# `default_lock_path()` so a deployment's RESEARCH_BRAIN_STATE_DIR is honored.
DEFAULT_LOCK_PATH = _PROJECT_ROOT / "pipeline" / ".run.lock"


def default_lock_path() -> Path:
    """The default run-lock path, resolved at CALL time (honors the env lazily).

    Routes the in-repo `pipeline/.run.lock` through the durable-state resolver, so
    with `RESEARCH_BRAIN_STATE_DIR` unset this is the exact in-repo default
    (byte-for-byte identity) and with it set the lock relocates onto the persistent
    volume — co-located with the registry/health state it serializes, keeping the
    os.replace/os.rename swaps same-filesystem atomic. Resolved per call (never
    frozen at import) so an env wired AFTER import is still honored.
    """
    return _state_root(DEFAULT_LOCK_PATH, project_root=_PROJECT_ROOT)

# A weekly run is minutes, not hours; 6h is a generous lease past which a lock is
# assumed orphaned (process/agent died without releasing) and may be reclaimed.
DEFAULT_STALE_AFTER = 6 * 3600


class Reason(str, Enum):
    """Why `acquire` returned the result it did."""

    ACQUIRED = "acquired"              # clean create, no prior lock
    HELD = "held"                      # a fresh lease → refused
    STOLEN_STALE = "stolen-stale"      # prior lease exceeded stale_after
    STOLEN_DEAD = "stolen-dead"        # prior holder pid dead (opt-in steal_dead)
    STOLEN_CORRUPT = "stolen-corrupt"  # prior lockfile unreadable → reclaimed


@dataclass(frozen=True)
class LockInfo:
    """The contents of a lockfile."""

    pid: int
    ts: float
    host: str
    token: str = ""
    note: str = ""


@dataclass(frozen=True)
class AcquireResult:
    """Outcome of an `acquire` attempt."""

    acquired: bool
    reason: Reason
    token: str = ""                     # the token to pass back to `release`
    holder_pid: int | None = None    # set when refused (HELD): who holds it
    holder_age: float | None = None  # seconds since the holder's timestamp


class LockHeldError(RuntimeError):
    """Raised by the `run_lock` context manager when the lock is already held."""

    def __init__(self, result: AcquireResult) -> None:
        self.result = result
        age = "" if result.holder_age is None else f" (age {result.holder_age:.0f}s)"
        super().__init__(f"run lock held by pid {result.holder_pid}{age}")


def is_pid_alive(pid: int) -> bool:
    """True if a process with `pid` currently exists.

    POSIX uses the signal-0 probe (a `PermissionError` means the process exists
    but is owned by another user — still alive). On Windows `os.kill(pid, 0)` would
    *terminate* the process, so a separate non-destructive probe is used instead.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _win_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _win_pid_alive(pid: int) -> bool:  # pragma: no cover - exercised only on Windows
    """Non-destructive Windows liveness probe via OpenProcess (no TerminateProcess).

    Opens the process for limited query; a valid handle whose exit code is still
    STILL_ACTIVE means alive. ERROR_ACCESS_DENIED means the process exists but is
    owned by another account — alive for our purposes, matching the POSIX branch.
    """
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]  # Windows-only API
    # Proper signatures: a HANDLE is pointer-sized, so the default int restype
    # would truncate it on 64-bit Windows and break CloseHandle.
    open_process = kernel32.OpenProcess
    open_process.restype = wintypes.HANDLE
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    get_exit_code = kernel32.GetExitCodeProcess
    get_exit_code.restype = wintypes.BOOL
    get_exit_code.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)

    handle = open_process(process_query_limited_information, False, pid)
    if not handle:
        # No handle: access-denied means it exists but isn't ours (alive); any
        # other error (e.g. invalid parameter) means there is no such process.
        return ctypes.get_last_error() == error_access_denied  # type: ignore[attr-defined]  # Windows-only API
    try:
        code = wintypes.DWORD()
        if get_exit_code(handle, ctypes.byref(code)):
            return code.value == still_active
        return True  # couldn't read the exit code — assume alive (don't reclaim)
    finally:
        close_handle(handle)


def read_lock(path: Path) -> LockInfo | None:
    """Parse a lockfile, or None if it is missing or unreadable/corrupt."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        data = json.loads(raw)
        return LockInfo(
            pid=int(data["pid"]),
            ts=float(data["ts"]),
            host=str(data.get("host", "")),
            token=str(data.get("token", "")),
            note=str(data.get("note", "")),
        )
    except (ValueError, KeyError, TypeError):
        return None


def _payload(info: LockInfo) -> str:
    return json.dumps(
        {
            "pid": info.pid,
            "ts": info.ts,
            "host": info.host,
            "token": info.token,
            "note": info.note,
        }
    )


def _held_result(survivor: LockInfo | None) -> AcquireResult:
    """A `Reason.HELD` refusal naming the current holder (or None if it vanished)."""
    return AcquireResult(
        acquired=False,
        reason=Reason.HELD,
        holder_pid=survivor.pid if survivor is not None else None,
        holder_age=None,
    )


def _matches_expected(aside: LockInfo | None, expected: LockInfo | None) -> bool:
    """True when the moved-aside lock is still the exact one we judged reclaimable.

    For a parseable stale/dead holder we require the same token AND timestamp (a
    refreshed lease would change `ts`). For a corrupt holder (`expected is None`)
    we require it to STILL be corrupt — if it now parses, someone wrote a valid
    lock between our read and our rename, so it is no longer ours to take.
    """
    if expected is None:
        return aside is None
    return aside is not None and aside.token == expected.token and aside.ts == expected.ts


# A reclaim's critical section is microseconds (a re-read + an atomic replace), so a
# reclaim-mutex sentinel older than this can only have leaked (a hard kill mid-reclaim)
# and is self-healed. Far below the run lease, so it never collides with a real reclaim.
_RECLAIM_MUTEX_STALE = 60.0


def _acquire_reclaim_mutex(mutex: Path, now: float) -> bool:
    """Take the short-lived O_EXCL sentinel that serialises reclaimers.

    Returns True iff we created it. A *leaked* sentinel (older than
    `_RECLAIM_MUTEX_STALE` — only possible if a holder was hard-killed inside the
    microsecond critical section) is unlinked and the create retried once.
    """
    for _attempt in (1, 2):
        try:
            fd = os.open(str(mutex), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                age = now - float(mutex.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return False  # unreadable/garbage but present → treat as held
            if age < _RECLAIM_MUTEX_STALE:
                return False  # a live reclaim is in progress → concede
            mutex.unlink(missing_ok=True)  # self-heal a leaked sentinel, then retry
            continue
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(str(now))
            return True
    return False


def _exclusive_create(
    path: Path,
    info: LockInfo,
    *,
    mid_create: Callable[[], None] | None = None,
) -> bool:
    """Atomically create `path` already holding `info`'s payload. False if it exists.

    The lockfile must never be observable EMPTY. The obvious form — `O_EXCL`
    create, then write the JSON — publishes a zero-byte file for the duration of
    the write, and a competitor arriving in that window reads it as *corrupt* and
    reclaims it while the creator still returns `acquired`. Two winners.

    So the payload is written to a private temp file first and published with
    `os.link`, which is atomic and fails when the target exists — exclusivity and
    content in a single step, leaving no window to observe.

    `mid_create` is a test-only injection fired at the moment of maximum exposure
    (payload staged, not yet published), so the race can be driven deterministically.
    """
    tmp = path.with_name(f"{path.name}.new.{info.token}")
    try:
        # Inside the try so a failed/partial write (full disk) still cleans up its
        # temp file rather than littering the state dir with orphans.
        tmp.write_text(_payload(info), encoding="utf-8")
        if mid_create is not None:
            mid_create()
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        except OSError:
            # No hardlink support (some network/FAT mounts; Windows without the
            # privilege). Degrade to the plain O_EXCL create rather than fail: the
            # empty-file window returns, but only where the atomic form is impossible.
            return _exclusive_create_unlinked(path, info)
        return True
    finally:
        tmp.unlink(missing_ok=True)


def _exclusive_create_unlinked(path: Path, info: LockInfo) -> bool:
    """Fallback create for filesystems without `os.link` (see `_exclusive_create`)."""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(_payload(info))
    return True


def _reclaim(
    path: Path,
    info: LockInfo,
    expected: LockInfo | None,
    reason: Reason,
    now: float,
    *,
    after_read: Callable[[], None] | None = None,
) -> AcquireResult:
    """Reclaim a reclaimable lock under a serialising mutex, with no empty window.

    `expected` is the lock we read and judged dead/stale/corrupt. We take a short-lived
    O_EXCL reclaim-mutex (so only one reclaimer runs at a time), re-read `path` under it,
    confirm it is still `expected` (else a competitor changed it → concede), then
    `os.replace` our fresh lock over it. `os.replace` is atomic and NEVER leaves `path`
    absent, so a concurrent fast-path `O_EXCL` always sees a file and fails — closing the
    empty-window race where a fast-path acquirer and a reclaimer could both win.

    `after_read` is a test-only injection fired before we take the mutex, to simulate a
    competitor that fully runs between our staleness decision and our reclaim.
    """
    if after_read is not None:
        after_read()

    mutex = path.with_name(path.name + ".reclaiming")
    if not _acquire_reclaim_mutex(mutex, now):
        return _held_result(read_lock(path))
    try:
        current = read_lock(path)
        if not _matches_expected(current, expected):
            # Changed since our staleness decision (a competitor reclaimed/refreshed
            # it) → it is no longer ours to take. Leave it untouched and concede.
            return _held_result(current)
        tmp = path.with_name(path.name + f".tmp.{info.token}")
        try:
            tmp.write_text(_payload(info), encoding="utf-8")
            os.replace(tmp, path)  # atomic swap — no moment where `path` is absent
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return AcquireResult(acquired=True, reason=reason, token=info.token)
    finally:
        mutex.unlink(missing_ok=True)


def acquire(
    path: Path = DEFAULT_LOCK_PATH,
    *,
    stale_after: float = DEFAULT_STALE_AFTER,
    pid: int | None = None,
    now: float | None = None,
    host: str | None = None,
    token: str | None = None,
    note: str = "",
    steal_dead: bool = False,
    is_alive: Callable[[int], bool] = is_pid_alive,
    _after_steal_read: Callable[[], None] | None = None,
    _mid_create: Callable[[], None] | None = None,
) -> AcquireResult:
    """Try to take the run lock.

    Acquires cleanly if the lockfile doesn't exist. If it does, steals it only
    when the holder is dead — lease expired (`age >= stale_after`), opt-in dead
    pid on THIS host (`steal_dead`), or corrupt file — otherwise refuses with
    `Reason.HELD` and reports the holder. The returned `token` must be passed
    back to `release` (cross-process ownership).
    """
    pid = os.getpid() if pid is None else pid
    now = time.time() if now is None else now
    host = socket.gethostname() if host is None else host
    token = secrets.token_hex(8) if token is None else token
    info = LockInfo(pid=pid, ts=now, host=host, token=token, note=note)

    path.parent.mkdir(parents=True, exist_ok=True)

    # Fast path: atomic exclusive create, payload included. Wins if no lock exists.
    if _exclusive_create(path, info, mid_create=_mid_create):
        return AcquireResult(acquired=True, reason=Reason.ACQUIRED, token=token)

    # A lock already exists — decide whether it is reclaimable. Each reclaim goes
    # through `_reclaim`, serialised on `os.rename`, so two concurrent reclaimers
    # can't both succeed: only the one that wins the rename (and still sees the
    # expected stale lock) recreates and returns `acquired`.
    holder = read_lock(path)
    if holder is None:
        return _reclaim(path, info, None, Reason.STOLEN_CORRUPT, now, after_read=_after_steal_read)

    age = now - holder.ts
    if age >= stale_after:
        return _reclaim(path, info, holder, Reason.STOLEN_STALE, now, after_read=_after_steal_read)
    if steal_dead and _holder_pid_is_dead_here(holder, host, is_alive):
        return _reclaim(path, info, holder, Reason.STOLEN_DEAD, now, after_read=_after_steal_read)

    return AcquireResult(
        acquired=False,
        reason=Reason.HELD,
        holder_pid=holder.pid,
        holder_age=age,
    )


def _holder_pid_is_dead_here(
    holder: LockInfo,
    host: str,
    is_alive: Callable[[int], bool],
) -> bool:
    """True only when we can PROVE the holder's process is gone — same host, no pid.

    A pid is meaningful solely on the machine that issued it. With a shared
    `RESEARCH_BRAIN_STATE_DIR` (two pods on one volume) our process table knows
    nothing about the other host's pids: a foreign pid reads as "dead" — or,
    worse, collides with an unrelated local process — so trusting it would let a
    second host seize a LIVE holder's lock instantly instead of waiting out the
    lease. A holder from another host, or one with no recorded host (an older
    writer), is therefore never dead-pid stealable; only its lease can free it.
    """
    if not holder.host or holder.host != host:
        return False
    return not is_alive(holder.pid)


def _owns(holder: LockInfo | None, token: str | None, pid: int | None) -> bool:
    """True when `holder` is ours by matching token (CLI) or owner pid (in-process)."""
    if holder is None:
        return False
    return (token is not None and holder.token == token) or (
        pid is not None and holder.pid == pid
    )


def release(
    path: Path = DEFAULT_LOCK_PATH,
    *,
    token: str | None = None,
    pid: int | None = None,
    force: bool = False,
) -> bool:
    """Remove the lockfile when we own it. Returns True if removed.

    Ownership is proven by matching `token` (cross-process CLI flow), or by
    matching the owner `pid` (in-process context manager), or `force`.

    Race-safe with no clobber window:
      - A release we do NOT own is a pure no-op — we read first and, if it isn't
        ours, return without touching the file at all. (Moving a non-owned lock
        aside and restoring it could clobber a third process that acquired in the
        gap — the prior bug.)
      - A release we DO own renames the lockfile aside (atomic snapshot) and
        verifies ownership on the moved copy before unlinking, closing the old
        read-check-unlink window. In the rare case our lease expired and a
        successor reclaimed between our read and our rename, we restore that
        successor with `O_CREAT | O_EXCL` so a brand-new acquirer that took the
        freed slot is never overwritten.
    """
    if not force and not _owns(read_lock(path), token, pid):
        return False  # not ours (or nothing there) — never touch the file

    aside = path.with_name(f"{path.name}.release.{os.getpid()}.{secrets.token_hex(4)}")
    try:
        os.rename(path, aside)
    except FileNotFoundError:
        return False  # nothing to release

    moved = read_lock(aside)
    if force or _owns(moved, token, pid):
        Path(aside).unlink(missing_ok=True)
        return True

    # Our lease expired and a successor reclaimed in the read→rename gap, so what we
    # moved is the successor's lock — not ours to remove. Put it back WITHOUT
    # clobbering any fresh acquirer that grabbed the freed slot: O_EXCL recreate, and
    # if that loses the race the new acquirer rightfully keeps the lock.
    if moved is not None:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            pass  # a new acquirer already owns the freed slot → leave it to them
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(_payload(moved))
    Path(aside).unlink(missing_ok=True)
    return False


def renew(
    path: Path = DEFAULT_LOCK_PATH,
    *,
    token: str | None = None,
    pid: int | None = None,
    now: float | None = None,
) -> bool:
    """Refresh the lease timestamp of a lock we own; returns True if refreshed.

    The lease is a fixed `stale_after` window, so a long agentic run can outlive it
    and have its lock reclaimed mid-flight. A heartbeat — calling `renew` between
    stages — pushes the lease forward so an active run keeps its lock. Ownership is
    by `token` (cross-process CLI) or owner `pid` (in-process).

    Race-safe: runs under the same reclaim mutex and atomic `os.replace` as
    `_reclaim`, so it never corrupts the file or fights a concurrent reclaimer, and
    only bumps the timestamp if the lock is still ours.
    """
    now = time.time() if now is None else now
    mutex = path.with_name(path.name + ".reclaiming")
    if not _acquire_reclaim_mutex(mutex, now):
        return False  # a reclaim is in progress — caller may retry
    try:
        holder = read_lock(path)
        if holder is None or not _owns(holder, token, pid):
            return False
        refreshed = LockInfo(
            pid=holder.pid, ts=now, host=holder.host,
            token=holder.token, note=holder.note,
        )
        tmp = path.with_name(f"{path.name}.tmp.{holder.token}")
        try:
            tmp.write_text(_payload(refreshed), encoding="utf-8")
            os.replace(tmp, path)  # atomic swap — no empty window
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return True
    finally:
        mutex.unlink(missing_ok=True)


@contextmanager
def run_lock(
    path: Path = DEFAULT_LOCK_PATH,
    *,
    stale_after: float = DEFAULT_STALE_AFTER,
    pid: int | None = None,
    now: float | None = None,
    host: str | None = None,
    note: str = "",
    is_alive: Callable[[int], bool] = is_pid_alive,
) -> Iterator[AcquireResult]:
    """Context manager for a long-lived Python holder.

    Acquires on enter (raising `LockHeldError` if held), releases on exit. Uses
    `steal_dead=True` since a single process owns the lock for its lifetime, so a
    dead holder pid genuinely means a crashed run.
    """
    pid = os.getpid() if pid is None else pid
    result = acquire(
        path,
        stale_after=stale_after,
        pid=pid,
        now=now,
        host=host,
        note=note,
        steal_dead=True,
        is_alive=is_alive,
    )
    if not result.acquired:
        raise LockHeldError(result)
    try:
        yield result
    finally:
        release(path, token=result.token, pid=pid)


# ── CLI ──────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Single run lock for the gated pipeline (weekly-run / run-now)."
    )
    sub = parser.add_subparsers(dest="command")

    def _add_lock(p: argparse.ArgumentParser) -> None:
        # Resolve the default at parse time so RESEARCH_BRAIN_STATE_DIR relocates the
        # lock onto the persistent volume (co-located with the state it guards).
        p.add_argument("--lock", default=str(default_lock_path()), help="Lockfile path.")

    p_acq = sub.add_parser("acquire", help="Take the lock (exit 1 if already held).")
    _add_lock(p_acq)
    p_acq.add_argument("--pid", type=int, default=None, help="Override pid (testing).")
    p_acq.add_argument("--now", type=float, default=None, help="Override clock (testing).")
    p_acq.add_argument("--token", default=None, help="Override token (testing).")
    p_acq.add_argument(
        "--stale-after", type=float, default=DEFAULT_STALE_AFTER,
        help="Seconds after which a held lock is treated as an orphaned lease.",
    )
    p_acq.add_argument("--note", default="", help="Free-text note stored in the lock.")

    p_rel = sub.add_parser("release", help="Release the lock we acquired.")
    _add_lock(p_rel)
    p_rel.add_argument("--token", default=None, help="The token printed by acquire.")
    p_rel.add_argument("--force", action="store_true", help="Release regardless of owner.")

    p_renew = sub.add_parser("renew", help="Refresh the lease of a lock we hold (heartbeat).")
    _add_lock(p_renew)
    p_renew.add_argument("--token", default=None, help="The token printed by acquire.")
    p_renew.add_argument("--now", type=float, default=None, help="Override clock (testing).")

    p_st = sub.add_parser("status", help="Print the current lock holder, if any.")
    _add_lock(p_st)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "acquire":
        res = acquire(
            Path(args.lock),
            stale_after=args.stale_after,
            pid=args.pid,
            now=args.now,
            token=args.token,
            note=args.note,
        )
        if res.acquired:
            print(f"OK: run lock acquired ({res.reason.value}).")
            print(f"lock-token: {res.token}")
            return 0
        # holder_pid/holder_age can be None (e.g. a corrupt lockfile while a
        # competitor holds the reclaim mutex) — render "unknown" instead of
        # crashing on formatting None.
        holder = "an unknown holder" if res.holder_pid is None else f"pid {res.holder_pid}"
        age = "" if res.holder_age is None else f" (age {res.holder_age:.0f}s)"
        print(f"REFUSED: a run is already in progress — held by {holder}{age}. Skip this run.")
        return 1

    if args.command == "release":
        removed = release(Path(args.lock), token=args.token, force=args.force)
        print("OK: run lock released." if removed else "NOTE: no matching lock to release.")
        return 0

    if args.command == "renew":
        refreshed = renew(Path(args.lock), token=args.token, now=args.now)
        print("OK: lease refreshed." if refreshed else "NOTE: no matching lock to renew.")
        return 0 if refreshed else 1

    if args.command == "status":
        info = read_lock(Path(args.lock))
        if info is None:
            print("free: no run lock held.")
        else:
            print(
                f"held: pid {info.pid} on {info.host} (ts {info.ts:.0f}) {info.note}".rstrip()
            )
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
