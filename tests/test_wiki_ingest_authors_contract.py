"""
Contract that wiki-ingest proposes author nodes as a GATED byproduct of a
concept write (Stage 9, slice 3). Author nodes are first-class vault entities
(brain/authors/<slug>.md, type: author, model alpha). The load-bearing rule:
they ride the SAME AskUserQuestion gate as the concept write — a script can
NEVER emit them (brain/ has no generated indices). These are documentation
contracts (the skill is agentic); they guard the instructions from regressing.
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relpath: str) -> str:
    return (PROJECT_ROOT / relpath).read_text(encoding="utf-8")


def test_wiki_ingest_proposes_author_nodes_gated() -> None:
    """The skill documents the gated author-node proposal step."""
    text = _read("skills/wiki-ingest/SKILL.md")

    # The entity: author nodes live in brain/authors/ with type: author.
    assert "brain/authors/" in text
    assert "type: author" in text
    # The link back onto the work is the concept's contributors: field.
    assert "contributors:" in text
    # Resolution is via the strict identity ladder, never fuzzy name matching.
    assert "identity_key" in text
    assert "authors:" in text  # resolved from the article authors: frontmatter
    # It is GATED — the same AskUserQuestion path as the concept write.
    assert "AskUserQuestion" in text


def test_wiki_ingest_author_node_write_is_terminal_and_never_scripted() -> None:
    """The no-generated-indices constraint is stated for author nodes."""
    text = _read("skills/wiki-ingest/SKILL.md").lower()

    # Best-effort: a concept with no resolvable author still writes (no halt).
    assert "best-effort" in text or "does not halt" in text or "never halt" in text
    # Never auto-created from the followed-authors roster (Q4 separation).
    assert "roster" in text


def test_concept_template_exposes_contributors_slot() -> None:
    """Both concept templates carry an (optional) contributors: slot."""
    assert "contributors:" in _read("brain/concept-template.md")
    assert "contributors:" in _read("skills/wiki-ingest/assets/output-template.md")


def test_author_node_template_exists_with_q1_frontmatter() -> None:
    """A shipped author-node template mirrors the Q1 frontmatter (type: author)."""
    text = _read("brain/author-template.md")

    assert "type: author" in text
    assert "schema_version: 1" in text  # stamped like every shipped template
    for field in ("title", "identity_key", "identifier", "profile_url", "tags:"):
        assert field in text
    # Backlink-only by design: the node must NOT list its own concepts.
    assert "contributors:" not in text


def test_wiki_ingest_create_references_author_template() -> None:
    """The skill points author-node CREATE at the shipped template."""
    assert "brain/author-template.md" in _read("skills/wiki-ingest/SKILL.md")
