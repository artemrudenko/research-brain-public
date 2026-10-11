"""
test_authors_store.py — loading config/authors.yaml into typed records.

The loader is tolerant where the validator is strict (same relationship
sources/store.py has with its validator), so these tests pin the tolerance
deliberately rather than by accident: unknown keys ignored, optionals defaulted,
absent file → empty roster.

The YAML→field renames (`id`→`identifier`, `url`→`profile_url`) are the part
most likely to rot silently — a typo there loads every author with no handle at
all, which `plan.py` would then refuse one by one with a confusing reason.
"""
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

yaml = pytest.importorskip("yaml", reason="PyYAML required for authors config tests")

from scripts.authors.model import MonitoredAuthor  # noqa: E402
from scripts.authors.store import (  # noqa: E402
    load_authors,
    parse_authors_yaml_text,
    roster_identity_key,
)
from scripts.source_report.authors import identity_key  # noqa: E402


def test_roster_identity_key_uses_the_one_shared_ladder() -> None:
    # roster_identity_key is the sole MonitoredAuthor → identity adapter, so it
    # must equal the shared ladder for the same fields — a second mapping is how
    # the roster and the collection metrics would drift on "who is who".
    by_id = MonitoredAuthor(name="Jane Doe", monitoring="scholarly", identifier="0000-1")
    assert roster_identity_key(by_id) == identity_key("Jane Doe", "", "0000-1", "")
    by_url = MonitoredAuthor(
        name="Jane Doe", monitoring="rss", profile_url="https://example.com/jane"
    )
    assert roster_identity_key(by_url) == identity_key(
        "Jane Doe", "https://example.com/jane", "", ""
    )
    # Name-only is scoped by the (lowercased) publication, keeping same-named
    # people on different sites apart.
    by_name = MonitoredAuthor(
        name="Jane Doe", monitoring="publication-filter", publication="Example.COM"
    )
    assert roster_identity_key(by_name) == identity_key("Jane Doe", "", "", "example.com")


def test_rss_authors_are_distinguished_by_feed_not_just_name() -> None:
    # Two same-named RSS authors followed on DIFFERENT feeds are DIFFERENT roster
    # rows — the feed is the stable roster handle. The name+publication fallback
    # alone collapsed them into one person (external review 2026-07-23, P1 #3).
    a = MonitoredAuthor(name="Jane Doe", monitoring="rss", feed="https://a.example/f.xml")
    b = MonitoredAuthor(name="Jane Doe", monitoring="rss", feed="https://b.example/f.xml")
    assert roster_identity_key(a) != roster_identity_key(b)
    # The same feed spelled differently (http/https/trailing slash) is one row.
    a2 = MonitoredAuthor(name="Jane Doe", monitoring="rss", feed="http://a.example/f.xml/")
    assert roster_identity_key(a) == roster_identity_key(a2)


def test_rss_feed_never_shadows_a_real_identifier_or_profile_url() -> None:
    # id / profile URL are PERSON identity (shared with author nodes, metrics and
    # suggestions), so a feed must not override them — else a followed author would
    # stop matching their brain/authors/ node. The feed only breaks a name-only tie.
    by_id = MonitoredAuthor(
        name="Jane Doe", monitoring="rss", identifier="0000-1", feed="https://a.example/f.xml"
    )
    assert roster_identity_key(by_id) == identity_key("Jane Doe", "", "0000-1", "")
    by_url = MonitoredAuthor(
        name="Jane Doe", monitoring="rss",
        profile_url="https://example.com/jane", feed="https://a.example/f.xml",
    )
    assert roster_identity_key(by_url) == identity_key(
        "Jane Doe", "https://example.com/jane", "", ""
    )


def test_missing_file_is_an_empty_roster(tmp_path: Path) -> None:
    # Absent is the default: nobody is followed, and that is not an error.
    assert load_authors(tmp_path / "authors.yaml") == []


def test_loads_a_full_entry(tmp_path: Path) -> None:
    path = tmp_path / "authors.yaml"
    path.write_text(
        "schema_version: 1\n"
        "authors:\n"
        "  - name: Jane Doe\n"
        "    monitoring: publication-filter\n"
        "    publication: example.com\n"
        "    id: 'orcid:0000-0002-1825-0097'\n"
        "    url: https://example.com/author/jane\n"
        "    active: false\n"
        "    added: '2026-07-21'\n"
        "    note: suggested by source-insights\n",
        encoding="utf-8",
    )
    (author,) = load_authors(path)
    assert author.name == "Jane Doe"
    assert author.monitoring == "publication-filter"
    assert author.publication == "example.com"
    # The two renamed keys — the silent-rot candidates.
    assert author.identifier == "orcid:0000-0002-1825-0097"
    assert author.profile_url == "https://example.com/author/jane"
    assert author.active is False
    assert author.added == "2026-07-21"
    assert author.note == "suggested by source-insights"


def test_optionals_default_and_active_defaults_true() -> None:
    (author,) = parse_authors_yaml_text(
        "authors:\n  - name: Jane Doe\n    monitoring: search\n    query: agents\n"
    )
    assert author.active is True
    assert (author.feed, author.identifier, author.profile_url, author.note) == ("", "", "", "")


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    # A roster written by a newer release must still load on this one.
    (author,) = parse_authors_yaml_text(
        "authors:\n  - name: Jane Doe\n    monitoring: rss\n"
        "    feed: https://e.com/f.xml\n    future_key: whatever\n"
    )
    assert author.name == "Jane Doe"


def test_empty_and_null_rosters(tmp_path: Path) -> None:
    assert parse_authors_yaml_text("authors: []\n") == []
    assert parse_authors_yaml_text("authors:\n") == []
    assert parse_authors_yaml_text("") == []


def test_roster_order_is_preserved() -> None:
    authors = parse_authors_yaml_text(
        "authors:\n"
        "  - name: Zoe Last\n    monitoring: search\n    query: a\n"
        "  - name: Amy First\n    monitoring: search\n    query: b\n"
    )
    # Not sorted: the file is the user's, and its order is theirs to choose.
    assert [a.name for a in authors] == ["Zoe Last", "Amy First"]


@pytest.mark.parametrize(
    "text",
    [
        "authors: [unclosed\n",
        "- not\n- a\n- mapping\n",
        "authors:\n  jane: yes\n",
        "authors:\n  - Jane Doe\n",
        "authors:\n  - name: Jane\n    monitoring: rss\n    active: maybe\n",
    ],
)
def test_malformed_rosters_raise(text: str) -> None:
    with pytest.raises(ValueError):
        parse_authors_yaml_text(text)
