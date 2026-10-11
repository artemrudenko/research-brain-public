#!/usr/bin/env python3
"""model.py — one proposed source, and the outcome of one discovery run."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Candidate:
    """A site we might start monitoring.

    The unit is a SITE, not a page: the user decides about sources, and a
    per-page list would let one prolific site crowd out every other candidate
    purely on volume.
    """

    domain: str
    url: str
    hits: int = 1
    title: str = ""
    snippet: str = ""
    role: str = "independent"
    feed_url: str = ""
    reason: str = ""
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiscoveryResult:
    """What one `/discover` run found. Proposals only — nothing was changed."""

    topic: str
    candidates: list[Candidate] = field(default_factory=list)
    note: str = ""
    # True when the configured provider is Claude's in-agent WebSearch, which a
    # headless process cannot call: the agent must search and feed results back.
    needs_agent_search: bool = False
