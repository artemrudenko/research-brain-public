from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from scripts.opml_import.model import UsageError

__all__ = [
    "_parse_assignments",
    "_parse_csv_ids",
    "_render_human",
]


def _parse_csv_ids(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    values = [part.strip() for part in raw.split(",")]
    if any(not value for value in values):
        raise UsageError("selection list contains an empty ID")
    return values


def _parse_assignments(raw_assignments: Sequence[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in raw_assignments:
        if "=" not in raw:
            raise UsageError(f"assignment {raw!r} must use ID=topic-slug")
        item_id, topic = (part.strip() for part in raw.split("=", 1))
        if not item_id or not topic:
            raise UsageError(f"assignment {raw!r} must use ID=topic-slug")
        if item_id in parsed:
            raise UsageError(f"repeated assignment ID {item_id!r}")
        parsed[item_id] = topic
    return parsed


def _render_human(report: dict[str, Any]) -> str:
    lines = [
        f"OPML {report['mode']} report",
        (
            f"Total: {report['counts']['total']} | Ready: {report['counts']['ready']} | "
            f"Selected: {report['counts']['selected']} | Added: {report['counts']['added']}"
        ),
    ]
    if report.get("proposed_topics"):
        lines.append("Proposed topics:")
        for topic in report["proposed_topics"]:
            lines.append(f"- {topic['slug']} ({topic['label']})")
    lines.append("Sources:")
    for item in report["items"]:
        marker = "*" if item["selected"] else "-"
        lines.append(
            f"{marker} {item['id']} {item['status']}: {item['title']} -> "
            f"{item['resulting_topic']} ({item['reason']})"
        )
    return "\n".join(lines)
