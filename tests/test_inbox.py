"""Tests for scripts/inbox.py — the ad-hoc article-capture queue.

The `source-capture` flow lets a user send a single article (e.g. a URL pasted to
the bot) instead of subscribing to a feed. Capture is immediate + cheap (the
article lands in pipeline/1-incoming/_inbox/), processing is batched: a threshold
(default 5), a manual /process, or the weekly run drains the inbox — routing each
article to its real topic so the normal curate → synthesis → wiki-ingest chain
picks it up. This module is the deterministic queue core; the agentic fetch /
extract / fan-out lives in the skill.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts import inbox

_WHEN = date(2026, 6, 21)


def _split_fm(text: str) -> dict[str, str]:
    """Flat parse of a frontmatter block into key→value (enough for assertions)."""
    fields: dict[str, str] = {}
    if not text.startswith("---"):
        return fields
    end = text.find("\n---", 3)
    for line in text[4:end].splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


# ── add_article ──────────────────────────────────────────────────────────────


def test_add_article_writes_frontmatter_strict_into_inbox(tmp_path: Path) -> None:
    inc = tmp_path / "1-incoming"
    path = inbox.add_article(
        inc, url="https://example.com/a", title="A Great Read",
        body="Some article body.", when=_WHEN,
    )
    assert path.exists()
    assert path.parent.name == inbox.INBOX_TOPIC
    fields = _split_fm(path.read_text(encoding="utf-8"))
    # CONVENTIONS §5 strict fields must all be present so the existing pipeline
    # (sanitize / digest) treats a captured article exactly like a collected one.
    for key in ("source", "url", "title", "author", "date_published", "collected", "category"):
        assert key in fields, key
    assert fields["url"] == "https://example.com/a"
    assert fields["collected"] == "2026-06-21"
    assert fields["category"] == inbox.INBOX_TOPIC
    assert "Some article body." in path.read_text(encoding="utf-8")


def test_add_article_unique_filenames_for_same_title(tmp_path: Path) -> None:
    inc = tmp_path / "1-incoming"
    p1 = inbox.add_article(inc, url="https://x/1", title="Same", body="one", when=_WHEN)
    p2 = inbox.add_article(inc, url="https://x/2", title="Same", body="two", when=_WHEN)
    assert p1 != p2
    assert p1.exists() and p2.exists()


def test_concurrent_captures_same_title_distinct_urls_dont_collide(tmp_path: Path) -> None:
    # Two parallel /save of DIFFERENT urls that slugify to the SAME filename must
    # both land: the filename claim and the temp file must be per-capture unique,
    # not a shared `{stem}.md` + `{stem}.md.tmp` that races to a FileNotFoundError.
    import threading

    inc = tmp_path / "1-incoming"
    inc.mkdir(parents=True, exist_ok=True)
    barrier = threading.Barrier(8)
    paths: list[Path] = []
    errors: list[str] = []
    lock = threading.Lock()

    def _capture(i: int) -> None:
        barrier.wait()
        try:
            p = inbox.add_article(
                inc, url=f"https://site/article-{i}", title="Same Headline",
                body=f"body {i}", when=_WHEN,
            )
        except Exception as exc:  # noqa: BLE001 - record, assert none below
            with lock:
                errors.append(repr(exc))
            return
        with lock:
            if p is not None:
                paths.append(p)

    threads = [threading.Thread(target=_capture, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []  # no FileNotFoundError / temp-collision crash
    assert len(paths) == 8  # all eight distinct articles captured
    assert len({p.name for p in paths}) == 8  # ...to eight distinct filenames
    assert all(p.exists() for p in paths)
    assert inbox.count(inc) == 8


def test_add_article_appends_registry_row(tmp_path: Path) -> None:
    # /save must NOT bypass the registry: a captured article gets a blank-status
    # row so dedup and curation (which marks it terminal) have a record to act on.
    from scripts.registry import iter_registry_rows

    inc = tmp_path / "1-incoming"
    inbox.add_article(inc, url="https://example.com/a", title="A", body="b", when=_WHEN)
    registry = tmp_path / "registry.md"  # pipeline/registry.md, sibling of 1-incoming
    rows = list(iter_registry_rows(registry))
    assert [r.url for r in rows] == ["https://example.com/a"]
    assert rows[0].status == ""  # blank = collected, not yet curated


def test_add_article_is_idempotent_by_url(tmp_path: Path) -> None:
    # Re-saving the same URL (even in a different shape) must not create a second
    # file or a second registry row — the reproduced /save dedup bug.
    from scripts.registry import iter_registry_rows

    inc = tmp_path / "1-incoming"
    p1 = inbox.add_article(inc, url="https://example.com/a", title="A", body="one", when=_WHEN)
    p2 = inbox.add_article(inc, url="https://www.example.com/a/", title="A again", body="two", when=_WHEN)
    assert p1 == p2  # same canonical capture returned, no duplicate
    assert inbox.count(inc) == 1
    registry = tmp_path / "registry.md"
    assert len(list(iter_registry_rows(registry))) == 1


def test_add_article_rolls_back_file_when_registry_append_fails(
    tmp_path: Path, monkeypatch
) -> None:
    # If the registry-row append fails, the just-written inbox file must be rolled
    # back so file and registry stay consistent (no orphan that blocks a retry).
    inc = tmp_path / "1-incoming"

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(inbox, "append_registry_row_if_absent", _boom)
    with pytest.raises(OSError):
        inbox.add_article(inc, url="https://example.com/a", title="A", body="b", when=_WHEN)
    assert inbox.count(inc) == 0  # the orphan file was rolled back


def test_add_article_repairs_missing_registry_row_on_retry(
    tmp_path: Path, monkeypatch
) -> None:
    # A partial prior capture (file written, row append crashed) leaves a queued
    # file with no registry row. A retry of the same URL must repair the row rather
    # than dedup-hit and leave it invisible to curation forever.
    from scripts.registry import iter_registry_rows

    inc = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"

    # Simulate the crash AFTER the file is written by making the (atomic) row insert
    # a no-op that still reports success, mimicking a row that never landed.
    monkeypatch.setattr(inbox, "append_registry_row_if_absent", lambda *a, **k: True)
    inbox.add_article(inc, url="https://example.com/a", title="A", body="b", when=_WHEN)
    assert inbox.count(inc) == 1
    assert list(iter_registry_rows(registry)) == []  # orphan: file but no row

    # Retry the same URL — repair must append the missing row (no duplicate file).
    # The repair path uses the plain `append_registry_row`, which stays real here.
    monkeypatch.undo()
    inbox.add_article(inc, url="https://www.example.com/a/", title="A", body="b", when=_WHEN)
    assert inbox.count(inc) == 1  # still one file (dedup)
    rows = list(iter_registry_rows(registry))
    assert [r.url for r in rows] == ["https://example.com/a"]


def test_add_article_skips_url_already_in_registry(tmp_path: Path) -> None:
    # A URL already known to the pipeline (collected via feeds, possibly curated)
    # must not be re-captured into the inbox — the registry is the dedup key.
    from scripts.registry import append_registry_row

    inc = tmp_path / "1-incoming"
    inc.mkdir(parents=True, exist_ok=True)
    registry = tmp_path / "registry.md"
    append_registry_row(
        registry, collected="2026-06-01", category="ai",
        url="https://example.com/known", title="Known", status="processed",
    )
    inbox.add_article(inc, url="https://example.com/known", title="Known", body="b", when=_WHEN)
    assert inbox.count(inc) == 0  # nothing queued — already known


def test_url_in_registry_tolerates_malformed_stored_url(tmp_path: Path) -> None:
    # A stored registry row with an out-of-range port (normalize() would raise) must
    # not abort the `_url_in_registry` scan: a row further down is still matched.
    from scripts.registry import append_registry_row

    registry = tmp_path / "registry.md"
    append_registry_row(
        registry, collected="2026-06-01", category="ai",
        url="https://h:99999/p", title="broken", status="processed",
    )
    append_registry_row(
        registry, collected="2026-06-01", category="ai",
        url="https://example.com/known", title="Known", status="processed",
    )
    # Must not raise; the well-formed row beyond the malformed one is still found.
    assert inbox._url_in_registry(registry, "https://example.com/known") is True
    assert inbox._url_in_registry(registry, "https://example.com/absent") is False


def test_find_in_inbox_by_url_tolerates_poisoned_queue_entry(tmp_path: Path) -> None:
    # A queued article whose stored `url:` has an out-of-range port (normalize() would
    # raise) must not break the dedup scan for a DIFFERENT, well-formed /save — one
    # poisoned entry previously made every subsequent /save crash.
    inc = tmp_path / "1-incoming"
    good = inbox.add_article(
        inc, url="https://example.com/good", title="Good", body="body", when=_WHEN
    )
    # Hand-write a queued article with a malformed url directly into the queue dir
    # (bypassing add_article, which validates), simulating a pre-existing bad entry.
    poisoned = good.parent / "poisoned.md"
    poisoned.write_text(
        "---\nurl: https://h:99999/p\ntitle: Broken\n---\nbody\n", encoding="utf-8"
    )
    # The scan must not raise, and the well-formed article is still matched.
    assert inbox.find_in_inbox_by_url(inc, "https://example.com/good") == good
    assert inbox.find_in_inbox_by_url(inc, "https://example.com/absent") is None


def test_inbox_add_malformed_url_reports_clean_error(tmp_path, capsys) -> None:
    # `/save https://h:99999/p` (a typo'd, out-of-range port) must exit non-zero with a
    # readable ERROR line, not a raw ValueError traceback.
    inc = tmp_path / "1-incoming"
    inc.mkdir()
    body = tmp_path / "body.txt"
    body.write_text("some body", encoding="utf-8")
    rc = inbox.main(
        ["add", "--incoming", str(inc), "--url", "https://h:99999/p",
         "--title", "T", "--body-file", str(body)]
    )
    assert rc == 2
    assert "ERROR" in capsys.readouterr().err


def test_route_concurrent_same_stem_does_not_clobber(tmp_path: Path) -> None:
    # Parallel routes whose articles share the SAME stem into the SAME topic must
    # all persist: a `_unique_path()`-then-write is a TOCTOU where two routers see
    # the same name free and clobber. The atomic unique-claim gives each its own file.
    import threading

    inc = tmp_path / "1-incoming"

    def _write_inbox(idx: int) -> Path:
        # Each source lives in its own per-thread inbox subdir so the sources do not
        # collide, but every one shares the stem "dup" so the DESTINATION races.
        src_dir = inc / inbox.INBOX_TOPIC / f"s{idx}"
        src_dir.mkdir(parents=True, exist_ok=True)
        p = src_dir / "dup.md"
        p.write_text(
            f"---\ntitle: dup\nurl: https://example.com/{idx}\ncollected: 2026-06-01\n"
            f"category: {inbox.INBOX_TOPIC}\ntags: [_inbox]\n---\n\nbody {idx}\n",
            encoding="utf-8",
        )
        return p

    n = 8
    sources = [_write_inbox(i) for i in range(n)]
    barrier = threading.Barrier(n)
    dests: list[Path] = []
    errors: list[str] = []
    lock = threading.Lock()

    def _route(src: Path) -> None:
        barrier.wait()
        try:
            dest = inbox.route(inc, src, "ai-agents")
        except Exception as exc:  # noqa: BLE001 - record, assert none below
            with lock:
                errors.append(repr(exc))
            return
        with lock:
            dests.append(dest)

    threads = [threading.Thread(target=_route, args=(s,)) for s in sources]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    # Every route persisted to a DISTINCT destination — none clobbered.
    assert len({d.name for d in dests}) == n
    assert all(d.exists() for d in dests)


def test_add_article_loses_dedup_race_leaves_no_orphan(tmp_path: Path, monkeypatch) -> None:
    # If a concurrent writer registers the URL AFTER our pre-check but before our
    # locked append, the atomic insert reports "already present": the just-written
    # file must be rolled back (no orphan) and the call must return None.
    inc = tmp_path / "1-incoming"
    inc.mkdir(parents=True, exist_ok=True)

    # Force the atomic insert to report the URL was already there (race lost).
    monkeypatch.setattr(inbox, "append_registry_row_if_absent", lambda *a, **k: False)
    result = inbox.add_article(inc, url="https://example.com/raced", title="R", body="b", when=_WHEN)
    assert result is None  # treated as a duplicate
    assert inbox.count(inc) == 0  # the orphan file was rolled back


def test_add_article_frontmatter_is_valid_yaml_for_nasty_metadata(tmp_path: Path) -> None:
    # Hand-rolled interpolation produced INVALID yaml for an author like `a: b` or a
    # title ending in a backslash. The block must now parse cleanly (the strict
    # pipeline validator uses yaml.safe_load).
    import yaml

    inc = tmp_path / "1-incoming"
    path = inbox.add_article(
        inc,
        url="https://ex.com/p?x=1#frag",
        title="Weird: title ends with backslash\\",
        body="b",
        author="Doe, J: editor",
        source="web",
        tags=["ai/agents", "x: y"],
        when=_WHEN,
    )
    text = path.read_text(encoding="utf-8")
    block = text.split("---", 2)[1]
    data = yaml.safe_load(block)  # must not raise
    assert data["url"] == "https://ex.com/p?x=1#frag"
    assert data["author"] == "Doe, J: editor"
    assert data["title"].endswith("\\")
    assert data["tags"] == ["ai/agents", "x: y"]
    assert data["category"] == inbox.INBOX_TOPIC


def test_capture_defaults_satisfy_strict_validator(tmp_path: Path) -> None:
    # A capture with no author/tags must still pass the STRICT pipeline frontmatter
    # validator (CONVENTIONS §5 requires non-empty author + a non-empty tags list).
    import subprocess
    import sys

    inc = tmp_path / "1-incoming"
    inbox.add_article(inc, url="https://example.com/a", title="A", body="b", when=_WHEN)
    result = subprocess.run(
        [sys.executable, "scripts/validate-pipeline-frontmatter.py", str(inc / "_inbox"), "--strict"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_capture_default_author_and_tag_are_non_empty(tmp_path: Path) -> None:
    import yaml

    inc = tmp_path / "1-incoming"
    path = inbox.add_article(inc, url="https://example.com/a", title="A", body="b", when=_WHEN)
    data = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
    assert data["author"] == inbox.DEFAULT_CAPTURE_AUTHOR
    assert data["tags"] == [inbox.DEFAULT_CAPTURE_TAG]


def test_capture_preserves_explicit_author_and_tags(tmp_path: Path) -> None:
    import yaml

    inc = tmp_path / "1-incoming"
    path = inbox.add_article(
        inc, url="https://example.com/a", title="A", body="b", when=_WHEN,
        author="J. Doe", tags=["ai/agents", "tech/news"],
    )
    data = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
    assert data["author"] == "J. Doe"
    assert data["tags"] == ["ai/agents", "tech/news"]


def test_route_updates_registry_category(tmp_path: Path) -> None:
    # Routing an inbox article to its real topic must also retarget its registry
    # row's category (not just the file), so per-category stats stay accurate.
    from scripts.registry import iter_registry_rows

    inc = tmp_path / "1-incoming"
    art = inbox.add_article(inc, url="https://x/1", title="On Agents", body="b", when=_WHEN)
    registry = tmp_path / "registry.md"
    assert [r.category for r in iter_registry_rows(registry)] == [inbox.INBOX_TOPIC]

    inbox.route(inc, art, "ai-agents")
    rows = list(iter_registry_rows(registry))
    assert [r.category for r in rows] == ["ai-agents"]
    assert rows[0].url == "https://x/1"  # same row, only category changed


def test_slugify_is_filesystem_safe(tmp_path: Path) -> None:
    assert inbox.slugify("Hello, World! 2026") == "hello-world-2026"
    assert inbox.slugify("   ") == "untitled"


# ── queue accounting ─────────────────────────────────────────────────────────


def test_pending_and_count_ignore_companions(tmp_path: Path) -> None:
    inc = tmp_path / "1-incoming"
    p1 = inbox.add_article(inc, url="https://x/1", title="One", body="b", when=_WHEN)
    p2 = inbox.add_article(inc, url="https://x/2", title="Two", body="b", when=_WHEN)
    # A sanitized companion under _inbox/sanitized/ must NOT be counted as pending.
    (inc / inbox.INBOX_TOPIC / "sanitized").mkdir(parents=True, exist_ok=True)
    (inc / inbox.INBOX_TOPIC / "sanitized" / "x.md").write_text("companion", encoding="utf-8")
    assert inbox.count(inc) == 2
    # pending() returns exactly the two articles — never the companion.
    assert {p.name for p in inbox.pending(inc)} == {p1.name, p2.name}


def test_threshold_reached(tmp_path: Path) -> None:
    inc = tmp_path / "1-incoming"
    for i in range(3):
        inbox.add_article(inc, url=f"https://x/{i}", title=f"T{i}", body="b", when=_WHEN)
    assert inbox.threshold_reached(inc, threshold=5) is False
    assert inbox.threshold_reached(inc, threshold=3) is True


def test_count_zero_when_no_inbox(tmp_path: Path) -> None:
    assert inbox.count(tmp_path / "1-incoming") == 0
    assert inbox.pending(tmp_path / "1-incoming") == []


# ── route ────────────────────────────────────────────────────────────────────


def test_route_moves_article_to_topic_and_updates_category(tmp_path: Path) -> None:
    inc = tmp_path / "1-incoming"
    art = inbox.add_article(inc, url="https://x/1", title="On Agents", body="b", when=_WHEN)
    dest = inbox.route(inc, art, "ai-agents")
    assert dest.parent.name == "ai-agents"
    assert not art.exists()  # moved out of the inbox
    fields = _split_fm(dest.read_text(encoding="utf-8"))
    # Category must follow the move so the digest groups it under the real topic.
    assert fields["category"] == "ai-agents"


def test_route_drops_stale_companion(tmp_path: Path) -> None:
    inc = tmp_path / "1-incoming"
    art = inbox.add_article(inc, url="https://x/1", title="On Agents", body="b", when=_WHEN)
    # A companion written before routing is location/hash-bound to the inbox — it
    # must be dropped so re-sanitization regenerates a correct one at the new path.
    comp_dir = inc / inbox.INBOX_TOPIC / "sanitized"
    comp_dir.mkdir(parents=True, exist_ok=True)
    (comp_dir / art.name).write_text("stale companion", encoding="utf-8")
    inbox.route(inc, art, "ai-agents")
    assert not (comp_dir / art.name).exists()


def test_route_heals_crashed_route_instead_of_duplicating(tmp_path: Path) -> None:
    # Crash window: a previous route wrote the topic copy but died before
    # unlinking the source, so the article sits in BOTH _inbox/ and the topic
    # dir. The retry must adopt the existing copy and finish the cleanup — not
    # write a second copy that the digest would then count twice.
    inc = tmp_path / "1-incoming"
    art = inbox.add_article(
        inc, url="https://x/crash", title="Crash Mid Route", body="b", when=_WHEN
    )
    topic_dir = inc / "ai-agents"
    topic_dir.mkdir(parents=True)
    pre_routed = topic_dir / art.name
    pre_routed.write_text(
        art.read_text(encoding="utf-8").replace(
            f"category: {inbox.INBOX_TOPIC}", "category: ai-agents"
        ),
        encoding="utf-8",
    )

    dest = inbox.route(inc, art, "ai-agents")

    assert dest == pre_routed
    assert not art.exists()  # cleanup finished: source left the inbox
    assert len(list(topic_dir.glob("*.md"))) == 1
    # The registry row follows the (re)route even though the copy pre-existed —
    # the crash may equally have hit before the registry retarget.
    from scripts.registry import iter_registry_rows

    rows = list(iter_registry_rows(inc.parent / "registry.md"))
    assert [row.category for row in rows] == ["ai-agents"]


def test_route_heals_cross_topic_crash_without_duplicating(tmp_path: Path) -> None:
    # A route to topic-a crashed after writing its copy; the retry (driven by
    # LLM curation) picks topic-b this time. The heal must adopt the topic-a
    # copy wherever it landed — not write a second copy under topic-b and leave
    # the topic-a orphan double-counted downstream.
    inc = tmp_path / "1-incoming"
    art = inbox.add_article(
        inc, url="https://x/crash2", title="Cross Topic", body="b", when=_WHEN
    )
    (inc / "topic-a").mkdir(parents=True)
    pre_routed = inc / "topic-a" / art.name
    pre_routed.write_text(
        art.read_text(encoding="utf-8").replace(
            f"category: {inbox.INBOX_TOPIC}", "category: topic-a"
        ),
        encoding="utf-8",
    )

    dest = inbox.route(inc, art, "topic-b")

    assert dest == pre_routed
    assert not art.exists()
    topic_b = inc / "topic-b"
    assert not topic_b.exists() or list(topic_b.glob("*.md")) == []
    # The registry follows the copy's REAL topic, not the retry's request.
    from scripts.registry import iter_registry_rows

    rows = list(iter_registry_rows(inc.parent / "registry.md"))
    assert [row.category for row in rows] == ["topic-a"]


def test_route_with_empty_quoted_url_does_not_adopt_unrelated_article(
    tmp_path: Path,
) -> None:
    # `url: ''` must read as empty — not as the truthy two-character string
    # "''" whose normalized key matches EVERY URL-less article, making the
    # adopt scan "heal" onto an unrelated file and destroy the routed
    # article's content.
    inc = tmp_path / "1-incoming"
    inbox_d = inc / inbox.INBOX_TOPIC
    inbox_d.mkdir(parents=True)
    art = inbox_d / "2026-06-21_no-url.md"
    art.write_text(
        "---\ntitle: No URL\nurl: ''\ncategory: _inbox\n---\n\nunique body A\n",
        encoding="utf-8",
    )
    topic = inc / "ai-agents"
    topic.mkdir(parents=True)
    other = topic / "2026-06-20_other.md"
    other.write_text(
        "---\ntitle: Other\nurl: ''\ncategory: ai-agents\n---\n\nunrelated body B\n",
        encoding="utf-8",
    )

    dest = inbox.route(inc, art, "ai-agents")

    assert dest != other
    assert "unique body A" in dest.read_text(encoding="utf-8")
    assert not art.exists()
    assert len(list(topic.glob("*.md"))) == 2


def test_route_concurrent_same_article_yields_single_copy(tmp_path: Path) -> None:
    # Two routes of the SAME article racing (e.g. two /process drains) must
    # produce exactly one topic copy. The barrier inside the injected writer
    # forces both threads into the write window at once — without route-level
    # locking both writes land (as -2 disambiguated names) and the article
    # is counted twice downstream.
    import dataclasses
    import threading

    from scripts.inbox_flow import queue as inbox_queue

    inc = tmp_path / "1-incoming"
    art = inbox.add_article(
        inc, url="https://x/race", title="Race Route", body="b", when=_WHEN
    )
    write_barrier = threading.Barrier(2)
    base = inbox_queue.default_deps()

    def barriered_write(directory: Path, stem: str, text: str, suffix: str = ".md") -> Path:
        try:
            write_barrier.wait(timeout=0.3)  # only met when BOTH threads write
        except threading.BrokenBarrierError:
            pass  # serialized (locked) execution never meets the barrier — fine
        return base.atomic_write_unique(directory, stem, text, suffix)

    deps = dataclasses.replace(base, atomic_write_unique=barriered_write)
    start = threading.Barrier(2)
    dests: list[Path] = []
    record = threading.Lock()

    def _route() -> None:
        start.wait()
        try:
            dest = inbox_queue.route(inc, art, "ai-agents", deps=deps)
        except FileNotFoundError:
            return  # acceptable: the loser may find the source already consumed
        with record:
            dests.append(dest)

    threads = [threading.Thread(target=_route) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    files = list((inc / "ai-agents").glob("*.md"))
    assert len(files) == 1, f"concurrent same-article route duplicated: {files}"
    assert dests, "at least the winning route must return the destination"
    assert all(dest == files[0] for dest in dests)


def test_route_unknown_article_raises(tmp_path: Path) -> None:
    inc = tmp_path / "1-incoming"
    try:
        inbox.route(inc, inc / inbox.INBOX_TOPIC / "nope.md", "ai-agents")
    except FileNotFoundError:
        pass
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("routing a missing article must raise FileNotFoundError")


# ── route topic validation (path-traversal guard) ────────────────────────────


import pytest  # noqa: E402 - kept local to the validation tests it supports


@pytest.mark.parametrize(
    "bad_topic",
    [
        "../../../../tmp/escaped",  # parent-dir traversal
        "/tmp/escaped",  # absolute path
        "ai/agents",  # forward separator
        "ai\\agents",  # backslash separator
        "..",  # bare parent ref
        "",  # empty / whitespace-only is not a valid topic
        "   ",
        # Reserved: routing INTO the inbox queue itself would make the adopt
        # scan match the SOURCE article by its own URL and delete the only copy.
        "_inbox",
    ],
)
def test_route_rejects_unsafe_topic(tmp_path: Path, bad_topic: str) -> None:
    # The agent picks `topic` closed-book; it must never be able to write outside the
    # incoming tree. An unsafe topic is rejected and the article stays put untouched.
    inc = tmp_path / "1-incoming"
    art = inbox.add_article(inc, url="https://x/1", title="On Agents", body="b", when=_WHEN)
    with pytest.raises(ValueError):
        inbox.route(inc, art, bad_topic)
    # The source article must remain in the inbox — nothing was moved or deleted.
    assert art.exists()


def test_route_rejects_article_outside_inbox(tmp_path: Path) -> None:
    # route() unlinks its source, so it must refuse any article that does not live
    # inside the inbox dir — otherwise a stray path (e.g. a config file) would be
    # read, copied into incoming, AND deleted. The outside file must be untouched.
    inc = tmp_path / "1-incoming"
    inc.mkdir(parents=True, exist_ok=True)
    victim = tmp_path / "config" / "channels.yaml"
    victim.parent.mkdir(parents=True, exist_ok=True)
    victim.write_text("telegram:\n  enabled: true\n", encoding="utf-8")
    with pytest.raises(ValueError):
        inbox.route(inc, victim, "ai-agents")
    assert victim.exists()  # never deleted
    # And nothing was copied into the incoming tree.
    assert not (inc / "ai-agents").exists()


def test_route_rejects_article_in_incoming_but_outside_inbox(tmp_path: Path) -> None:
    # A real topic article (already routed) is inside incoming but NOT in _inbox/;
    # routing it again must be rejected rather than move+delete a curated file.
    inc = tmp_path / "1-incoming"
    routed = inc / "ai" / "2026-06-21_already.md"
    routed.parent.mkdir(parents=True, exist_ok=True)
    routed.write_text("---\ncategory: ai\n---\nbody\n", encoding="utf-8")
    with pytest.raises(ValueError):
        inbox.route(inc, routed, "ml")
    assert routed.exists()


def test_route_unsafe_topic_writes_nothing_outside_incoming(tmp_path: Path) -> None:
    # Belt-and-braces: confirm a traversal attempt leaves no file outside the tree.
    inc = tmp_path / "1-incoming"
    art = inbox.add_article(inc, url="https://x/1", title="On Agents", body="b", when=_WHEN)
    escaped = tmp_path / "escaped"
    with pytest.raises(ValueError):
        inbox.route(inc, art, "../escaped")
    assert not escaped.exists()
    # Every written file is still inside `inc`.
    for p in inc.rglob("*"):
        assert inc.resolve() in p.resolve().parents or p.resolve() == inc.resolve()


# ── atomic write failure path ────────────────────────────────────────────────


def test_atomic_write_cleans_up_tmp_and_reraises_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the os.replace step fails (e.g. disk full), the temp sibling must be removed
    # and the error must propagate — never leave a half-written .tmp behind nor a
    # truncated final file.
    target = tmp_path / "sub" / "note.md"

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(inbox.os, "replace", _boom)
    with pytest.raises(OSError):
        inbox._atomic_write_text(target, "hello")
    assert not target.exists()
    # The temp now carries a per-process+random suffix; assert NONE linger (the old
    # fixed `note.md.tmp` check was vacuously true after the unique-temp change).
    assert list(target.parent.glob(f"{target.name}.tmp.*")) == []


# ── CLI (main) ───────────────────────────────────────────────────────────────


def _body_file(tmp_path: Path, text: str = "Captured body.") -> Path:
    f = tmp_path / "body.txt"
    f.write_text(text, encoding="utf-8")
    return f


def test_main_add_captures_and_reports_queue(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inc = tmp_path / "1-incoming"
    rc = inbox.main([
        "add", "--incoming", str(inc),
        "--url", "https://x/1", "--title", "A Read",
        "--body-file", str(_body_file(tmp_path)),
        "--tags", "ai, agents",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "captured" in out and "queued: 1" in out
    # The tags arg is split + threaded through to the written article.
    (article,) = inbox.pending(inc)
    assert "ai" in article.read_text(encoding="utf-8")


def test_main_count_prints_ready_at_threshold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inc = tmp_path / "1-incoming"
    inbox.add_article(inc, url="https://x/1", title="One", body="b", when=_WHEN)
    rc = inbox.main(["count", "--incoming", str(inc), "--threshold", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "queued: 1" in out and "READY" in out


def test_main_pending_lists_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inc = tmp_path / "1-incoming"
    art = inbox.add_article(inc, url="https://x/1", title="One", body="b", when=_WHEN)
    rc = inbox.main(["pending", "--incoming", str(inc)])
    assert rc == 0
    assert art.name in capsys.readouterr().out


def test_main_route_moves_article(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inc = tmp_path / "1-incoming"
    art = inbox.add_article(inc, url="https://x/1", title="One", body="b", when=_WHEN)
    rc = inbox.main(["route", "--incoming", str(inc), str(art), "ai-agents"])
    assert rc == 0
    assert "routed" in capsys.readouterr().out
    assert not art.exists()


def test_main_no_command_prints_help(
    capsys: pytest.CaptureFixture[str]
) -> None:
    # A bare invocation falls through to the help text (and exits 0, not an error).
    rc = inbox.main([])
    assert rc == 0
    assert "usage" in capsys.readouterr().out.lower()


# ── PyYAML guard ─────────────────────────────────────────────────────────────
# inbox.py writes frontmatter via PyYAML. PyYAML is a declared runtime dependency
# (pyproject.toml [project].dependencies), but if a user runs this script with a
# bare system Python where it is absent, the failure must be the same friendly,
# actionable message the rest of the pipeline emits — not a raw ModuleNotFoundError.

import builtins  # noqa: E402 - kept local to the guard tests it supports


def test_load_yaml_returns_module_when_present() -> None:
    # Happy path: the lazy loader returns the real PyYAML module.
    yaml = inbox._load_yaml()
    assert hasattr(yaml, "safe_dump")


def test_load_yaml_missing_exits_with_actionable_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Simulate PyYAML being uninstalled: intercept `import yaml` only.
    real_import = builtins.__import__

    def _fake_import(name: str, *args: object, **kwargs: object):
        if name == "yaml":
            raise ImportError("No module named 'yaml'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    with pytest.raises(SystemExit) as exc:
        inbox._load_yaml()
    assert exc.value.code != 0  # non-zero: the write genuinely cannot proceed
    err = capsys.readouterr().err
    assert "PyYAML" in err
    assert "pip install" in err
