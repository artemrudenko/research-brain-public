"""Synthesis run, topic lead, value evidence, and brain-health readers."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from scripts.digest.parsing import split_flat_frontmatter
from scripts.synthesis_freshness import is_fresh as topic_synthesis_is_fresh

SYNTHESIS_LOG_TEMPLATE = "synthesis-run_{date}.md"
SYNTHESIS_LOG_GRACE_DAYS = 1
LEAD_MAX_CHARS = 240

VALUE_EVIDENCE_KEYS = {
    "concepts created": 0,
    "concepts updated": 1,
    "existing concepts reused": 2,
}
VALUE_EVIDENCE_RE = re.compile(
    r"^\s*-\s*(concepts created|concepts updated|existing concepts reused)\s*:\s*(-?\d+)\b",
    re.IGNORECASE,
)


def load_topic_leads(synthesis_dir: Path, curated_dir: Path) -> dict[str, str]:
    """Map topic to a fresh one-line digest lead from the per-topic sidecar."""
    leads: dict[str, str] = {}
    if not synthesis_dir.exists():
        return leads
    for sidecar in sorted(synthesis_dir.glob("*/digest-lead.md")):
        topic = sidecar.parent.name
        if not topic_synthesis_is_fresh(curated_dir, synthesis_dir, topic):
            continue
        for raw in sidecar.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line == "---" or line.startswith("#"):
                continue
            if len(line) > LEAD_MAX_CHARS:
                line = line[: LEAD_MAX_CHARS - 1].rstrip() + "…"
            leads[topic] = line
            break
    return leads


def synthesis_log_exists(synthesis_dir: Path, *, today: date) -> bool:
    """True when a recent synthesis run log exists."""
    if not synthesis_dir.exists():
        return False
    newest: date | None = None
    for marker in synthesis_dir.glob("synthesis-run_*.md"):
        stamp = marker.stem[len("synthesis-run_"):]
        try:
            logdate = date.fromisoformat(stamp)
        except ValueError:
            continue
        if logdate > today:
            continue
        if newest is None or logdate > newest:
            newest = logdate
    if newest is None:
        return False
    return 0 <= (today - newest).days <= SYNTHESIS_LOG_GRACE_DAYS


def newest_synthesis_run(synthesis_dir: Path, *, today: date | None = None) -> Path | None:
    """Newest date-stamped synthesis run log, ignoring invalid and future stamps."""
    if not synthesis_dir.exists():
        return None
    newest: tuple[date, Path] | None = None
    for marker in synthesis_dir.glob("synthesis-run_*.md"):
        stamp = marker.stem[len("synthesis-run_"):]
        try:
            logdate = date.fromisoformat(stamp)
        except ValueError:
            continue
        if today is not None and logdate > today:
            continue
        if newest is None or logdate > newest[0]:
            newest = (logdate, marker)
    return newest[1] if newest is not None else None


def latest_synthesis_summary(synthesis_dir: Path) -> str | None:
    """Summarize the newest synthesis run log's first prose paragraph."""
    latest = newest_synthesis_run(synthesis_dir)
    if latest is None:
        return None
    _, body = split_flat_frontmatter(latest.read_text(encoding="utf-8"))
    paragraph: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not paragraph:
            if stripped and not stripped.startswith("#") and stripped != "---":
                paragraph.append(stripped)
            continue
        if not stripped:
            break
        paragraph.append(stripped)
    return " ".join(paragraph) or None


def latest_value_evidence(
    synthesis_dir: Path, *, today: date | None = None
) -> tuple[int, int, int]:
    """Return (concepts created, concepts updated, existing concepts reused)."""
    latest = newest_synthesis_run(synthesis_dir, today=today)
    if latest is None:
        return (0, 0, 0)
    _, body = split_flat_frontmatter(latest.read_text(encoding="utf-8"))
    counts = [0, 0, 0]
    in_totals = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_totals = stripped.casefold() == "## totals"
            continue
        if not in_totals:
            continue
        if stripped.startswith("#"):
            break
        match = VALUE_EVIDENCE_RE.match(line)
        if not match:
            continue
        value = int(match.group(2))
        if value < 0:
            continue
        counts[VALUE_EVIDENCE_KEYS[match.group(1).casefold()]] = value
    return (counts[0], counts[1], counts[2])


def latest_brain_health(synthesis_dir: Path) -> str | None:
    """One-line health summary from the newest brain-health report, or None."""
    if not synthesis_dir.exists():
        return None
    reports = sorted(synthesis_dir.glob("brain-health_*.md"))
    if not reports:
        return None
    latest = reports[-1]
    _, body = split_flat_frontmatter(latest.read_text(encoding="utf-8"))
    fallback = ""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "---":
            continue
        lowered = stripped.lower()
        if lowered.startswith("health:"):
            return stripped.split(":", 1)[1].strip()
        if not fallback and not stripped.startswith("#"):
            fallback = stripped.lstrip("-*+ ").strip()
    return fallback or None


__all__ = [
    "LEAD_MAX_CHARS",
    "SYNTHESIS_LOG_GRACE_DAYS",
    "SYNTHESIS_LOG_TEMPLATE",
    "VALUE_EVIDENCE_KEYS",
    "VALUE_EVIDENCE_RE",
    "latest_brain_health",
    "latest_synthesis_summary",
    "latest_value_evidence",
    "load_topic_leads",
    "newest_synthesis_run",
    "synthesis_log_exists",
]
