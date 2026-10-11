from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Source:
    """One Active-sources row."""

    url: str
    type: str
    tier: str
    priority: str
    filter_note: str
    active: bool


@dataclass
class Category:
    """A `## Category:` block in sources.md and its parsed source rows."""

    name: str
    sources: list[Source] = field(default_factory=list)


@dataclass
class Topic:
    """One monitored topic (a `## Topic:` section / a `topics:` YAML entry).

    `tags` / `include` / `exclude` are additive fields carried by the YAML
    format (config/topics.yaml) and extracted best-effort from the markdown
    bullets; legacy callers that only need the name keep constructing
    `Topic(name=...)` unchanged.
    """

    name: str
    tags: list[str] = field(default_factory=list)
    include: str = ""
    exclude: str = ""


@dataclass
class State:
    """The combined, machine-readable view of both config files."""

    topics: list[Topic] = field(default_factory=list)
    categories: list[Category] = field(default_factory=list)


