"""
test_discovery.py — proposing new sources for a topic.

`/discover <topic>` answers "who else should I be reading?" It searches, groups
what it finds by site, throws away everything already monitored, and proposes at
most a handful — each with the reason it was proposed.

It is a PROPOSAL ENGINE, not a configuration tool. The rules that keep it that
way, all pinned below: it never writes config, it never adds a source, and it
hands accepted candidates to `source-manage` rather than editing YAML itself.
The user stays the one who decides what enters their source list.

Search itself is injected, so these tests never touch the network and never
depend on which provider a user configured.
"""

from __future__ import annotations

from pathlib import Path

from scripts.discovery.candidates import (
    MAX_CANDIDATES,
    classify_role,
    drop_known,
    group_by_domain,
    rank,
)
from scripts.discovery.model import Candidate


def _result(url: str, title: str = "A post", snippet: str = "") -> dict[str, str]:
    return {"url": url, "title": title, "snippet": snippet}


# ── grouping ──────────────────────────────────────────────────────────────────


def test_results_are_grouped_by_site_not_listed_per_page() -> None:
    """A site with four good posts is ONE candidate, not four.

    The unit the user decides about is a source to monitor, so the page list
    would be the wrong shape — and a prolific site would crowd out every other
    candidate purely by volume.
    """
    found = group_by_domain(
        [
            _result("https://example.com/a"),
            _result("https://example.com/b"),
            _result("https://other.example/x"),
        ]
    )
    assert len(found) == 2
    by_domain = {c.domain: c for c in found}
    assert by_domain["example.com"].hits == 2
    assert by_domain["other.example"].hits == 1


def test_www_and_scheme_variants_are_one_site() -> None:
    found = group_by_domain(
        [_result("https://www.example.com/a"), _result("http://example.com/b")]
    )
    assert len(found) == 1
    assert found[0].hits == 2


def test_non_http_results_are_ignored() -> None:
    assert group_by_domain([_result("javascript:alert(1)"), _result("mailto:a@b.c")]) == []


def test_malformed_result_rows_are_skipped_not_fatal() -> None:
    # Provider payloads vary; a missing url must not take the whole run down.
    assert group_by_domain([{"title": "no url"}, _result("https://ok.example/1")]) != []


# ── what we already have ──────────────────────────────────────────────────────


def test_already_monitored_sites_are_dropped() -> None:
    found = group_by_domain([_result("https://known.example/a"), _result("https://new.example/b")])
    kept = drop_known(found, {"known.example"})
    assert [c.domain for c in kept] == ["new.example"]


def test_known_matching_ignores_www_prefix() -> None:
    found = group_by_domain([_result("https://www.known.example/a")])
    assert drop_known(found, {"known.example"}) == []


# ── role classification ───────────────────────────────────────────────────────


def test_roles_are_recognised_from_the_domain() -> None:
    assert classify_role("arxiv.org") == "academic"
    assert classify_role("news.ycombinator.com") == "aggregator"
    assert classify_role("reddit.com") == "aggregator"
    assert classify_role("medium.com") == "community"
    assert classify_role("github.com") == "community"


def test_unknown_domains_default_to_the_weakest_claim() -> None:
    """We cannot tell a company blog from a personal one by its domain.

    Guessing "official" would put unearned authority next to the name, so an
    unrecognised site is labelled `independent` and the user decides.
    """
    assert classify_role("some-random-blog.example") == "independent"


# ── ranking ───────────────────────────────────────────────────────────────────


def test_more_matching_pages_ranks_a_site_higher() -> None:
    ranked = rank(
        [
            Candidate(domain="thin.example", url="https://thin.example", hits=1),
            Candidate(domain="rich.example", url="https://rich.example", hits=4),
        ]
    )
    assert [c.domain for c in ranked] == ["rich.example", "thin.example"]


def test_a_discovered_feed_outweighs_raw_volume() -> None:
    """A monitorable site beats a busier one we would have to scrape."""
    ranked = rank(
        [
            Candidate(domain="busy.example", url="https://busy.example", hits=5),
            Candidate(
                domain="feedy.example", url="https://feedy.example", hits=3,
                feed_url="https://feedy.example/rss",
            ),
        ]
    )
    assert ranked[0].domain == "feedy.example"


def test_aggregators_rank_below_primary_sites() -> None:
    ranked = rank(
        [
            Candidate(domain="news.ycombinator.com", url="https://news.ycombinator.com",
                      hits=9, role="aggregator"),
            Candidate(domain="primary.example", url="https://primary.example",
                      hits=2, role="independent"),
        ]
    )
    # An aggregator is a pointer to sources, not a source — monitoring one floods
    # the pipeline with links to things we would rather monitor directly.
    assert ranked[0].domain == "primary.example"


def test_the_proposal_list_is_capped() -> None:
    many = [
        Candidate(domain=f"s{i}.example", url=f"https://s{i}.example", hits=i)
        for i in range(MAX_CANDIDATES + 8)
    ]
    assert len(rank(many)) == MAX_CANDIDATES


def test_ranking_is_deterministic_for_equal_candidates() -> None:
    equal = [
        Candidate(domain="b.example", url="https://b.example", hits=2),
        Candidate(domain="a.example", url="https://a.example", hits=2),
    ]
    assert [c.domain for c in rank(equal)] == [c.domain for c in rank(list(reversed(equal)))]


# ── the run, end to end ───────────────────────────────────────────────────────


def test_discover_proposes_and_explains_without_touching_config(tmp_path: Path) -> None:
    from scripts.discovery.run import discover

    config = tmp_path / "config"
    config.mkdir()
    (config / "sources.yaml").write_text(
        "categories:\n  - name: ai\n    sources:\n"
        "      - url: https://known.example/feed.xml\n        type: rss\n"
        "        tier: high\n        active: true\n",
        encoding="utf-8",
    )
    before = (config / "sources.yaml").read_text(encoding="utf-8")

    result = discover(
        "ai agents",
        config_dir=config,
        search_fn=lambda q: [
            _result("https://known.example/post"),  # already monitored → dropped
            _result("https://fresh.example/one"),
            _result("https://fresh.example/two"),
        ],
    )

    assert [c.domain for c in result.candidates] == ["fresh.example"]
    assert result.candidates[0].reason, "every proposal must say why it is proposed"
    # Read-only: discovery proposes, `source-manage` is what actually adds.
    assert (config / "sources.yaml").read_text(encoding="utf-8") == before


def test_discover_soft_skips_when_search_is_unavailable(tmp_path: Path) -> None:
    """`provider: none` (or a missing key) yields no results, not an error."""
    from scripts.discovery.run import discover

    config = tmp_path / "config"
    config.mkdir()
    result = discover("ai agents", config_dir=config, search_fn=lambda q: [])
    assert result.candidates == []
    assert "no" in result.note.lower()


def test_discover_reports_the_in_agent_search_sentinel(tmp_path: Path) -> None:
    """The default provider can only be run by the agent, not a headless process.

    Rather than silently returning nothing, discovery passes that note through so
    the agent knows to run WebSearch itself and feed the results back.
    """
    from scripts.discovery.run import discover
    from scripts.search.search import CLAUDE_WEBSEARCH_KIND

    config = tmp_path / "config"
    config.mkdir()
    result = discover(
        "ai agents",
        config_dir=config,
        search_fn=lambda q: [{"kind": CLAUDE_WEBSEARCH_KIND, "note": "use WebSearch"}],
    )
    assert result.needs_agent_search is True
    assert result.candidates == []


def test_cli_renders_proposals(tmp_path: Path, capsys) -> None:
    from scripts.discover import main

    config = tmp_path / "config"
    config.mkdir()
    (config / "sources.yaml").write_text("categories: []\n", encoding="utf-8")
    results = tmp_path / "results.json"
    results.write_text(
        '[{"url": "https://fresh.example/a", "title": "Post"}]', encoding="utf-8"
    )

    assert main(["ai agents", "--config-dir", str(config), "--results", str(results)]) == 0
    out = capsys.readouterr().out
    assert "fresh.example" in out
    # Nothing is added without the user saying so.
    assert "source-manage" in out or "confirm" in out.lower()
