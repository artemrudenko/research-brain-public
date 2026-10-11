#!/usr/bin/env python3
"""
presend_review.py — deterministic pre-send checks for a built digest.

The opt-in **pre-send review gate** (BACKLOG) runs an adversarial pass over a
built digest BEFORE a real delivery. The agent-runtime `digest-review` skill owns
the LLM-grade checks (are the digest's claims grounded in the cited concepts /
sources? are the 🟢/🔵/🟡 trust markers justified?); this module is the
DETERMINISTIC backbone it builds on — and the only part a headless run can do
alone:

  1. **injection-leak scan** — a sanitizer placeholder (`[STRIPPED:…]`) or an
     injection pattern in the *delivered* text means untrusted source content
     leaked through synthesis into the digest. Reuses the S1–S9 ruleset from
     `sanitize_incoming` (DRY) so the two never drift.
  2. **link resolution** (opt-in, network) — every http(s) link the digest cites
     actually resolves, so a reader never clicks a dead source.

Every check is **advisory** by default: the unattended weekly digest is soft by
design and must never silently fail to deliver (BACKLOG). `--strict` turns a
finding into a non-zero exit for callers who want a hard gate.

Usage:
    python3 scripts/presend_review.py <digest.md> [--check-links] [--strict]
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.error
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts import sanitize_incoming  # noqa: E402 — reuse the S1–S9 injection ruleset

# A liveness probe: given a URL, fetch it (return body) or raise on any failure.
FetchFn = Callable[[str], str]

# Markdown link target `](URL)` and a bare http(s) URL; both restricted to http(s)
# so relative links, mailto:, etc. are ignored (they aren't sources to resolve).
_MD_LINK = re.compile(r"\]\((https?://[^)\s]+)\)")
_BARE_URL = re.compile(r"(?<![(\w])(https?://[^\s)\]]+)")
# A leaked sanitizer placeholder that should never reach a delivered digest.
_STRIPPED_MARKER = re.compile(r"\[STRIPPED[^\]]*\]")


@dataclass(frozen=True)
class ReviewReport:
    """Outcome of the deterministic pre-send checks over one digest."""

    checked_links: int
    broken_links: list[str] = field(default_factory=list)
    injection_findings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when nothing suspicious surfaced (no broken links, no leak)."""
        return not self.broken_links and not self.injection_findings

    def summary(self) -> str:
        """A one-line human verdict for the CLI / skill report."""
        if self.ok:
            return f"PASS — {self.checked_links} link(s) checked, no injection leak."
        parts: list[str] = []
        if self.injection_findings:
            parts.append(f"{len(self.injection_findings)} injection-leak finding(s)")
        if self.broken_links:
            parts.append(f"{len(self.broken_links)} broken link(s)")
        return "FINDINGS — " + ", ".join(parts) + "."


def extract_links(markdown: str) -> list[str]:
    """Return the http(s) links a digest cites, in order, de-duplicated.

    Both markdown `[text](url)` targets and bare URLs count; a bare URL that is
    already the target of a markdown link is not double-counted."""
    ordered: list[str] = []
    seen: set[str] = set()
    for match in _MD_LINK.finditer(markdown):
        url = match.group(1)
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    for match in _BARE_URL.finditer(markdown):
        url = match.group(1)
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def scan_injection_leak(markdown: str) -> list[str]:
    """Return a finding per sign that untrusted content leaked into the digest.

    Two deterministic signals: a literal sanitizer placeholder that reached the
    delivered text, and any span the `sanitize_incoming` ruleset would strip
    (an injection pattern that survived synthesis). Reusing that ruleset keeps
    the gate in lock-step with the incoming sanitizer."""
    findings: list[str] = []
    for marker in _STRIPPED_MARKER.findall(markdown):
        findings.append(f"sanitizer placeholder leaked into digest: {marker}")
    for finding in sanitize_incoming.sanitize_text(markdown).findings:
        findings.append(
            f"injection pattern in digest ({finding.rule}/{finding.severity}): "
            f"{finding.snippet.strip()[:80]}"
        )
    return findings


def _default_fetch(url: str) -> str:
    """Probe via the collector's SSRF-guarded fetch (imported lazily so the common
    injection-only path never pulls in the collector)."""
    from scripts import collect  # noqa: WPS433 (intentional lazy import)

    return collect.fetch(url)


def check_links_resolve(urls: Iterable[str], *, fetch: FetchFn | None = None) -> list[str]:
    """Return one finding per unreachable link. Injectable + best-effort: `fetch`
    defaults to the SSRF-guarded collector fetch; tests pass a fake."""
    probe = fetch if fetch is not None else _default_fetch
    broken: list[str] = []
    for url in urls:
        try:
            probe(url)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            broken.append(f"{url}: unreachable ({exc})")
    return broken


def review(
    markdown: str, *, fetch: FetchFn | None = None, check_links: bool = True
) -> ReviewReport:
    """Run the deterministic pre-send checks and return a composite report.

    `check_links=False` skips the network probe (injection scan only) — the
    default for a fast, offline pass; the skill turns links on for a real gate."""
    injection = scan_injection_leak(markdown)
    if check_links:
        links = extract_links(markdown)
        broken = check_links_resolve(links, fetch=fetch)
        return ReviewReport(len(links), broken_links=broken, injection_findings=injection)
    return ReviewReport(0, broken_links=[], injection_findings=injection)


def _print_report(report: ReviewReport) -> None:
    print("# Pre-send review\n")
    print(report.summary())
    for finding in report.injection_findings:
        print(f"- ⚠️  {finding}")
    for finding in report.broken_links:
        print(f"- 🔗 {finding}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("digest", help="path to the built digest markdown file")
    ap.add_argument(
        "--check-links", action="store_true",
        help="also probe every cited link over the network (opt-in)",
    )
    ap.add_argument(
        "--strict", action="store_true",
        help="exit 1 when any finding surfaces (default: advisory, always exit 0)",
    )
    args = ap.parse_args(argv)

    markdown = Path(args.digest).read_text(encoding="utf-8")
    report = review(markdown, check_links=args.check_links)
    _print_report(report)
    # Advisory by default: a finding never blocks a send unless --strict is set.
    return 1 if (args.strict and not report.ok) else 0


if __name__ == "__main__":
    sys.exit(main())
