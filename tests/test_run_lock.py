"""Tests for scripts/run_lock.py — the single weekly-run mutual-exclusion lock.

The lock guards the whole gated pipeline (weekly-run / run-now) so a manual
run-now and the scheduled weekly-run can't interleave writes to the registry,
curated indexes, or brain/.

Ownership model (learned from the real consumer): the lock is taken at the start
of a run and released at the end, and in the CLI flow those are TWO SEPARATE
python processes (an agent runs `run_lock.py acquire` … then `run_lock.py
release` minutes later). So ownership is keyed on a **token** the acquirer emits,
not on the ephemeral python pid — and staleness is **time-based**, because the
acquiring process exits immediately while the logical run continues. Dead-pid
stealing is an opt-in extra, useful only for the in-process context manager where
one long-lived process holds the lock for its lifetime.

`acquire` takes injectable `now`, `pid`, `host`, `token`, and `is_alive` so the
tests stay deterministic.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from scripts import run_lock as rl


def _lock(tmp_path: Path) -> Path:
    return tmp_path / ".run.lock"


def test_acquire_clean_creates_lockfile(tmp_path):
    path = _lock(tmp_path)
    res = rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)

    assert res.acquired is True
    assert res.reason is rl.Reason.ACQUIRED
    assert res.token == "tok-a"
    assert path.exists()
    info = rl.read_lock(path)
    assert info is not None
    assert info.pid == 111
    assert info.ts == 1000.0
    assert info.token == "tok-a"


def test_acquire_emits_a_token_when_not_supplied(tmp_path):
    res = rl.acquire(_lock(tmp_path), pid=111, now=1000.0, stale_after=3600)
    assert res.acquired is True
    assert isinstance(res.token, str) and res.token  # non-empty


def test_acquire_blocked_by_fresh_holder(tmp_path):
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)

    # Another run tries 10s later; the lease is still fresh → refused. Liveness
    # of the (already-exited) acquirer pid is irrelevant on the CLI path.
    res = rl.acquire(path, pid=222, now=1010.0, host="h2", token="tok-b", stale_after=3600)

    assert res.acquired is False
    assert res.reason is rl.Reason.HELD
    assert res.holder_pid == 111
    assert rl.read_lock(path).token == "tok-a"  # original holder untouched


def test_acquire_steals_time_stale_lock(tmp_path):
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)

    # Two hours later — past the 1h lease — the orphaned lock is reclaimed.
    res = rl.acquire(path, pid=222, now=1000.0 + 7200, host="h2", token="tok-b", stale_after=3600)

    assert res.acquired is True
    assert res.reason is rl.Reason.STOLEN_STALE
    assert rl.read_lock(path).token == "tok-b"


def test_stale_lock_reclaimed_then_rerun_can_acquire_without_manual_delete(tmp_path):
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)

    res = rl.acquire(path, pid=222, now=1000.0 + 3601, host="h2", token="tok-b", stale_after=3600)

    assert res.acquired is True
    assert res.reason is rl.Reason.STOLEN_STALE
    assert rl.read_lock(path).token == "tok-b"
    assert path.exists()


def test_acquire_steals_dead_holder_when_steal_dead(tmp_path):
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)

    # In-process context-manager scenario: a fresh lease but the holder process
    # crashed (pid dead). Opt-in steal_dead reclaims it without waiting for the
    # lease. Same host, because a pid is only meaningful on the host that owns it.
    res = rl.acquire(
        path, pid=222, now=1010.0, host="h1", token="tok-b", stale_after=3600,
        steal_dead=True, is_alive=lambda _pid: False,
    )

    assert res.acquired is True
    assert res.reason is rl.Reason.STOLEN_DEAD
    assert rl.read_lock(path).token == "tok-b"


# ── a pid is only meaningful on its own host ──────────────────────────────────
#
# External review 2026-07-25 P1: `steal_dead` consulted `is_alive(holder.pid)`
# without ever comparing `holder.host`. On a shared RESEARCH_BRAIN_STATE_DIR (two
# pods/hosts, one volume) the second host's process table cannot answer anything
# about the first host's pid — an unrelated-or-absent pid reads as "dead", so a
# LIVE holder's lock is taken instantly instead of waiting out the lease. The
# delivery lock runs with steal_dead=True (mcp_receipts.record_mcp), so this is
# the double-delivery path, not a theoretical one.


def test_acquire_refuses_dead_pid_steal_from_another_host(tmp_path):
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="hostA", token="tok-a", stale_after=3600)

    # hostB asks ITS OWN process table about pid 111 and hears "no such process".
    # That is not evidence about hostA — the lease is the only valid signal here.
    res = rl.acquire(
        path, pid=222, now=1010.0, host="hostB", token="tok-b", stale_after=3600,
        steal_dead=True, is_alive=lambda _pid: False,
    )

    assert res.acquired is False, "a cross-host holder must wait out the lease"
    assert res.reason is rl.Reason.HELD
    assert rl.read_lock(path).token == "tok-a"  # live holder untouched


def test_acquire_refuses_dead_pid_steal_when_holder_host_is_unknown(tmp_path):
    """A lock with no recorded host (an older writer) is not stealable by pid.

    We cannot prove the pid belongs to us, so the fail-safe answer is to fall
    back to the lease rather than guess.
    """
    path = _lock(tmp_path)
    path.write_text('{"pid": 111, "ts": 1000.0, "token": "tok-a"}', encoding="utf-8")

    res = rl.acquire(
        path, pid=222, now=1010.0, host="hostB", token="tok-b", stale_after=3600,
        steal_dead=True, is_alive=lambda _pid: False,
    )

    assert res.acquired is False
    assert res.reason is rl.Reason.HELD


def test_cross_host_lock_is_still_reclaimed_once_the_lease_expires(tmp_path):
    """The host check must not make a genuinely orphaned cross-host lock permanent."""
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="hostA", token="tok-a", stale_after=3600)

    res = rl.acquire(
        path, pid=222, now=1000.0 + 3601, host="hostB", token="tok-b", stale_after=3600,
        steal_dead=True, is_alive=lambda _pid: False,
    )

    assert res.acquired is True
    assert res.reason is rl.Reason.STOLEN_STALE


# ── the fast-path create must never publish an empty lockfile ─────────────────
#
# External review 2026-07-25 P1: the fast path created the file with
# `O_CREAT|O_EXCL` and wrote the JSON payload as a SEPARATE step. A competitor
# arriving in that window read a zero-byte file, parsed it as corrupt, and
# reclaimed it — while the original creator went on to return acquired=True.
# Two winners, both believing they hold the lock.


def test_concurrent_acquire_during_create_yields_exactly_one_winner(tmp_path):
    """Drive a competitor into the middle of our create and demand one winner."""
    path = _lock(tmp_path)
    competitor: list[rl.AcquireResult] = []

    def midway() -> None:
        # Fires while our own create is in flight — the exact interleaving that
        # used to produce two owners.
        competitor.append(
            rl.acquire(
                path, pid=222, now=1000.0, host="h2", token="tok-b", stale_after=3600
            )
        )

    ours = rl.acquire(
        path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600,
        _mid_create=midway,
    )

    winners = [res for res in [ours, *competitor] if res.acquired]
    assert len(winners) == 1, (
        f"exactly one acquirer may win; got {[(w.token, w.reason) for w in winners]}"
    )
    # Whoever won, the file on disk must be theirs and must be parseable.
    survivor = rl.read_lock(path)
    assert survivor is not None, "the lockfile must never be left empty/corrupt"
    assert survivor.token == winners[0].token


def test_fast_path_lockfile_is_never_observable_empty(tmp_path):
    """The published lock parses the instant it exists — no empty window at all."""
    path = _lock(tmp_path)
    observed: list[str | None] = []

    def midway() -> None:
        # Mid-create, the path either does not exist yet or already holds the
        # full payload; a zero-byte file is what the race fed on.
        observed.append(path.read_text(encoding="utf-8") if path.exists() else None)

    rl.acquire(
        path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600,
        _mid_create=midway,
    )

    assert observed and observed[0] != "", "the lockfile was observable as zero bytes"


def test_acquire_does_not_steal_dead_holder_by_default(tmp_path):
    """Default (CLI) path: a fresh lease is NOT stolen just because the acquirer
    pid is dead — that's the normal state for an ephemeral CLI acquirer."""
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)

    res = rl.acquire(
        path, pid=222, now=1010.0, host="h2", token="tok-b", stale_after=3600,
        is_alive=lambda _pid: False,
    )

    assert res.acquired is False
    assert res.reason is rl.Reason.HELD


def test_acquire_steals_corrupt_lockfile(tmp_path):
    path = _lock(tmp_path)
    path.write_text("not json at all {{{", encoding="utf-8")

    res = rl.acquire(path, pid=222, now=1010.0, host="h2", token="tok-b", stale_after=3600)

    assert res.acquired is True
    assert res.reason is rl.Reason.STOLEN_CORRUPT
    assert rl.read_lock(path).token == "tok-b"


def test_release_by_matching_token_removes_lock(tmp_path):
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)

    # Released from a DIFFERENT pid (the real cross-process CLI case) — token wins.
    assert rl.release(path, token="tok-a", pid=999) is True
    assert not path.exists()


def test_release_wrong_token_keeps_lock(tmp_path):
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)

    assert rl.release(path, token="tok-wrong", pid=999) is False
    assert path.exists()
    assert rl.read_lock(path).token == "tok-a"


def test_release_by_owner_pid_removes_lock(tmp_path):
    """In-process context-manager case: same pid, no token threading needed."""
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)

    assert rl.release(path, pid=111) is True
    assert not path.exists()


def test_release_force_removes_any_lock(tmp_path):
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)

    assert rl.release(path, token="tok-wrong", force=True) is True
    assert not path.exists()


def test_release_missing_lock_is_noop(tmp_path):
    assert rl.release(_lock(tmp_path), token="tok-a") is False


def test_renew_extends_the_lease(tmp_path):
    # A heartbeat must push the lease forward so an active long run keeps its lock.
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)

    # Just before expiry, the owner renews — the lease timestamp moves to `now`.
    assert rl.renew(path, token="tok-a", now=1000.0 + 3500) is True
    assert rl.read_lock(path).ts == 1000.0 + 3500

    # A would-be stealer at a time that WOULD have been stale vs the original ts is
    # now refused, because the renewed lease is still fresh.
    res = rl.acquire(path, pid=222, now=1000.0 + 4000, host="h2", token="tok-b", stale_after=3600)
    assert res.acquired is False
    assert res.reason is rl.Reason.HELD
    assert rl.read_lock(path).token == "tok-a"


def test_renew_by_wrong_token_is_noop(tmp_path):
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)
    assert rl.renew(path, token="tok-wrong", now=2000.0) is False
    assert rl.read_lock(path).ts == 1000.0  # unchanged


def test_renew_missing_lock_is_false(tmp_path):
    assert rl.renew(_lock(tmp_path), token="tok-a", now=1000.0) is False


def test_non_owner_release_does_not_touch_the_file(tmp_path):
    """A release we don't own must be a PURE no-op — it must not even move the file
    aside, or a third process acquiring in that gap could be clobbered when the
    non-owner restores. We assert the holder's bytes are unchanged and no temp leaks.
    """
    path = _lock(tmp_path)
    rl.acquire(path, pid=222, now=2000.0, host="hB", token="successor", stale_after=3600)
    before = path.read_bytes()

    # An expired ex-holder releases with its OLD token — it no longer owns the lock.
    assert rl.release(path, token="tok-a-old", pid=111) is False

    assert path.read_bytes() == before  # byte-identical: never moved or rewritten
    assert rl.read_lock(path).token == "successor"
    assert not list(tmp_path.glob(".run.lock.release.*")), "no orphaned release temp"


def test_non_owner_release_cannot_clobber_a_fresh_acquirer(tmp_path, monkeypatch):
    """Regression for the reviewer's repro: B holds the lock; an ex-holder A issues a
    non-owned release while a third process C acquires in the window. C's lock must
    survive — A must never overwrite it.
    """
    path = _lock(tmp_path)
    rl.acquire(path, pid=222, now=2000.0, host="hB", token="successor", stale_after=3600)

    third: dict[str, rl.AcquireResult] = {}
    real_replace = os.replace

    def _c_acquires_then_replace(src, dst, *a, **k):
        # If A ever tries to restore via os.replace, let C grab the freed slot first.
        if str(dst).endswith(".run.lock") and "res" not in third:
            third["res"] = rl.acquire(
                path, pid=333, now=2001.0, host="hC", token="third", stale_after=3600,
            )
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", _c_acquires_then_replace)
    assert rl.release(path, token="tok-a-old", pid=111) is False

    # With the fix, A never moves the file (pure no-op), so C never even fires; B's
    # lock is intact. Either way, the invariant is: whoever the file says holds it is
    # a real winner, never silently overwritten.
    survivor = rl.read_lock(path)
    assert survivor is not None
    if "res" in third and third["res"].acquired:
        assert survivor.token == "third"  # C won → must not be clobbered back
    else:
        assert survivor.token == "successor"  # A was a pure no-op → B intact


def test_read_lock_missing_returns_none(tmp_path):
    assert rl.read_lock(_lock(tmp_path)) is None


def test_is_pid_alive_self_is_true():
    import os

    assert rl.is_pid_alive(os.getpid()) is True


def test_is_pid_alive_routes_to_windows_probe(monkeypatch):
    # On Windows, os.kill(pid, 0) would *terminate* the process, so is_pid_alive
    # must dispatch to the non-destructive _win_pid_alive probe. The ctypes body
    # is Windows-only; here we just assert the routing (and the pid<=0 guard).
    monkeypatch.setattr(rl.sys, "platform", "win32")
    monkeypatch.setattr(rl, "_win_pid_alive", lambda pid: pid == 4321)
    assert rl.is_pid_alive(4321) is True
    assert rl.is_pid_alive(9999) is False
    assert rl.is_pid_alive(0) is False  # guard short-circuits before the platform branch


def test_run_lock_contextmanager_acquires_and_releases(tmp_path):
    path = _lock(tmp_path)
    with rl.run_lock(path, pid=111, now=1000.0, host="h1", stale_after=3600) as held:
        assert held.acquired is True
        assert path.exists()
    assert not path.exists()  # released on exit


def test_run_lock_contextmanager_raises_when_held(tmp_path):
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)

    # Holder appears alive and the lease is fresh → the context manager (which uses
    # steal_dead=True) must still refuse rather than reclaim.
    with pytest.raises(rl.LockHeldError):
        with rl.run_lock(
            path, pid=222, now=1010.0, host="h2", stale_after=3600,
            is_alive=lambda _pid: True,
        ):
            pass
    assert rl.read_lock(path).token == "tok-a"  # other holder untouched


def test_concurrent_reclaim_of_stale_lock_yields_exactly_one_winner(tmp_path):
    """TOCTOU regression: two processes both judge the SAME stale lock reclaimable.

    The previous CAS (write + re-read own token) had a hole — a process that
    re-read before the competitor's write would see its OWN token and wrongly win,
    so both could report `acquired`. The reclaim is now serialised on `os.rename`
    and re-validates the moved-aside lock, so exactly ONE may win.

    Deterministic interleave: process A reads the stale lock and is about to rename
    it; in that window (before A's rename) process B runs its ENTIRE acquire and
    legitimately reclaims (B renames the stale file, recreates with tok-b). When A
    resumes and renames, what it moves aside is B's FRESH lock (tok-b ≠ tok-old),
    so A must restore it and concede — not double-steal.
    """
    path = _lock(tmp_path)
    # A stale lease both contenders will try to reclaim (now == ts + 2h, lease 1h).
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-old", stale_after=3600)
    steal_now = 1000.0 + 7200

    results: dict[str, rl.AcquireResult] = {}

    def _b_steals_before_a_renames() -> None:
        # Process B does its entire reclaim before A's rename runs.
        results["b"] = rl.acquire(
            path, pid=333, now=steal_now, host="h3", token="tok-b", stale_after=3600,
        )

    results["a"] = rl.acquire(
        path, pid=222, now=steal_now, host="h2", token="tok-a", stale_after=3600,
        _after_steal_read=_b_steals_before_a_renames,
    )

    winners = [k for k, r in results.items() if r.acquired]
    losers = [k for k, r in results.items() if not r.acquired]
    assert len(winners) == 1, f"expected exactly one winner, got {winners}"
    assert len(losers) == 1

    winner = results[winners[0]]
    loser = results[losers[0]]
    # Winner reclaimed legitimately (B saw no competitor mid-reclaim → STOLEN_STALE);
    # the loser is told the lock is HELD, never a false success.
    assert winner.reason in {
        rl.Reason.ACQUIRED,
        rl.Reason.STOLEN_STALE, rl.Reason.STOLEN_DEAD, rl.Reason.STOLEN_CORRUPT,
    }
    assert loser.reason is rl.Reason.HELD
    # The surviving lockfile token must be the winner's token (no leftover temp).
    survived = rl.read_lock(path)
    assert survived is not None
    assert survived.token == winner.token
    assert winner.token == "tok-b"  # B won the legitimate reclaim; A conceded
    assert not list(tmp_path.glob(".run.lock.reclaim.*")), "no orphaned reclaim temp"


def test_genuine_concurrent_reclaim_has_exactly_one_winner(tmp_path):
    """Real-parallelism check (no injection): N threads all reclaim the SAME stale
    lock at once. `os.rename` releases the GIL during the syscall, so the threads
    genuinely race — mutual exclusion must hold without any test-only interleave.
    """
    path = _lock(tmp_path)
    rl.acquire(path, pid=1, now=1000.0, host="h0", token="tok-old", stale_after=3600)
    steal_now = 1000.0 + 7200

    barrier = threading.Barrier(12)
    results: list[rl.AcquireResult] = []
    lock = threading.Lock()

    def _contend(i: int) -> None:
        barrier.wait()  # release all threads at the same instant
        res = rl.acquire(
            path, pid=100 + i, now=steal_now, host=f"h{i}",
            token=f"tok-{i}", stale_after=3600,
        )
        with lock:
            results.append(res)

    threads = [threading.Thread(target=_contend, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [r for r in results if r.acquired]
    assert len(winners) == 1, f"expected exactly one winner, got {len(winners)}"
    survived = rl.read_lock(path)
    assert survived is not None
    assert survived.token == winners[0].token
    assert not list(tmp_path.glob(".run.lock.reclaim.*")), "no orphaned reclaim temp"


def test_release_does_not_delete_a_lock_reclaimed_after_lease_expiry(tmp_path):
    """read-check-unlink regression: an expired holder must not delete a lock that
    a NEW run has since legitimately reclaimed.

    Holder A's lease expires; run B reclaims the lock (now holds tok-b at the same
    path). A then calls release(token=tok-a). Because release snapshots via rename
    and verifies ownership on the moved copy, it sees tok-b (not tok-a), restores
    it, and reports False — B's lock survives intact.
    """
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)
    # B reclaims the stale lease two hours later.
    res_b = rl.acquire(path, pid=222, now=1000.0 + 7200, host="h2", token="tok-b", stale_after=3600)
    assert res_b.acquired is True

    # A (the expired holder) tries to release using its old token — must be a no-op.
    assert rl.release(path, token="tok-a", pid=111) is False
    survivor = rl.read_lock(path)
    assert survivor is not None
    assert survivor.token == "tok-b"  # B's reclaimed lock is intact
    assert not list(tmp_path.glob(".run.lock.release.*")), "no orphaned release temp"


def test_release_restores_successor_reclaimed_in_read_to_rename_gap(tmp_path, monkeypatch):
    """Successor-restore branch of release(): A's initial read still shows A's own
    (soon-to-expire) lock, but a successor B legitimately reclaims the stale lease
    BETWEEN A's read and A's rename-aside. A then moves B's FRESH lock aside, sees
    it isn't A's, and must restore it via O_CREAT|O_EXCL instead of deleting it.
    """
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)

    real_rename = os.rename
    fired: dict[str, rl.AcquireResult] = {}

    def _b_reclaims_then_rename(src, dst, *a, **k):
        # B's whole reclaim runs in the read→rename gap of A's release.
        if str(src).endswith(".run.lock") and "b" not in fired:
            fired["b"] = rl.acquire(
                path, pid=222, now=1000.0 + 7200, host="h2", token="tok-b", stale_after=3600,
            )
        return real_rename(src, dst, *a, **k)

    monkeypatch.setattr(os, "rename", _b_reclaims_then_rename)
    assert rl.release(path, token="tok-a", pid=111) is False

    assert fired["b"].acquired is True  # B's reclaim of the stale lease was legitimate
    survivor = rl.read_lock(path)
    assert survivor is not None
    assert survivor.token == "tok-b"  # B's lock was restored, not deleted
    assert not list(tmp_path.glob(".run.lock.release.*")), "no orphaned release temp"


def test_release_restore_concedes_to_a_fresh_acquirer(tmp_path, monkeypatch):
    """FileExistsError sub-branch of the successor-restore: a brand-new acquirer C
    grabs the freed slot between A's rename-aside and A's O_EXCL restore. C must
    rightfully keep the lock — A's restore concedes instead of clobbering C.
    """
    path = _lock(tmp_path)
    rl.acquire(path, pid=111, now=1000.0, host="h1", token="tok-a", stale_after=3600)

    real_rename = os.rename
    real_open = os.open
    state: dict[str, object] = {}

    def _b_reclaims_then_rename(src, dst, *a, **k):
        if str(src).endswith(".run.lock") and "b" not in state:
            state["b"] = rl.acquire(
                path, pid=222, now=1000.0 + 7200, host="h2", token="tok-b", stale_after=3600,
            )
        return real_rename(src, dst, *a, **k)

    def _c_acquires_then_open(p, flags, *a, **k):
        # Fire exactly once: on A's O_EXCL restore attempt (after B's reclaim was
        # moved aside). C acquires the freed slot first, so A's create must lose.
        if (
            str(p) == str(path)
            and flags & os.O_EXCL
            and "b" in state
            and "restore_seen" not in state
        ):
            state["restore_seen"] = True
            state["c"] = rl.acquire(
                path, pid=333, now=1000.0 + 7201, host="h3", token="tok-c", stale_after=3600,
            )
        return real_open(p, flags, *a, **k)

    monkeypatch.setattr(os, "rename", _b_reclaims_then_rename)
    monkeypatch.setattr(os, "open", _c_acquires_then_open)
    assert rl.release(path, token="tok-a", pid=111) is False

    c_res = state["c"]
    assert isinstance(c_res, rl.AcquireResult) and c_res.acquired is True
    survivor = rl.read_lock(path)
    assert survivor is not None
    assert survivor.token == "tok-c"  # C keeps the slot; A's restore conceded
    assert not list(tmp_path.glob(".run.lock.release.*")), "no orphaned release temp"


# ── Reclaim-mutex sentinel hygiene ────────────────────────────────────────────


def test_leaked_reclaim_mutex_is_self_healed(tmp_path):
    """A `.reclaiming` sentinel older than the 60s staleness bar can only have
    leaked (a holder hard-killed mid-reclaim). The next reclaimer must unlink it,
    retry the O_EXCL create, and proceed with the reclaim."""
    path = _lock(tmp_path)
    path.write_text("not json at all {{{", encoding="utf-8")  # corrupt → reclaimable
    mutex = tmp_path / ".run.lock.reclaiming"
    mutex.write_text("1000", encoding="utf-8")  # leaked: age 120s at now=1120

    res = rl.acquire(path, pid=222, now=1120.0, host="h2", token="tok-b", stale_after=3600)

    assert res.acquired is True
    assert res.reason is rl.Reason.STOLEN_CORRUPT
    assert rl.read_lock(path).token == "tok-b"
    assert not mutex.exists()  # healed, then removed after the reclaim finished


def test_unreadable_reclaim_mutex_is_treated_as_held(tmp_path):
    """A present-but-garbage sentinel is conservatively treated as a live reclaim:
    the acquirer concedes (HELD) rather than guessing it may steal."""
    path = _lock(tmp_path)
    path.write_text("not json at all {{{", encoding="utf-8")
    mutex = tmp_path / ".run.lock.reclaiming"
    mutex.write_text("garbage-not-a-float", encoding="utf-8")

    res = rl.acquire(path, pid=222, now=1120.0, host="h2", token="tok-b", stale_after=3600)

    assert res.acquired is False
    assert res.reason is rl.Reason.HELD
    assert mutex.exists()  # never touched — it may belong to a live reclaimer


# ── Durable-state co-location (FIX 3) ─────────────────────────────────────────


def test_default_lock_path_unset_is_in_repo(monkeypatch):
    """With RESEARCH_BRAIN_STATE_DIR unset, the default lock path is the exact
    in-repo `pipeline/.run.lock` — pure identity, zero behavior change."""
    monkeypatch.delenv("RESEARCH_BRAIN_STATE_DIR", raising=False)
    assert rl.default_lock_path() == rl.DEFAULT_LOCK_PATH


def test_default_lock_path_relocates_under_state_dir(tmp_path, monkeypatch):
    """On a persistent-volume deployment the run lock must co-locate with the
    relocated runtime state (so os.replace/os.rename stay same-filesystem atomic),
    not stay frozen in-repo on a different volume."""
    state_dir = tmp_path / "vol"
    monkeypatch.setenv("RESEARCH_BRAIN_STATE_DIR", str(state_dir))
    relocated = rl.default_lock_path()
    assert relocated == state_dir / "pipeline" / ".run.lock"


# ── CLI ──────────────────────────────────────────────────────────────────────


def test_cli_acquire_prints_token_then_blocks(tmp_path, capsys):
    path = _lock(tmp_path)

    rc = rl.main(["acquire", "--lock", str(path), "--pid", "111", "--now", "1000"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "lock-token:" in out
    assert path.exists()

    # A second acquire while the lease is fresh is refused with exit 1.
    rc = rl.main(["acquire", "--lock", str(path), "--pid", "222", "--now", "1010"])
    assert rc == 1
    out = capsys.readouterr().out.lower()
    assert "in progress" in out or "held" in out


def test_cli_release_by_token_across_processes(tmp_path, capsys):
    """Reproduces the real flow: acquire in one process, release in another via token."""
    path = _lock(tmp_path)
    rl.main(["acquire", "--lock", str(path), "--pid", "111", "--now", "1000", "--token", "tok-x"])
    capsys.readouterr()

    rc = rl.main(["release", "--lock", str(path), "--token", "tok-x"])
    assert rc == 0
    assert not path.exists()


def test_cli_release_wrong_token_keeps_lock(tmp_path):
    path = _lock(tmp_path)
    rl.main(["acquire", "--lock", str(path), "--pid", "111", "--now", "1000", "--token", "tok-x"])
    rc = rl.main(["release", "--lock", str(path), "--token", "nope"])
    assert rc == 0  # release CLI is best-effort; non-removal isn't a hard error
    assert path.exists()


def test_cli_status_reports_holder(tmp_path, capsys):
    path = _lock(tmp_path)
    rl.main(["acquire", "--lock", str(path), "--pid", "111", "--now", "1000"])
    capsys.readouterr()
    rc = rl.main(["status", "--lock", str(path)])
    assert rc == 0
    assert "111" in capsys.readouterr().out


def test_cli_acquire_refused_with_unknown_holder_does_not_crash(tmp_path, capsys):
    """Reviewer's repro: a CORRUPT lockfile plus a FRESH `.reclaiming` sentinel (a
    competitor is mid-reclaim). `acquire` concedes with holder_pid/holder_age both
    None, and the CLI must print a clean REFUSED line and exit 1 — not crash with
    `TypeError: unsupported format string passed to NoneType.__format__`."""
    path = _lock(tmp_path)
    path.write_text("not json at all {{{", encoding="utf-8")
    mutex = tmp_path / ".run.lock.reclaiming"
    mutex.write_text("1000", encoding="utf-8")  # fresh: age 0s at --now 1000

    rc = rl.main(["acquire", "--lock", str(path), "--now", "1000"])

    assert rc == 1
    out = capsys.readouterr().out
    assert "REFUSED" in out
    assert "None" not in out  # unknown holder rendered gracefully, not "pid None"


def test_cli_renew_refreshes_lease(tmp_path, capsys):
    """CLI heartbeat: `renew --token` pushes the lease timestamp to --now, exit 0."""
    path = _lock(tmp_path)
    rl.main(["acquire", "--lock", str(path), "--pid", "111", "--now", "1000", "--token", "tok-x"])
    capsys.readouterr()

    rc = rl.main(["renew", "--lock", str(path), "--token", "tok-x", "--now", "4500"])

    assert rc == 0
    assert "refreshed" in capsys.readouterr().out.lower()
    assert rl.read_lock(path).ts == 4500.0


def test_cli_renew_wrong_token_exits_nonzero(tmp_path, capsys):
    """A renew we don't own is refused with exit 1 and leaves the lease untouched."""
    path = _lock(tmp_path)
    rl.main(["acquire", "--lock", str(path), "--pid", "111", "--now", "1000", "--token", "tok-x"])
    capsys.readouterr()

    rc = rl.main(["renew", "--lock", str(path), "--token", "nope", "--now", "4500"])

    assert rc == 1
    assert "no matching lock" in capsys.readouterr().out.lower()
    assert rl.read_lock(path).ts == 1000.0  # unchanged
