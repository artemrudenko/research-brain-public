"""
test_author_node_roster.py — read-only cross-reference between author NODES
(brain/authors/, "here is what we know of them") and the followed-authors
ROSTER (config/authors.yaml, "I want more of them") — Stage 9, slice 4.

A node is marked "followed" purely by intersecting its `identity_key` with the
roster's keys through the ONE shared identity ladder. NEVER a write across the
boundary (Q4): the two are distinct intents that must not auto-create each other.
"""
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

yaml = pytest.importorskip("yaml", reason="PyYAML required for the roster")

from scripts.authors.nodes import followed_node_status  # noqa: E402
from scripts.authors.store import roster_identity_keys  # noqa: E402


def _write_roster(root: Path, body: str) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "authors.yaml").write_text(body, encoding="utf-8")


def _write_author_node(root: Path, stem: str, identity_key: str) -> None:
    note_dir = root / "brain" / "authors"
    note_dir.mkdir(parents=True, exist_ok=True)
    text = (
        "---\n"
        f"title: {stem}\n"
        "type: author\n"
        f"identity_key: {identity_key}\n"
        "tags: [author]\n"
        "created: 2026-07-22\n"
        "last_updated: 2026-07-22\n"
        "---\n\n"
        f"# {stem}\n"
    )
    (note_dir / f"{stem}.md").write_text(text, encoding="utf-8")


def test_roster_identity_keys_uses_shared_ladder(tmp_path: Path) -> None:
    """The roster key set is built through the same ladder as author_metrics."""
    _write_roster(
        tmp_path,
        "authors:\n"
        "  - name: Jane Doe\n"
        "    monitoring: scholarly\n"
        "    id: 0000-0002-1825-0097\n",
    )
    assert roster_identity_keys(tmp_path) == {"id:0000-0002-1825-0097"}


def test_node_is_followed_when_identity_key_in_roster(tmp_path: Path) -> None:
    """A node whose identity_key is in the roster is marked followed: yes."""
    _write_roster(
        tmp_path,
        "authors:\n"
        "  - name: Jane Doe\n"
        "    monitoring: scholarly\n"
        "    id: 0000-0002-1825-0097\n",
    )
    _write_author_node(tmp_path, "jane-doe", "id:0000-0002-1825-0097")
    _write_author_node(tmp_path, "someone-else", "id:9999-0000-0000-0000")

    status = followed_node_status(tmp_path)

    assert status == {"jane-doe": True, "someone-else": False}


def test_node_with_empty_identity_key_never_followed(tmp_path: Path) -> None:
    """An empty identity_key cannot match any roster key."""
    _write_roster(
        tmp_path,
        "authors:\n  - name: Jane Doe\n    monitoring: scholarly\n    id: k-1\n",
    )
    _write_author_node(tmp_path, "unknown", "")

    assert followed_node_status(tmp_path) == {"unknown": False}


def test_missing_roster_marks_all_nodes_not_followed(tmp_path: Path) -> None:
    """No roster file → nobody followed, never an error (forgiving, read-only)."""
    _write_author_node(tmp_path, "jane-doe", "id:k-1")

    assert roster_identity_keys(tmp_path) == set()
    assert followed_node_status(tmp_path) == {"jane-doe": False}
