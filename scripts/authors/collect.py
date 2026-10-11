"""Join monitored authors to the ordinary collect path (CONVENTIONS §2.4).

The plan's wording for the first variant is literal, and worth taking literally:
an author RSS feed becomes *an ordinary RSS source*. So the bridge is a
conversion, not a branch — the collector gains no author-specific code path, and
authors inherit every guarantee it already provides: cross-run dedup, source
ordering, the fair per-source budget, health events, and journal provenance.

Two variants convert. `rss` is an author's own feed, taken whole.
`publication-filter` is a PAUSED publication feed, so it converts to a source
**plus** a per-item predicate — the two always travel together, and a caller
that takes `author_sources_by_topic` without `author_item_filters` would collect
the entire publication under one author's name, crediting them with every other
writer's work. That is the precise harm the identity ladder exists to prevent,
so the pairing is not optional.

`scholarly` returns JSON, which the RSS parser would read as zero items and look
like an author who stopped publishing. Legacy `search` has no collection path. Both are
withheld here rather than half-supported.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.authors.match import item_matches  # noqa: E402
from scripts.authors.model import CollectionPlan, MonitoredAuthor  # noqa: E402
from scripts.normalize_url import normalize_or_raw  # noqa: E402
from scripts.sources.model import Category, Source  # noqa: E402


class FeedItemLike(Protocol):
    """The one field an author predicate reads off a parsed feed entry.

    Typed structurally so this module does not import the collector (which
    imports this one), and so a test can pass a plain stub.
    """

    @property
    def author(self) -> str: ...


# Author feeds are collected at the same tier/priority as an ordinary source.
# A person is not more or less credible than a publication by virtue of being a
# person, and inventing a tier here would quietly outrank the user's own choices.
_AUTHOR_TIER = "medium"
_AUTHOR_PRIORITY = "medium"


# The only variant the RSS collector can consume with no further work. This is
# an ALLOW-list, not a set of exclusions: `scholarly` also carries a fetch_url
# and no filter flag, so "has a URL and no flags" would quietly hand a JSON API
# to the feed parser — zero items, indistinguishable from an author who stopped
# publishing. A new variant must be added here deliberately.
_FEED_SHAPED_VARIANTS = ("rss", "publication-filter")


def _is_feed_shaped(plan: CollectionPlan) -> bool:
    """True when the RSS collector can fetch and parse this plan's target."""
    return (
        plan.variant in _FEED_SHAPED_VARIANTS
        and bool(plan.fetch_url)
        and not plan.agent_only
    )


def not_collected_caveat(monitoring: str) -> str | None:
    """A one-line honest caveat when a monitoring VARIANT stages but never collects.

    Keyed off the same `_FEED_SHAPED_VARIANTS` allow-list the collector uses, so
    "which variants actually collect" has ONE source of truth. Returns None for a
    collected variant (`rss` / `publication-filter`). Used by `/author add` so the
    not-built-yet limit is structural at add-time — not only agent prose in the
    skill (review 2026-07-22, product finding).
    """
    if monitoring in _FEED_SHAPED_VARIANTS:
        return None
    return (
        f"note: `{monitoring}` monitoring is not collected yet — the author is in "
        f"the roster, but nothing is fetched for them until this ships"
    )


def withheld_author_warnings(plans: list[CollectionPlan]) -> list[str]:
    """Human-readable WARNINGs for resolved plans this headless run cannot collect.

    `scholarly` and legacy `search` resolve to a valid plan but have NO headless
    collection path — a `scholarly` plan targets a JSON registry the feed parser
    would read as zero items, and a `search` plan is `agent_only`. They are
    therefore dropped by `author_sources_by_topic`. Without this they vanished
    SILENTLY, indistinguishable from an author who published nothing — the one
    failure the user cannot debug. Say it out loud instead.

    Guardrail per review 2026-07-22 (P1): show the reason for every withheld
    author. One warning per withheld author, in plan
    order. The reason is chosen per plan so a message is never self-contradictory:
    a staged variant (`scholarly`) or retired one (`search`) reads differently from a
    collected variant whose entry is degenerate (an `rss` author missing its feed
    must NOT be told rss "is not built yet").
    """
    return [
        f"{plan.display_name}: {_withheld_reason(plan)}, so nothing was collected "
        f"for them this run"
        for plan in plans
        if not _is_feed_shaped(plan)
    ]


def _withheld_reason(plan: CollectionPlan) -> str:
    """Why this not-feed-shaped plan could not be collected headlessly.

    Three distinct causes, so the message is honest for each: an unbuilt variant,
    a collected variant with no feed URL (incomplete roster entry), or a collected
    variant that is agent-only for this entry.
    """
    if plan.variant == "search":
        return (
            "legacy `search` author monitoring was retired and never collected work "
            "— use /discover for source proposals"
        )
    if plan.variant not in _FEED_SHAPED_VARIANTS:
        return (
            f"`{plan.variant}` has no headless collection path yet — rss / "
            f"publication-filter authors are collected, `{plan.variant}` is not "
            f"built yet"
        )
    if not plan.fetch_url:
        # A collected variant (e.g. rss) whose entry resolved to no feed URL: the
        # roster row is incomplete, NOT the variant unbuilt.
        return (
            f"`{plan.variant}` monitoring resolved to no feed URL — the roster "
            f"entry is missing its feed, so there is nothing to fetch"
        )
    return (
        f"`{plan.variant}` monitoring is not collectable headlessly for this entry"
    )


def _actively_collected(existing: list[Category]) -> set[str]:
    """Feeds already being FETCHED — active only.

    A paused source is registered but not collected, so it is not a duplicate
    fetch; that is precisely what a `publication-filter` author re-adds under
    their own topic.
    """
    return {
        normalize_or_raw(source.url)
        for category in existing
        for source in category.sources
        if source.active
    }


def author_sources_by_topic(
    plans: list[CollectionPlan], existing: list[Category] | None = None
) -> dict[str, list[Source]]:
    """Group the feed-shaped plans into `{topic: [Source, …]}`.

    `existing` is the already-configured categories: a feed the user already
    monitors is NOT added again, so following an author who writes on a blog you
    already collect does not fetch it twice or double-count its items. Matching
    goes through the normalize_url key, so an http/https/www/trailing-slash
    variant is recognised as the same feed (the project's dedup contract).

    A plan with no topic is skipped rather than defaulted — the validator
    requires one for exactly these variants, so an absent topic here means a
    hand-edited roster, and guessing a folder would file someone's work under a
    topic they do not write about.
    """
    already = _actively_collected(existing or [])
    seen: set[tuple[str, str]] = set()
    by_topic: dict[str, list[Source]] = {}
    for plan in plans:
        if not _is_feed_shaped(plan) or not plan.topic:
            continue
        key = normalize_or_raw(plan.fetch_url)
        # Skipped when the feed is ALREADY being fetched, or when this same feed
        # was already added for this same topic (two followed authors sharing one
        # paused publication need it fetched once, not twice).
        if key in already or (plan.topic, key) in seen:
            continue
        seen.add((plan.topic, key))
        by_topic.setdefault(plan.topic, []).append(
            Source(
                url=plan.fetch_url,
                type="rss",
                tier=_AUTHOR_TIER,
                priority=_AUTHOR_PRIORITY,
                # Named, because an unexplained feed URL sitting among a topic's
                # sources is the confusing thing to run into later.
                filter_note=f"author: {plan.display_name}",
                active=True,
            )
        )
    return by_topic


def author_item_filters(
    plans: list[CollectionPlan], authors: list[MonitoredAuthor]
) -> dict[str, Callable[[FeedItemLike], bool]]:
    """Per-feed predicates for the plans that need one, keyed by feed URL.

    Only `publication-filter` produces an entry; a feed with no predicate is
    collected whole, which is what every ordinary source and every `rss` author
    wants.

    Keyed by feed URL because that is what the collector holds per source. Two
    followed authors on the SAME paused publication collide on that key, so their
    predicates are OR-ed — the feed is fetched once and an item is kept when it
    belongs to either of them.

    KNOWN LIMIT: if those two authors sit on DIFFERENT topics, the feed is added
    under both and the OR-ed predicate applies in both, so cross-run URL dedup
    decides which topic an article lands in. Rare enough to state rather than
    design around; documented in CONVENTIONS §2.4.
    """
    by_name = {author.name: author for author in authors}
    filters: dict[str, Callable[[FeedItemLike], bool]] = {}
    for plan in plans:
        author = by_name.get(plan.display_name)
        if not plan.match_identity or not plan.fetch_url or author is None:
            continue
        predicate = _predicate_for(author)
        existing = filters.get(plan.fetch_url)
        filters[plan.fetch_url] = (
            predicate if existing is None else _either(existing, predicate)
        )
    return filters


def _predicate_for(author: MonitoredAuthor) -> Callable[[FeedItemLike], bool]:
    """A predicate closing over ONE author, deferring to the shared matcher."""

    def keep(item: FeedItemLike) -> bool:
        # A publication feed credits a bare `dc:creator` in the common case; the
        # matcher owns the asymmetry against the roster's stable handle.
        return item_matches(author, name=getattr(item, "author", "") or "")

    return keep


def _either(
    first: Callable[[FeedItemLike], bool], second: Callable[[FeedItemLike], bool]
) -> Callable[[FeedItemLike], bool]:
    """Keep an item belonging to EITHER author sharing one publication feed."""
    return lambda item: first(item) or second(item)


__all__ = [
    "author_item_filters",
    "author_sources_by_topic",
    "not_collected_caveat",
    "withheld_author_warnings",
]
