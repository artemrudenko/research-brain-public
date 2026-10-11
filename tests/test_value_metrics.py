"""Tests for scripts/value_metrics.py — read-only value evidence.

The audit's item 11: activation is instrumented (setup_check), but recurring
value was manual-only. These metrics read ONLY durable artifacts (delivery
receipts, registry, synthesis logs, feedback log) and never write anything.
Cost-per-digest stays a manual pilot field by design — asserted here so the
report can never silently pretend to know it.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from scripts import value_metrics as vm  # noqa: E402

TODAY = date(2026, 6, 15)  # a Monday


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "pipeline" / "3-synthesis").mkdir(parents=True)
    (tmp_path / "brain" / "concepts").mkdir(parents=True)
    return tmp_path


def _receipt(vault: Path, stem: str) -> None:
    d = vault / "pipeline" / "3-synthesis" / ".delivered"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.json").write_text("{}", encoding="utf-8")


def _registry(vault: Path, rows: list[tuple[str, str, str]]) -> None:
    lines = [
        "| collected | category | status | url | title |",
        "|---|---|---|---|---|",
    ]
    for i, (collected, category, status) in enumerate(rows):
        lines.append(f"| {collected} | {category} | {status} | https://x.com/{i} | t{i} |")
    (vault / "pipeline" / "registry.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_retention_counts_iso_weeks_with_any_receipt(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _receipt(vault, "digest_2026-06-15")          # this week
    _receipt(vault, "digest_2026-06-01")          # two weeks back
    _receipt(vault, "digest_2026-06-01.telegram")  # same week, MCP receipt — no double count
    _receipt(vault, "digest_2026-01-05")          # far outside the window
    hit, window = vm.retention(vault, today=TODAY, weeks=4)
    assert (hit, window) == (2, 4)


def test_retention_zero_without_receipts(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    assert vm.retention(vault, today=TODAY, weeks=4) == (0, 4)


def test_source_yield_counts_statuses(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _registry(vault, [
        ("2026-06-10", "ai", "processed"),
        ("2026-06-11", "ai", ""),
        ("2026-06-12", "devops", "rejected"),
    ])
    y = vm.source_yield(vault / "pipeline" / "registry.md")
    assert (y.total, y.processed, y.rejected, y.pending) == (3, 1, 1, 1)
    assert y.per_category["ai"] == (1, 2)  # processed of total


def test_source_yield_missing_registry_is_empty(tmp_path: Path) -> None:
    y = vm.source_yield(tmp_path / "pipeline" / "registry.md")
    assert y.total == 0


def test_feedback_counts_by_kind_within_window(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    log = vault / "pipeline" / ".feedback" / "feedback.jsonl"
    log.parent.mkdir(parents=True)
    entries = [
        {"ts": "2026-06-14T10:00:00+00:00", "kind": "too_technical"},
        {"ts": "2026-06-13T10:00:00+00:00", "kind": "useful"},
        {"ts": "2026-06-12T10:00:00+00:00", "kind": "useful"},
        {"ts": "2026-01-01T10:00:00+00:00", "kind": "useful"},  # outside window
        "not json at all",  # a corrupt line must not kill the report
    ]
    log.write_text(
        "\n".join(e if isinstance(e, str) else json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )
    counts = vm.feedback_counts(vault, today=TODAY, days=28)
    assert counts == {"too_technical": 1, "useful": 2}


def test_report_composes_and_names_manual_cost(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    _receipt(vault, "digest_2026-06-15")
    _registry(vault, [("2026-06-10", "ai", "processed")])
    (vault / "pipeline" / "3-synthesis" / "synthesis-run_2026-06-15.md").write_text(
        "# run\n\n## Totals\n- concepts created: 2\n- concepts updated: 1\n"
        "- existing concepts reused: 3\n",
        encoding="utf-8",
    )
    rc = vm.main(["report", "--root", str(vault), "--today", "2026-06-15"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 of last 4 weeks" in out
    assert "1/1 processed" in out
    assert "reused: 3" in out
    # Honesty line: cost is a manual pilot measurement, never computed here.
    assert "manual" in out and "PILOT" in out


def test_report_json_shape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = _vault(tmp_path)
    rc = vm.main(["report", "--root", str(vault), "--today", "2026-06-15", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["retention"] == {"weeks_with_delivery": 0, "window_weeks": 4}
    assert data["yield"]["total"] == 0
    assert data["cost_per_digest"] == "manual (docs/PILOT.md)"


def test_report_is_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = _vault(tmp_path)
    before = sorted(p for p in vault.rglob("*"))
    assert vm.main(["report", "--root", str(vault), "--today", "2026-06-15"]) == 0
    capsys.readouterr()
    assert sorted(p for p in vault.rglob("*")) == before
