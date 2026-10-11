#!/usr/bin/env python3
"""
run.py — one discovery run: search, shape, explain. Never writes.

The boundary matters more than the algorithm: discovery PROPOSES, and
`source-manage` is the only thing that adds a source. Keeping the write path out
of here means a bug in ranking can never enrol a site the user did not choose.

Search is injected so the caller decides the provider (and tests need neither a
network nor a configured key). The default routes through the existing dispatcher
in `scripts/search/` rather than adding another provider — its `none` /
missing-key soft-skip is exactly the behaviour discovery wants.
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from urllib.parse import urlsplit  # noqa: E402

from scripts.discovery.candidates import drop_known, group_by_domain, rank  # noqa: E402
from scripts.discovery.model import Candidate, DiscoveryResult  # noqa: E402
from scripts.search.search import CLAUDE_WEBSEARCH_KIND, web_search  # noqa: E402
from scripts.sources.store import active_sources_path, load_categories  # noqa: E402

SearchFn = Callable[[str], list[dict[str, str]]]

# Several angles on one topic: a single phrasing finds one slice of a field.
_QUERY_SHAPES = (
    "{topic} blog",
    "best {topic} newsletter OR blog to follow",
    "{topic} research updates",
)


def known_domains(config_dir: Path) -> set[str]:
    """Hosts already present in the source config, so proposals exclude them."""
    path = active_sources_path(config_dir)
    if not path.exists():
        return set()
    try:
        categories = load_categories(path)
    except (OSError, ValueError):
        return set()
    hosts: set[str] = set()
    for category in categories:
        for source in category.sources:
            host = (urlsplit(source.url).hostname or "").lower()
            if host:
                hosts.add(host[4:] if host.startswith("www.") else host)
    return hosts


def _explain(candidate: Candidate) -> str:
    """Why this site is being proposed, in the terms the decision is made on."""
    parts = [f"{candidate.hits} matching page(s) for your topic"]
    if candidate.feed_url:
        parts.append("has its own feed")
    else:
        parts.append("no feed found yet — would need a page-based source")
    article = "an" if candidate.role[:1] in "aeiou" else "a"
    parts.append(f"looks like {article} {candidate.role} source")
    return "; ".join(parts)


def discover(
    topic: str,
    *,
    config_dir: Path,
    search_fn: SearchFn | None = None,
    queries: tuple[str, ...] = _QUERY_SHAPES,
) -> DiscoveryResult:
    """Propose sources for `topic`. Read-only: nothing is fetched or written here."""
    search = search_fn if search_fn is not None else web_search
    results: list[dict[str, str]] = []
    for shape in queries:
        found = search(shape.format(topic=topic))
        # The default provider is Claude's in-agent WebSearch, which a headless
        # process cannot call. Pass the note through instead of reporting an
        # empty field: the agent can search and feed the results back.
        if any(str(r.get("kind", "")) == CLAUDE_WEBSEARCH_KIND for r in found if isinstance(r, dict)):
            return DiscoveryResult(
                topic=topic,
                note="Search must be run by the agent (provider: claude-websearch).",
                needs_agent_search=True,
            )
        results.extend(found)

    candidates = rank(drop_known(group_by_domain(results), known_domains(config_dir)))
    explained = [
        Candidate(
            domain=c.domain, url=c.url, hits=c.hits, title=c.title, snippet=c.snippet,
            role=c.role, feed_url=c.feed_url, examples=c.examples, reason=_explain(c),
        )
        for c in candidates
    ]
    note = (
        ""
        if explained
        else "No new sources found — the search returned nothing usable, or every "
        "result is already in your source list."
    )
    return DiscoveryResult(topic=topic, candidates=explained, note=note)
