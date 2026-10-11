"""
test_source_report_html.py — the standalone Source Insights page.

A sibling of the digest report, not a sixth tab inside it: that report
deliberately holds at five tabs because five fit a phone (the 2026-07-14 merge of
Trends/Stats/Audit into Pulse exists for exactly that reason). Source
intelligence is a different audience and a different cadence, so it gets its own
artifact.

Everything on this page came out of a remote document — source URLs, article
titles, author names — so the escaping contracts are ported wholesale from the
digest report's tests rather than reinvented. The two that matter most:
attacker-controlled text must not escape a text node, and it must not escape a
double-quoted attribute (a bare quote is inert in one and fatal in the other).
"""

from __future__ import annotations

from pathlib import Path

from scripts.source_report.metrics import SourceMetrics
from scripts.source_report.render import render_source_report

DATE = "2026-07-21"


def _row(**kw: object) -> SourceMetrics:
    base: dict[str, object] = {
        "source_url": "https://example.com/feed.xml",
        "considered": 25,
        "selected": 10,
        "by_decision": {"selected": 10, "duplicate_url": 10, "too_short": 5},
        "passed_curation": 7,
        "rejected_curation": 2,
        "pending_curation": 1,
        "authors": ("Jane Doe",),
        "topics": ("ai",),
        "last_seen": "2026-07-20T10:00:00+00:00",
    }
    base.update(kw)
    return SourceMetrics(**base)  # type: ignore[arg-type]


# ── document shape ────────────────────────────────────────────────────────────


def test_returns_a_standalone_document() -> None:
    html = render_source_report([_row()], generated_for=DATE)
    assert html.startswith("<!DOCTYPE html>")
    assert "<html lang=\"en\">" in html
    assert html.rstrip().endswith("</html>")


def test_has_semantic_landmarks_and_aria() -> None:
    html = render_source_report([_row()], generated_for=DATE)
    assert 'role="banner"' in html
    assert "<main" in html
    assert 'role="tablist"' in html


def test_tabs_stay_within_the_mobile_budget() -> None:
    """Same constraint the digest report holds to: tabs must fit a phone."""
    html = render_source_report([_row()], generated_for=DATE)
    assert html.count('role="tab"') <= 5
    for label in ("Sources", "Authors", "Decisions"):
        assert f">{label}</button>" in html


def test_supports_dark_mode_and_print() -> None:
    html = render_source_report([_row()], generated_for=DATE)
    assert "prefers-color-scheme: dark" in html or "prefers-color-scheme:dark" in html
    assert "@media print" in html


def test_is_deterministic_for_the_same_input() -> None:
    """No timestamps, no randomness — the same data renders byte-identically."""
    rows = [_row()]
    assert render_source_report(rows, generated_for=DATE) == render_source_report(
        rows, generated_for=DATE
    )


def test_sources_render_in_the_order_given() -> None:
    # Ordering is the caller's job (the metrics layer sorts), same contract the
    # digest renderer holds — so the page never re-sorts behind the caller's back.
    html = render_source_report(
        [_row(source_url="https://b.example/f.xml"), _row(source_url="https://a.example/f.xml")],
        generated_for=DATE,
    )
    assert html.index("b.example") < html.index("a.example")


# ── honesty about thin evidence ───────────────────────────────────────────────


def test_thin_evidence_is_labelled_not_rendered_as_confident() -> None:
    html = render_source_report([_row(considered=2, selected=1)], generated_for=DATE)
    assert "insufficient" in html.lower()


def test_established_source_is_marked_as_such() -> None:
    html = render_source_report([_row(considered=40)], generated_for=DATE)
    assert "established" in html.lower()


def test_empty_report_explains_itself_rather_than_rendering_blank() -> None:
    html = render_source_report([], generated_for=DATE)
    assert "<!DOCTYPE html>" in html
    # A new install has no history yet; say so instead of showing an empty table
    # that reads like "your sources produced nothing".
    assert "no collection decisions" in html.lower()


def test_no_single_blended_score_is_displayed() -> None:
    html = render_source_report([_row()], generated_for=DATE).lower()
    assert "utility score" not in html
    assert "overall score" not in html


# ── escaping: everything here came from a remote document ─────────────────────


def test_escapes_hostile_author_names() -> None:
    from scripts.source_report.authors import AuthorMetrics

    hostile = AuthorMetrics(
        key="name:x", display_name="<script>alert(1)</script>", articles=1, runs=1,
        passed_curation=0, rejected_curation=0,
    )
    html = render_source_report([_row()], generated_for=DATE, authors=[hostile])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_suggestion_shows_the_identity_handle_to_disambiguate_same_named_authors() -> None:
    # Review 2026-07-22 (P2): a suggestion carried only name + reason, so two
    # people with the same name were indistinguishable. Surface the stable handle
    # (identifier preferred, else the profile URL) that the model already holds.
    from scripts.source_report.authors import AuthorMetrics, MonitoringSuggestion

    author = AuthorMetrics(
        key="name:jane", display_name="Jane Doe", articles=3, runs=2,
        passed_curation=3, rejected_curation=0,
    )
    one = MonitoringSuggestion(
        display_name="Jane Doe", reason="strong signal",
        identifier="orcid:0000-0002-1825-0097",
    )
    two = MonitoringSuggestion(
        display_name="Jane Doe", reason="strong signal",
        profile_url="https://example.org/~jdoe",
    )
    html = render_source_report(
        [_row()], generated_for=DATE, authors=[author], suggestions=[one, two]
    )
    # The identifier disambiguates the first Jane; the profile URL the second.
    assert "orcid:0000-0002-1825-0097" in html
    assert "https://example.org/~jdoe" in html


def test_suggestion_copy_does_not_claim_monitoring_is_unbuilt() -> None:
    # Review 2026-07-22 (P2): author monitoring shipped in v0.10.0, so the panel
    # must not tell the user it "is not built yet". It must still be honest that
    # nothing on THIS page has been enabled (Source Insights only suggests).
    from scripts.source_report.authors import AuthorMetrics, MonitoringSuggestion

    author = AuthorMetrics(
        key="name:jane", display_name="Jane Doe", articles=3, runs=2,
        passed_curation=3, rejected_curation=0,
    )
    html = render_source_report(
        [_row()], generated_for=DATE, authors=[author],
        suggestions=[MonitoringSuggestion(display_name="Jane Doe", reason="strong")],
    ).lower()
    assert "not built yet" not in html
    assert "nothing here has been enabled" in html


def test_source_url_with_embedded_quote_cannot_break_out_of_an_attribute() -> None:
    html = render_source_report(
        [_row(source_url='https://evil.example/" onmouseover="alert(1)')],
        generated_for=DATE,
    )
    assert 'onmouseover="alert' not in html
    assert "&quot;" in html


def test_javascript_url_never_becomes_an_href() -> None:
    html = render_source_report(
        [_row(source_url="javascript:alert(1)")], generated_for=DATE
    )
    assert 'href="javascript:' not in html
    # The value is still shown, just not as a link — dropping it silently would
    # hide which source produced the row.
    assert "javascript:alert(1)" in html or "javascript:alert(1)".replace(":", "&#x3a;") in html


def test_protocol_relative_url_is_not_linked() -> None:
    html = render_source_report([_row(source_url="//evil.example/feed")], generated_for=DATE)
    assert 'href="//evil.example' not in html


def test_topic_and_decision_labels_are_escaped() -> None:
    html = render_source_report(
        [_row(topics=("<img src=x onerror=alert(1)>",))], generated_for=DATE
    )
    assert "<img src=x" not in html


# ── the artifact on disk ──────────────────────────────────────────────────────


def test_report_filename_is_rotated_and_gitignored() -> None:
    """Both gaps a new dated artifact falls into, closed and pinned.

    Without the rotation prefix the file accumulates forever; without the ignore
    rule it lands in the user's next commit.
    """
    from scripts.rotate_pipeline import _artifact_date

    name = f"source-insights_{DATE}.report.html"
    assert _artifact_date(name) is not None, "rotate_pipeline must recognise the artifact"

    ignore = Path(__file__).resolve().parents[1] / ".gitignore"
    assert "source-insights_*.report.html" in ignore.read_text(encoding="utf-8")


def test_cli_writes_the_report(tmp_path: Path) -> None:
    from scripts.source_insights import main
    from scripts.source_report.events import record_decision
    from scripts.source_report.model import CandidateDecision

    record_decision(
        tmp_path,
        CandidateDecision(
            topic="ai",
            source_url="https://example.com/feed.xml",
            candidate_url="https://example.com/1",
            decision="selected",
        ),
    )
    out = tmp_path / "out.report.html"
    assert main(["--root", str(tmp_path), "report", "--out", str(out), "--today", DATE]) == 0
    assert out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
