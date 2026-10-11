"""Tests for scripts/feedback.py — the reader-feedback event log.

The durable half of the digest feedback loop: the `digest-feedback` skill maps
natural-language reactions ("too technical", "less of X") onto config changes
via existing surfaces, and records every event here so later value metrics can
count reader signal. Append-only JSONL under `pipeline/.feedback/`, relocatable
via RESEARCH_BRAIN_STATE_DIR like every other runtime-state path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import feedback


def _record(root: Path, *args: str) -> int:
    return feedback.main(["record", "--root", str(root), *args])


def _log_path(root: Path) -> Path:
    return root / "pipeline" / ".feedback" / "feedback.jsonl"


def test_record_writes_one_json_line_with_ts_and_kind(tmp_path: Path) -> None:
    rc = _record(tmp_path, "--kind", "too_technical")
    assert rc == 0
    lines = _log_path(tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["kind"] == "too_technical"
    assert entry["ts"].endswith("+00:00")  # UTC axis, same as the rest of the product


def test_records_append_and_list_newest_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _record(tmp_path, "--kind", "too_technical") == 0
    assert _record(tmp_path, "--kind", "mute_topic", "--target", "ai-ml") == 0
    capsys.readouterr()  # drain the record confirmations; parse only list output
    rc = feedback.main(["list", "--root", str(tmp_path), "--json"])
    assert rc == 0
    entries = json.loads(capsys.readouterr().out)
    assert [e["kind"] for e in entries] == ["mute_topic", "too_technical"]
    assert entries[0]["target"] == "ai-ml"


def test_list_applies_limit_and_skips_malformed_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = _log_path(tmp_path)
    log.parent.mkdir(parents=True)
    log.write_text(
        'not json at all\n{"ts": "2026-07-01T00:00:00+00:00", "kind": "useful"}\n',
        encoding="utf-8",
    )
    assert _record(tmp_path, "--kind", "too_technical") == 0
    capsys.readouterr()  # drain the record confirmation; parse only list output
    rc = feedback.main(["list", "--root", str(tmp_path), "--json", "--limit", "1"])
    assert rc == 0
    entries = json.loads(capsys.readouterr().out)
    assert len(entries) == 1
    assert entries[0]["kind"] == "too_technical"


def test_list_without_log_is_empty_not_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = feedback.main(["list", "--root", str(tmp_path), "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_invalid_kind_is_rejected_and_writes_nothing(tmp_path: Path) -> None:
    rc = _record(tmp_path, "--kind", "Not A Slug!")
    assert rc == 2
    assert not (tmp_path / "pipeline" / ".feedback").exists()


def test_free_text_fields_are_truncated_to_caps(tmp_path: Path) -> None:
    # Feedback notes come from chat text; a runaway paste must not bloat the log.
    assert (
        _record(
            tmp_path, "--kind", "other", "--note", "x" * 1000, "--target", "t" * 500
        )
        == 0
    )
    entry = json.loads(_log_path(tmp_path).read_text(encoding="utf-8").splitlines()[0])
    assert len(entry["note"]) == feedback.NOTE_CAP
    assert len(entry["target"]) == feedback.TARGET_CAP


def test_state_dir_relocates_the_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    volume = tmp_path / "volume"
    monkeypatch.setenv("RESEARCH_BRAIN_STATE_DIR", str(volume))
    root = tmp_path / "repo"
    root.mkdir()
    assert _record(root, "--kind", "useful") == 0
    assert (volume / "pipeline" / ".feedback" / "feedback.jsonl").exists()
    assert not (root / "pipeline" / ".feedback").exists()
