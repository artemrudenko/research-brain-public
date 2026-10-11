#!/usr/bin/env python3
"""
registry.py — the single source of truth for the `pipeline/registry.md` schema.

The dedup registry is a markdown table whose columns are, in order (CONVENTIONS
§9):

    collected | category | status | url | title

Each collection run appends one row. Several readers need to walk this table —
`health.py` derives per-category last-collected dates (feed liveness), and
`build_digest.py` maps url -> status (the "needs attention" scan). Before this
module each kept its own copy of the row-parsing loop and the column indices, so
a schema change had to be mirrored by hand in two places (a latent schema-drift
bug). They now share `iter_registry_rows`, which yields rows as a `RegistryRow`
NamedTuple — callers address columns by NAME, never by magic index.

Parsing is deliberately tolerant (best-effort, like the rest of the pipeline):
a missing file, blank/commented/header/separator rows, and rows with too few
cells are skipped rather than raised, so an old-format registry degrades to
"fewer usable rows" instead of crashing a real run. Per-cell interpretation
(date parsing, status case-folding) stays with each caller, since they differ.
"""
from __future__ import annotations

import os
import secrets
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

# Number of leading cells a row must have to be a usable data row. Extra trailing
# columns (a future schema addition) are tolerated and ignored.
_MIN_CELLS = 5

# The canonical table header written when creating a fresh registry.md, so the
# file `iter_registry_rows` reads back has the exact `collected|category|status|
# url|title` schema this module owns.
_REGISTRY_HEADER = (
    "# Article Registry\n\n"
    "URL is the primary key for deduplication. Rows are appended by collection\n"
    "and `/save` capture; the status cell is set by curation. Do not edit by hand.\n\n"
    "| collected | category | status | url | title |\n"
    "|---|---|---|---|---|\n"
)


class RegistryRow(NamedTuple):
    """One data row of `pipeline/registry.md`, addressed by column name.

    Cells are returned verbatim (stripped of surrounding whitespace only) — a
    blank cell is the empty string, and no case-folding or date parsing is done
    here. That keeps this parser a pure schema boundary; semantics live in the
    callers, which interpret the same columns differently.
    """

    collected: str
    category: str
    status: str
    url: str
    title: str


def _data_cells(raw: str) -> list[str] | None:
    """Parse one registry line into its stripped cells, or None if not a data row.

    Returns None for blank lines, HTML-commented rows, the `collected | …` header,
    the `---|---` separator, and rows with fewer than five cells (older/partial
    format) — the single place the data-row shape is decided.
    """
    line = raw.strip()
    if not line.startswith("|") or line.startswith("<!--"):
        return None
    cells = [c.strip() for c in line.strip("|").split("|")]
    if len(cells) < _MIN_CELLS:
        return None
    if cells[0].lower() == "collected" or set(cells[0]) <= {"-", ":"}:
        return None
    return cells


def iter_registry_rows(path: Path) -> Iterator[RegistryRow]:
    """Yield each usable data row of the registry table at `path`.

    Skips, without raising: a missing file; blank lines; HTML-commented rows;
    the `collected | …` header and its `---|---` separator; and any row with
    fewer than five cells (an older/partial format). The result is empty rather
    than an error when nothing parses.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        cells = _data_cells(raw)
        if cells is not None:
            yield RegistryRow(*cells[:_MIN_CELLS])


def _select_flock() -> tuple[
    Callable[[int], None], Callable[[int], None], Callable[[int], bool]
]:
    """Return (acquire, release, try_acquire) for an exclusive lock on an open fd.

    `try_acquire` is the NON-BLOCKING variant: it grabs the lock and returns True,
    or returns False immediately when someone else holds it (never waits).

    POSIX uses `fcntl.flock` (kernel-advisory, auto-released when the fd closes).
    Windows has no `fcntl`, so it uses `msvcrt.locking` on a one-byte region. The
    platform-specific import lives inside the chosen branch so `import registry`
    works on every OS — a top-level `import fcntl` would break every native-Windows
    install (this module is imported by ~12 scripts). Runtime stays stdlib-only.
    """
    if sys.platform == "win32":
        import msvcrt

        def _win_acquire(fd: int) -> None:
            # LK_LOCK blocks ~10s then raises; loop so this is a true blocking wait.
            while True:
                try:
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                    return
                except OSError:
                    continue

        def _win_release(fd: int) -> None:
            try:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass

        def _win_try(fd: int) -> bool:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # non-blocking; raises if held
                return True
            except OSError:
                return False

        return _win_acquire, _win_release, _win_try

    import fcntl

    def _posix_acquire(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _posix_release(_fd: int) -> None:
        pass  # POSIX releases the flock when the fd is closed (below).

    def _posix_try(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:  # BlockingIOError (a subclass) when another owner holds it
            return False

    return _posix_acquire, _posix_release, _posix_try


_flock_exclusive, _flock_release, _flock_try = _select_flock()


@contextmanager
def advisory_lock(lock_path: Path) -> Iterator[None]:
    """Hold an exclusive cross-process advisory lock on `lock_path`.

    Backed by `_select_flock` (fcntl on POSIX, msvcrt on Windows). On POSIX the
    lock auto-releases when the fd is closed or the process dies, so a crashed
    holder can never leave a stale lock behind. Reused wherever a multi-step
    read-check-write sequence must not interleave across processes (registry
    read-modify-writes, inbox routing).
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        _flock_exclusive(fd)
        yield
    finally:
        _flock_release(fd)
        os.close(fd)


@contextmanager
def try_advisory_lock(
    lock_path: Path, *, timeout: float = 0.0, poll: float = 0.05
) -> Iterator[bool]:
    """Bounded variant of `advisory_lock`: yields whether the lock was acquired.

    Yields True (and holds the lock until the block exits) if it can be grabbed
    within `timeout` seconds, otherwise yields False WITHOUT holding it. A zero
    timeout makes a single non-blocking attempt. Use this where waiting forever
    would be worse than skipping the guarded work — e.g. a best-effort append that
    must never stall its caller behind a long-running compaction of the same file.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    acquired = False
    try:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            acquired = _flock_try(fd)
            if acquired or time.monotonic() >= deadline:
                break
            time.sleep(poll)
        yield acquired
    finally:
        if acquired:
            _flock_release(fd)
        os.close(fd)


@contextmanager
def _registry_lock(path: Path) -> Iterator[None]:
    """Serialise concurrent registry read-modify-writes across processes.

    Without this, two concurrent `append_registry_row` calls each did a
    read-modify-write through a shared temp and one update was lost.
    """
    with advisory_lock(path.with_name(path.name + ".lock")):
        yield  # closing the fd also releases the lock


def _fsync_dir(directory: Path) -> None:
    """Best-effort fsync of a directory so a completed rename survives power loss.

    Windows cannot open directories (and some filesystems refuse the fsync), so
    any OSError degrades to the pre-fsync behavior — the rename may be lost and
    the OLD complete file resurface, which is safe — rather than failing a write
    whose data is already durable.
    """
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically AND durably (temp + fsync + os.replace).

    The single source of truth for atomic same-path writes across the pipeline
    (registry, inbox, build_digest, …). The temp name is per-process + random so
    two writers targeting the same final path can't share one `{name}.tmp` and
    race to a FileNotFoundError on replace; the temp lives in `path`'s own
    directory so the replace is a same-filesystem rename.

    Durability ordering: the temp's data is fsynced BEFORE the rename (a crash
    can otherwise expose a truncated file under the final name — for the dedup
    registry that means mass re-collection), and the parent directory after it
    (else the rename itself can be lost; the old complete file resurfacing is
    the acceptable failure mode `_fsync_dir` degrades to).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def atomic_write_unique(directory: Path, stem: str, text: str, suffix: str = ".md") -> Path:
    """Write `text` to a UNIQUELY-NAMED `{stem}{suffix}` in `directory`; return the path.

    A `_unique_path()`-then-write sequence is a TOCTOU: two concurrent writers
    whose inputs slugify to the same stem both see the name free, pick the same
    `{stem}{suffix}`, and clobber each other. Here the final name is CLAIMED
    atomically via `os.link` (which raises if the target exists), retrying -2/-3/…
    on collision, so each writer gets its own file even under contention.

    The single source of truth for unique-name writes (inbox capture + collect).
    """
    directory.mkdir(parents=True, exist_ok=True)
    # The temp deliberately does NOT end in `suffix` (.md): callers that glob `*.md`
    # must not list — then read — another writer's half-written, about-to-be-unlinked
    # temp file.
    tmp = directory / f".{stem}.tmp.{os.getpid()}.{secrets.token_hex(4)}"
    # The temp write is INSIDE the try so a failed/partial write (ENOSPC, perms) is
    # always cleaned up rather than left as an orphan.
    try:
        tmp.write_text(text, encoding="utf-8")
        counter = 1
        while True:
            name = stem if counter == 1 else f"{stem}-{counter}"
            candidate = directory / f"{name}{suffix}"
            try:
                os.link(tmp, candidate)  # atomic claim: raises if the name is taken
                return candidate
            except FileExistsError:
                counter += 1  # name taken by a concurrent writer — try the next
            except OSError as exc:
                # Any OTHER link error (e.g. a filesystem without hardlink support)
                # must surface with context, not as an opaque errno mid-pipeline.
                raise OSError(
                    f"could not atomically claim {candidate} "
                    f"(does this filesystem support hardlinks?): {exc}"
                ) from exc
    finally:
        tmp.unlink(missing_ok=True)


# Back-compat alias: registry's internal callers still use the private name.
_atomic_write = atomic_write_text


def _cell(value: str) -> str:
    """Neutralise a value for a single markdown-table cell.

    A literal `|` would split the row into extra cells and corrupt the table, and
    a newline would break the row entirely — fold both to a space so the appended
    row always round-trips through `iter_registry_rows`.
    """
    return value.replace("|", "/").replace("\n", " ").replace("\r", " ").strip()


def append_registry_row(
    path: Path,
    *,
    collected: str,
    category: str,
    url: str,
    title: str,
    status: str = "",
) -> None:
    """Append one data row to the registry at `path` (creating it if missing).

    The row carries a blank `status` by default — "collected, not yet curated"
    (CONVENTIONS §9) — which curation later flips to `processed`/`rejected`. When
    the file does not yet exist it is created with the canonical header so the
    schema stays self-describing. The whole read-modify-write runs under the
    cross-process registry lock and writes via a per-process temp, so concurrent
    appends can't lose a row; cell values are sanitised so a `|`/newline in the
    title can't corrupt the table.
    """
    row = (
        f"| {_cell(collected)} | {_cell(category)} | {_cell(status)} "
        f"| {_cell(url)} | {_cell(title)} |\n"
    )
    with _registry_lock(path):
        body = path.read_text(encoding="utf-8") if path.exists() else _REGISTRY_HEADER
        if not body.endswith("\n"):
            body += "\n"
        _atomic_write(path, body + row)


def append_registry_row_if_absent(
    path: Path,
    *,
    collected: str,
    category: str,
    url: str,
    title: str,
    status: str = "",
) -> bool:
    """Append a row only if `url` (normalised) is not already in the registry.

    Returns True iff a new row was written; False when the URL is already present
    (a duplicate the caller should treat as "already collected"). Unlike a
    separate `_url_in_registry(...)` check followed by `append_registry_row(...)`,
    the URL existence test AND the append run inside ONE `_registry_lock`, so two
    concurrent collectors / a `/save` capture can't both observe the URL missing
    and each write a row — the registry's URL primary key (CONVENTIONS §9) stays
    unique even under contention.
    """
    from scripts.normalize_url import normalize  # local import: keep registry low-level

    key = normalize(url)
    row = (
        f"| {_cell(collected)} | {_cell(category)} | {_cell(status)} "
        f"| {_cell(url)} | {_cell(title)} |\n"
    )
    with _registry_lock(path):
        # Read the file ONCE under the lock: scan it for the URL and reuse the same
        # text as the append base, so the existence check and the write are a single
        # consistent view (no second read that could disagree).
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing is not None:
            for raw in existing.splitlines():
                cells = _data_cells(raw)
                if cells is not None and normalize(cells[3]) == key:
                    return False
        body = existing if existing is not None else _REGISTRY_HEADER
        if not body.endswith("\n"):
            body += "\n"
        _atomic_write(path, body + row)
    return True


def set_registry_category(path: Path, *, url: str, category: str) -> bool:
    """Update the `category` cell of the row whose URL matches `url` (normalised).

    Returns True iff a row was changed. Used when an inbox article is routed to its
    real topic so per-category stats / health signals stay accurate (routing the
    file alone used to leave the registry row stuck at `_inbox`). The match is by
    normalised URL (the dedup key), and the rewrite runs under the registry lock.
    """
    if not path.exists():
        return False
    from scripts.normalize_url import normalize  # local import: keep registry low-level

    key = normalize(url)
    with _registry_lock(path):
        out: list[str] = []
        changed = False
        for raw in path.read_text(encoding="utf-8").splitlines(keepends=True):
            cells = _data_cells(raw)
            if cells is not None and normalize(cells[3]) == key:
                cells[1] = _cell(category)
                raw = "| " + " | ".join(cells[:_MIN_CELLS]) + " |\n"
                changed = True
            out.append(raw)
        if changed:
            _atomic_write(path, "".join(out))
    return changed
