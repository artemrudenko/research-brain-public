"""Tests for the shipped Obsidian Bases front doors.

These files are user-facing navigation, not executable code, but they are part of
the vault contract: concepts, lessons, and playbooks should all be discoverable
without maintaining generated indexes.
"""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relpath: str) -> str:
    return (_PROJECT_ROOT / relpath).read_text(encoding="utf-8")


def test_lessons_base_scopes_to_lesson_notes() -> None:
    text = _read("brain/lessons.base")

    assert 'type == "lesson"' in text
    assert 'file.inFolder("lessons")' in text
    assert "All lessons" in text
    assert "By confidence" in text


def test_playbooks_base_scopes_to_playbook_notes() -> None:
    text = _read("brain/playbooks.base")

    assert 'type == "playbook"' in text
    assert 'file.inFolder("playbooks")' in text
    assert "All playbooks" in text
    assert "By status" in text


def test_concepts_index_points_to_all_live_frontdoors() -> None:
    text = _read("brain/INDEX.md")

    assert "[`concepts.base`](concepts.base)" in text
    assert "[`lessons.base`](lessons.base)" in text
    assert "[`playbooks.base`](playbooks.base)" in text
