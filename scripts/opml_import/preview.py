from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scripts.manage_sources import _validate_topic_name, list_state
from scripts.normalize_url import normalize_or_raw
from scripts.opml_import.model import STATUSES, OpmlEntry, Status, UsageError
from scripts.opml_import.parsing import _is_http_url, _stable_folder_slugs

_ID_RE = re.compile(r"^feed-[0-9]{3}$")


def _existing_state(config_dir: Path) -> tuple[set[str], set[str]]:
    state = list_state(config_dir)
    topics = {topic.name for topic in state.topics}
    urls = {
        normalize_or_raw(source.url)
        for category in state.categories
        for source in category.sources
    }
    return topics, urls


def _validate_id(value: str, known_ids: set[str], label: str) -> None:
    if not _ID_RE.fullmatch(value):
        raise UsageError(f"malformed {label} ID {value!r}; expected feed-001")
    if value not in known_ids:
        raise UsageError(f"unknown {label} ID {value!r}")


def _validate_repeated(ids: Sequence[str], label: str) -> None:
    seen: set[str] = set()
    for value in ids:
        if value in seen:
            raise UsageError(f"repeated {label} ID {value!r}")
        seen.add(value)


def _topic_label(slug: str) -> str:
    if slug == "imported":
        return "Imported"
    return slug.replace("-", " ").title()


def _base_items(entries: Sequence[OpmlEntry], config_dir: Path) -> list[dict[str, Any]]:
    existing_topics, existing_urls = _existing_state(config_dir)
    folder_labels = [entry.folder_label for entry in entries if entry.folder_label]
    folder_slugs = _stable_folder_slugs(label for label in folder_labels if label is not None)
    seen_urls: set[str] = set()
    items: list[dict[str, Any]] = []

    for entry in entries:
        topic = folder_slugs[entry.folder_label] if entry.folder_label else "imported"
        canonical_url = normalize_or_raw(entry.xml_url)
        status: Status = "ready"
        reason = "Ready to import"

        if not entry.xml_url:
            status = "invalid"
            reason = "Missing xmlUrl"
            canonical_url = ""
        elif not _is_http_url(entry.xml_url):
            status = "invalid"
            reason = "xmlUrl must be HTTP(S)"
        elif entry.outline_type and entry.outline_type not in {"rss", "atom"}:
            status = "unsupported"
            reason = f"Unsupported outline type {entry.outline_type!r}"
        elif canonical_url in existing_urls:
            status = "already_existing"
            reason = "Already present in config"
        elif canonical_url in seen_urls:
            status = "already_existing"
            reason = "Duplicate URL within OPML"

        if canonical_url:
            seen_urls.add(canonical_url)

        items.append(
            {
                "id": entry.id,
                "title": entry.title,
                "url": entry.xml_url,
                "canonical_url": canonical_url,
                "outline_type": entry.outline_type,
                "folder": entry.folder_label,
                "topic_label": _topic_label(topic),
                "resulting_topic": topic,
                "assignment": None,
                "status": status,
                "reason": reason,
                "selected": status == "ready",
                "existing_topic": topic in existing_topics,
            }
        )

    return items


def _apply_selection(items: list[dict[str, Any]], selected: Sequence[str] | None) -> None:
    known_ids = {str(item["id"]) for item in items}
    ready_ids = {str(item["id"]) for item in items if item["status"] == "ready"}

    if selected is None:
        for item in items:
            item["selected"] = item["status"] == "ready"
        return

    selected_ids = list(selected)
    _validate_repeated(selected_ids, "selection")
    for item_id in selected_ids:
        _validate_id(item_id, known_ids, "selection")
        if item_id not in ready_ids:
            raise UsageError(f"selection ID {item_id!r} is not a ready item")

    selected_set = set(selected_ids)
    for item in items:
        item["selected"] = item["id"] in selected_set and item["status"] == "ready"


def _apply_assignments(
    items: list[dict[str, Any]], assignments: dict[str, str] | None
) -> None:
    if not assignments:
        return

    known_ids = {str(item["id"]) for item in items}
    by_id = {str(item["id"]): item for item in items}
    for item_id, topic in assignments.items():
        _validate_id(item_id, known_ids, "assignment")
        _validate_topic_name(topic)
        if by_id[item_id]["status"] != "ready":
            raise UsageError(f"assignment ID {item_id!r} is not a ready item")
        by_id[item_id]["assignment"] = topic
        by_id[item_id]["resulting_topic"] = topic
        by_id[item_id]["topic_label"] = _topic_label(topic)


def _counts(items: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {status: 0 for status in STATUSES}
    for item in items:
        counts[str(item["status"])] += 1
    counts["selected"] = sum(1 for item in items if item["selected"])
    counts["total"] = len(items)
    return counts


def _proposed_topics(items: Sequence[dict[str, Any]], config_dir: Path) -> list[dict[str, str]]:
    existing_topics, _ = _existing_state(config_dir)
    proposed: dict[str, str] = {}
    for item in items:
        if item["status"] != "ready":
            continue
        topic = str(item["resulting_topic"])
        if topic not in existing_topics:
            proposed[topic] = str(item["topic_label"])
    return [{"slug": slug, "label": label} for slug, label in sorted(proposed.items())]


def build_preview(
    entries: Sequence[OpmlEntry],
    config_dir: str | Path,
    assignments: dict[str, str] | None = None,
    selected: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic OPML import preview without writing config."""

    cfg = Path(config_dir)
    items = _base_items(entries, cfg)
    _apply_assignments(items, assignments)
    _apply_selection(items, selected)
    return {
        "mode": "preview",
        "items": items,
        "proposed_topics": _proposed_topics(items, cfg),
        "counts": _counts(items),
    }

