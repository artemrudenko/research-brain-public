"""
test_authors_collect.py — monitored authors joining the ordinary collect path.

The plan's wording for the first variant is literal: an author RSS feed becomes
"an ordinary RSS source". So this layer converts resolved plans into `Source`
records and merges them into the category being collected — the collector needs
no author-specific branch at all, and every guarantee it already has (dedup,
ordering, per-source budget, journal provenance) applies to authors for free.

The `topic` requirement is the gap integration exposed: a collected article
lands in `pipeline/1-incoming/<topic>/` and is judged by that topic's curate
rules, so an author with no topic has nowhere to go. Only the user knows where
a person's work belongs, so the roster asks rather than guessing.
"""
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

yaml = pytest.importorskip("yaml", reason="PyYAML required for authors config tests")

from scripts.authors.collect import (  # noqa: E402
    author_item_filters,
    author_sources_by_topic,
)
from scripts.authors.model import MonitoredAuthor  # noqa: E402
from scripts.authors.plan import resolve_plans  # noqa: E402
from scripts.sources.model import Category, Source  # noqa: E402


def _categories() -> list[Category]:
    return [
        Category(
            name="ai-agents",
            sources=[
                Source(
                    url="https://example.com/feed.xml",
                    type="rss",
                    tier="medium",
                    priority="medium",
                    filter_note="—",
                    active=True,
                )
            ],
        )
    ]


def _plans(*authors: MonitoredAuthor) -> list:
    plans, problems = resolve_plans(list(authors), _categories())
    assert problems == [], problems
    return plans


def test_rss_author_becomes_an_ordinary_source() -> None:
    author = MonitoredAuthor(
        name="Jane Doe",
        monitoring="rss",
        feed="https://example.com/jane/feed.xml",
        topic="ai-agents",
    )
    by_topic = author_sources_by_topic(_plans(author))
    (source,) = by_topic["ai-agents"]
    assert source.url == "https://example.com/jane/feed.xml"
    assert source.type == "rss"
    assert source.active is True


def test_author_source_names_the_person_in_its_filter_note() -> None:
    # The note is what a human sees in `source-manage list` / the config; an
    # unexplained feed URL among the topic's sources is the confusing outcome.
    author = MonitoredAuthor(
        name="Jane Doe",
        monitoring="rss",
        feed="https://example.com/jane/feed.xml",
        topic="ai-agents",
    )
    (source,) = author_sources_by_topic(_plans(author))["ai-agents"]
    assert "Jane Doe" in source.filter_note


def test_authors_group_under_their_own_topics() -> None:
    jane = MonitoredAuthor(
        name="Jane Doe", monitoring="rss", feed="https://a.example/f.xml", topic="ai-agents"
    )
    john = MonitoredAuthor(
        name="John Roe", monitoring="rss", feed="https://b.example/f.xml", topic="ml"
    )
    by_topic = author_sources_by_topic(_plans(jane, john))
    assert sorted(by_topic) == ["ai-agents", "ml"]


def _paused_categories() -> list[Category]:
    """A registered but NOT-collected publication — publication-filter's shape."""
    return [
        *_categories(),
        Category(
            name="press",
            sources=[
                Source(
                    url="https://paper.test/rss",
                    type="rss",
                    tier="medium",
                    priority="medium",
                    filter_note="—",
                    active=False,
                )
            ],
        ),
    ]


def _jane_at_paper() -> MonitoredAuthor:
    return MonitoredAuthor(
        name="Jane Doe",
        monitoring="publication-filter",
        publication="paper.test",
        profile_url="https://paper.test/author/jane",
        topic="ai-agents",
    )


class _Item:
    """The one field a predicate reads off a parsed feed entry."""

    def __init__(self, author: str) -> None:
        self.author = author


def test_publication_filter_converts_to_a_source_on_the_authors_topic() -> None:
    plans, problems = resolve_plans([_jane_at_paper()], _paused_categories())
    assert problems == []
    by_topic = author_sources_by_topic(plans, existing=_paused_categories())
    (source,) = by_topic["ai-agents"]
    assert source.url == "https://paper.test/rss"


def test_publication_filter_always_comes_with_its_predicate() -> None:
    # Without the predicate the merged feed collects the WHOLE publication under
    # one author's name. The pairing is the safety property, so pin it.
    author = _jane_at_paper()
    plans, _ = resolve_plans([author], _paused_categories())
    assert author_sources_by_topic(plans, existing=_paused_categories()) != {}
    filters = author_item_filters(plans, [author])
    assert "https://paper.test/rss" in filters


def test_the_predicate_keeps_only_the_authors_items() -> None:
    author = _jane_at_paper()
    plans, _ = resolve_plans([author], _paused_categories())
    keep = author_item_filters(plans, [author])["https://paper.test/rss"]
    assert keep(_Item("Jane Doe")) is True
    assert keep(_Item("John Roe")) is False
    assert keep(_Item("")) is False


def test_two_authors_on_one_publication_share_a_single_fetch() -> None:
    # The feed is fetched once; an item is kept when it belongs to EITHER.
    jane = _jane_at_paper()
    john = MonitoredAuthor(
        name="John Roe",
        monitoring="publication-filter",
        publication="paper.test",
        profile_url="https://paper.test/author/john",
        topic="ai-agents",
    )
    plans, _ = resolve_plans([jane, john], _paused_categories())
    assert len(author_sources_by_topic(plans, existing=_paused_categories())["ai-agents"]) == 1
    keep = author_item_filters(plans, [jane, john])["https://paper.test/rss"]
    assert keep(_Item("Jane Doe")) is True
    assert keep(_Item("John Roe")) is True
    assert keep(_Item("Someone Else")) is False


def test_rss_authors_get_no_predicate() -> None:
    # An author's own feed is theirs whole; a name filter could only lose their
    # co-authored pieces.
    author = MonitoredAuthor(
        name="Jane Doe", monitoring="rss", feed="https://a.example/f.xml", topic="ai-agents"
    )
    assert author_item_filters(_plans(author), [author]) == {}


def test_agent_only_variants_are_not_plain_sources() -> None:
    author = MonitoredAuthor(
        name="Jane Doe", monitoring="search", query="agents", topic="ai-agents"
    )
    assert author_sources_by_topic(_plans(author)) == {}


def test_scholarly_is_not_a_plain_rss_source() -> None:
    # The endpoint returns JSON, not a feed; handing it to the RSS parser would
    # produce zero items and look like an author who stopped publishing.
    author = MonitoredAuthor(
        name="Jane Doe",
        monitoring="scholarly",
        identifier="orcid:0000-0002-1825-0097",
        topic="ai-agents",
    )
    assert author_sources_by_topic(_plans(author)) == {}


def test_withheld_variants_warn_instead_of_silently_collecting_nothing() -> None:
    # Review 2026-07-22 (P1): `scholarly` + `search` resolve to a valid plan but
    # have NO headless collection path, so they were dropped SILENTLY —
    # indistinguishable from an author who published nothing. Say it out loud.
    from scripts.authors.collect import withheld_author_warnings

    scholarly = MonitoredAuthor(
        name="Jane Doe", monitoring="scholarly",
        identifier="orcid:0000-0002-1825-0097", topic="ai-agents",
    )
    search = MonitoredAuthor(
        name="John Roe", monitoring="search", query="agents", topic="ai-agents",
    )
    rss = MonitoredAuthor(
        name="Ada Feed", monitoring="rss",
        feed="https://ada.example/atom.xml", topic="ai-agents",
    )
    warnings = withheld_author_warnings(_plans(scholarly, search, rss))
    joined = " | ".join(warnings)
    # One warning per withheld author, each NAMING the person and the variant.
    assert len(warnings) == 2
    assert "Jane Doe" in joined and "scholarly" in joined
    assert "John Roe" in joined and "search" in joined
    # The collectable rss author is NOT warned about.
    assert "Ada Feed" not in joined


def test_degenerate_rss_author_warning_is_not_self_contradictory() -> None:
    # A hand-edited/corrupt `rss` author with no feed resolves to a plan with an
    # empty fetch_url — correctly withheld. But the fixed "rss / publication-filter
    # authors are collected, `rss` is not built yet" tail is self-contradictory for
    # the rss variant (rss IS a collected variant). The warning must instead name
    # the real cause: a missing feed, not an unbuilt variant.
    from scripts.authors.collect import withheld_author_warnings

    broken = MonitoredAuthor(
        name="Nofeed Nan", monitoring="rss", feed="", topic="ai-agents"
    )
    (warning,) = withheld_author_warnings(_plans(broken))
    assert "Nofeed Nan" in warning
    assert "not built yet" not in warning, "rss must not be called unbuilt"
    assert "feed" in warning.lower(), "must name the missing feed as the cause"


def test_a_feed_already_monitored_is_not_added_twice() -> None:
    # Following an author whose feed is already a category source must not make
    # the collector fetch it twice or double-count its items.
    author = MonitoredAuthor(
        name="Jane Doe",
        monitoring="rss",
        feed="https://example.com/feed.xml",  # already in _categories()
        topic="ai-agents",
    )
    by_topic = author_sources_by_topic(_plans(author), existing=_categories())
    assert by_topic == {}


def test_url_variants_count_as_already_monitored() -> None:
    author = MonitoredAuthor(
        name="Jane Doe",
        monitoring="rss",
        feed="http://www.example.com/feed.xml/",  # same feed, spelled differently
        topic="ai-agents",
    )
    assert author_sources_by_topic(_plans(author), existing=_categories()) == {}


def test_empty_roster_yields_nothing() -> None:
    assert author_sources_by_topic([]) == {}


# --------------------------------------------------------------------------- #
# The collect.py seam — authors reaching the real category list
# --------------------------------------------------------------------------- #


def test_merge_appends_author_feeds_to_the_selected_category(tmp_path: Path) -> None:
    from scripts.collect import _merge_author_sources

    (tmp_path / "authors.yaml").write_text(
        "authors:\n  - name: Jane Doe\n    monitoring: rss\n    topic: ai-agents\n"
        "    feed: https://example.com/jane/feed.xml\n",
        encoding="utf-8",
    )
    categories = _categories()
    _filters, problems = _merge_author_sources(tmp_path, categories, categories)
    assert problems == []
    assert "https://example.com/jane/feed.xml" in [s.url for s in categories[0].sources]


def test_merge_is_a_no_op_without_a_roster(tmp_path: Path) -> None:
    # Absent authors.yaml is the default: nobody followed, nothing changed.
    from scripts.collect import _merge_author_sources

    categories = _categories()
    before = [s.url for s in categories[0].sources]
    assert _merge_author_sources(tmp_path, categories, categories) == ({}, [])
    assert [s.url for s in categories[0].sources] == before


def test_merge_reports_an_author_on_an_unknown_topic(tmp_path: Path) -> None:
    from scripts.collect import _merge_author_sources

    (tmp_path / "authors.yaml").write_text(
        "authors:\n  - name: Jane Doe\n    monitoring: rss\n    topic: nowhere\n"
        "    feed: https://example.com/jane/feed.xml\n",
        encoding="utf-8",
    )
    categories = _categories()
    _filters, problems = _merge_author_sources(tmp_path, categories, categories)
    assert any("nowhere" in p for p in problems), problems


def test_merge_survives_a_malformed_roster(tmp_path: Path) -> None:
    # A broken authors.yaml must not take the whole collect run down: the
    # sources config is still valid and its feeds are still worth collecting.
    from scripts.collect import _merge_author_sources

    (tmp_path / "authors.yaml").write_text("authors: [unclosed\n", encoding="utf-8")
    categories = _categories()
    _filters, problems = _merge_author_sources(tmp_path, categories, categories)
    assert problems != []
    assert [s.url for s in categories[0].sources] == ["https://example.com/feed.xml"]


def test_merge_does_not_collect_authors_of_unselected_topics(tmp_path: Path) -> None:
    # A --category run must not start fetching an author who writes elsewhere.
    from scripts.collect import _merge_author_sources

    (tmp_path / "authors.yaml").write_text(
        "authors:\n  - name: Jane Doe\n    monitoring: rss\n    topic: ml\n"
        "    feed: https://example.com/jane/feed.xml\n",
        encoding="utf-8",
    )
    categories = _categories() + [Category(name="ml", sources=[])]
    selected = [c for c in categories if c.name == "ai-agents"]
    _filters, problems = _merge_author_sources(tmp_path, categories, selected)
    assert any("not part of this run" in p for p in problems), problems
    assert all(not c.sources or c.name == "ai-agents" for c in categories)


def test_collect_category_applies_the_item_filter(tmp_path: Path) -> None:
    # End-to-end through the real collector: a filtered feed must save only the
    # monitored author's item, and must not save the other writer's.
    from scripts import collect

    feed = (
        '<?xml version="1.0"?><rss version="2.0"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>'
        "<item><title>Hers</title><link>https://paper.test/a</link>"
        "<dc:creator>Jane Doe</dc:creator>"
        f"<description>{'her prose. ' * 120}</description></item>"
        "<item><title>His</title><link>https://paper.test/b</link>"
        "<dc:creator>John Roe</dc:creator>"
        f"<description>{'his prose. ' * 120}</description></item>"
        "</channel></rss>"
    )
    source = Source(
        url="https://paper.test/rss", type="rss", tier="medium",
        priority="medium", filter_note="—", active=True,
    )
    author = _jane_at_paper()
    plans, _ = resolve_plans([author], _paused_categories())

    result = collect.collect_category(
        category="ai-agents",
        sources=[source],
        incoming_dir=tmp_path / "incoming",
        registry_path=tmp_path / "registry.md",
        today="2026-07-22",
        known_urls=set(),
        fetch_fn=lambda url: feed,
        item_filters=author_item_filters(plans, [author]),
    )
    assert result.saved == 1
    saved = list((tmp_path / "incoming" / "ai-agents").glob("*.md"))
    assert len(saved) == 1
    body = saved[0].read_text(encoding="utf-8")
    assert "Hers" in body and "His" not in body
