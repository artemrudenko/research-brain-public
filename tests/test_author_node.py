"""
test_author_node.py — offline tests for the author-node frontmatter model
(Stage 9, slice 1). An author node is a first-class vault entity living at
`brain/authors/<slug>.md` with `type: author` (design 2026-07-22, variant B /
model alpha). These tests cover ONLY the typed frontmatter reader
(`Author` + `load_author`/`load_authors`); the hygiene wiring lives in
`test_validate_brain.py`.
"""
from pathlib import Path

from scripts.hygiene.load import load_author, load_authors
from scripts.hygiene.model import Author


def _author_md(
    *,
    title: str = "Ada Lovelace",
    identity_key: str = "orcid:0000-0002-1825-0097",
    identifier: str | None = "0000-0002-1825-0097",
    profile_url: str | None = "https://orcid.org/0000-0002-1825-0097",
    tags: list[str] | None = None,
    body: str = "First programmer.",
) -> str:
    """Build an author note's markdown (Q1 frontmatter shape)."""
    lines = ["---", f"title: {title}", "type: author", f"identity_key: {identity_key}"]
    if identifier is not None:
        lines.append(f"identifier: {identifier}")
    if profile_url is not None:
        lines.append(f"profile_url: {profile_url}")
    lines.append("tags: [" + ", ".join(tags or ["author"]) + "]")
    lines.append("created: 2026-07-22")
    lines.append("last_updated: 2026-07-22")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(body)
    return "\n".join(lines) + "\n"


def _write_author(vault: Path, stem: str, text: str) -> Path:
    note_dir = vault / "brain" / "authors"
    note_dir.mkdir(parents=True, exist_ok=True)
    path = note_dir / f"{stem}.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_author_parses_full_frontmatter(tmp_path: Path) -> None:
    """Every Q1 field is read into the typed model."""
    path = _write_author(tmp_path, "ada-lovelace", _author_md())
    author = load_author(path)

    assert isinstance(author, Author)
    assert author.stem == "ada-lovelace"
    assert author.note_type == "author"
    assert author.title == "Ada Lovelace"
    assert author.identity_key == "orcid:0000-0002-1825-0097"
    assert author.identifier == "0000-0002-1825-0097"
    assert author.profile_url == "https://orcid.org/0000-0002-1825-0097"
    assert author.tags == ["author"]
    assert author.created == "2026-07-22"
    assert author.last_updated == "2026-07-22"
    assert "First programmer." in author.body


def test_load_author_tolerates_missing_optional_fields(tmp_path: Path) -> None:
    """identifier/profile_url are unknown-when-absent, not a parse error."""
    path = _write_author(
        tmp_path,
        "jane-doe",
        _author_md(title="Jane Doe", identity_key="name:jane-doe",
                   identifier=None, profile_url=None),
    )
    author = load_author(path)

    assert author.identity_key == "name:jane-doe"
    assert author.identifier == ""
    assert author.profile_url == ""


def test_load_authors_loads_sorted_and_skips_seed(tmp_path: Path) -> None:
    """load_authors returns non-seed nodes, sorted by stem."""
    _write_author(tmp_path, "zeta", _author_md(title="Zeta", identity_key="name:zeta"))
    _write_author(tmp_path, "alpha", _author_md(title="Alpha", identity_key="name:alpha"))
    _write_author(
        tmp_path,
        "demo",
        _author_md(title="Demo", identity_key="name:demo", tags=["author", "seed"]),
    )

    authors = load_authors(tmp_path / "brain" / "authors")

    assert [a.stem for a in authors] == ["alpha", "zeta"]


def test_load_authors_missing_dir_is_empty(tmp_path: Path) -> None:
    """A vault with no authors/ dir yields an empty roster, never an error."""
    assert load_authors(tmp_path / "brain" / "authors") == []
