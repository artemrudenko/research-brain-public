"""
test_source_journal.py — the append-only collection-decision journal.

Nothing in the pipeline currently remembers WHY a candidate was or wasn't
collected. The registry records what landed; everything rejected — the
off-topic, the too-short, the duplicate — vanishes. That makes "is this source
actually useful?" unanswerable: a feed that produces fifty candidates and one
keeper looks identical to one that produces two candidates and one keeper.

This journal is the missing half. Three properties make it safe to write from
inside the collection loop, and each is pinned here:

  - **It can never break collection.** A full disk, a read-only volume, a
    permission error: the write fails silently and the article is still saved.
    Observability is strictly subordinate to the pipeline's real work.
  - **It relocates with the rest of the runtime state.** Same
    `RESEARCH_BRAIN_STATE_DIR` resolver as the delivery receipts, the health log
    and the feedback log — not a fourth path convention.
  - **A torn line is survivable.** The log is append-only across crashes and
    concurrent runs, so the reader skips garbage rather than failing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.source_report.events import journal_path, read_decisions, record_decision
from scripts.source_report.model import DECISIONS, CandidateDecision


def _decision(**kw: object) -> CandidateDecision:
    base: dict[str, object] = {
        "topic": "ai-agents",
        "source_url": "https://example.com/feed.xml",
        "candidate_url": "https://example.com/posts/hello",
        "decision": "selected",
        "reason_codes": ("recent",),
    }
    base.update(kw)
    return CandidateDecision(**base)  # type: ignore[arg-type]


# ── writing ───────────────────────────────────────────────────────────────────


def test_record_appends_one_parseable_line(tmp_path: Path) -> None:
    assert record_decision(tmp_path, _decision()) is True
    lines = journal_path(tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["decision"] == "selected"
    assert entry["topic"] == "ai-agents"
    assert entry["candidate_url"] == "https://example.com/posts/hello"
    assert entry["schema"] == "collection_candidate.v1"
    assert entry["ts"]


def test_records_accumulate_rather_than_overwrite(tmp_path: Path) -> None:
    record_decision(tmp_path, _decision(candidate_url="https://example.com/a"))
    record_decision(tmp_path, _decision(candidate_url="https://example.com/b"))
    assert len(read_decisions(tmp_path)) == 2


def test_author_and_ranking_are_optional_and_omitted_when_absent(tmp_path: Path) -> None:
    record_decision(tmp_path, _decision())
    entry = json.loads(journal_path(tmp_path).read_text(encoding="utf-8").strip())
    # The RSS-lite path has no relevance score and often no author; the entry
    # stays honest rather than carrying empty scaffolding.
    assert "author" not in entry
    assert "ranking" not in entry


def test_author_is_recorded_when_known(tmp_path: Path) -> None:
    record_decision(
        tmp_path, _decision(author_name="Jane Doe", author_url="https://example.com/jane")
    )
    entry = json.loads(journal_path(tmp_path).read_text(encoding="utf-8").strip())
    assert entry["author"] == {"name": "Jane Doe", "url": "https://example.com/jane"}


# ── the closed decision vocabulary ────────────────────────────────────────────


def test_every_documented_decision_code_is_accepted(tmp_path: Path) -> None:
    for code in sorted(DECISIONS):
        assert record_decision(tmp_path, _decision(decision=code)) is True
    assert len(read_decisions(tmp_path)) == len(DECISIONS)


def test_unknown_decision_code_is_rejected_at_construction() -> None:
    """Metrics group on `decision`, so a typo would silently create a new bucket."""
    with pytest.raises(ValueError, match="unknown decision"):
        _decision(decision="totally_made_up")


def test_reason_codes_stay_open_but_slug_shaped() -> None:
    # Reason codes explain a decision and will grow; they are validated for shape
    # only, so a new one needs no schema change.
    assert _decision(reason_codes=("high_relevance", "primary-source")).reason_codes
    with pytest.raises(ValueError, match="reason code"):
        _decision(reason_codes=("not a slug!",))


# ── bounded, hostile-input-safe ───────────────────────────────────────────────


def test_free_text_fields_are_capped(tmp_path: Path) -> None:
    from scripts.source_report.model import TITLE_CAP

    record_decision(tmp_path, _decision(title="T" * (TITLE_CAP + 500)))
    entry = json.loads(journal_path(tmp_path).read_text(encoding="utf-8").strip())
    assert len(entry["title"]) == TITLE_CAP


def test_newlines_in_a_title_cannot_forge_a_second_entry(tmp_path: Path) -> None:
    # One record must be one line. A title carrying a newline plus valid JSON
    # would otherwise inject a fabricated decision into the log.
    forged = 'x\n{"schema":"collection_candidate.v1","decision":"selected"}'
    record_decision(tmp_path, _decision(title=forged))
    assert len(journal_path(tmp_path).read_text(encoding="utf-8").strip().splitlines()) == 1
    assert len(read_decisions(tmp_path)) == 1


# ── reading ───────────────────────────────────────────────────────────────────


def test_missing_log_reads_as_empty(tmp_path: Path) -> None:
    assert read_decisions(tmp_path) == []


def test_corrupt_line_is_skipped_not_fatal(tmp_path: Path) -> None:
    record_decision(tmp_path, _decision())
    path = journal_path(tmp_path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{ this is not json\n")
    record_decision(tmp_path, _decision(candidate_url="https://example.com/b"))

    entries = read_decisions(tmp_path)
    assert len(entries) == 2
    assert {e["candidate_url"] for e in entries} == {
        "https://example.com/posts/hello",
        "https://example.com/b",
    }


# ── never breaks collection ───────────────────────────────────────────────────


def test_unwritable_location_fails_quietly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A journal write must never raise into the collection loop."""

    def boom(*_a: object, **_kw: object) -> int:
        raise OSError("disk full")

    monkeypatch.setattr("scripts.source_report.events.os.open", boom)
    assert record_decision(tmp_path, _decision()) is False


def test_record_decision_does_not_block_on_a_held_journal_lock(tmp_path: Path) -> None:
    """A journal write must never STALL the collect loop.

    The lock serialises the writer against `rotate_pipeline`'s compaction. If the
    compactor holds it, the writer must drop the row (best-effort, per the failure
    contract) rather than block indefinitely — losing an observability row is
    acceptable; stalling collection is not. A zero timeout makes a single
    non-blocking attempt, so this asserts the fail-fast path deterministically.
    """
    from scripts.registry import advisory_lock

    journal = journal_path(tmp_path)
    lock_path = journal.with_name(journal.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with advisory_lock(lock_path):  # stand in for an in-progress compaction
        assert record_decision(tmp_path, _decision(), lock_timeout=0.0) is False
    # The contended write appended nothing.
    assert read_decisions(tmp_path) == []


def test_contention_stall_does_not_multiply_across_candidates(tmp_path: Path) -> None:
    """The per-write timeout must not become a per-CANDIDATE tax.

    External review 2026-07-25 P2: `record_decision` is called once per candidate
    from inside the collection loop with a 2 s lock budget. The docstring claimed
    a compaction "can never stall the collect loop", but the bound is per call —
    a held lock costs 2 s × N, so ~100 candidates approaches ~200 s of pure
    waiting for rows that are, by contract, droppable. After the first contention
    the writer must stop paying the full budget.
    """
    import time

    from scripts.registry import advisory_lock
    from scripts.source_report import events

    journal = journal_path(tmp_path)
    lock_path = journal.with_name(journal.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    events._reset_lock_contention()

    budget = 0.2
    with advisory_lock(lock_path):
        started = time.monotonic()
        for _ in range(3):
            assert record_decision(tmp_path, _decision(), lock_timeout=budget) is False
        elapsed = time.monotonic() - started

    # Only the FIRST write may spend the budget; the rest fail fast.
    assert elapsed < budget * 2, (
        f"three contended writes took {elapsed:.2f}s — the per-write timeout is "
        "still multiplying across candidates"
    )


def test_contention_backoff_clears_so_journaling_resumes(tmp_path: Path) -> None:
    """The fast-fail must be a temporary backoff, not a permanent silencing —
    once the compactor releases, rows have to land again."""
    from scripts.registry import advisory_lock
    from scripts.source_report import events

    journal = journal_path(tmp_path)
    lock_path = journal.with_name(journal.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    events._reset_lock_contention()

    with advisory_lock(lock_path):
        assert record_decision(tmp_path, _decision(), lock_timeout=0.05) is False

    events._reset_lock_contention()  # stand in for the cooldown elapsing
    assert record_decision(tmp_path, _decision()) is True
    assert len(read_decisions(tmp_path)) == 1


def test_unreadable_log_reads_as_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record_decision(tmp_path, _decision())

    def boom(*_a: object, **_kw: object) -> str:
        raise OSError("I/O error")

    monkeypatch.setattr(Path, "read_text", boom)
    assert read_decisions(tmp_path) == []


# ── relocatable runtime state ─────────────────────────────────────────────────


def test_journal_defaults_into_the_pipeline_dir(tmp_path: Path) -> None:
    assert journal_path(tmp_path) == tmp_path / "pipeline" / ".source-insights" / "events.jsonl"


def test_journal_relocates_with_the_state_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    volume = tmp_path / "volume"
    monkeypatch.setenv("RESEARCH_BRAIN_STATE_DIR", str(volume))
    resolved = journal_path(tmp_path)
    assert volume in resolved.parents
    assert resolved.name == "events.jsonl"


# ── the collector actually writes it ──────────────────────────────────────────
#
# The gates matter more than the happy path here: `setup_check.py` calls
# `collect_category` directly on every health probe, so a journal that wrote by
# default would fill up with phantom runs nobody triggered.


def _collect(tmp_path: Path, **kw: object) -> object:
    from scripts import collect
    from tests.test_collect import _TODAY, RSS_SAMPLE, _rss_source

    def fetch(url: str, **_: object) -> str:
        return RSS_SAMPLE

    params: dict[str, object] = {
        "category": "ai",
        "sources": [_rss_source()],
        "incoming_dir": tmp_path / "1-incoming",
        "registry_path": tmp_path / "registry.md",
        "today": _TODAY,
        "known_urls": set(),
        "fetch_fn": fetch,
    }
    params.update(kw)
    return collect.collect_category(**params)  # type: ignore[arg-type]


def test_collector_journals_selected_candidates(tmp_path: Path) -> None:
    _collect(tmp_path, journal_root=tmp_path, run_id="run-1")
    entries = read_decisions(tmp_path)
    assert entries, "a real collect run must leave a decision trail"
    selected = [e for e in entries if e["decision"] == "selected"]
    assert selected
    assert selected[0]["topic"] == "ai"
    assert selected[0]["source_url"] == "https://feed.example.com/rss.xml"
    assert selected[0]["run_id"] == "run-1"


def test_collector_journals_duplicates_with_the_predicate_that_fired(tmp_path: Path) -> None:
    known = {"https://blog.example.com/first-post"}
    _collect(tmp_path, journal_root=tmp_path, known_urls=known)
    dups = [e for e in read_decisions(tmp_path) if e["decision"] == "duplicate_url"]
    assert dups, "a registry hit must be recorded, not just counted"
    assert dups[0]["reason_codes"] == ["registry"]


def test_dry_run_writes_no_journal(tmp_path: Path) -> None:
    """A dry run reports what it would save and records nothing."""
    result = _collect(tmp_path, journal_root=tmp_path, dry_run=True)
    assert result.saved >= 1
    assert read_decisions(tmp_path) == []
    assert not journal_path(tmp_path).exists()


def test_journaling_is_off_unless_a_root_is_given(tmp_path: Path) -> None:
    """The default is silence — `setup_check` probes must not pollute the log."""
    _collect(tmp_path)
    assert read_decisions(tmp_path) == []


def test_a_failing_journal_never_breaks_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Patched at the collector's own seam. (Patching `events.os.open` would hit
    # `os.open` globally and take the registry write down with it — which is how
    # this test first caught that the guarantee rested on the wrong seam.)
    def boom(*_a: object, **_kw: object) -> bool:
        raise OSError("disk full")

    monkeypatch.setattr("scripts.collect.record_decision", boom)
    result = _collect(tmp_path, journal_root=tmp_path)
    assert result.saved >= 1, "articles must still be collected"


# ── retention ─────────────────────────────────────────────────────────────────


def _write_raw(root: Path, *entries: dict[str, object]) -> None:
    path = journal_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8"
    )


def _row(days_ago: int, url: str) -> dict[str, object]:
    from datetime import UTC, datetime, timedelta

    return {
        "ts": (datetime.now(UTC) - timedelta(days=days_ago)).isoformat(timespec="seconds"),
        "schema": "collection_candidate.v1",
        "topic": "ai",
        "source_url": "https://example.com/feed.xml",
        "candidate_url": url,
        "decision": "selected",
    }


def test_rotation_prunes_journal_rows_past_the_journal_horizon(tmp_path: Path) -> None:
    from scripts.rotate_pipeline import rotate

    _write_raw(tmp_path, _row(400, "https://example.com/ancient"), _row(3, "https://example.com/new"))
    result = rotate(tmp_path)

    assert result.journal_dropped == 1
    urls = {e["candidate_url"] for e in read_decisions(tmp_path)}
    assert urls == {"https://example.com/new"}


def test_journal_outlives_the_ordinary_artifact_horizon(tmp_path: Path) -> None:
    """Source usefulness needs many runs of history, so the journal is kept longer.

    A row older than DEFAULT_KEEP_DAYS (which prunes digests and the health log)
    but younger than JOURNAL_KEEP_DAYS must survive — that extra history is the
    whole point of keeping the journal at all.
    """
    from scripts.rotate_pipeline import DEFAULT_KEEP_DAYS, JOURNAL_KEEP_DAYS, rotate

    assert JOURNAL_KEEP_DAYS > DEFAULT_KEEP_DAYS
    _write_raw(tmp_path, _row(DEFAULT_KEEP_DAYS + 20, "https://example.com/older"))
    result = rotate(tmp_path)

    assert result.journal_dropped == 0
    assert len(read_decisions(tmp_path)) == 1


def test_rotation_keeps_unparseable_journal_lines(tmp_path: Path) -> None:
    # Never guess at a line we cannot date — dropping it would silently destroy
    # data on a format change.
    _write_raw(tmp_path, _row(400, "https://example.com/ancient"))
    with journal_path(tmp_path).open("a", encoding="utf-8") as fh:
        fh.write("{ torn line\n")

    from scripts.rotate_pipeline import rotate

    rotate(tmp_path)
    assert "torn line" in journal_path(tmp_path).read_text(encoding="utf-8")


# ── the read facade ───────────────────────────────────────────────────────────


def test_summary_groups_by_source_and_flags_thin_evidence(tmp_path: Path) -> None:
    from scripts.source_insights import MIN_OBSERVATIONS, summarize

    for i in range(MIN_OBSERVATIONS):
        record_decision(tmp_path, _decision(candidate_url=f"https://example.com/{i}"))
    record_decision(
        tmp_path,
        _decision(source_url="https://quiet.example/feed.xml", decision="too_short"),
    )

    data = summarize(tmp_path)
    by_url = {s.source_url: s for s in data.sources}
    assert by_url["https://example.com/feed.xml"].confident is True
    # One observation says nothing about a source — the report must say so
    # rather than rendering a confident-looking 100% rejection rate.
    assert by_url["https://quiet.example/feed.xml"].confident is False


def test_summary_on_an_empty_journal_explains_itself(tmp_path: Path) -> None:
    from scripts.source_insights import main

    assert main(["--root", str(tmp_path), "summary"]) == 0


def test_cli_list_outputs_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.source_insights import main

    record_decision(tmp_path, _decision())
    assert main(["--root", str(tmp_path), "list", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["decision"] == "selected"


def test_main_journals_beside_a_real_pipeline_not_the_checkout(tmp_path: Path) -> None:
    """`main()` must journal where it is operating, never into this checkout.

    Regression: the root was originally hardcoded to the project root, so every
    test that ran `collect.main()` with temp paths appended fixture rows to the
    developer's own journal.
    """
    from scripts import collect

    repo_journal = journal_path(Path(collect.__file__).resolve().parents[1])
    before = repo_journal.read_text(encoding="utf-8") if repo_journal.exists() else ""

    sources = tmp_path / "sources.yaml"
    sources.write_text(
        "categories:\n  - name: ai\n    sources:\n"
        "      - url: https://feed.example.com/rss.xml\n        type: rss\n"
        "        tier: high\n        active: true\n",
        encoding="utf-8",
    )
    collect.main(
        [
            "--sources", str(sources),
            "--incoming", str(tmp_path / "1-incoming"),
            "--registry", str(tmp_path / "registry.md"),
            "--today", "2026-07-21",
            "--dry-run",
        ]
    )

    after = repo_journal.read_text(encoding="utf-8") if repo_journal.exists() else ""
    assert after == before, "a test run must not append to the repo's own journal"
