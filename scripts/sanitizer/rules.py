"""Deterministic S1-S9 instruction-stripping rules."""

from __future__ import annotations

import re
from dataclasses import dataclass

from scripts.sanitizer.model import Finding, SanitizeResult


@dataclass(frozen=True)
class Rule:
    rule: str
    severity: str
    pattern: re.Pattern[str]
    action: str
    placeholder: str = ""


# S9 is deliberately applied FIRST. It removes zero-width and bidi control chars,
# which an attacker inserts *inside* a trigger phrase (e.g. "ig​nore previous
# instructions") to break the S1-S8 pattern regexes. If S9 ran after them, the
# invisible chars would defeat detection and then be cleaned away — reconstructing a
# readable injection in the "sanitized" output. Normalizing first lets S1-S8 match the
# de-obfuscated text. (Layered-obfuscation bypass; security review 2026-07-08.)
RULES: tuple[Rule, ...] = (
    Rule(
        "S9",
        "critical",
        # B613: intentional — this class detects and strips bidi/zero-width control
        # chars: U+061C (ALM), U+200B-U+200F, U+202A-U+202E, U+2060 (WJ),
        # U+2066-U+2069 (Trojan-Source isolates), U+FEFF (ZWNBSP/BOM).
        re.compile("[؜​-‏‪-‮⁠⁦-⁩﻿]"),  # nosec B613
        "remove",
    ),
    Rule(
        "S1",
        "critical",
        re.compile(
            r"(?i)(you\s+are\s+now|"
            # "ignore <one-or-more injection-signal fillers> instructions" — catches the
            # canonical "ignore all previous instructions" (stacked fillers) and the
            # single-filler forms. The filler set is restricted to injection signals
            # (all/any/previous/prior/earlier) and requires >=1 (`+`), so benign prose
            # like "ignore the instructions in the README" is NOT stripped.
            r"ignore(?:\s+(?:all|any|previous|prior|earlier))+\s+instructions|"
            r"disregard\s+(?:above|prior)|new\s+instructions:|from\s+now\s+on\s+you\s+are|"
            r"forget\s+(?:everything|all)\s+(?:you|previous)|"
            r"act\s+as\s+(?:an?\s+)?(?:admin|root|system))"
            r"[^.\n]*",
        ),
        "replace",
        "[STRIPPED:S1]",
    ),
    Rule(
        "S2",
        "critical",
        re.compile(
            r"(?i)(<\|im_start\|>|<\|im_end\|>|---END SYSTEM---|---END PROMPT---|"
            r"</?system>|</?user>|</?assistant>)",
        ),
        "remove",
    ),
    Rule(
        "S3",
        "critical",
        re.compile(
            r"(?i)(summarize\s+(?:all\s+of\s+)?the\s+above(?:\s+in\s+bullet\s+points)?|"
            r"reveal\s+your\s+(?:instructions|system\s+prompt)|"
            r"what\s+are\s+your\s+(?:instructions|guidelines)|"
            r"repeat\s+(?:your\s+)?(?:instructions|system\s+prompt))",
        ),
        "replace",
        "[STRIPPED:S3]",
    ),
    Rule(
        "S5",
        "critical",
        re.compile(r"!\[[^\]]*\]\(https?://[^\)]+\?[^\)]*\{[^}]+\}[^\)]*\)"),
        "remove",
    ),
    Rule(
        "S6",
        "critical",
        re.compile(r"https?://[^\s]+\?[^&\s]*\{[^}]+\}"),
        "replace",
        "[STRIPPED-URL:S6]",
    ),
    Rule(
        "S4",
        "medium",
        re.compile(
            r"(?i)(pretend (?:to be|that you are)|act as (?:an? )?[a-z]+|"
            r"simulate (?:an? )?[a-z]+|you(?:'re| are) now (?:an? )?[a-z]+|imagine you are)",
        ),
        "flag",
    ),
    Rule(
        "S7",
        "medium",
        re.compile(
            r"(?i)(os\.system\(|subprocess\.|exec\(|eval\(|\|\s*sh\b|\|\s*bash\b|"
            r"; ?(?:rm|cat|curl|wget) )",
        ),
        "flag",
    ),
    Rule(
        "S8",
        "informational",
        re.compile(
            r"(?i)(first,? agree (?:that|to)|building on (?:your )?previous|"
            r"continuing from (?:where|our)|as (?:we|you) (?:just )?discussed|"
            r"remember when (?:you|we))",
        ),
        "flag",
    ),
)


def sanitize_text(text: str) -> SanitizeResult:
    """Apply the ruleset. Critical classes are removed/replaced; others are flagged."""
    findings: list[Finding] = []
    clean = text

    for rule in RULES:
        if rule.action == "flag":
            for match in rule.pattern.finditer(clean):
                findings.append(
                    Finding(rule.rule, rule.severity, "flagged", match.group(0)[:80])
                )
            continue

        replacement = rule.placeholder if rule.action == "replace" else ""

        def _sub(match: re.Match[str], _rule: Rule = rule, _rep: str = replacement) -> str:
            findings.append(
                Finding(_rule.rule, _rule.severity, "stripped", match.group(0)[:80])
            )
            return _rep

        clean = rule.pattern.sub(_sub, clean)

    return SanitizeResult(clean_text=clean, findings=findings)


__all__ = [
    "RULES",
    "Rule",
    "sanitize_text",
]
