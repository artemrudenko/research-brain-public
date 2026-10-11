"""
test_manage_authors.py — the ONLY write path into config/authors.yaml.

Adding a row here is the moment a person starts being followed, so this module
carries the plan's hard rule: nothing may start monitoring an author on its own.
Two tests pin that structurally rather than by intention —

  - `test_source_report_cannot_reach_the_write_path` walks the import graph:
    the suggesting side must not be able to call the writing side at all. A
    comment saying "we only suggest" is not a constraint; an absent import is.
  - `test_suggestion_is_not_an_entry` pins that a MonitoringSuggestion carries
    no method, field, or helper that turns itself into a roster row.

Everything else is the ordinary mutator contract source-manage already has:
idempotent on identity, validated at the boundary, atomic on disk.
"""
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

yaml = pytest.importorskip("yaml", reason="PyYAML required for authors config tests")

from scripts import manage_authors, validate_config  # noqa: E402
from scripts.authors.store import load_authors  # noqa: E402


def _path(tmp_path: Path) -> Path:
    return tmp_path / "authors.yaml"


def _add_jane(tmp_path: Path, **overrides: object) -> bool:
    kwargs: dict[str, object] = {
        "name": "Jane Doe",
        "monitoring": "rss",
        "topic": "ai-agents",
        "feed": "https://example.com/jane/feed.xml",
    }
    kwargs.update(overrides)
    return manage_authors.add_author(tmp_path, **kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# The hard rule: suggesting and writing are separated structurally
# --------------------------------------------------------------------------- #


def test_source_report_cannot_reach_the_write_path() -> None:
    # The suggesting side must have no route to the writing side. Checked on the
    # source text so a transitive import cannot sneak the capability back in.
    import scripts.source_report.authors as suggest

    source = Path(suggest.__file__).read_text(encoding="utf-8")
    assert "manage_authors" not in source
    assert "scripts.authors" not in source


def test_suggestion_is_not_an_entry() -> None:
    # A suggestion is inert: no accept(), no to_entry(), nothing that writes.
    from scripts.source_report.authors import MonitoringSuggestion

    suggestion = MonitoringSuggestion(display_name="Jane Doe", reason="…")
    assert not [n for n in dir(suggestion) if n in ("accept", "to_entry", "save", "add")]


# --------------------------------------------------------------------------- #
# add_author
# --------------------------------------------------------------------------- #


def test_add_creates_the_file_and_the_entry(tmp_path: Path) -> None:
    assert _add_jane(tmp_path) is True
    (author,) = load_authors(_path(tmp_path))
    assert (author.name, author.monitoring) == ("Jane Doe", "rss")
    assert author.active is True


def test_add_is_idempotent_on_identity(tmp_path: Path) -> None:
    # Re-accepting the same suggestion must not create a second row.
    assert _add_jane(tmp_path, identifier="orcid:0000-0002-1825-0097") is True
    assert _add_jane(tmp_path, identifier="orcid:0000-0002-1825-0097") is False
    assert len(load_authors(_path(tmp_path))) == 1


def test_two_same_named_people_stay_two_entries(tmp_path: Path) -> None:
    # The identity ladder's non-merge, enforced at the write boundary too.
    _add_jane(tmp_path, profile_url="https://a.example/jane")
    _add_jane(tmp_path, profile_url="https://b.example/jane")
    assert len(load_authors(_path(tmp_path))) == 2


def test_two_same_named_rss_authors_on_different_feeds_both_get_a_row(
    tmp_path: Path,
) -> None:
    # An RSS author is identified by its feed. Two same-named people followed on
    # different feeds must both be kept — before, the name-only key collapsed the
    # second into the first and it was silently dropped (review 2026-07-23, P1 #3).
    assert _add_jane(tmp_path, feed="https://a.example/jane.xml") is True
    assert _add_jane(tmp_path, feed="https://b.example/jane.xml") is True
    assert len(load_authors(_path(tmp_path))) == 2
    # The same feed remains idempotent (spelled differently → still one row).
    assert _add_jane(tmp_path, feed="http://a.example/jane.xml/") is False
    assert len(load_authors(_path(tmp_path))) == 2


def test_add_refuses_an_entry_the_validator_would_reject(tmp_path: Path) -> None:
    # One rule set: you cannot write a roster that then fails validate_config.
    with pytest.raises(ValueError):
        manage_authors.add_author(
            tmp_path, name="Jane Doe", monitoring="scholarly", topic="ml"
        )


def test_add_refuses_an_unknown_variant(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        manage_authors.add_author(tmp_path, name="Jane Doe", monitoring="telepathy")


def test_add_refuses_retired_search_but_existing_row_can_be_removed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not available for new author monitoring"):
        manage_authors.add_author(
            tmp_path, name="Jane Doe", monitoring="search", query="Jane Doe research"
        )
    assert not _path(tmp_path).exists()
    _path(tmp_path).write_text(
        "authors:\n  - name: Jane Doe\n    monitoring: search\n"
        "    query: Jane Doe research\n",
        encoding="utf-8",
    )
    assert "retired: no collection" in manage_authors.human_summary(tmp_path)
    assert manage_authors.remove_author(tmp_path, "Jane Doe") is True
    assert load_authors(_path(tmp_path)) == []


def test_add_scholarly_prints_a_not_collected_caveat(tmp_path: Path, capsys) -> None:
    # Structural honesty at add-time (review 2026-07-22, product finding): the CLI
    # itself must say a scholarly author is only staged, not collected —
    # the guarantee cannot ride on agent prose obeying the skill.
    rc = manage_authors.main([
        "--config-dir", str(tmp_path), "add", "Dr Cited",
        "--monitoring", "scholarly", "--topic", "ml",
        "--id", "orcid:0000-0002-1825-0097",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Now following Dr Cited" in out
    assert "not collected yet" in out.lower()


def test_readding_existing_scholarly_author_still_prints_caveat(
    tmp_path: Path, capsys
) -> None:
    # The "not collected yet" caveat is a property of the monitoring VARIANT, not
    # of whether this call happened to insert a row. Re-running `add` for an author
    # already in the roster (a no-op on the file) must still tell the truth — the
    # old code only printed it on added=True, so a repeat add silently dropped it.
    argv = [
        "--config-dir", str(tmp_path), "add", "Dr Cited",
        "--monitoring", "scholarly", "--topic", "ml",
        "--id", "orcid:0000-0002-1825-0097",
    ]
    assert manage_authors.main(argv) == 0
    capsys.readouterr()  # discard first-add output
    assert manage_authors.main(argv) == 0
    out = capsys.readouterr().out
    assert "already in the roster" in out
    assert "not collected yet" in out.lower()


def test_add_rss_has_no_caveat(tmp_path: Path, capsys) -> None:
    # A genuinely collected variant must NOT carry the caveat.
    rc = manage_authors.main([
        "--config-dir", str(tmp_path), "add", "Ada",
        "--monitoring", "rss", "--topic", "ml",
        "--feed", "https://ada.example/feed.xml",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Now following Ada" in out
    assert "not collected yet" not in out.lower()


def test_written_roster_passes_the_validator(tmp_path: Path) -> None:
    _add_jane(tmp_path, note="suggested by source-insights", added="2026-07-21")
    _add_jane(
        tmp_path,
        name="John Roe",
        monitoring="scholarly",
        topic="ml",
        identifier="orcid:0000-0002-1825-0097",
    )
    assert validate_config.validate_authors_yaml(_path(tmp_path), yaml) == []


# --------------------------------------------------------------------------- #
# pause / resume / remove
# --------------------------------------------------------------------------- #


def test_pause_and_resume(tmp_path: Path) -> None:
    _add_jane(tmp_path)
    assert manage_authors.set_author_active(tmp_path, "Jane Doe", False) is True
    assert load_authors(_path(tmp_path))[0].active is False
    # Idempotent: already paused is a no-op, not an error.
    assert manage_authors.set_author_active(tmp_path, "Jane Doe", False) is False
    assert manage_authors.set_author_active(tmp_path, "Jane Doe", True) is True


def test_pause_unknown_author_raises(tmp_path: Path) -> None:
    _add_jane(tmp_path)
    with pytest.raises(LookupError):
        manage_authors.set_author_active(tmp_path, "Nobody At All", False)


def test_remove_drops_only_that_entry(tmp_path: Path) -> None:
    _add_jane(tmp_path)
    _add_jane(tmp_path, name="John Roe", feed="https://example.com/john/feed.xml")
    assert manage_authors.remove_author(tmp_path, "Jane Doe") is True
    assert [a.name for a in load_authors(_path(tmp_path))] == ["John Roe"]


def test_remove_absent_author_is_a_clean_no_op(tmp_path: Path) -> None:
    _add_jane(tmp_path)
    assert manage_authors.remove_author(tmp_path, "Nobody At All") is False
    assert len(load_authors(_path(tmp_path))) == 1


# --------------------------------------------------------------------------- #
# On-disk shape
# --------------------------------------------------------------------------- #


def test_roster_round_trips_through_the_emitter(tmp_path: Path) -> None:
    _add_jane(
        tmp_path,
        monitoring="publication-filter",
        feed="",
        publication="example.com",
        profile_url="https://example.com/author/jane",
        note="has: a colon, and #hash",
    )
    before = load_authors(_path(tmp_path))
    manage_authors.set_author_active(tmp_path, "Jane Doe", False)
    manage_authors.set_author_active(tmp_path, "Jane Doe", True)
    assert load_authors(_path(tmp_path)) == before


def test_empty_roster_is_written_not_deleted(tmp_path: Path) -> None:
    # Removing the last author leaves an explicit empty roster: the file is the
    # record of a decision, and its absence would read as "never configured".
    _add_jane(tmp_path)
    manage_authors.remove_author(tmp_path, "Jane Doe")
    assert _path(tmp_path).exists()
    assert load_authors(_path(tmp_path)) == []


def test_list_authors_reports_the_roster(tmp_path: Path) -> None:
    _add_jane(tmp_path)
    summary = manage_authors.human_summary(tmp_path)
    assert "Jane Doe" in summary
    assert "rss" in summary


# --------------------------------------------------------------------------- #
# `nodes` subcommand (Stage 9 slice-4 UI) — read-only listing of author NODES
# (brain/authors/) each marked followed: yes/no against the roster. This never
# writes; it is the read side of the node↔roster cross-reference.
# --------------------------------------------------------------------------- #


def _write_node(root: Path, stem: str, identity_key: str) -> None:
    note_dir = root / "brain" / "authors"
    note_dir.mkdir(parents=True, exist_ok=True)
    (note_dir / f"{stem}.md").write_text(
        "---\n"
        f"title: {stem}\n"
        "type: author\n"
        f"identity_key: {identity_key}\n"
        "tags: [author]\n"
        "created: 2026-07-22\nlast_updated: 2026-07-22\n---\n\n"
        f"# {stem}\n",
        encoding="utf-8",
    )


def _write_roster(root: Path, body: str) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "authors.yaml").write_text(body, encoding="utf-8")


def test_nodes_summary_marks_followed_and_unfollowed(tmp_path: Path) -> None:
    _write_roster(
        tmp_path,
        "authors:\n  - name: Jane Doe\n    monitoring: scholarly\n    id: k-1\n",
    )
    _write_node(tmp_path, "jane-doe", "id:k-1")
    _write_node(tmp_path, "someone-else", "id:k-2")

    summary = manage_authors.nodes_summary(tmp_path)

    assert "jane-doe — followed: yes" in summary
    assert "someone-else — followed: no" in summary


def test_nodes_summary_empty_vault(tmp_path: Path) -> None:
    assert "No author nodes" in manage_authors.nodes_summary(tmp_path)


def test_nodes_command_prints_summary(tmp_path: Path, capsys) -> None:
    _write_roster(
        tmp_path,
        "authors:\n  - name: Jane Doe\n    monitoring: scholarly\n    id: k-1\n",
    )
    _write_node(tmp_path, "jane-doe", "id:k-1")

    rc = manage_authors.main(["--config-dir", str(tmp_path / "config"), "nodes"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "jane-doe — followed: yes" in out
