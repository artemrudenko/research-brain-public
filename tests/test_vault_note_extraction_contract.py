"""Contracts that make generated concepts feed lesson/playbook extraction."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relpath: str) -> str:
    return (PROJECT_ROOT / relpath).read_text(encoding="utf-8")


def test_concept_template_exposes_extractable_sections() -> None:
    text = _read("brain/concept-template.md")

    assert "## Lessons" in text
    assert "## Playbook:" in text
    assert "scripts/extract_vault_notes.py" in text


def test_wiki_ingest_contract_preserves_extractable_sections() -> None:
    text = _read("skills/wiki-ingest/SKILL.md")
    template = _read("skills/wiki-ingest/assets/output-template.md")

    assert "## Lessons" in text
    assert "## Playbook:" in text
    assert "extract_vault_notes.py" in text
    assert "Do not bury" in text
    assert "## Lessons" in template
    assert "## Playbook:" in template


def test_research_build_outputs_downstream_extraction_hints() -> None:
    text = _read("skills/research-build/SKILL.md")

    assert "Downstream extraction hints" in text
    assert "candidate lessons" in text
    assert "candidate playbooks" in text
    assert "wiki-ingest" in text
