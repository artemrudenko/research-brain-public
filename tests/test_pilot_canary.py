"""CLI tests for the offline pilot evidence canary validator."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_validate(evidence_path: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/pilot_canary.py",
            "validate",
            str(evidence_path),
            *extra_args,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _completed_go_evidence(**overrides: str) -> str:
    values = {
        "version": "v1.0.0",
        "runtime": "codex balanced",
        "operating_system": "macOS 15",
        "product_version_source": "release artifact abc123",
        "live_target": "disposable",
        "development_checkout": "no",
        "topics_source_count": "ai-agents / 8 sources",
        "channel_label": "email redacted-test-recipient",
        "activation_time": "24 minutes",
        "run_duration": "18 minutes",
        "cost": "USD 1.20",
        "source_yield": "10 collected / 8 curated",
        "concepts": "2 created / 1 updated",
        "deliveries": "cycle 1=delivered, cycle 2=delivered",
        "useful": "6/10 (60%)",
        "intervention": "cycle 1=10, cycle 2=0",
        "critical_failure": "none",
        "first_send_approval": "approved before send",
        "second_cycle": "yes - updated concept from new source",
        "recurring": "yes - keep enabled",
        "activation_status": "PASS",
        "quality_status": "PASS",
        "reuse_status": "PASS",
        "recovery_status": "PASS",
        "second_cycle_status": "PASS",
        "decision": "GO",
        "primary_cause": "",
        "next_action": "Continue recurring run.",
    }
    values.update(overrides)
    return f"""# Pilot evidence - live canary

Copy this file to `docs/pilot-evidence/live-canary.md` for the release canary.
Keep evidence aggregate and redacted. Do not paste secrets, webhook URLs, raw
tokens, recipient-private message contents, or private vault note contents.

Version: {values["version"]}
Runtime/model/profile: {values["runtime"]}
Operating system: {values["operating_system"]}
Product version source: {values["product_version_source"]}
Live target: {values["live_target"]}
Development checkout used for live run: {values["development_checkout"]}
Topics / source count: {values["topics_source_count"]}
Channel type / redacted label: {values["channel_label"]}
Activation time: {values["activation_time"]}
Run duration: {values["run_duration"]}
Estimated model/API cost: {values["cost"]}
Source yield: {values["source_yield"]}
Concepts created/updated: {values["concepts"]}
Cycle deliveries: {values["deliveries"]}
Useful surfaced items: {values["useful"]}
Post-setup intervention per cycle: {values["intervention"]}
Critical trust/safety failure: {values["critical_failure"]}
Explicit first-send approval: {values["first_send_approval"]}
Second-cycle useful new/updated concept: {values["second_cycle"]}
User wants recurring run enabled: {values["recurring"]}

## Stage results

| Stage | PASS/FAIL | Evidence | Intervention |
|---|---|---|---|
| Activation | {values["activation_status"]} | setup and first send completed | 10 min |
| Content quality | {values["quality_status"]} | 6 useful items | reviewer |
| Idempotency/reuse | {values["reuse_status"]} | registry and receipts held | 0 min |
| Recovery | {values["recovery_status"]} | degraded path recovered | 0 min |
| Second cycle | {values["second_cycle_status"]} | useful updated concept | 0 min |

## Quality scoring

- Useful: 6
- Relevant but routine: 3
- Noise: 1
- Concepts reviewed: 3
- Unsupported claims: 0
- Sanitization findings: none
- Delivery outcome: delivered to redacted recipient
- Vault-only answer evidence: cited local concept
- Vault-only miss evidence: offered research only

## Redaction check

Confirm the evidence file does not include:

- secret values
- webhook URLs
- raw tokens
- recipient-private message contents
- private vault note contents
- config/.env

Acceptable evidence includes redacted channel labels, env-var names, aggregate
counts, relative artifact paths, pass/fail outcomes, and reviewer notes that do
not expose private content.

## Decision

GO / NO-GO: {values["decision"]}
Primary cause: {values["primary_cause"]}
Next corrective action: {values["next_action"]}
"""


def _write_evidence(tmp_path: Path, content: str) -> Path:
    evidence_path = tmp_path / "pilot-evidence.md"
    evidence_path.write_text(content, encoding="utf-8")
    return evidence_path


def test_template_mode_accepts_blank_template() -> None:
    result = _run_validate(REPO_ROOT / "templates" / "pilot-evidence.md", "--template")

    assert result.returncode == 0
    assert "PILOT_CANARY_TEMPLATE_OK" in result.stdout


def test_validate_accepts_completed_go_evidence(tmp_path: Path) -> None:
    evidence_path = _write_evidence(tmp_path, _completed_go_evidence())

    result = _run_validate(evidence_path)

    assert result.returncode == 0
    assert "PILOT_CANARY_OK" in result.stdout


def test_validate_rejects_missing_required_field(tmp_path: Path) -> None:
    evidence = _completed_go_evidence().replace("Runtime/model/profile: codex balanced\n", "")
    evidence_path = _write_evidence(tmp_path, evidence)

    result = _run_validate(evidence_path)

    assert result.returncode == 2
    assert "Missing required field: Runtime/model/profile:" in result.stderr


def test_validate_rejects_secret_like_values(tmp_path: Path) -> None:
    secret_values = [
        "sk-live-12345678",
        "xoxb-123456789",
        "ghp_1234567890",
        "https://hooks.example.test/token",
        "SMTP_PASSWORD=secret",
    ]

    for secret_value in secret_values:
        evidence_path = _write_evidence(
            tmp_path,
            _completed_go_evidence(channel_label=f"email redacted {secret_value}"),
        )

        result = _run_validate(evidence_path)

        assert result.returncode == 2
        assert "Forbidden secret-like content" in result.stderr


def test_validate_rejects_inconsistent_go_decision(tmp_path: Path) -> None:
    inconsistent_cases = [
        {"activation_status": "FAIL"},
        {"useful": "5/10 (50%)"},
        {"intervention": "cycle 1=11, cycle 2=0"},
        {"deliveries": "cycle 1=delivered, cycle 2=failed"},
        {"critical_failure": "unsupported claim"},
        {"second_cycle": "no"},
        {"recurring": "no"},
        {"development_checkout": "yes"},
    ]

    for overrides in inconsistent_cases:
        evidence_path = _write_evidence(tmp_path, _completed_go_evidence(**overrides))

        result = _run_validate(evidence_path)

        assert result.returncode == 2
        assert "GO decision is inconsistent with pilot criteria" in result.stderr


def test_validate_rejects_invalid_no_go_primary_cause(tmp_path: Path) -> None:
    evidence_path = _write_evidence(
        tmp_path,
        _completed_go_evidence(
            decision="NO-GO",
            primary_cause="uncategorized",
            next_action="Fix the pilot evidence.",
        ),
    )

    result = _run_validate(evidence_path)

    assert result.returncode == 2
    assert "Invalid NO-GO primary cause" in result.stderr
