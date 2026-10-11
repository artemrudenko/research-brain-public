"""Output rendering for URL intake classification."""

from __future__ import annotations

import json

from scripts.intake_flow.models import Classification, Preview


def _preview_lines(preview: Preview) -> list[str]:
    """The facts behind the verdict, so a reader can check it rather than trust it.

    Authors are REPORTED, never offered as something to act on: author monitoring
    does not exist yet, and an action that silently does nothing costs more trust
    than staying quiet would.
    """
    lines: list[str] = []
    if preview.title:
        lines.append(f"Title: {preview.title}")
    if preview.publication:
        lines.append(f"Publication: {preview.publication}")
    if preview.authors:
        names = ", ".join(a.name for a in preview.authors)
        label = "Author" if len(preview.authors) == 1 else "Authors"
        lines.append(f"{label}: {names}")
    if preview.published_at:
        lines.append(f"Published: {preview.published_at}")
    if preview.feed_url:
        lines.append(f"Feed found: {preview.feed_url}")
    return lines


def render_human(result: Classification) -> str:
    data = result.to_dict()
    lines = [
        f"Recognized: {data['kind']}",
        f"Proposed action: {data['proposed_action']}",
        f"Confidence: {data['confidence']:.2f}",
        f"Reason: {data['reason']}",
    ]
    if result.preview is not None:
        # Blank line first: the verdict and the evidence for it read as two blocks.
        found = _preview_lines(result.preview)
        if found:
            lines.extend(["", *found])
    if result.kind == "recurring_source":
        lines.append("")
        lines.append(f"Source URL: {result.source_url}")
        lines.append(f"Source type: {result.source_type}")
        lines.append(f"Proposed topic: {result.proposed_topic} ({result.topic_mode})")
    if result.clarification_question:
        lines.append(result.clarification_question)
    return "\n".join(lines)


def render_json(result: Classification) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True)
