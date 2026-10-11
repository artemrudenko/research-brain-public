from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree  # nosec B405

from scripts.opml_import.model import OpmlEntry, OpmlError

MAX_OPML_BYTES = 10 * 1024 * 1024

# OPML is parsed only after size + DOCTYPE guards.
_SLUG_RE = re.compile(r"[a-z0-9]+")


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _safe_slug(label: str) -> str:
    ascii_label = (
        unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    )
    parts = _SLUG_RE.findall(ascii_label.lower())
    if parts:
        return "-".join(parts)
    return f"imported-{_short_hash(label)}"


def _stable_folder_slugs(labels: Iterable[str]) -> dict[str, str]:
    """Map distinct folder labels to deterministic, non-merging topic slugs."""

    label_to_slug: dict[str, str] = {}
    base_owner: dict[str, str] = {}
    for label in labels:
        if label in label_to_slug:
            continue
        base = _safe_slug(label)
        owner = base_owner.get(base)
        if owner is None:
            base_owner[base] = label
            label_to_slug[label] = base
        elif owner == label:
            label_to_slug[label] = base
        else:
            label_to_slug[label] = f"{base}-{_short_hash(label)}"
    return label_to_slug


def _is_http_url(url: str) -> bool:
    parts = urlsplit(url.strip())
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _outline_attr(element: ElementTree.Element, name: str) -> str:
    for key, value in element.attrib.items():
        if key.lower() == name.lower():
            return value.strip()
    return ""


def _outline_children(element: ElementTree.Element) -> list[ElementTree.Element]:
    return [child for child in list(element) if _local_name(child.tag) == "outline"]


def parse_opml(path: str | Path) -> list[OpmlEntry]:
    """Parse OPML into stable candidate entries without touching config."""

    opml_path = Path(path)
    try:
        data = opml_path.read_bytes()
    except OSError as exc:
        raise OpmlError(f"could not read OPML file: {exc}") from exc

    if len(data) > MAX_OPML_BYTES:
        raise OpmlError("OPML file is larger than the 10 MiB safety limit")
    if b"<!doctype" in data.lower():
        raise OpmlError("OPML files containing DOCTYPE are not accepted")

    try:
        # DOCTYPE is rejected above before ElementTree sees the bytes.
        root = ElementTree.fromstring(data)  # nosec B314
    except ElementTree.ParseError as exc:
        raise OpmlError(f"malformed OPML XML: {exc}") from exc

    body = next((child for child in root.iter() if _local_name(child.tag) == "body"), None)
    if body is None:
        raise OpmlError("OPML file has no body")

    raw_entries: list[tuple[str, str, str, str | None]] = []

    def visit(element: ElementTree.Element, folder: str | None) -> None:
        children = _outline_children(element)
        text = _outline_attr(element, "text")
        title = _outline_attr(element, "title") or text or "Untitled feed"
        xml_url = _outline_attr(element, "xmlUrl")
        outline_type = _outline_attr(element, "type").lower()

        if xml_url or not children:
            raw_entries.append((title, xml_url, outline_type, folder))
            return

        next_folder = title or folder
        for child in children:
            visit(child, next_folder)

    for outline in _outline_children(body):
        visit(outline, None)

    return [
        OpmlEntry(
            id=f"feed-{index:03d}",
            title=title,
            xml_url=xml_url,
            outline_type=outline_type,
            folder_label=folder,
            sequence=index,
        )
        for index, (title, xml_url, outline_type, folder) in enumerate(raw_entries, start=1)
    ]

