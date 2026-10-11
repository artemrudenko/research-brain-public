"""Concept-note loading for the hygiene pass.

Frontmatter reading (the `---` split and the PyYAML/stdlib parse fallback) is
owned by `scripts.fm`; the split/parse helpers below are re-exported under their
historical private names so `scripts.validate_brain`'s stable import surface —
and the tests that reach through it — keep resolving unchanged.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from scripts.fm import (  # noqa: F401 — re-export surface for validate_brain
    _parse_frontmatter_fallback,
    _parse_inline_list,
    _strip_quotes,
)
from scripts.fm import parse_frontmatter as _parse_frontmatter
from scripts.fm import split_frontmatter as _split_frontmatter
from scripts.hygiene.model import Author, Concept

# Tags marking a note as a shipped demo rather than real knowledge (§5.1).
_SEED_EXAMPLE_TAGS = frozenset({"seed", "example"})


def _as_str_list(value: object) -> list[str]:
    """Coerce a frontmatter value to a list of strings."""
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _parse_iso_date(value: object) -> date | None:
    """Parse a `YYYY-MM-DD` value to a date, tolerating quotes/time tails."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    cleaned = value.strip().strip("\"'").split("T")[0].split(" ")[0]
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_int(value: object) -> int | None:
    """Coerce a frontmatter value to a positive-or-zero int, else None."""
    if isinstance(value, bool):  # bool is an int subclass — exclude it
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _is_seed_or_example(tags: list[str]) -> bool:
    """True when a concept carries a `seed`/`example` tag (shipped demo)."""
    return any(t.split("/")[0].strip().lower() in _SEED_EXAMPLE_TAGS for t in tags)


def load_concept(path: Path) -> Concept:
    """Parse one concept note into a Concept dataclass."""
    block, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    fields = _parse_frontmatter(block)
    raw_sources = fields.get("sources")
    sources: list[object] = raw_sources if isinstance(raw_sources, list) else []
    return Concept(
        path=path,
        stem=path.stem,
        note_type=str(fields.get("type", "")).strip().strip("\"'"),
        tags=[t.strip() for t in _as_str_list(fields.get("tags"))],
        related=_as_str_list(fields.get("related_concept")),
        contributors=_as_str_list(fields.get("contributors")),
        parent_playbook=_as_str_list(fields.get("parent_playbook")),
        source_concepts=_as_str_list(fields.get("source_concepts")),
        sources=sources,
        last_verified=_parse_iso_date(fields.get("last_verified")),
        ttl_days=_parse_int(fields.get("ttl_days")),
        body=body,
    )


def load_concepts(concepts_dir: Path) -> list[Concept]:
    """Load every non-seed concept note from `concepts_dir` (sorted)."""
    concepts: list[Concept] = []
    if not concepts_dir.exists():
        return concepts
    for path in sorted(concepts_dir.glob("*.md")):
        concept = load_concept(path)
        if _is_seed_or_example(concept.tags):
            continue
        concepts.append(concept)
    return concepts


def _fm_str(fields: dict[str, object], key: str) -> str:
    """Read a scalar frontmatter field as a trimmed, unquoted string ("" if absent)."""
    return str(fields.get(key, "")).strip().strip("\"'")


def load_author(path: Path) -> Author:
    """Parse one author node (`type: author`) into an Author dataclass."""
    block, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    fields = _parse_frontmatter(block)
    return Author(
        path=path,
        stem=path.stem,
        note_type=_fm_str(fields, "type"),
        title=_fm_str(fields, "title"),
        identity_key=_fm_str(fields, "identity_key"),
        identifier=_fm_str(fields, "identifier"),
        profile_url=_fm_str(fields, "profile_url"),
        tags=[t.strip() for t in _as_str_list(fields.get("tags"))],
        related=_as_str_list(fields.get("related_concept")),
        created=_fm_str(fields, "created"),
        last_updated=_fm_str(fields, "last_updated"),
        body=body,
    )


def load_authors(authors_dir: Path) -> list[Author]:
    """Load every non-seed author node from `authors_dir` (sorted by stem)."""
    authors: list[Author] = []
    if not authors_dir.exists():
        return authors
    for path in sorted(authors_dir.glob("*.md")):
        author = load_author(path)
        if _is_seed_or_example(author.tags):
            continue
        authors.append(author)
    return authors


def load_notes_by_type(note_dir: Path, note_type: str) -> list[Concept]:
    """Load non-seed markdown notes from a vault folder matching `type:`."""
    notes: list[Concept] = []
    if not note_dir.exists():
        return notes
    for path in sorted(note_dir.glob("*.md")):
        note = load_concept(path)
        if note.note_type != note_type:
            continue
        if _is_seed_or_example(note.tags):
            continue
        notes.append(note)
    return notes
