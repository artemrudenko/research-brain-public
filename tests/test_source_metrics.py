"""
test_source_metrics.py — per-source usefulness, joined from the journal and the registry.

Two halves answer "is this source worth keeping?", and neither is enough alone:

  - the **journal** knows what a source OFFERED and what the collector did with it
    (considered / selected / dropped, and why);
  - the **registry** knows what happened to the survivors afterwards — whether
    curation kept or rejected them.

Joining them is the whole feature: a feed whose articles are always collected and
always rejected at curation looks productive in the journal and useless in truth.

Two rules this file pins hard:

1. **One definition of "processed".** The status classification is shared with
   `value_metrics`, not re-implemented. Two reports disagreeing about the same
   registry would be worse than having only one.
2. **Counts are not verdicts.** Below a handful of observations the numbers say
   more about when collection started than about the source, so every row carries
   an explicit confidence band instead of a confident-looking percentage.
"""

from __future__ import annotations

from pathlib import Path

from scripts.registry import _REGISTRY_HEADER as REGISTRY_HEADER
from scripts.source_report.events import record_decision
from scripts.source_report.metrics import (
    ESTABLISHED_AT,
    LOW_CONFIDENCE_AT,
    source_metrics,
)
from scripts.source_report.model import CandidateDecision

FEED = "https://example.com/feed.xml"


def _journal(root: Path, url: str, decision: str = "selected", **kw: object) -> None:
    record_decision(
        root,
        CandidateDecision(
            topic="ai",
            source_url=str(kw.pop("source_url", FEED)),
            candidate_url=url,
            decision=decision,
            **kw,  # type: ignore[arg-type]
        ),
    )


def _registry(root: Path, rows: list[tuple[str, str]]) -> Path:
    """Write a registry with (url, status) rows."""
    path = root / "pipeline" / "registry.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(
        f"| 2026-07-21 | ai | {status} | {url} | Title |\n" for url, status in rows
    )
    path.write_text(REGISTRY_HEADER + body, encoding="utf-8")
    return path


# ── the journal half ──────────────────────────────────────────────────────────


def test_counts_what_a_source_offered_and_what_was_taken(tmp_path: Path) -> None:
    for i in range(3):
        _journal(tmp_path, f"https://example.com/{i}")
    _journal(tmp_path, "https://example.com/dup", decision="duplicate_url")
    _journal(tmp_path, "https://example.com/short", decision="too_short")

    metrics = source_metrics(tmp_path, _registry(tmp_path, []))
    assert len(metrics) == 1
    row = metrics[0]
    assert row.source_url == FEED
    assert row.considered == 5
    assert row.selected == 3
    assert row.by_decision["duplicate_url"] == 1
    assert row.by_decision["too_short"] == 1


def test_sources_are_reported_separately(tmp_path: Path) -> None:
    _journal(tmp_path, "https://a.example/1", source_url="https://a.example/feed.xml")
    _journal(tmp_path, "https://b.example/1", source_url="https://b.example/feed.xml")
    assert {m.source_url for m in source_metrics(tmp_path, _registry(tmp_path, []))} == {
        "https://a.example/feed.xml",
        "https://b.example/feed.xml",
    }


def test_empty_journal_yields_no_rows(tmp_path: Path) -> None:
    assert source_metrics(tmp_path, _registry(tmp_path, [])) == []


# ── the join with curation ────────────────────────────────────────────────────


def test_curation_outcome_is_joined_onto_the_source(tmp_path: Path) -> None:
    _journal(tmp_path, "https://example.com/kept")
    _journal(tmp_path, "https://example.com/dropped")
    _journal(tmp_path, "https://example.com/waiting")
    registry = _registry(
        tmp_path,
        [
            ("https://example.com/kept", "processed"),
            ("https://example.com/dropped", "rejected"),
            ("https://example.com/waiting", ""),
        ],
    )

    row = source_metrics(tmp_path, registry)[0]
    assert row.passed_curation == 1
    assert row.rejected_curation == 1
    assert row.pending_curation == 1


def test_join_survives_url_normalization_differences(tmp_path: Path) -> None:
    """The journal records the raw link; the registry stores the canonical key.

    Joining on the raw string would silently report zero curation outcomes for
    every source whose feed appends tracking parameters.
    """
    _journal(tmp_path, "https://example.com/post?utm_source=feed")
    registry = _registry(tmp_path, [("https://example.com/post", "processed")])

    assert source_metrics(tmp_path, registry)[0].passed_curation == 1


def test_a_source_with_no_registry_rows_is_not_an_error(tmp_path: Path) -> None:
    _journal(tmp_path, "https://example.com/never-saved", decision="too_short")
    row = source_metrics(tmp_path, _registry(tmp_path, []))[0]
    assert row.passed_curation == 0
    assert row.considered == 1


def test_missing_registry_degrades_to_journal_only(tmp_path: Path) -> None:
    _journal(tmp_path, "https://example.com/1")
    row = source_metrics(tmp_path, tmp_path / "pipeline" / "absent.md")[0]
    assert row.selected == 1
    assert row.passed_curation == 0


# ── confidence, not false precision ───────────────────────────────────────────


def test_confidence_bands_reflect_how_much_we_have_seen(tmp_path: Path) -> None:
    for i in range(LOW_CONFIDENCE_AT - 1):
        _journal(tmp_path, f"https://example.com/{i}")
    assert source_metrics(tmp_path, _registry(tmp_path, []))[0].confidence == "insufficient"


def test_confidence_reaches_low_then_established(tmp_path: Path) -> None:
    for i in range(LOW_CONFIDENCE_AT):
        _journal(tmp_path, f"https://example.com/{i}")
    assert source_metrics(tmp_path, _registry(tmp_path, []))[0].confidence == "low"

    for i in range(ESTABLISHED_AT - LOW_CONFIDENCE_AT):
        _journal(tmp_path, f"https://example.com/more-{i}")
    assert source_metrics(tmp_path, _registry(tmp_path, []))[0].confidence == "established"


def test_no_single_score_is_exposed(tmp_path: Path) -> None:
    """Deliberately absent: one opaque number would hide which signal moved it."""
    _journal(tmp_path, "https://example.com/1")
    row = source_metrics(tmp_path, _registry(tmp_path, []))[0]
    assert not hasattr(row, "score")
    assert not hasattr(row, "utility")


# ── authors ───────────────────────────────────────────────────────────────────


def test_authors_seen_through_a_source_are_collected(tmp_path: Path) -> None:
    _journal(tmp_path, "https://example.com/1", author_name="Jane Doe")
    _journal(tmp_path, "https://example.com/2", author_name="Jane Doe")
    _journal(tmp_path, "https://example.com/3", author_name="John Roe")

    row = source_metrics(tmp_path, _registry(tmp_path, []))[0]
    # Exact repeats collapse; distinct names stay distinct. No fuzzy merging.
    assert sorted(row.authors) == ["Jane Doe", "John Roe"]


# ── one definition of "processed" ─────────────────────────────────────────────


def test_curation_totals_agree_with_value_metrics(tmp_path: Path) -> None:
    """The two reports must never disagree about the same registry.

    Both read the registry through the same shared classifier; this asserts the
    agreement rather than trusting that nobody re-implements the status rules.
    """
    from scripts.value_metrics import source_yield

    rows = [
        ("https://example.com/a", "processed"),
        ("https://example.com/b", "Processed"),  # case differences must not split
        ("https://example.com/c", "rejected"),
        ("https://example.com/d", ""),
    ]
    for url, _ in rows:
        _journal(tmp_path, url)
    registry = _registry(tmp_path, rows)

    row = source_metrics(tmp_path, registry)[0]
    totals = source_yield(registry)
    assert row.passed_curation == totals.processed
    assert row.rejected_curation == totals.rejected
    assert row.pending_curation == totals.pending
