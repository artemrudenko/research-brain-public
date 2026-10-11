"""
test_authors_plan.py — the four monitoring variants, resolved to a fetch plan.

`config/authors.yaml` records WHO the user follows; this layer answers WHAT to
actually poll for each of them. It is pure resolution — no network, no writes —
so the awkward cases can be pinned offline:

  - `publication-filter` reuses a feed the user ALREADY monitors rather than
    inventing a network target of its own. An author attached to a publication
    that is not in sources.yaml is unresolvable, and says so.
  - `scholarly` derives its endpoint from the identifier SCHEME. An unknown
    scheme is refused rather than guessed at, because guessing an API here
    means fetching some other person's papers.
  - `search` has no headless path at all and is marked agent-only, so cron
    skips it visibly instead of appearing to work.

Every unresolvable entry produces a stated reason. Silence would read as
"nothing new from this author", which is indistinguishable from a broken config
and is exactly the failure the user cannot debug.
"""
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

yaml = pytest.importorskip("yaml", reason="PyYAML required for authors config tests")

from scripts.authors.model import MonitoredAuthor  # noqa: E402
from scripts.authors.plan import resolve_plans  # noqa: E402
from scripts.sources.model import Category, Source  # noqa: E402


def _source(url: str) -> Source:
    return Source(
        url=url, type="rss", tier="medium", priority="medium", filter_note="—", active=True
    )


def _paused(url: str) -> Source:
    """A registered but NOT-collected source — what publication-filter needs."""
    return Source(
        url=url, type="rss", tier="medium", priority="medium", filter_note="—", active=False
    )


def _categories() -> list[Category]:
    return [
        Category(name="ai-agents", sources=[_source("https://example.com/feed.xml")]),
        Category(name="ml", sources=[_source("https://www.journal.org/rss")]),
        # Registered, paused: the shape `publication-filter` resolves against.
        Category(name="press", sources=[_paused("https://paper.test/rss"),
                                        _paused("https://www.quarterly.test/atom")]),
    ]


def _author(**kwargs: object) -> MonitoredAuthor:
    base: dict[str, object] = {"name": "Jane Doe", "monitoring": "rss"}
    base.update(kwargs)
    return MonitoredAuthor(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# rss — the simplest variant: the author's own feed, every item is theirs
# --------------------------------------------------------------------------- #


def test_rss_polls_the_authors_own_feed() -> None:
    author = _author(monitoring="rss", feed="https://example.com/jane/feed.xml")
    plans, problems = resolve_plans([author], _categories())
    assert problems == []
    assert len(plans) == 1
    assert plans[0].fetch_url == "https://example.com/jane/feed.xml"


def test_rss_takes_every_item_without_identity_matching() -> None:
    # An author-specific feed is already filtered by construction; re-filtering
    # it on a bare dc:creator name would drop their co-authored pieces.
    author = _author(monitoring="rss", feed="https://example.com/jane/feed.xml")
    plans, _ = resolve_plans([author], _categories())
    assert plans[0].match_identity is False
    assert plans[0].agent_only is False


# --------------------------------------------------------------------------- #
# publication-filter — reuse a monitored feed, narrow it to one identity
# --------------------------------------------------------------------------- #


def test_publication_filter_reuses_a_monitored_feed() -> None:
    author = _author(
        monitoring="publication-filter",
        publication="paper.test",
        profile_url="https://paper.test/author/jane",
    )
    plans, problems = resolve_plans([author], _categories())
    assert problems == []
    assert plans[0].fetch_url == "https://paper.test/rss"
    assert plans[0].match_identity is True


def test_publication_filter_matches_host_ignoring_www() -> None:
    author = _author(
        monitoring="publication-filter",
        publication="quarterly.test",
        identifier="orcid:0000-0002-1825-0097",
    )
    plans, problems = resolve_plans([author], _categories())
    assert problems == []
    assert plans[0].fetch_url == "https://www.quarterly.test/atom"


def test_publication_filter_accepts_a_full_url_as_publication() -> None:
    author = _author(
        monitoring="publication-filter",
        publication="https://paper.test/blog",
        identifier="orcid:0000-0002-1825-0097",
    )
    plans, problems = resolve_plans([author], _categories())
    assert problems == []
    assert plans[0].fetch_url == "https://paper.test/rss"


def test_publication_filter_on_an_unmonitored_publication_is_unresolvable() -> None:
    # We never invent a feed URL for a site the user does not already collect.
    author = _author(
        monitoring="publication-filter",
        publication="nowhere.test",
        identifier="orcid:0000-0002-1825-0097",
    )
    plans, problems = resolve_plans([author], _categories())
    assert plans == []
    assert any("nowhere.test" in p and "Jane Doe" in p for p in problems), problems


# --------------------------------------------------------------------------- #
# scholarly — endpoint derived from the identifier SCHEME, never from the name
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("identifier", "expected_host"),
    [
        ("orcid:0000-0002-1825-0097", "orcid.org"),
        ("openalex:A5023888391", "api.openalex.org"),
        ("s2:1741101", "api.semanticscholar.org"),
    ],
)
def test_scholarly_endpoint_per_scheme(identifier: str, expected_host: str) -> None:
    author = _author(monitoring="scholarly", identifier=identifier)
    plans, problems = resolve_plans([author], _categories())
    assert problems == []
    assert expected_host in plans[0].fetch_url
    # The bare identifier must reach the endpoint — not the display name.
    assert identifier.split(":", 1)[1] in plans[0].fetch_url


def test_scholarly_unknown_scheme_is_refused_not_guessed() -> None:
    author = _author(monitoring="scholarly", identifier="researchgate:12345")
    plans, problems = resolve_plans([author], _categories())
    assert plans == []
    assert any("researchgate" in p for p in problems), problems


def test_scholarly_bare_identifier_without_scheme_is_refused() -> None:
    # "0000-0002-1825-0097" looks like an ORCID, and acting on that hunch is how
    # you end up querying the wrong registry for the wrong person.
    author = _author(monitoring="scholarly", identifier="0000-0002-1825-0097")
    plans, problems = resolve_plans([author], _categories())
    assert plans == []
    assert problems != []


def test_scholarly_never_matches_identity_downstream() -> None:
    # The endpoint is already the person; a second name filter could only lose
    # papers where the feed spells them differently.
    author = _author(monitoring="scholarly", identifier="orcid:0000-0002-1825-0097")
    plans, _ = resolve_plans([author], _categories())
    assert plans[0].match_identity is False


# --------------------------------------------------------------------------- #
# search — agent-mode only; cron must skip it visibly
# --------------------------------------------------------------------------- #


def test_search_is_agent_only_and_has_no_fetch_url() -> None:
    author = _author(monitoring="search", query="Jane Doe agents")
    plans, problems = resolve_plans([author], _categories())
    assert problems == []
    assert plans[0].agent_only is True
    assert plans[0].fetch_url == ""
    assert plans[0].query == "Jane Doe agents"


# --------------------------------------------------------------------------- #
# Cross-cutting: active flag, identity key, ordering
# --------------------------------------------------------------------------- #


def test_inactive_authors_are_skipped_without_complaint() -> None:
    # Pausing someone is a valid state, not a configuration problem.
    author = _author(monitoring="rss", feed="https://example.com/f.xml", active=False)
    plans, problems = resolve_plans([author], _categories())
    assert plans == []
    assert problems == []


def test_plan_carries_the_shared_identity_key() -> None:
    # The roster and the journal-derived metrics must resolve identity through
    # ONE ladder, or the report cannot tell you whom you already follow.
    from scripts.source_report.authors import identity_key

    author = _author(monitoring="scholarly", identifier="orcid:0000-0002-1825-0097")
    plans, _ = resolve_plans([author], _categories())
    assert plans[0].author_key == identity_key(
        "Jane Doe", "", "orcid:0000-0002-1825-0097", "example.com"
    )


def test_problems_do_not_stop_the_other_authors() -> None:
    good = _author(name="Jane Doe", monitoring="rss", feed="https://example.com/f.xml")
    bad = _author(name="John Roe", monitoring="scholarly", identifier="nope:1")
    plans, problems = resolve_plans([good, bad], _categories())
    assert [p.display_name for p in plans] == ["Jane Doe"]
    assert len(problems) == 1


def test_empty_roster_resolves_to_nothing() -> None:
    assert resolve_plans([], _categories()) == ([], [])


# --------------------------------------------------------------------------- #
# publication-filter and the ACTIVE/paused distinction (decision (c))
# --------------------------------------------------------------------------- #


def test_publication_filter_accepts_a_PAUSED_publication_source() -> None:
    # This is the variant's real shape: the feed is registered (so we never
    # invent a URL) but paused, so polling it filtered collects it ONLY for the
    # people the user follows.
    author = _author(
        monitoring="publication-filter",
        publication="paper.test",
        identifier="orcid:0000-0002-1825-0097",
    )
    plans, problems = resolve_plans([author], _categories())
    assert problems == []
    assert plans[0].fetch_url == "https://paper.test/rss"
    assert plans[0].match_identity is True


def test_publication_filter_on_an_ACTIVE_publication_is_redundant() -> None:
    # An active source is already collected whole, so their articles already
    # arrive. Filtering it would break that whole-feed collection for everyone.
    # Say so — silently doing nothing is the outcome nobody can debug.
    author = _author(
        monitoring="publication-filter",
        publication="example.com",  # active in _categories()
        identifier="orcid:0000-0002-1825-0097",
    )
    plans, problems = resolve_plans([author], _categories())
    assert plans == []
    assert any("pause" in p.lower() and "Jane Doe" in p for p in problems), problems
