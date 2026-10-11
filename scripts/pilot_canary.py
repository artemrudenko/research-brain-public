"""Offline validator for live-pilot canary evidence Markdown."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TEMPLATE_OK = "PILOT_CANARY_TEMPLATE_OK"
STRICT_OK = "PILOT_CANARY_OK"

REQUIRED_VALUE_LABELS = (
    "Version:",
    "Runtime/model/profile:",
    "Operating system:",
    "Product version source:",
    "Live target:",
    "Development checkout used for live run:",
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
)

REQUIRED_QUALITY_LABELS = (
    "Useful:",
    "Relevant but routine:",
    "Noise:",
    "Concepts reviewed:",
    "Unsupported claims:",
    "Sanitization findings:",
    "Delivery outcome:",
    "Vault-only answer evidence:",
    "Vault-only miss evidence:",
)

DECISION_LABELS = (
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

REDACTION_BOUNDARIES = (
    "secret values",
    "webhook URLs",
    "raw tokens",
    "recipient-private message contents",
    "private vault note contents",
    "config/.env",
)

ALLOWED_NO_GO_PRIMARY_CAUSES = (
    "onboarding",
    "source quality",
    "collection reliability",
    "synthesis quality",
    "trust/citations",
    "delivery",
    "runtime cost",
    "insufficient user value",
)

SECRET_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"sk-[A-Za-z0-9_-]{8,}",
        r"xox[baprs]-[A-Za-z0-9-]{8,}",
        r"gh[pousr]_[A-Za-z0-9_]{8,}",
        r"BEGIN (RSA|OPENSSH|PRIVATE) KEY",
        r"https?://[^\s)]*(hook|webhook)[^\s)]*",
        r"[A-Z0-9_]*(TOKEN|SECRET|PASSWORD|WEBHOOK)[A-Z0-9_]*\s*=\s*\S+",
    )
)

PLACEHOLDER_VALUES = {
    "",
    "tbd",
    "todo",
    "placeholder",
    "n/a",
    "na",
    "disposable|dedicated",
    "pass/fail",
}


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _label_pattern(label: str) -> re.Pattern[str]:
    return re.compile(rf"^(?:-\s*)?{re.escape(label)}\s*(.*)$", re.MULTILINE)


def _extract_label_value(text: str, label: str) -> str | None:
    match = _label_pattern(label).search(text)
    if match is None:
        return None
    return match.group(1).strip()


def _is_placeholder(value: str, *, none_is_placeholder: bool = False) -> bool:
    normalized = _normalize(value)
    if none_is_placeholder and normalized == "none":
        return True
    return normalized in PLACEHOLDER_VALUES


def _parse_stage_rows(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        stage = cells[0]
        if stage in REQUIRED_STAGE_ROWS:
            rows[stage] = cells[1]
    return rows


def _redaction_errors(text: str) -> list[str]:
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return ["Forbidden secret-like content"]
    return []


def _structure_errors(text: str) -> list[str]:
    errors: list[str] = []
    for label in (*REQUIRED_VALUE_LABELS, *REQUIRED_QUALITY_LABELS, *DECISION_LABELS):
        if _extract_label_value(text, label) is None:
            errors.append(f"Missing required field: {label}")

    stage_rows = _parse_stage_rows(text)
    for stage in REQUIRED_STAGE_ROWS:
        if stage not in stage_rows:
            errors.append(f"Missing stage row: {stage}")

    for boundary in REDACTION_BOUNDARIES:
        if boundary not in text:
            errors.append(f"Missing redaction boundary: {boundary}")

    return errors


def _strict_required_value_errors(text: str) -> list[str]:
    errors: list[str] = []
    for label in (*REQUIRED_VALUE_LABELS, *REQUIRED_QUALITY_LABELS, "Next corrective action:"):
        value = _extract_label_value(text, label)
        if value is None:
            continue
        if _is_placeholder(value):
            errors.append(f"Missing required field: {label}")
    return errors


def _stage_status_errors(stage_rows: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for stage in REQUIRED_STAGE_ROWS:
        status = stage_rows.get(stage, "")
        if status not in {"PASS", "FAIL"}:
            errors.append(f"Invalid stage status: {stage}")
    return errors


def _percentage(value: str) -> int | None:
    match = re.search(r"(\d+)\s*%", value)
    if match is None:
        return None
    return int(match.group(1))


def _cycle_minutes(value: str) -> tuple[int, int] | None:
    cycle_1 = re.search(r"cycle\s*1\s*=\s*(\d+)", value, re.IGNORECASE)
    cycle_2 = re.search(r"cycle\s*2\s*=\s*(\d+)", value, re.IGNORECASE)
    if cycle_1 is None or cycle_2 is None:
        return None
    return int(cycle_1.group(1)), int(cycle_2.group(1))


def _has_delivered_cycles(value: str) -> bool:
    normalized = _normalize(value)
    return "cycle 1=delivered" in normalized and "cycle 2=delivered" in normalized


def _is_affirmative(value: str) -> bool:
    return _normalize(value).startswith("yes")


def _go_consistency_errors(text: str, stage_rows: dict[str, str]) -> list[str]:
    errors: list[str] = []

    if any(stage_rows.get(stage) != "PASS" for stage in REQUIRED_STAGE_ROWS):
        errors.append("GO decision is inconsistent with pilot criteria")

    deliveries = _extract_label_value(text, "Cycle deliveries:") or ""
    if not _has_delivered_cycles(deliveries):
        errors.append("GO decision is inconsistent with pilot criteria")

    useful_percentage = _percentage(_extract_label_value(text, "Useful surfaced items:") or "")
    if useful_percentage is None or useful_percentage < 60:
        errors.append("GO decision is inconsistent with pilot criteria")

    minutes = _cycle_minutes(_extract_label_value(text, "Post-setup intervention per cycle:") or "")
    if minutes is None or minutes[0] > 10 or minutes[1] > 10:
        errors.append("GO decision is inconsistent with pilot criteria")

    critical_failure = _extract_label_value(text, "Critical trust/safety failure:") or ""
    if _normalize(critical_failure) != "none":
        errors.append("GO decision is inconsistent with pilot criteria")

    second_cycle = _extract_label_value(text, "Second-cycle useful new/updated concept:") or ""
    if not _is_affirmative(second_cycle):
        errors.append("GO decision is inconsistent with pilot criteria")

    recurring = _extract_label_value(text, "User wants recurring run enabled:") or ""
    if not _is_affirmative(recurring):
        errors.append("GO decision is inconsistent with pilot criteria")

    development_checkout = _extract_label_value(text, "Development checkout used for live run:") or ""
    if _normalize(development_checkout) != "no":
        errors.append("GO decision is inconsistent with pilot criteria")

    return list(dict.fromkeys(errors))


def _decision_errors(text: str, stage_rows: dict[str, str]) -> list[str]:
    decision = _normalize(_extract_label_value(text, "GO / NO-GO:") or "")
    primary_cause = _normalize(_extract_label_value(text, "Primary cause:") or "")
    next_action = _extract_label_value(text, "Next corrective action:") or ""

    if decision == "go":
        return _go_consistency_errors(text, stage_rows)

    if decision == "no-go":
        errors: list[str] = []
        if primary_cause not in ALLOWED_NO_GO_PRIMARY_CAUSES:
            errors.append("Invalid NO-GO primary cause")
        if _is_placeholder(next_action, none_is_placeholder=True):
            errors.append("Missing required field: Next corrective action:")
        return errors

    return ["Missing required field: GO / NO-GO:"]


def validate_text(text: str, *, template: bool = False) -> list[str]:
    errors = [*_redaction_errors(text), *_structure_errors(text)]
    if template:
        return errors

    stage_rows = _parse_stage_rows(text)
    errors.extend(_strict_required_value_errors(text))
    errors.extend(_stage_status_errors(stage_rows))
    errors.extend(_decision_errors(text, stage_rows))
    return list(dict.fromkeys(errors))


def _validate_command(args: argparse.Namespace) -> int:
    evidence_path = Path(args.evidence_path)
    try:
        text = evidence_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Unable to read evidence file: {exc}", file=sys.stderr)
        return 2

    errors = validate_text(text, template=args.template)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2

    print(TEMPLATE_OK if args.template else STRICT_OK)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate pilot canary evidence Markdown.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate an evidence Markdown file")
    validate_parser.add_argument("evidence_path")
    validate_parser.add_argument(
        "--template",
        action="store_true",
        help="allow blank values while checking the evidence template contract",
    )
    validate_parser.set_defaults(func=_validate_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
