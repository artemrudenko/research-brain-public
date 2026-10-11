"""
test_author_insights.py — who keeps showing up, and who is worth following.

This is read-only aggregation over data already on disk. There is no author
monitoring yet; the output is at most a SUGGESTION the user may act on.

The identity rules are the substance, and they are conservative on purpose:

    same identifier          → the same person
    same canonical profile   → the same person
    same name, one publication → the same person
    anything else            → different people

Merging two "Jane Doe"s from different sites, or matching names fuzzily, would
attribute someone's work to a stranger. That is not a bug you find later — it
silently poisons every count built on top. So the ladder never guesses, and the
tests below assert the NON-merges as hard as the merges.
"""

from __future__ import annotations

from pathlib import Path

from scripts.registry import _REGISTRY_HEADER as REGISTRY_HEADER
from scripts.source_report.authors import (
    MIN_ARTICLES,
    MIN_CURATION_RATE,
    MIN_RUNS,
    author_metrics,
    monitoring_suggestions,
)
from scripts.source_report.events import record_decision
from scripts.source_report.model import CandidateDecision

FEED = "https://example.com/feed.xml"


def _seen(
    root: Path,
    url: str,
    *,
    name: str = "Jane Doe",
    author_url: str = "",
    author_id: str = "",
    source_url: str = FEED,
    run_id: str = "run-1",
    decision: str = "selected",
) -> None:
    record_decision(
        root,
        CandidateDecision(
            topic="ai",
            source_url=source_url,
            candidate_url=url,
            decision=decision,
            author_name=name,
            author_url=author_url,
            author_id=author_id,
            run_id=run_id,
        ),
    )


def _registry(root: Path, rows: list[tuple[str, str]]) -> Path:
    path = root / "pipeline" / "registry.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        REGISTRY_HEADER
        + "".join(f"| 2026-07-21 | ai | {st} | {u} | T |\n" for u, st in rows),
        encoding="utf-8",
    )
    return path


# ── identity: what merges ─────────────────────────────────────────────────────


def test_same_identifier_is_one_person_across_publications(tmp_path: Path) -> None:
    _seen(tmp_path, "https://a.example/1", author_id="orcid:0000-1", source_url="https://a/f")
    _seen(tmp_path, "https://b.example/1", author_id="orcid:0000-1", source_url="https://b/f")
    rows = author_metrics(tmp_path, _registry(tmp_path, []))
    assert len(rows) == 1
    assert rows[0].articles == 2


def test_same_profile_url_is_one_person(tmp_path: Path) -> None:
    for i, src in enumerate(("https://a/f", "https://b/f")):
        _seen(tmp_path, f"https://x.example/{i}", author_url="https://example.com/jane",
              source_url=src)
    assert len(author_metrics(tmp_path, _registry(tmp_path, []))) == 1


def test_same_name_within_one_publication_is_one_person(tmp_path: Path) -> None:
    _seen(tmp_path, "https://example.com/1")
    _seen(tmp_path, "https://example.com/2")
    rows = author_metrics(tmp_path, _registry(tmp_path, []))
    assert len(rows) == 1
    assert rows[0].articles == 2


def test_name_matching_ignores_case_and_spacing_only(tmp_path: Path) -> None:
    _seen(tmp_path, "https://example.com/1", name="Jane Doe")
    _seen(tmp_path, "https://example.com/2", name="  jane   doe ")
    assert len(author_metrics(tmp_path, _registry(tmp_path, []))) == 1


# ── identity: what must NOT merge ─────────────────────────────────────────────


def test_same_name_on_different_publications_stays_two_people(tmp_path: Path) -> None:
    """The single most damaging wrong merge, so it gets its own test.

    "Jane Doe" on two unrelated sites is not evidence of one person. Deciding
    otherwise needs corroboration we do not have here.
    """
    _seen(tmp_path, "https://a.example/1", source_url="https://a.example/feed.xml")
    _seen(tmp_path, "https://b.example/1", source_url="https://b.example/feed.xml")
    assert len(author_metrics(tmp_path, _registry(tmp_path, []))) == 2


def test_similar_names_are_never_fuzzily_merged(tmp_path: Path) -> None:
    _seen(tmp_path, "https://example.com/1", name="Jane Doe")
    _seen(tmp_path, "https://example.com/2", name="J. Doe")
    _seen(tmp_path, "https://example.com/3", name="Jane A. Doe")
    assert len(author_metrics(tmp_path, _registry(tmp_path, []))) == 3


def test_different_identifiers_stay_apart_even_with_one_name(tmp_path: Path) -> None:
    _seen(tmp_path, "https://example.com/1", author_id="orcid:0000-1")
    _seen(tmp_path, "https://example.com/2", author_id="orcid:0000-2")
    assert len(author_metrics(tmp_path, _registry(tmp_path, []))) == 2


def test_anonymous_rows_are_not_grouped_into_one_author(tmp_path: Path) -> None:
    _seen(tmp_path, "https://example.com/1", name="")
    _seen(tmp_path, "https://example.com/2", name="")
    assert author_metrics(tmp_path, _registry(tmp_path, [])) == []


# ── metrics ───────────────────────────────────────────────────────────────────


def test_metrics_count_articles_runs_topics_and_curation(tmp_path: Path) -> None:
    _seen(tmp_path, "https://example.com/1", run_id="run-1")
    _seen(tmp_path, "https://example.com/2", run_id="run-2")
    registry = _registry(
        tmp_path,
        [("https://example.com/1", "processed"), ("https://example.com/2", "rejected")],
    )
    row = author_metrics(tmp_path, registry)[0]
    assert row.display_name == "Jane Doe"
    assert row.articles == 2
    assert row.runs == 2
    assert row.passed_curation == 1
    assert row.topics == ("ai",)
    assert row.sources == (FEED,)


def test_only_collected_articles_count_as_the_authors_output(tmp_path: Path) -> None:
    # A candidate we rejected is not something the author "published to us".
    _seen(tmp_path, "https://example.com/1")
    _seen(tmp_path, "https://example.com/2", decision="duplicate_url")
    assert author_metrics(tmp_path, _registry(tmp_path, []))[0].articles == 1


# ── monitoring suggestions ────────────────────────────────────────────────────


def _prolific(tmp_path: Path, **kw: object) -> Path:
    """An author who clears every bar: enough articles, runs and curation passes."""
    urls = [f"https://example.com/{i}" for i in range(MIN_ARTICLES)]
    for i, url in enumerate(urls):
        _seen(tmp_path, url, run_id=f"run-{i % MIN_RUNS}", **kw)  # type: ignore[arg-type]
    return _registry(tmp_path, [(u, "processed") for u in urls])


def test_a_consistently_useful_author_with_a_profile_is_suggested(tmp_path: Path) -> None:
    registry = _prolific(tmp_path, author_url="https://example.com/jane")
    suggestions = monitoring_suggestions(author_metrics(tmp_path, registry))
    assert [s.display_name for s in suggestions] == ["Jane Doe"]
    assert suggestions[0].reason


def test_an_author_we_cannot_actually_follow_is_never_suggested(tmp_path: Path) -> None:
    """No stable URL or id means no way to monitor them — so we do not offer to.

    Suggesting an action the system cannot carry out is an empty promise, and it
    is the state ALL feed-only authors are in today (RSS gives a bare name).
    """
    registry = _prolific(tmp_path)  # name only
    assert monitoring_suggestions(author_metrics(tmp_path, registry)) == []


def test_too_few_articles_is_not_a_pattern(tmp_path: Path) -> None:
    for i in range(MIN_ARTICLES - 1):
        _seen(tmp_path, f"https://example.com/{i}", run_id=f"run-{i}",
              author_url="https://example.com/jane")
    registry = _registry(
        tmp_path, [(f"https://example.com/{i}", "processed") for i in range(MIN_ARTICLES - 1)]
    )
    assert monitoring_suggestions(author_metrics(tmp_path, registry)) == []


def test_one_run_is_not_a_habit(tmp_path: Path) -> None:
    """Everything from a single run could be one backfill, not a recurring author."""
    urls = [f"https://example.com/{i}" for i in range(MIN_ARTICLES + 2)]
    for url in urls:
        _seen(tmp_path, url, run_id="only-run", author_url="https://example.com/jane")
    registry = _registry(tmp_path, [(u, "processed") for u in urls])
    assert monitoring_suggestions(author_metrics(tmp_path, registry)) == []


def test_an_author_whose_work_keeps_getting_rejected_is_not_suggested(tmp_path: Path) -> None:
    urls = [f"https://example.com/{i}" for i in range(4)]
    for i, url in enumerate(urls):
        _seen(tmp_path, url, run_id=f"run-{i % 2}", author_url="https://example.com/jane")
    # One kept out of four is well under the bar.
    registry = _registry(
        tmp_path, [(urls[0], "processed")] + [(u, "rejected") for u in urls[1:]]
    )
    rows = author_metrics(tmp_path, registry)
    assert rows[0].curation_rate < MIN_CURATION_RATE
    assert monitoring_suggestions(rows) == []


def test_an_already_followed_author_is_not_suggested_again(tmp_path: Path) -> None:
    """A suggestion is a proposal to FOLLOW someone. If they are already in the
    roster the proposal is moot, so it is filtered out via the shared identity
    key — the report never tells you to follow someone you already follow."""
    registry = _prolific(tmp_path, author_url="https://example.com/jane")
    rows = author_metrics(tmp_path, registry)
    # She clears every bar and IS suggested when nobody is followed yet.
    assert [s.display_name for s in monitoring_suggestions(rows)] == ["Jane Doe"]
    # Once followed (matched by her own identity key), she drops off the list.
    assert monitoring_suggestions(rows, followed={rows[0].key}) == []


def test_following_a_different_person_leaves_the_suggestion(tmp_path: Path) -> None:
    """The filter is keyed on identity, not name — following someone else does
    not silence a genuine suggestion."""
    registry = _prolific(tmp_path, author_url="https://example.com/jane")
    rows = author_metrics(tmp_path, registry)
    assert [s.display_name for s in monitoring_suggestions(rows, followed={"id:9999"})] == [
        "Jane Doe"
    ]


def test_followed_keys_match_the_metrics_keys_they_filter(tmp_path: Path) -> None:
    """The report's roster-suppression only works if the roster's key for a person
    equals author_metrics' key for that same person. Prove they intersect (so the
    filter can bite) and that the suggestion is then actually dropped."""
    from scripts.source_insights import _followed_keys

    registry = _prolific(tmp_path, author_url="https://example.com/jane")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "authors.yaml").write_text(
        "authors:\n  - name: Jane Doe\n    monitoring: rss\n    topic: ai\n"
        "    url: https://example.com/jane\n"
        "    feed: https://example.com/jane/feed.xml\n",
        encoding="utf-8",
    )
    followed = _followed_keys(tmp_path)
    row_keys = {row.key for row in author_metrics(tmp_path, registry)}
    assert followed & row_keys  # the roster key really matches a metrics key
    assert monitoring_suggestions(author_metrics(tmp_path, registry), followed=followed) == []


def test_followed_keys_absent_roster_is_empty(tmp_path: Path) -> None:
    """No config/authors.yaml → nobody followed → every qualifying author stands."""
    from scripts.source_insights import _followed_keys

    assert _followed_keys(tmp_path) == set()


def test_a_suggestion_is_only_a_suggestion(tmp_path: Path) -> None:
    """Nothing is ever started automatically — the type carries no action."""
    registry = _prolific(tmp_path, author_url="https://example.com/jane")
    suggestion = monitoring_suggestions(author_metrics(tmp_path, registry))[0]
    assert not hasattr(suggestion, "apply")
    assert not hasattr(suggestion, "enable")
