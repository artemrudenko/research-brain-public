"""Resolve each monitored author to a concrete fetch plan (CONVENTIONS §2.4).

Pure resolution: this module decides WHAT would be fetched, never fetches it.
That split is what lets the awkward half of author monitoring — publications we
do not actually collect, identifier schemes we do not support — be pinned by
offline tests instead of discovered in production.

Two refusals shape the whole module, and both are the same refusal the identity
ladder in `scripts/source_report/authors.py` makes:

  - **we never invent a feed URL.** A `publication-filter` author is followed
    through a feed already registered in `sources.yaml` — and a PAUSED one, which
    is the whole point: the URL is the user's, and polling it filtered collects
    that publication only for the people they follow. An ACTIVE publication is
    already collected whole, so the entry is redundant and says so rather than
    breaking the shared feed for every other reader. A publication that is not
    registered at all is unresolvable — the alternative is guessing at
    `/feed.xml` and quietly polling a stranger's site.
  - **we never infer an identifier's registry.** `0000-0002-1825-0097` looks
    like an ORCID, but acting on that resemblance means querying some registry
    for some person and attributing the results to this one.

Every unresolvable entry yields a stated reason. An author who silently drops
out of the roster reads as "published nothing lately", and no user can tell that
apart from a broken config.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.authors.model import CollectionPlan, MonitoredAuthor  # noqa: E402
from scripts.source_report.authors import identity_key  # noqa: E402
from scripts.sources.model import Category  # noqa: E402

# Scholarly registries, keyed by the identifier scheme the user writes in
# `id:`. The scheme is REQUIRED — see the module docstring on why a bare
# identifier is refused rather than sniffed.
_SCHOLARLY_ENDPOINTS = {
    "orcid": "https://pub.orcid.org/v3.0/{ident}/works",
    "openalex": "https://api.openalex.org/works?filter=author.id:{ident}",
    "s2": "https://api.semanticscholar.org/graph/v1/author/{ident}/papers",
}


def _host(value: str) -> str:
    """The bare host of a URL or a bare hostname, lowercased, `www.` dropped.

    `www.` is spelling, not identity — the same normalisation the identity
    ladder applies to names.
    """
    text = value.strip().lower()
    host = urlsplit(text).hostname if "//" in text else text.split("/", 1)[0]
    host = (host or "").removeprefix("www.")
    return host


def _feed_for_publication(
    publication: str, categories: list[Category]
) -> tuple[str, bool]:
    """`(feed url, is_active)` for `publication`, or `("", False)` when unknown.

    The ACTIVE flag decides whether this variant has anything to do. A paused
    source is registered but not being fetched, which is exactly the state
    `publication-filter` needs: the URL is the user's (we never invent one) and
    polling it filtered collects it only for the people they follow.
    """
    wanted = _host(publication)
    for category in categories:
        for source in category.sources:
            if _host(source.url) == wanted:
                return source.url, source.active
    return "", False


def _scholarly_url(identifier: str) -> str:
    """The registry endpoint for a `scheme:id` identifier, or "" when unsupported."""
    scheme, _, ident = identifier.partition(":")
    template = _SCHOLARLY_ENDPOINTS.get(scheme.strip().lower())
    if not template or not ident.strip():
        return ""
    return template.format(ident=ident.strip())


def _plan_for(
    author: MonitoredAuthor, categories: list[Category]
) -> tuple[CollectionPlan | None, str]:
    """Resolve one author to (plan, "") or (None, reason)."""
    def plan(
        fetch_url: str = "",
        query: str = "",
        match_identity: bool = False,
        agent_only: bool = False,
    ) -> CollectionPlan:
        """This author's plan; only the variant-specific fields differ."""
        return CollectionPlan(
            author_key=identity_key(
                author.name,
                author.profile_url,
                author.identifier,
                _host(author.publication),
            ),
            display_name=author.name,
            variant=author.monitoring,
            topic=author.topic,
            fetch_url=fetch_url,
            query=query,
            match_identity=match_identity,
            agent_only=agent_only,
        )

    if author.monitoring == "rss":
        # An author-specific feed is filtered by construction. Re-filtering it on
        # a bare feed name would drop exactly their co-authored pieces.
        return plan(fetch_url=author.feed), ""

    if author.monitoring == "publication-filter":
        feed, active = _feed_for_publication(author.publication, categories)
        if not feed:
            return None, (
                f"{author.name}: `publication: {author.publication}` is not a source "
                f"you monitor — add its feed to sources.yaml first (we never guess a "
                f"feed URL for a site you do not collect)"
            )
        if active:
            # The publication is collected WHOLE, so their articles already
            # arrive; filtering the shared source would break that for every
            # other reader of the feed. Redundant, not broken — but said out
            # loud, because an entry that quietly does nothing is the one thing
            # the user cannot debug.
            return None, (
                f"{author.name}: `publication: {author.publication}` is an ACTIVE "
                f"source, so it is already collected whole and their articles "
                f"already arrive — pause that source in sources.yaml if you want "
                f"it collected only for the authors you follow"
            )
        return plan(fetch_url=feed, match_identity=True), ""

    if author.monitoring == "scholarly":
        url = _scholarly_url(author.identifier)
        if not url:
            return None, (
                f"{author.name}: `id: {author.identifier}` has no supported registry "
                f"scheme — use one of "
                f"{', '.join(f'{s}:' for s in sorted(_SCHOLARLY_ENDPOINTS))} "
                f"(an unprefixed identifier is not guessed at: the wrong registry "
                f"returns the wrong person's work)"
            )
        # The endpoint IS the person; a second name filter could only lose papers
        # the registry spells differently.
        return plan(fetch_url=url), ""

    if author.monitoring == "search":
        # No headless equivalent — a standing query needs the agent's search.
        return plan(query=author.query, agent_only=True), ""

    return None, f"{author.name}: unknown `monitoring: {author.monitoring}`"


def resolve_plans(
    authors: list[MonitoredAuthor], categories: list[Category]
) -> tuple[list[CollectionPlan], list[str]]:
    """Resolve the roster to (plans, problems), in roster order.

    One unresolvable author never costs the others their run — the problems are
    collected and returned alongside the plans that did resolve.
    """
    plans: list[CollectionPlan] = []
    problems: list[str] = []
    for author in authors:
        if not author.active:
            continue  # a paused entry is a valid state, not a problem to report
        plan, reason = _plan_for(author, categories)
        if plan is not None:
            plans.append(plan)
        else:
            problems.append(reason)
    return plans, problems


__all__ = ["resolve_plans"]
