"""Shared sanitizer result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    """One matched injection span."""

    rule: str
    severity: str
    action: str
    snippet: str


@dataclass
class SanitizeResult:
    """The outcome of sanitizing one body of text."""

    clean_text: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def stripped_classes(self) -> set[str]:
        return {f.rule for f in self.findings if f.action == "stripped"}

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for finding in self.findings:
            out[finding.rule] = out.get(finding.rule, 0) + 1
        return out

    @property
    def severity(self) -> str:
        sev = {f.severity for f in self.findings if f.action == "stripped"}
        if "critical" in sev:
            return "critical"
        if sev or any(f.severity == "medium" for f in self.findings):
            return "medium"
        if self.findings:
            return "informational"
        return "clean"


@dataclass(frozen=True)
class FileOutcome:
    source: Path
    companion: Path
    result: SanitizeResult


@dataclass(frozen=True)
class GateResult:
    ok: bool
    missing: list[Path] = field(default_factory=list)
    stale: list[Path] = field(default_factory=list)
    corrupt: list[Path] = field(default_factory=list)
    unreadable: list[Path] = field(default_factory=list)
    # Companion produced by a superseded ruleset (its recorded sanitizer_version
    # no longer matches the current one). Distinct from `stale`: the SOURCE is
    # unchanged; it is the RULES that moved on, so the companion must be rebuilt
    # before synthesis may trust it. Fail-closed like every other bucket.
    outdated: list[Path] = field(default_factory=list)


__all__ = [
    "FileOutcome",
    "Finding",
    "GateResult",
    "SanitizeResult",
]
