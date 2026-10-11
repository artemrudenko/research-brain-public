"""Drift tests for the live pilot evidence contract."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_EVIDENCE_LABELS = (
    "Version:",
    "Runtime/model/profile:",
    "Operating system:",
    "Product version source:",
    "Live target: disposable|dedicated",
    "Development checkout used for live run: no",
    "Topics / source count:",
    "Channel type / redacted label:",
    "Activation time:",
    "Run duration:",
    "Estimated model/API cost:",
    "Source yield:",
    "Concepts created/updated:",
    "Cycle deliveries:",
    "Useful surfaced items:",
    "Post-setup intervention per cycle:",
    "Critical trust/safety failure:",
    "Explicit first-send approval:",
    "Second-cycle useful new/updated concept:",
    "User wants recurring run enabled:",
    "GO / NO-GO:",
    "Primary cause:",
    "Next corrective action:",
)

REQUIRED_STAGE_ROWS = (
    "Activation",
    "Content quality",
    "Idempotency/reuse",
    "Recovery",
    "Second cycle",
)

FORBIDDEN_EVIDENCE_CONTENT_LABELS = (
    "secret values",
    "webhook URLs",
    "raw tokens",
    "recipient-private message contents",
    "private vault note contents",
    "config/.env",
)


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_pilot_template_contains_required_evidence_fields() -> None:
    template = _read("templates/pilot-evidence.md")

    missing = [label for label in REQUIRED_EVIDENCE_LABELS if label not in template]
    assert not missing, f"pilot evidence template missing labels: {missing}"


def test_pilot_template_contains_all_stage_rows() -> None:
    template = _read("templates/pilot-evidence.md")

    for row in REQUIRED_STAGE_ROWS:
        assert f"| {row} |" in template


def test_pilot_template_contains_redaction_boundaries() -> None:
    template = _read("templates/pilot-evidence.md")

    missing = [
        label for label in FORBIDDEN_EVIDENCE_CONTENT_LABELS if label not in template
    ]
    assert not missing, f"pilot evidence template missing redaction labels: {missing}"


def test_pilot_docs_reference_template_and_validator() -> None:
    pilot_doc = _read("docs/PILOT.md")

    assert "templates/pilot-evidence.md" in pilot_doc
    assert "docs/pilot-evidence/live-canary.md" in pilot_doc
    assert (
        "python3 scripts/pilot_canary.py validate docs/pilot-evidence/live-canary.md"
        in pilot_doc
    )
    assert "Second-cycle useful new/updated concept:" in pilot_doc
    assert "User wants recurring run enabled:" in pilot_doc
