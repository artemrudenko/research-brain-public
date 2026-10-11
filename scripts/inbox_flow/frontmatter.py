"""Frontmatter serialization for inbox-captured articles."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any


def yaml_scalar_line(key: str, value: str, load_yaml: Callable[[], Any]) -> str:
    """One valid `key: value` YAML line, correctly quoting `value`."""
    flat = " ".join(str(value).split())
    return load_yaml().safe_dump(
        {key: flat}, default_flow_style=False, allow_unicode=True, sort_keys=False
    ).strip()


def article_frontmatter(
    *,
    schema_version: int,
    source: str,
    url: str,
    title: str,
    author: str,
    when: date,
    category: str,
    tags: list[str] | None,
    load_yaml: Callable[[], Any],
) -> str:
    """A CONVENTIONS §5 strict frontmatter block emitted as valid YAML."""
    flow_tags = load_yaml().safe_dump(
        list(tags or []), default_flow_style=True, allow_unicode=True
    ).strip()
    # Dates are emitted bare: an ISO date is always YAML-safe, and YAML would
    # otherwise quote it, which the lightweight date parsers read back literally.
    iso = when.isoformat()
    lines = [
        "---",
        f"schema_version: {schema_version}",
        yaml_scalar_line("source", source, load_yaml),
        yaml_scalar_line("url", url, load_yaml),
        yaml_scalar_line("title", title, load_yaml),
        yaml_scalar_line("author", author, load_yaml),
        f"date_published: {iso}",
        f"collected: {iso}",
        yaml_scalar_line("category", category, load_yaml),
        f"tags: {flow_tags}",
        "---",
    ]
    return "\n".join(lines)


__all__ = [
    "article_frontmatter",
    "yaml_scalar_line",
]
