"""Rendering and output of a hygiene pass: the human summary, the durable
brain-health report the digest later reads, and the `--json` serialization.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

# Shared atomic writer (random-suffixed temp + replace) for the durable brain-health
# report the digest later reads — a crash mid-write must not leave a torn report.
from scripts.hygiene.model import BrainHealth
from scripts.registry import atomic_write_text

# Human-friendly section titles for each warning kind, in report order.
_KIND_TITLES = [
    ("orphan", "Orphans"),
    ("weakly-linked", "Weakly-linked (tag-only)"),
    ("broken-link", "Broken links"),
    ("missing-sources", "Missing sources"),
    ("uncited-fact", "Uncited key facts"),
    ("missing-from-index", "Missing from INDEX.md"),
    ("stale", "Stale (needs re-verification)"),
    ("tag", "Tag hygiene"),
]


def render_summary(health: BrainHealth, *, today: date) -> str:
    """Render the human-readable brain-health summary markdown."""
    out: list[str] = [
        f"# Brain health — {today.isoformat()}",
        "",
        health.health_headline,  # machine-matched `Health:` line for the digest
        health.headline,         # human-readable summary line
        "",
    ]
    if not health.warnings:
        if health.concept_count == 0:
            # An empty vault has no hygiene issues, but "healthy" would hide the
            # uninitialised state from a new user — say so plainly instead.
            out.append(
                "The vault is empty — no concepts yet. Add sources and run the "
                "pipeline (collect → synthesis) to populate it."
            )
        else:
            out.append("No hygiene issues found. The vault is healthy.")
        return "\n".join(out).rstrip() + "\n"

    for kind, title in _KIND_TITLES:
        items = [w for w in health.warnings if w.kind == kind]
        if not items:
            continue
        out.append(f"## {title} ({len(items)})")
        out.append("")
        for item in items:
            out.append(f"- {item.message}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def default_report_path(root: Path, today: date) -> Path:
    """The conventional output: pipeline/3-synthesis/brain-health_YYYY-MM-DD.md."""
    return root / "pipeline" / "3-synthesis" / f"brain-health_{today.isoformat()}.md"


def write_report(health: BrainHealth, *, root: Path, today: date) -> Path:
    """Write the summary to the conventional report path; return that path."""
    path = default_report_path(root, today)
    atomic_write_text(path, render_summary(health, today=today))
    return path


def health_to_dict(health: BrainHealth) -> dict[str, object]:
    """Serialize a BrainHealth result for `--json` output."""
    return {
        "concepts": health.concept_count,
        "orphans": health.orphans,
        "weakly_linked": health.weakly_linked,
        "broken_links": health.broken_links,
        "missing_sources": health.missing_sources,
        "uncited_facts": health.uncited_facts,
        "missing_from_index": health.missing_from_index,
        "stale": health.stale,
        "tag_findings": health.tag_findings,
        "headline": health.headline,
        "health_headline": health.health_headline,
        "warnings": [
            {"kind": w.kind, "concept": w.concept, "message": w.message}
            for w in health.warnings
        ],
    }
