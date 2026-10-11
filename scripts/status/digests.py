from __future__ import annotations

import re
from pathlib import Path

from scripts.build_digest import _parse_iso_date, _split_frontmatter
from scripts.status.model import DigestEntry, Findings

# A digest filename is `digest_YYYY-MM-DD.md`; this captures the date stem.
_DIGEST_NAME_RE = re.compile(r"^digest_(\d{4}-\d{2}-\d{2})\.md$")

# Identifies a quiet-week digest body (CONVENTIONS §10 / build_digest.render).
_QUIET_RE = re.compile(r"\bquiet week\b", re.IGNORECASE)

# Section headings in a rendered digest that carry the highlight bullets.
_HIGHLIGHT_SECTIONS = ("new sources", "updated concepts")


def _digest_summary(text: str) -> tuple[str, bool]:
    """Return (one-line summary, is_quiet) for a digest's markdown body."""
    # Strip a leading `---`…`---` YAML frontmatter block (an agent-authored
    # digest may open with one) so the fence isn't mistaken for the headline and
    # summarized as a bare "---" (FIX 4; reuses build_digest's splitter).
    _, body = _split_frontmatter(text)
    lines = body.splitlines()
    # Match on the BODY, not the raw text: a digest whose frontmatter happens to
    # contain "quiet week" (e.g. in its title) must not be misflagged (BUG M6).
    if _QUIET_RE.search(body):
        return "Quiet week — no new sources or concept updates.", True

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # The volume headline is wrapped in italics: `_…_`.
        if stripped.startswith("_") and stripped.endswith("_") and len(stripped) > 2:
            return stripped.strip("_").strip(), False
        return stripped, False
    return "", False


def list_digests(*, n: int | None = None, root: Path) -> list[DigestEntry]:
    """List produced digests newest-first, optionally truncated to `n`."""
    synthesis_dir = root / "pipeline" / "3-synthesis"
    if not synthesis_dir.exists():
        return []

    entries: list[DigestEntry] = []
    for path in synthesis_dir.glob("digest_*.md"):
        match = _DIGEST_NAME_RE.match(path.name)
        if not match:
            continue
        parsed = _parse_iso_date(match.group(1))
        if parsed is None:
            continue
        summary, is_quiet = _digest_summary(path.read_text(encoding="utf-8"))
        entries.append(
            DigestEntry(date=parsed, path=path, summary=summary, is_quiet=is_quiet)
        )

    entries.sort(key=lambda e: e.date, reverse=True)
    return entries[:n] if n is not None else entries


def _extract_highlights(text: str) -> list[str]:
    """Pull the top-level bullets from a digest's highlight sections."""
    highlights: list[str] = []
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("## "):
            heading = stripped[3:].lower()
            in_section = any(heading.startswith(s) for s in _HIGHLIGHT_SECTIONS)
            continue

        if not in_section:
            continue

        # Top-level bullets only: indented sub-bullets (trust lines) start with
        # whitespace before the marker, so we check the raw, un-stripped line.
        if line.startswith(("- ", "* ", "+ ")):
            item = stripped.lstrip("-*+ ").strip()
            if item and not item.lower().startswith(("no new sources", "no concept updates")):
                highlights.append(item)
    return highlights


def latest_findings(*, root: Path) -> Findings:
    """Extract key findings from the most recent digest."""
    digests = list_digests(n=1, root=root)
    if not digests:
        return Findings(
            no_digests=True,
            message="No digests have been produced yet.",
        )

    latest = digests[0]
    if latest.is_quiet:
        return Findings(
            digest_date=latest.date,
            is_quiet=True,
            message=(
                f"The latest digest ({latest.date.isoformat()}) was a quiet week "
                "— nothing new to report."
            ),
        )

    highlights = _extract_highlights(latest.path.read_text(encoding="utf-8"))
    if not highlights:
        # A non-quiet digest with no parseable bullets — still a clear signal.
        return Findings(
            digest_date=latest.date,
            message=(
                f"The latest digest ({latest.date.isoformat()}) has no listed "
                "highlights."
            ),
        )
    count = len(highlights)
    return Findings(
        digest_date=latest.date,
        highlights=highlights,
        message=(
            f"{count} highlight{'' if count == 1 else 's'} from the latest digest "
            f"({latest.date.isoformat()})."
        ),
    )


__all__ = [
    "_DIGEST_NAME_RE",
    "_HIGHLIGHT_SECTIONS",
    "_QUIET_RE",
    "_digest_summary",
    "_extract_highlights",
    "latest_findings",
    "list_digests",
]
