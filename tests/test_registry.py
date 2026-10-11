"""
test_registry.py — offline tests for the shared `pipeline/registry.md` parser.

`scripts/registry.py` owns the registry table schema (CONVENTIONS §9) in one
place so `health.py` and `build_digest.py` can no longer drift apart on column
order. These tests pin the row-extraction contract both callers depend on.
"""
import sys
import threading
from pathlib import Path

from scripts.registry import (  # noqa: E402
    RegistryRow,
    append_registry_row,
    append_registry_row_if_absent,
    iter_registry_rows,
    set_registry_category,
)

_HEADER = (
    "| collected | category | status | url | title |\n"
    "|---|---|---|---|---|\n"
)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "registry.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_missing_file_yields_nothing(tmp_path: Path) -> None:
    assert list(iter_registry_rows(tmp_path / "absent.md")) == []


def test_parses_a_data_row_into_named_columns(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _HEADER + "| 2026-05-26 | ai | processed | https://x.com/a | A Post |\n",
    )
    rows = list(iter_registry_rows(path))
    assert rows == [
        RegistryRow(
            collected="2026-05-26",
            category="ai",
            status="processed",
            url="https://x.com/a",
            title="A Post",
        )
    ]
    # Columns are addressable by name, not magic index — the drift guard.
    assert rows[0].url == "https://x.com/a"
    assert rows[0].status == "processed"


def test_skips_header_separator_blank_and_comment_rows(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _HEADER
        + "\n"
        + "<!-- | 2026-01-01 | ai | x | https://c | c | -->\n"
        + "| 2026-05-26 | ai | processed | https://x.com/a | A |\n"
        + "not a table line\n",
    )
    rows = list(iter_registry_rows(path))
    assert [r.url for r in rows] == ["https://x.com/a"]


def test_skips_rows_with_too_few_cells(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _HEADER + "| 2026-05-26 | ai | processed |\n",  # only 3 cells -> dropped
    )
    assert list(iter_registry_rows(path)) == []


def test_preserves_blank_cells_verbatim(tmp_path: Path) -> None:
    # A blank status cell is a real, addressable state — not skipped or coerced.
    path = _write(
        tmp_path,
        _HEADER + "| 2026-05-26 | ai |  | https://x.com/a | A |\n",
    )
    (row,) = list(iter_registry_rows(path))
    assert row.status == ""
    assert row.category == "ai"


def test_tolerates_extra_trailing_columns(tmp_path: Path) -> None:
    # A future schema that appends a 6th column must still parse the first five.
    path = _write(
        tmp_path,
        _HEADER + "| 2026-05-26 | ai | new | https://x.com/a | A | extra |\n",
    )
    (row,) = list(iter_registry_rows(path))
    assert row.title == "A"
    assert row.url == "https://x.com/a"


# ── append_registry_row ───────────────────────────────────────────────────────


def test_append_creates_file_with_header_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "registry.md"
    append_registry_row(
        path, collected="2026-06-22", category="ai", url="https://x/1", title="One"
    )
    rows = list(iter_registry_rows(path))
    assert rows == [
        RegistryRow(
            collected="2026-06-22",
            category="ai",
            status="",
            url="https://x/1",
            title="One",
        )
    ]


def test_append_adds_row_to_existing_table(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _HEADER + "| 2026-06-20 | ml | processed | https://x/0 | Zero |\n",
    )
    append_registry_row(
        path, collected="2026-06-22", category="ai", url="https://x/1", title="One"
    )
    assert [r.url for r in iter_registry_rows(path)] == ["https://x/0", "https://x/1"]
    # The appended row carries a blank (not-yet-curated) status.
    assert list(iter_registry_rows(path))[-1].status == ""


def test_append_escapes_pipe_in_title(tmp_path: Path) -> None:
    # A title with a literal pipe would otherwise split into extra cells and
    # corrupt the table; it must be neutralised so the row round-trips.
    path = tmp_path / "registry.md"
    append_registry_row(
        path, collected="2026-06-22", category="ai",
        url="https://x/1", title="A | B pipes",
    )
    (row,) = list(iter_registry_rows(path))
    assert row.url == "https://x/1"
    assert "|" not in row.title


# ── concurrency + category update ─────────────────────────────────────────────


def test_concurrent_appends_lose_no_rows(tmp_path: Path) -> None:
    # The flock-serialised read-modify-write must not drop rows under contention.
    path = tmp_path / "registry.md"
    append_registry_row(path, collected="2026-01-01", category="ai", url="https://seed", title="s")
    barrier = threading.Barrier(8)
    errors: list[str] = []

    def _append(i: int) -> None:
        barrier.wait()
        try:
            append_registry_row(
                path, collected="2026-06-22", category="ai", url=f"https://x/{i}", title=f"T{i}"
            )
        except Exception as exc:  # noqa: BLE001 - record, assert none below
            errors.append(repr(exc))

    threads = [threading.Thread(target=_append, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(list(iter_registry_rows(path))) == 9  # seed + 8 appended, none lost


# ── append_registry_row_if_absent (atomic check-then-append dedup) ────────────


def test_if_absent_appends_when_url_is_new(tmp_path: Path) -> None:
    path = tmp_path / "registry.md"
    appended = append_registry_row_if_absent(
        path, collected="2026-06-22", category="ai", url="https://x/a", title="A"
    )
    assert appended is True
    assert [r.url for r in iter_registry_rows(path)] == ["https://x/a"]


def test_if_absent_skips_when_url_already_present(tmp_path: Path) -> None:
    path = tmp_path / "registry.md"
    append_registry_row(path, collected="2026-06-22", category="ai", url="https://x/a", title="A")
    # A different SHAPE of the same article (scheme/www/trailing slash) must collide.
    appended = append_registry_row_if_absent(
        path, collected="2026-06-22", category="ai", url="http://www.x/a/", title="dup"
    )
    assert appended is False
    assert len(list(iter_registry_rows(path))) == 1  # no duplicate primary key


def test_if_absent_is_atomic_under_contention(tmp_path: Path) -> None:
    # The whole check-then-append must run under the registry lock, so N threads
    # racing to insert the SAME url yield exactly one row (not one per thread).
    path = tmp_path / "registry.md"
    barrier = threading.Barrier(8)
    appended_count = 0
    lock = threading.Lock()

    def _try(i: int) -> None:
        nonlocal appended_count
        barrier.wait()
        did = append_registry_row_if_absent(
            path, collected="2026-06-22", category="ai", url="https://x/same", title=f"T{i}"
        )
        if did:
            with lock:
                appended_count += 1

    threads = [threading.Thread(target=_try, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert appended_count == 1  # exactly one thread won the insert
    assert len(list(iter_registry_rows(path))) == 1  # one row, one primary key


def test_set_registry_category_updates_matching_row(tmp_path: Path) -> None:
    path = tmp_path / "registry.md"
    append_registry_row(path, collected="2026-06-22", category="_inbox", url="https://x/a", title="A")
    append_registry_row(path, collected="2026-06-22", category="_inbox", url="https://x/b", title="B")

    # Match by normalised URL (different shape) — only the matching row changes.
    assert set_registry_category(path, url="https://www.x/a/", category="ai-agents") is True
    rows = {r.url: r for r in iter_registry_rows(path)}
    assert rows["https://x/a"].category == "ai-agents"
    assert rows["https://x/b"].category == "_inbox"  # untouched
    # Other cells of the changed row are preserved.
    assert rows["https://x/a"].title == "A"
    assert rows["https://x/a"].status == ""


def test_set_registry_category_no_match_is_noop(tmp_path: Path) -> None:
    path = tmp_path / "registry.md"
    append_registry_row(path, collected="2026-06-22", category="_inbox", url="https://x/a", title="A")
    assert set_registry_category(path, url="https://nope", category="ai") is False
    assert [r.category for r in iter_registry_rows(path)] == ["_inbox"]


def test_set_registry_category_missing_file_is_false(tmp_path: Path) -> None:
    assert set_registry_category(tmp_path / "absent.md", url="https://x", category="ai") is False


# --- Cross-platform registry lock (native Windows support) ---

def test_registry_has_no_module_level_fcntl() -> None:
    # `import fcntl` must stay inside the POSIX branch of _select_flock, never at
    # module top — a top-level import would crash `import registry` on Windows
    # (the module is imported by ~12 scripts). This guards that regression.
    import scripts.registry as reg

    assert not hasattr(reg, "fcntl")


def test_select_flock_posix_acquires_and_releases(tmp_path: Path) -> None:
    import os

    from scripts.registry import _select_flock

    acquire, release, try_acquire = _select_flock()  # non-win32 host → fcntl backend
    fd = os.open(str(tmp_path / "x.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        acquire(fd)  # exclusive flock — must not raise
        release(fd)  # POSIX release is a no-op (fd close releases) — must not raise
    finally:
        os.close(fd)

    # A non-blocking acquire on a free lock succeeds; a second owner is refused.
    a = os.open(str(tmp_path / "y.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    b = os.open(str(tmp_path / "y.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        assert try_acquire(a) is True
        assert try_acquire(b) is False  # held by `a` — must not block, must return False
    finally:
        os.close(a)
        os.close(b)


def test_select_flock_windows_uses_msvcrt(monkeypatch: object) -> None:
    import types

    calls: list[tuple[int, int, int]] = []
    fake_msvcrt = types.ModuleType("msvcrt")
    fake_msvcrt.LK_LOCK = 1  # type: ignore[attr-defined]
    fake_msvcrt.LK_UNLCK = 0  # type: ignore[attr-defined]
    fake_msvcrt.LK_NBLCK = 2  # type: ignore[attr-defined]
    fake_msvcrt.locking = lambda fd, mode, n: calls.append((fd, mode, n))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)  # type: ignore[attr-defined]
    monkeypatch.setattr(sys, "platform", "win32")  # type: ignore[attr-defined]

    from scripts.registry import _select_flock

    acquire, release, try_acquire = _select_flock()  # win32 branch — no fcntl touched
    acquire(7)
    release(7)
    assert (7, 1, 1) in calls  # acquired via msvcrt.locking(LK_LOCK, 1)
    assert (7, 0, 1) in calls  # released via msvcrt.locking(LK_UNLCK, 1)
    # The non-blocking try uses LK_NBLCK; the fake never raises, so it reads True.
    assert try_acquire(7) is True
    assert (7, 2, 1) in calls


def test_atomic_write_text_is_crash_durable(tmp_path: Path, monkeypatch) -> None:
    """Durability contract: fsync(temp) → replace → fsync(parent dir).

    Without the temp fsync a crash after the replace can surface a TRUNCATED
    registry (rename visible, data blocks not flushed) → mass re-collection.
    Without the dir fsync the rename itself can be lost, resurrecting the old
    file — acceptable — so the dir sync is best-effort but must still happen.
    """
    import os
    import stat

    from scripts import registry as reg

    events: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def recording_fsync(fd: int) -> None:
        kind = "dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
        events.append(f"fsync-{kind}")
        real_fsync(fd)

    def recording_replace(src: object, dst: object) -> None:
        events.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(reg.os, "fsync", recording_fsync)
    monkeypatch.setattr(reg.os, "replace", recording_replace)

    target = tmp_path / "registry.md"
    reg.atomic_write_text(target, _HEADER)

    assert target.read_text(encoding="utf-8") == _HEADER
    assert "fsync-file" in events, "temp file must be fsynced"
    assert events.index("fsync-file") < events.index("replace"), (
        f"data must be durable before the rename is visible: {events}"
    )
    if sys.platform != "win32":
        # Windows cannot open directories, so _fsync_dir deliberately degrades
        # there (covered by the tolerates-unsyncable-directory test below).
        assert "fsync-dir" in events, "parent directory must be fsynced"
        assert events.index("replace") < events.index("fsync-dir"), (
            f"durability ordering violated: {events}"
        )


def test_atomic_write_text_tolerates_unsyncable_directory(
    tmp_path: Path, monkeypatch
) -> None:
    """Windows can't open directories — dir fsync degrades, the write survives."""
    from scripts import registry as reg

    real_open = reg.os.open

    def deny_dir_open(path: object, flags: int, *args: object) -> int:
        if Path(str(path)).is_dir():
            raise PermissionError(13, "directories cannot be opened here")
        return real_open(path, flags, *args)

    monkeypatch.setattr(reg.os, "open", deny_dir_open)

    target = tmp_path / "registry.md"
    reg.atomic_write_text(target, _HEADER)

    assert target.read_text(encoding="utf-8") == _HEADER
