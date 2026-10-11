"""tests for scripts/rotate_pipeline.py — bounded growth for pipeline artifacts.

Dated artifacts in pipeline/3-synthesis/ (digests, brain-health, trends,
synthesis-run logs) and the append-only health event log grew forever. Rotation
MOVES old artifacts into pipeline/0-archive/ (never deletes) and compacts the
event log by date — receipts, sidecars, and per-topic dirs are never touched.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from scripts import rotate_pipeline as rp

TODAY = date(2026, 7, 3)


def _vault(tmp_path: Path) -> Path:
    synth = tmp_path / "pipeline" / "3-synthesis"
    synth.mkdir(parents=True)
    return tmp_path


def _touch(root: Path, rel: str, text: str = "x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_moves_old_dated_artifacts_keeps_recent(tmp_path):
    root = _vault(tmp_path)
    old = [
        _touch(root, "pipeline/3-synthesis/digest_2026-01-05.md"),
        _touch(root, "pipeline/3-synthesis/digest_2026-01-05.html"),
        _touch(root, "pipeline/3-synthesis/brain-health_2026-02-01.md"),
        _touch(root, "pipeline/3-synthesis/trends_2026-01-12.md"),
        _touch(root, "pipeline/3-synthesis/synthesis-run_2026-01-19.md"),
    ]
    fresh = _touch(root, "pipeline/3-synthesis/digest_2026-06-29.md")

    result = rp.rotate(root, today=TODAY, keep_days=90)

    archive = root / "pipeline" / "0-archive" / "3-synthesis"
    for path in old:
        assert not path.exists()
        assert (archive / path.name).exists()
    assert fresh.exists()
    assert result.moved == len(old)


def test_never_touches_receipts_sidecars_topic_dirs_or_undated_files(tmp_path):
    root = _vault(tmp_path)
    keep = [
        _touch(root, "pipeline/3-synthesis/.delivered/digest_2026-01-05.json"),
        _touch(root, "pipeline/3-synthesis/ai-agents/digest-lead.md"),
        _touch(root, "pipeline/3-synthesis/ai-agents/.synthesis-meta.json"),
        _touch(root, "pipeline/3-synthesis/notes.md"),
    ]
    rp.rotate(root, today=TODAY, keep_days=90)
    for path in keep:
        assert path.exists(), path


def test_compacts_event_log_by_date_keeping_unparseable_lines(tmp_path):
    root = _vault(tmp_path)
    events = root / "pipeline" / ".health" / "events.jsonl"
    events.parent.mkdir(parents=True)
    lines = [
        json.dumps({"ts": "2026-01-01T09:00:00+00:00", "kind": "collect", "status": "ok"}),
        json.dumps({"ts": "2026-07-01T09:00:00+00:00", "kind": "deliver", "status": "sent"}),
        "not-json-garbage",
    ]
    events.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = rp.rotate(root, today=TODAY, keep_days=90)

    kept = events.read_text(encoding="utf-8").splitlines()
    assert len(kept) == 2  # recent event + the unparseable line survive
    assert any("2026-07-01" in line for line in kept)
    assert "not-json-garbage" in kept
    assert result.events_dropped == 1


def test_compacts_relocated_event_log_under_state_dir(tmp_path, monkeypatch):
    # With RESEARCH_BRAIN_STATE_DIR set, record_event/load_events write the event log
    # onto the persistent volume, NOT the in-repo pipeline/.health/. Rotation must
    # compact the SAME file the rest of the runtime uses — otherwise it reports
    # "0 dropped" forever while the live log grows unbounded.
    from scripts.health_checks.events import events_path

    root = _vault(tmp_path)
    state_dir = tmp_path / "state"
    monkeypatch.setenv("RESEARCH_BRAIN_STATE_DIR", str(state_dir))

    events = events_path(root)  # resolves under state_dir, not root/pipeline
    events.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"ts": "2026-01-01T09:00:00+00:00", "kind": "collect", "status": "ok"}),
        json.dumps({"ts": "2026-07-01T09:00:00+00:00", "kind": "deliver", "status": "sent"}),
    ]
    events.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = rp.rotate(root, today=TODAY, keep_days=90)

    assert result.events_dropped == 1
    kept = events.read_text(encoding="utf-8").splitlines()
    assert len(kept) == 1
    assert "2026-07-01" in kept[0]


def test_dry_run_moves_and_rewrites_nothing(tmp_path, capsys):
    root = _vault(tmp_path)
    old = _touch(root, "pipeline/3-synthesis/digest_2026-01-05.md")
    events = root / "pipeline" / ".health" / "events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text(
        json.dumps({"ts": "2026-01-01T09:00:00+00:00", "kind": "collect"}) + "\n",
        encoding="utf-8",
    )
    before = events.read_bytes()

    rc = rp.main(["--root", str(root), "--today", "2026-07-03", "--dry-run"])

    assert rc == 0
    assert old.exists()
    assert events.read_bytes() == before
    out = capsys.readouterr().out
    assert "digest_2026-01-05.md" in out


def test_missing_dirs_are_a_clean_noop(tmp_path):
    root = tmp_path  # no pipeline/ at all
    result = rp.rotate(root, today=TODAY, keep_days=90)
    assert result.moved == 0
    assert result.events_dropped == 0
    assert rp.main(["--root", str(root), "--today", "2026-07-03"]) == 0


def test_record_event_waits_for_event_log_lock(tmp_path, monkeypatch):
    # An append landing between compaction's read and its atomic replace was
    # silently dropped (rotate rewrote the file from a stale snapshot). Both
    # writers must serialize on the event-log lock — here: an append started
    # while the lock is held must block until it is released, then land.
    import threading

    from scripts.health_checks import events as ev
    from scripts.registry import advisory_lock

    # Pin the log to tmp_path: with the env var exported this test would append
    # junk to the OPERATOR'S real relocated event log.
    monkeypatch.delenv("RESEARCH_BRAIN_STATE_DIR", raising=False)
    root = _vault(tmp_path)
    path = ev.events_path(root)
    lock_path = path.with_name(path.name + ".lock")
    done = threading.Event()

    def _append() -> None:
        ev.record_event(root, "collect", timestamp="2099-01-01T00:00:00+00:00")
        done.set()

    with advisory_lock(lock_path):
        thread = threading.Thread(target=_append)
        thread.start()
        blocked = not done.wait(timeout=0.4)
    thread.join(timeout=5)
    assert blocked, "record_event must wait for the event-log lock"
    assert done.is_set(), "record_event must proceed once the lock is released"
    assert any(e["ts"].startswith("2099") for e in ev.load_events(root))


def test_compaction_waits_for_event_log_lock(tmp_path, monkeypatch):
    # The rotate side of the same contract: compaction's read-filter-replace
    # must not start while an appender holds the event-log lock.
    import threading

    from scripts.health_checks import events as ev
    from scripts.registry import advisory_lock

    # Pin the log to tmp_path: with the env var exported this test would
    # irreversibly compact the OPERATOR'S real relocated event log and then
    # assert it is empty.
    monkeypatch.delenv("RESEARCH_BRAIN_STATE_DIR", raising=False)
    root = _vault(tmp_path)
    ev.record_event(root, "collect", timestamp="2020-01-01T00:00:00+00:00")
    path = ev.events_path(root)
    lock_path = path.with_name(path.name + ".lock")
    done = threading.Event()

    def _rotate() -> None:
        rp.rotate(root, today=TODAY, keep_days=30)
        done.set()

    with advisory_lock(lock_path):
        thread = threading.Thread(target=_rotate)
        thread.start()
        blocked = not done.wait(timeout=0.4)
    thread.join(timeout=5)
    assert blocked, "event-log compaction must wait for the event-log lock"
    assert done.is_set(), "compaction must proceed once the lock is released"
    assert ev.load_events(root) == []  # the pre-cutoff event was compacted


# --------------------------------------------------------------------------- #
# The SAME read-filter-replace race, for the collection-decision journal
# (review 2026-07-22, P2). The journal writer used a lock-free O_APPEND while
# `_compact_journal` did an unlocked read-filter-replace, and the comment wrongly
# claimed the run lock covered it — standalone `rotate_pipeline.py` never takes
# that lock. Fixed by a dedicated `journal_lock`, mirroring the event log.
# --------------------------------------------------------------------------- #


def _decision():
    from scripts.source_report.model import CandidateDecision

    return CandidateDecision(
        topic="ai-agents",
        source_url="https://feed.example/rss",
        candidate_url="https://feed.example/a",
        decision="selected",
    )


def test_record_decision_waits_for_journal_lock(tmp_path, monkeypatch):
    # An append landing between compaction's read and its atomic replace was
    # silently dropped. Both writers must serialize on the journal lock.
    import threading

    from scripts.registry import advisory_lock
    from scripts.source_report import events as je

    # Pin the journal to tmp_path so an exported state dir can't route this at the
    # operator's real journal.
    monkeypatch.delenv("RESEARCH_BRAIN_STATE_DIR", raising=False)
    root = _vault(tmp_path)
    path = je.journal_path(root)
    lock_path = path.with_name(path.name + ".lock")
    done = threading.Event()

    def _append() -> None:
        je.record_decision(root, _decision())
        done.set()

    with advisory_lock(lock_path):
        thread = threading.Thread(target=_append)
        thread.start()
        blocked = not done.wait(timeout=0.4)
    thread.join(timeout=5)
    assert blocked, "record_decision must wait for the journal lock"
    assert done.is_set(), "record_decision must proceed once the lock is released"
    assert len(je.read_decisions(root)) == 1


def test_journal_compaction_waits_for_journal_lock(tmp_path, monkeypatch):
    # The rotate side of the same contract: journal compaction's read-filter-
    # replace must not start while an appender holds the journal lock.
    import threading

    from scripts.registry import advisory_lock
    from scripts.source_report import events as je

    monkeypatch.delenv("RESEARCH_BRAIN_STATE_DIR", raising=False)
    root = _vault(tmp_path)
    je.record_decision(root, _decision())
    path = je.journal_path(root)
    lock_path = path.with_name(path.name + ".lock")
    done = threading.Event()

    def _rotate() -> None:
        rp.rotate(root, today=TODAY, keep_days=30)
        done.set()

    with advisory_lock(lock_path):
        thread = threading.Thread(target=_rotate)
        thread.start()
        blocked = not done.wait(timeout=0.4)
    thread.join(timeout=5)
    assert blocked, "journal compaction must wait for the journal lock"
    assert done.is_set(), "compaction must proceed once the lock is released"
