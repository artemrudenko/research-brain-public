"""Tests for scripts/concept_manage.py — user-facing concept vault management.

The synthesis pipeline CREATEs and UPDATEs concepts automatically, but there is
no user-facing way to *browse*, *soft-delete*, or *restore* a concept by hand.
This module is the deterministic backend behind the `concept-manage` skill
(`/concept list | archive | restore`):

  - list      — enumerate concepts (title, tags, source count, freshness)
  - backlinks — which live concepts link TO a given concept (orphaning guard)
  - archive   — SOFT-delete: move out of the vault, leave a restorable marker,
                report inbound backlinks (the project never hard-deletes a
                concept, so links never silently break — CONVENTIONS §13)
  - restore   — move an archived concept back into the live vault

The wizard (`/concept new`) and `/concept update` are skill-orchestration over
the existing research chain, not code — they are not exercised here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import concept_manage as cm

# A minimal but realistic concept note. `{stem}` / `{title}` / `{tags}` /
# `{related}` are filled per-fixture so tests can wire a small graph.
_CONCEPT_TMPL = """\
---
title: "{title}"
type: concept
tags: [{tags}]
created: 2026-06-15
last_updated: 2026-06-20
related_concept:
{related}
sources:
  - url: "https://example.com/{stem}"
    archive: pipeline/0-archive/2026-06/x/{stem}.md
    date: 2026-06-15
    tier: high
---

# {title}

## Key facts

- A durable fact about {title}. Source: https://example.com/{stem}

## Change log

| Date | What changed | Trigger |
|---|---|---|
| 2026-06-15 | Created note | Initial synthesis |
"""


def _write_concept(
    concepts_dir: Path,
    stem: str,
    *,
    title: str | None = None,
    tags: str = "pkm/notes",
    related: list[str] | None = None,
) -> Path:
    """Write one concept .md into `concepts_dir`; return its path."""
    related_block = "\n".join(f'  - "[[concepts/{r}]]"' for r in (related or []))
    if not related_block:
        related_block = "  []"
    path = concepts_dir / f"{stem}.md"
    path.write_text(
        _CONCEPT_TMPL.format(
            stem=stem,
            title=title or stem.replace("-", " ").title(),
            tags=tags,
            related=related_block,
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    """A temp project root with a populated brain/concepts/ tree.

    Graph: gradient-descent <- backprop (backprop links to gradient-descent),
    plus a standalone `transformers` and a seed/example note.
    """
    concepts = tmp_path / "brain" / "concepts"
    concepts.mkdir(parents=True)
    _write_concept(concepts, "gradient-descent", tags="ml/training")
    _write_concept(
        concepts, "backprop", tags="ml/training", related=["gradient-descent"]
    )
    _write_concept(concepts, "transformers", tags="ml/architecture")
    _write_concept(concepts, "atomic-notes", tags="seed, example, pkm/notes")
    return tmp_path


# ── list ─────────────────────────────────────────────────────────────────────


def test_list_returns_live_concepts_excluding_seed(brain: Path) -> None:
    stems = {c.stem for c in cm.list_concepts(brain)}
    assert stems == {"gradient-descent", "backprop", "transformers"}


def test_list_can_include_seed(brain: Path) -> None:
    stems = {c.stem for c in cm.list_concepts(brain, include_seed=True)}
    assert "atomic-notes" in stems


def test_list_carries_title_tags_and_source_count(brain: Path) -> None:
    by_stem = {c.stem: c for c in cm.list_concepts(brain)}
    gd = by_stem["gradient-descent"]
    assert gd.title == "Gradient Descent"
    assert gd.tags == ["ml/training"]
    assert gd.sources == 1
    assert gd.last_updated == "2026-06-20"
    assert gd.archived is False


def test_list_filters_by_tag_domain_or_pair(brain: Path) -> None:
    # Domain-level filter matches both ml/* concepts but not the pair-mismatch.
    arch = {c.stem for c in cm.list_concepts(brain, tag="ml/architecture")}
    assert arch == {"transformers"}
    training = {c.stem for c in cm.list_concepts(brain, tag="ml")}
    assert training == {"gradient-descent", "backprop", "transformers"}


def test_list_is_sorted_by_stem(brain: Path) -> None:
    stems = [c.stem for c in cm.list_concepts(brain)]
    assert stems == sorted(stems)


# ── backlinks ─────────────────────────────────────────────────────────────────


def test_backlinks_finds_inbound_links(brain: Path) -> None:
    # backprop -> gradient-descent, so gradient-descent has one backlink.
    assert cm.find_backlinks(brain, "gradient-descent") == ["backprop"]


def test_backlinks_empty_when_unreferenced(brain: Path) -> None:
    assert cm.find_backlinks(brain, "transformers") == []


def test_backlinks_excludes_self(brain: Path) -> None:
    assert "gradient-descent" not in cm.find_backlinks(brain, "gradient-descent")


# ── archive (soft-delete) ─────────────────────────────────────────────────────


def test_archive_moves_file_out_of_live_vault(brain: Path) -> None:
    result = cm.archive_concept(brain, "transformers", today="2026-06-28")
    assert not (brain / "brain" / "concepts" / "transformers.md").exists()
    assert result.dest.exists()
    assert result.dest == brain / "brain" / ".archive" / "concepts" / "transformers.md"


def test_archive_leaves_restorable_marker_and_reason(brain: Path) -> None:
    result = cm.archive_concept(
        brain, "transformers", reason="superseded", today="2026-06-28"
    )
    text = result.dest.read_text(encoding="utf-8")
    assert cm.ARCHIVE_SENTINEL_OPEN in text
    assert cm.ARCHIVE_SENTINEL_CLOSE in text
    assert "2026-06-28" in text
    assert "superseded" in text
    # The original body survives the move.
    assert "## Key facts" in text


def test_archive_reports_backlinks_that_would_break(brain: Path) -> None:
    result = cm.archive_concept(brain, "gradient-descent", today="2026-06-28")
    assert result.backlinks == ["backprop"]


def test_archived_concept_hidden_from_default_list_but_shown_with_flag(
    brain: Path,
) -> None:
    cm.archive_concept(brain, "transformers", today="2026-06-28")
    live = {c.stem for c in cm.list_concepts(brain)}
    assert "transformers" not in live
    with_arch = {
        c.stem: c for c in cm.list_concepts(brain, include_archived=True)
    }
    assert with_arch["transformers"].archived is True


def test_archive_missing_concept_raises(brain: Path) -> None:
    with pytest.raises(FileNotFoundError):
        cm.archive_concept(brain, "nope", today="2026-06-28")


def test_archive_already_archived_raises(brain: Path) -> None:
    cm.archive_concept(brain, "transformers", today="2026-06-28")
    with pytest.raises(ValueError):
        cm.archive_concept(brain, "transformers", today="2026-06-28")


# ── restore ───────────────────────────────────────────────────────────────────


def test_restore_round_trips_back_into_live_vault(brain: Path) -> None:
    cm.archive_concept(brain, "transformers", today="2026-06-28")
    restored = cm.restore_concept(brain, "transformers", today="2026-06-29")
    assert restored == brain / "brain" / "concepts" / "transformers.md"
    assert restored.exists()
    assert not (
        brain / "brain" / ".archive" / "concepts" / "transformers.md"
    ).exists()
    assert "transformers" in {c.stem for c in cm.list_concepts(brain)}


def test_restore_strips_archive_marker_keeps_body(brain: Path) -> None:
    cm.archive_concept(brain, "transformers", today="2026-06-28")
    restored = cm.restore_concept(brain, "transformers", today="2026-06-29")
    text = restored.read_text(encoding="utf-8")
    assert cm.ARCHIVE_SENTINEL_OPEN not in text
    assert cm.ARCHIVE_SENTINEL_CLOSE not in text
    assert "## Key facts" in text


def test_restore_missing_archive_raises(brain: Path) -> None:
    with pytest.raises(FileNotFoundError):
        cm.restore_concept(brain, "nope", today="2026-06-29")


def test_restore_refuses_to_clobber_live_concept(brain: Path) -> None:
    cm.archive_concept(brain, "transformers", today="2026-06-28")
    # A new live concept claims the same stem before restore.
    _write_concept(brain / "brain" / "concepts", "transformers", tags="ml/x")
    with pytest.raises(ValueError):
        cm.restore_concept(brain, "transformers", today="2026-06-29")


# ── CLI ────────────────────────────────────────────────────────────────────────


def test_cli_list_json(brain: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json

    rc = cm.main(["list", "--root", str(brain), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    stems = {c["stem"] for c in payload["concepts"]}
    assert stems == {"gradient-descent", "backprop", "transformers"}


def test_cli_archive_then_restore(
    brain: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cm.main(
        ["archive", "transformers", "--root", str(brain), "--today", "2026-06-28"]
    )
    assert rc == 0
    assert not (brain / "brain" / "concepts" / "transformers.md").exists()

    rc = cm.main(
        ["restore", "transformers", "--root", str(brain), "--today", "2026-06-29"]
    )
    assert rc == 0
    assert (brain / "brain" / "concepts" / "transformers.md").exists()


def test_cli_archive_reports_backlinks(
    brain: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cm.main(
        ["archive", "gradient-descent", "--root", str(brain), "--today", "2026-06-28"]
    )
    assert rc == 0
    assert "backprop" in capsys.readouterr().out


def test_cli_backlinks(brain: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cm.main(["backlinks", "gradient-descent", "--root", str(brain)])
    assert rc == 0
    assert "backprop" in capsys.readouterr().out


def test_cli_missing_concept_exits_nonzero(
    brain: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cm.main(["archive", "nope", "--root", str(brain), "--today", "2026-06-28"])
    assert rc != 0
