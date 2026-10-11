#!/usr/bin/env python3
"""
candidates.py — turn raw search results into a short, explained proposal list.

Four steps, each with a reason to exist:

  group   — by site, because the user decides about sources, not pages;
  drop    — everything already monitored, so the list is only news to them;
  role    — a coarse label, deliberately pessimistic where we cannot tell;
  rank    — monitorability over volume, primary sources over aggregators.

Nothing here searches, fetches, or writes. It is pure shaping, so it is fully
testable without a network and without a configured provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from scripts.discovery.model import Candidate

# Ten is what a person will actually read and decide on. Past that the list stops
# being a decision and becomes a chore, and the tail is the weakest evidence.
MAX_CANDIDATES = 10

# Domain suffixes we can label with confidence. Everything else is deliberately
# left as `independent` — see `classify_role`.
_ROLE_BY_DOMAIN = {
    "arxiv.org": "academic",
    "openreview.net": "academic",
    "acm.org": "academic",
    "semanticscholar.org": "academic",
    "news.ycombinator.com": "aggregator",
    "reddit.com": "aggregator",
    "lobste.rs": "aggregator",
    "medium.com": "community",
    "dev.to": "community",
    "substack.com": "community",
    "github.com": "community",
    "youtube.com": "community",
}

# An aggregator points AT sources rather than being one; monitoring it floods the
# pipeline with links to things we would rather monitor directly. Still proposed
# (it is real signal about where a topic lives), just never at the top.
_ROLE_WEIGHT = {
    "official": 3.0,
    "publication": 2.5,
    "academic": 2.5,
    "independent": 2.0,
    "community": 1.5,
    "aggregator": 0.5,
}


def _domain_of(url: str) -> str:
    """Lowercased host without `www.`; "" when the URL is not http(s)."""
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https"):
        return ""
    host = (parts.hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def classify_role(domain: str) -> str:
    """A coarse role for `domain`, pessimistic when unsure.

    Only well-known hosts are labelled. A company blog and a personal one are
    indistinguishable by domain, and guessing `official` would print unearned
    authority next to the name — so anything unrecognised is `independent` and
    the user judges it.
    """
    host = domain.lower()
    for known, role in _ROLE_BY_DOMAIN.items():
        if host == known or host.endswith("." + known):
            return role
    return "independent"


@dataclass
class _Group:
    """Accumulator for one site while results are being folded together."""

    url: str
    title: str = ""
    snippet: str = ""
    examples: list[str] = field(default_factory=list)


def group_by_domain(results: list[dict[str, str]]) -> list[Candidate]:
    """Collapse search results into one candidate per site, in first-seen order."""
    order: list[str] = []
    grouped: dict[str, _Group] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url", ""))
        domain = _domain_of(url)
        if not domain:
            continue  # non-http(s) or unparseable — never a monitorable source
        if domain not in grouped:
            order.append(domain)
            grouped[domain] = _Group(
                url=f"https://{domain}",
                title=str(row.get("title", "")),
                snippet=str(row.get("snippet", "")),
            )
        grouped[domain].examples.append(url)

    return [
        Candidate(
            domain=domain,
            url=grouped[domain].url,
            hits=len(grouped[domain].examples),
            title=grouped[domain].title,
            snippet=grouped[domain].snippet,
            role=classify_role(domain),
            examples=tuple(grouped[domain].examples[:3]),
        )
        for domain in order
    ]


def drop_known(candidates: list[Candidate], known_domains: set[str]) -> list[Candidate]:
    """Remove sites already in the source list — the proposal must be all news."""
    known = {d.lower()[4:] if d.lower().startswith("www.") else d.lower() for d in known_domains}
    return [c for c in candidates if c.domain not in known]


def _score(candidate: Candidate) -> float:
    """Monitorability first, then volume, weighted by role.

    A site with a feed can be monitored today; a busier one without would have to
    be scraped, so raw hit count is the weaker signal of the two.
    """
    return (
        _ROLE_WEIGHT.get(candidate.role, 2.0)
        * (2.0 if candidate.feed_url else 1.0)
        * (1.0 + candidate.hits / 10.0)
    )


def rank(candidates: list[Candidate]) -> list[Candidate]:
    """Best proposals first, capped. Ties break on domain so output is stable."""
    ordered = sorted(candidates, key=lambda c: (-_score(c), c.domain))
    return ordered[:MAX_CANDIDATES]
