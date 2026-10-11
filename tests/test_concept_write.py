"""Tests for scripts/concept_write.py — the atomic concept-file writer.

`wiki-ingest` writes concept files into `brain/concepts/` as agent-authored
markdown. A plain write can be interrupted mid-stream, leaving a truncated
`brain/concepts/x.md` on disk. This module provides an atomic write path (temp
sibling + os.replace, temp cleaned up on failure) the skill calls instead, so a
crash can never leave a partial concept file. Mirrors the atomic-write pattern
in scripts/inbox.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import concept_write
from scripts import registry as _registry  # atomic-write idiom (and os.replace) lives here now

_BODY = "---\ntitle: Example\ntype: concept\n---\n\nKey fact. Source: x\n"


# ── atomic_write_text ──────────────────────────────────────────────────────────


def test_writes_exact_bytes(tmp_path: Path) -> None:
    dest = tmp_path / "brain" / "concepts" / "example.md"
    concept_write.atomic_write_text(dest, _BODY)
    assert dest.read_text(encoding="utf-8") == _BODY


def test_creates_parent_dirs(tmp_path: Path) -> None:
    dest = tmp_path / "brain" / "concepts" / "deep" / "nested.md"
    assert not dest.parent.exists()
    concept_write.atomic_write_text(dest, _BODY)
    assert dest.read_text(encoding="utf-8") == _BODY


def test_uses_unique_temp_not_shared_fixed_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: the old writer used a fixed `{name}.tmp`, so two concurrent writers
    # to the same path raced on one temp and one died with FileNotFoundError on
    # os.replace. The shared registry writer carries a per-process + random suffix.
    seen: list[str] = []
    real_replace = _registry.os.replace

    def _capture(src: object, dst: object) -> object:
        seen.append(Path(str(src)).name)
        return real_replace(src, dst)

    monkeypatch.setattr(_registry.os, "replace", _capture)
    dest = tmp_path / "brain" / "concepts" / "example.md"
    concept_write.atomic_write_text(dest, _BODY)
    assert seen and seen[0] != "example.md.tmp"  # not the old shared fixed name
    assert seen[0].startswith("example.md.tmp.")  # unique per-process+random
    assert list((tmp_path / "brain" / "concepts").glob("example.md.tmp*")) == []


def test_replace_failure_cleans_temp_and_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a simulated os.replace failure: error propagates, the temp sibling is
    removed, and no partial final file is left behind."""
    dest = tmp_path / "brain" / "concepts" / "example.md"

    def _boom(_src: object, _dst: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(_registry.os, "replace", _boom)

    with pytest.raises(OSError):
        concept_write.atomic_write_text(dest, _BODY)

    assert not dest.exists()
    # No leftover temp sibling.
    assert list(dest.parent.glob("*.tmp")) == []


# ── CLI ────────────────────────────────────────────────────────────────────────


def test_cli_writes_from_body_file(tmp_path: Path) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text(_BODY, encoding="utf-8")
    dest = tmp_path / "brain" / "concepts" / "example.md"

    rc = concept_write.main(
        [str(dest), "--body-file", str(body_file), "--root", str(tmp_path)]
    )

    assert rc == 0
    assert dest.read_text(encoding="utf-8") == _BODY


def test_cli_writes_from_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    dest = tmp_path / "brain" / "concepts" / "example.md"
    monkeypatch.setattr("sys.stdin", io.StringIO(_BODY))

    rc = concept_write.main([str(dest), "--root", str(tmp_path)])

    assert rc == 0
    assert dest.read_text(encoding="utf-8") == _BODY


# ── containment guard ────────────────────────────────────────────────────────────


def test_cli_allows_normal_concept_path(tmp_path: Path) -> None:
    """A plain `brain/concepts/<slug>.md` write under the root still succeeds."""
    body_file = tmp_path / "body.md"
    body_file.write_text(_BODY, encoding="utf-8")
    dest = tmp_path / "brain" / "concepts" / "foo.md"

    rc = concept_write.main(
        [str(dest), "--body-file", str(body_file), "--root", str(tmp_path)]
    )

    assert rc == 0
    assert dest.read_text(encoding="utf-8") == _BODY


def test_cli_rejects_traversal_escape(tmp_path: Path) -> None:
    """A `brain/concepts/../../escape.md` path resolves outside the concepts dir
    and is rejected: non-zero exit, no file written outside the tree."""
    body_file = tmp_path / "body.md"
    body_file.write_text(_BODY, encoding="utf-8")
    dest = tmp_path / "brain" / "concepts" / ".." / ".." / "escape.md"

    rc = concept_write.main(
        [str(dest), "--body-file", str(body_file), "--root", str(tmp_path)]
    )

    assert rc != 0
    assert not (tmp_path / "escape.md").exists()


def test_cli_rejects_absolute_outside_tree(tmp_path: Path) -> None:
    """An absolute path outside the project tree is rejected and writes nothing."""
    body_file = tmp_path / "body.md"
    body_file.write_text(_BODY, encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    dest = outside / "escape.md"

    rc = concept_write.main(
        [str(dest), "--body-file", str(body_file), "--root", str(root)]
    )

    assert rc != 0
    assert not dest.exists()


# ── INDEX.md safety-net append ────────────────────────────────────────────────
# wiki-query navigates ONLY via the brain/INDEX.md MOC (+ wikilinks), so a
# concept the MOC doesn't list is invisible to every vault query — the live
# vault has already drifted this way. The writer idempotently lists what it
# writes; validate_brain keeps flagging drift from other write paths.

_INDEX_SEED = (
    "# Knowledge Vault — Map of Content (MOC)\n\n"
    "## Thematic clusters\n\n"
    "### Cluster A\n\n"
    "- [[existing-concept]] — already here.\n"
)
_H1_BODY = (
    "---\ntitle: Example\ntype: concept\n---\n\n"
    "# Retrieval-Augmented Generation\n\nKey fact. Source: x\n"
)


def _write_concept(
    tmp_path: Path, name: str, *, body: str = _H1_BODY, extra: tuple[str, ...] = ()
) -> tuple[int, Path]:
    body_file = tmp_path / f"{name}.body.md"
    body_file.write_text(body, encoding="utf-8")
    dest = tmp_path / "brain" / "concepts" / f"{name}.md"
    rc = concept_write.main(
        [str(dest), "--body-file", str(body_file), "--root", str(tmp_path), *extra]
    )
    return rc, dest


def _seed_index(tmp_path: Path, text: str = _INDEX_SEED) -> Path:
    index = tmp_path / "brain" / "INDEX.md"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(text, encoding="utf-8")
    return index


def test_index_append_lists_new_concept(tmp_path: Path) -> None:
    index = _seed_index(tmp_path)
    rc, _ = _write_concept(tmp_path, "rag-eval")
    assert rc == 0
    text = index.read_text(encoding="utf-8")
    assert "[[rag-eval]]" in text
    assert "Recently added" in text
    # The concept's H1 becomes the one-line description the MOC asks for.
    assert "Retrieval-Augmented Generation" in text


def test_index_append_is_idempotent(tmp_path: Path) -> None:
    index = _seed_index(tmp_path)
    assert _write_concept(tmp_path, "rag-eval")[0] == 0
    assert _write_concept(tmp_path, "rag-eval")[0] == 0
    text = index.read_text(encoding="utf-8")
    assert text.count("[[rag-eval]]") == 1
    assert text.count("Recently added") == 1


def test_index_untouched_when_stem_listed_as_raw_text(tmp_path: Path) -> None:
    # The hygiene check accepts a raw-stem mention as "listed"; the writer must
    # use the same predicate or the two would fight (append despite no warning).
    index = _seed_index(tmp_path, _INDEX_SEED + "\nSee also rag-eval for grounding.\n")
    before = index.read_text(encoding="utf-8")
    assert _write_concept(tmp_path, "rag-eval")[0] == 0
    assert index.read_text(encoding="utf-8") == before


def test_missing_index_is_permissive_noop(tmp_path: Path) -> None:
    rc, dest = _write_concept(tmp_path, "rag-eval")
    assert rc == 0
    assert dest.exists()
    assert not (tmp_path / "brain" / "INDEX.md").exists()


def test_no_index_flag_opts_out(tmp_path: Path) -> None:
    index = _seed_index(tmp_path)
    assert _write_concept(tmp_path, "rag-eval", extra=("--no-index",))[0] == 0
    assert index.read_text(encoding="utf-8") == _INDEX_SEED


def test_index_entry_lands_inside_recently_added_section(tmp_path: Path) -> None:
    # A human may add clusters BELOW "Recently added"; the entry must land in
    # that section, not leak into whatever section happens to end the file.
    seeded = (
        _INDEX_SEED
        + "\n### Recently added (file into a cluster)\n\n- [[earlier-add]]\n"
        + "\n### Curated later cluster\n\n- [[other-concept]]\n"
    )
    index = _seed_index(tmp_path, seeded)
    assert _write_concept(tmp_path, "rag-eval")[0] == 0
    text = index.read_text(encoding="utf-8")
    assert text.index("[[rag-eval]]") < text.index("### Curated later cluster")
    assert text.count("Recently added") == 1
