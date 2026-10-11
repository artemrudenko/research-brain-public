"""
test_validate_authors_config.py — offline tests for the authors.yaml validator.

config/authors.yaml is OPTIONAL and its absence is the DEFAULT: no file means no
author monitoring at all. That is the schema's half of the plan's hard rule —
nothing may start following a person on its own, so the configured-off state has
to be the one you get for free.

When the file IS present, every entry must carry a handle the corresponding
monitoring variant can actually act on. A `scholarly` entry with only a display
name is the failure this validator exists to prevent: OpenAlex would happily
resolve "Jane Doe" to the wrong Jane Doe, and the person misrepresented never
gets to correct it (the same reasoning as the identity ladder in
scripts/source_report/authors.py).

Skips cleanly if PyYAML is missing.
"""
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# The validator imports PyYAML lazily; the assertions here need it directly.
yaml = pytest.importorskip("yaml", reason="PyYAML required for config schema tests")

from scripts import validate_config  # noqa: E402
from scripts.config_schema import (  # noqa: E402
    AUTHOR_MONITORING_VARIANTS,
    LEGACY_AUTHOR_MONITORING_VARIANTS,
)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "authors.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _errors(tmp_path: Path, body: str) -> list[str]:
    return validate_config.validate_authors_yaml(_write(tmp_path, body), yaml)


# --------------------------------------------------------------------------- #
# The file is optional, and absent is the default (monitoring OFF)
# --------------------------------------------------------------------------- #


def test_missing_file_is_ok(tmp_path: Path) -> None:
    # No authors.yaml is a valid configuration: nobody is being followed.
    errors = validate_config.validate_authors_yaml(tmp_path / "authors.yaml", yaml)
    assert errors == []


def test_empty_authors_list_is_ok(tmp_path: Path) -> None:
    # An explicitly empty roster is equally valid — author-manage writes this
    # shape when the last entry is removed.
    assert _errors(tmp_path, "schema_version: 1\nauthors: []\n") == []


def test_null_authors_is_ok(tmp_path: Path) -> None:
    assert _errors(tmp_path, "schema_version: 1\nauthors:\n") == []


# --------------------------------------------------------------------------- #
# Structural shape
# --------------------------------------------------------------------------- #


def test_broken_yaml_fails(tmp_path: Path) -> None:
    errors = _errors(tmp_path, "authors: [unclosed\n")
    assert any("parse error" in e for e in errors), errors


def test_root_not_mapping_fails(tmp_path: Path) -> None:
    errors = _errors(tmp_path, "- just\n- a\n- list\n")
    assert any("mapping" in e for e in errors), errors


def test_authors_not_a_list_fails(tmp_path: Path) -> None:
    errors = _errors(tmp_path, "authors:\n  jane: yes\n")
    assert any("`authors` must be a list" in e for e in errors), errors


def test_entry_not_a_mapping_fails(tmp_path: Path) -> None:
    errors = _errors(tmp_path, "authors:\n  - Jane Doe\n")
    assert any("must be a mapping" in e for e in errors), errors


# --------------------------------------------------------------------------- #
# name + monitoring: the two required keys
# --------------------------------------------------------------------------- #


def test_missing_name_fails(tmp_path: Path) -> None:
    errors = _errors(
        tmp_path, "authors:\n  - monitoring: rss\n    feed: https://e.com/f.xml\n"
    )
    assert any("`name`" in e for e in errors), errors


def test_blank_name_fails(tmp_path: Path) -> None:
    # An all-whitespace name is not a person; it would render as an empty row.
    errors = _errors(
        tmp_path,
        "authors:\n  - name: '   '\n    monitoring: rss\n    feed: https://e.com/f.xml\n",
    )
    assert any("`name`" in e for e in errors), errors


def test_missing_monitoring_fails(tmp_path: Path) -> None:
    errors = _errors(tmp_path, "authors:\n  - name: Jane Doe\n")
    assert any("`monitoring`" in e for e in errors), errors


def test_unknown_monitoring_variant_fails(tmp_path: Path) -> None:
    errors = _errors(tmp_path, "authors:\n  - name: Jane Doe\n    monitoring: telepathy\n")
    assert any("`monitoring`" in e and "telepathy" in e for e in errors), errors


def test_every_variant_is_reachable() -> None:
    # Guards against the enum and the per-variant requirement table drifting:
    # a variant nobody can configure is dead code.
    assert set(AUTHOR_MONITORING_VARIANTS) == {
        "rss",
        "publication-filter",
        "scholarly",
    }
    assert LEGACY_AUTHOR_MONITORING_VARIANTS == ("search",)


# --------------------------------------------------------------------------- #
# Per-variant required companion field — the "handle you can act on" rule
# --------------------------------------------------------------------------- #


def test_rss_requires_feed(tmp_path: Path) -> None:
    errors = _errors(tmp_path, "authors:\n  - name: Jane Doe\n    monitoring: rss\n")
    assert any("`feed`" in e for e in errors), errors


def test_rss_feed_must_be_a_url(tmp_path: Path) -> None:
    errors = _errors(
        tmp_path, "authors:\n  - name: Jane Doe\n    monitoring: rss\n    feed: not-a-url\n"
    )
    assert any("`feed`" in e for e in errors), errors


def test_rss_with_feed_passes(tmp_path: Path) -> None:
    assert (
        _errors(
            tmp_path,
            "authors:\n  - name: Jane Doe\n    monitoring: rss\n    topic: ai-agents\n"
            "    feed: https://example.com/jane/feed.xml\n",
        )
        == []
    )


def test_publication_filter_requires_publication(tmp_path: Path) -> None:
    errors = _errors(
        tmp_path,
        "authors:\n  - name: Jane Doe\n    monitoring: publication-filter\n"
        "    url: https://example.com/author/jane\n",
    )
    assert any("`publication`" in e for e in errors), errors


def test_publication_filter_requires_a_stable_identity(tmp_path: Path) -> None:
    # Filtering a shared publication feed by display name alone is exactly the
    # name-collision the identity ladder refuses to make; the config must too.
    errors = _errors(
        tmp_path,
        "authors:\n  - name: Jane Doe\n    monitoring: publication-filter\n"
        "    publication: example.com\n",
    )
    assert any("`id`" in e and "`url`" in e for e in errors), errors


def test_publication_filter_complete_passes(tmp_path: Path) -> None:
    assert (
        _errors(
            tmp_path,
            "authors:\n  - name: Jane Doe\n    monitoring: publication-filter\n"
            "    topic: ai-agents\n    publication: example.com\n"
            "    url: https://example.com/author/jane\n",
        )
        == []
    )


def test_scholarly_requires_an_identifier(tmp_path: Path) -> None:
    # A profile URL is not enough here: OpenAlex/ORCID are queried BY identifier,
    # and resolving a bare name would attribute someone else's papers.
    errors = _errors(
        tmp_path,
        "authors:\n  - name: Jane Doe\n    monitoring: scholarly\n"
        "    url: https://example.com/author/jane\n",
    )
    assert any("`id`" in e for e in errors), errors


def test_scholarly_with_identifier_passes(tmp_path: Path) -> None:
    assert (
        _errors(
            tmp_path,
            "authors:\n  - name: Jane Doe\n    monitoring: scholarly\n    topic: ml\n"
            "    id: orcid:0000-0002-1825-0097\n",
        )
        == []
    )


def test_search_requires_a_query(tmp_path: Path) -> None:
    errors = _errors(tmp_path, "authors:\n  - name: Jane Doe\n    monitoring: search\n")
    assert any("`query`" in e for e in errors), errors


def test_search_with_query_passes(tmp_path: Path) -> None:
    # Existing roster entries remain readable during the retirement.
    assert (
        _errors(
            tmp_path,
            "authors:\n  - name: Jane Doe\n    monitoring: search\n"
            '    query: "Jane Doe transformers"\n',
        )
        == []
    )


# --------------------------------------------------------------------------- #
# Optional field types
# --------------------------------------------------------------------------- #


def test_active_must_be_boolean(tmp_path: Path) -> None:
    errors = _errors(
        tmp_path,
        "authors:\n  - name: Jane Doe\n    monitoring: rss\n"
        "    feed: https://example.com/f.xml\n    active: yes-please\n",
    )
    assert any("`active`" in e for e in errors), errors


def test_active_false_is_valid(tmp_path: Path) -> None:
    # A paused entry is still a valid entry — that is how you stop following
    # someone without losing the record of having followed them.
    assert (
        _errors(
            tmp_path,
            "authors:\n  - name: Jane Doe\n    monitoring: rss\n    topic: ai-agents\n"
            "    feed: https://example.com/f.xml\n    active: false\n",
        )
        == []
    )


def test_profile_url_must_be_a_url(tmp_path: Path) -> None:
    errors = _errors(
        tmp_path,
        "authors:\n  - name: Jane Doe\n    monitoring: scholarly\n"
        "    id: orcid:0000-0002-1825-0097\n    url: mailto:jane@example.com\n",
    )
    assert any("`url`" in e for e in errors), errors


def test_note_and_added_are_free_text(tmp_path: Path) -> None:
    assert (
        _errors(
            tmp_path,
            "authors:\n  - name: Jane Doe\n    monitoring: rss\n    topic: ai-agents\n"
            "    feed: https://example.com/f.xml\n"
            "    added: '2026-07-21'\n    note: suggested by source-insights\n",
        )
        == []
    )


# --------------------------------------------------------------------------- #
# Errors are located, and they accumulate
# --------------------------------------------------------------------------- #


def test_errors_name_the_offending_entry(tmp_path: Path) -> None:
    errors = _errors(
        tmp_path,
        "authors:\n"
        "  - name: Jane Doe\n    monitoring: rss\n    topic: t\n    feed: https://example.com/f.xml\n"
        "  - name: John Roe\n    monitoring: rss\n    topic: t\n",
    )
    assert any("authors[1]" in e for e in errors), errors
    assert not any("authors[0]" in e for e in errors), errors


def test_multiple_problems_all_reported(tmp_path: Path) -> None:
    # One pass should tell the user everything wrong, not the first thing.
    errors = _errors(
        tmp_path, "authors:\n  - monitoring: telepathy\n    active: maybe\n"
    )
    assert len(errors) >= 3, errors


def test_collecting_variants_require_a_topic(tmp_path: Path) -> None:
    # A collected article lands in `pipeline/1-incoming/<topic>/` and is judged
    # by that topic's curate rules. Without one there is nowhere to put it, and
    # only the user knows where a person's work belongs.
    errors = _errors(
        tmp_path,
        "authors:\n  - name: Jane Doe\n    monitoring: rss\n"
        "    feed: https://example.com/f.xml\n",
    )
    assert any("`topic`" in e for e in errors), errors


def test_search_does_not_require_a_topic(tmp_path: Path) -> None:
    # Legacy rows may never have had a topic; keep them parseable for removal.
    assert (
        _errors(
            tmp_path,
            "authors:\n  - name: Jane Doe\n    monitoring: search\n    query: agents\n",
        )
        == []
    )
