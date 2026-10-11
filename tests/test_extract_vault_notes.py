"""Tests for deterministic lesson/playbook extraction from existing vault notes."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts import build_digest as bd
from scripts import extract_vault_notes as evn
from scripts import validate_brain as vb

TODAY = date(2026, 6, 15)


def _concept_note() -> str:
    return (
        "---\n"
        "schema_version: 1\n"
        "title: Runtime Governance\n"
        "type: concept\n"
        "tags: [ai/agents, ai]\n"
        "created: 2026-06-01\n"
        "last_updated: 2026-06-14\n"
        "related_concept:\n"
        "  - \"[[concepts/agent-risk]]\"\n"
        "sources:\n"
        "  - url: \"https://example.com/runtime\"\n"
        "    archive: pipeline/2-curated/ai/runtime.md\n"
        "    date: 2026-06-13\n"
        "    tier: high\n"
        "---\n\n"
        "# Runtime Governance\n\n"
        "## What it is\n\n"
        "A way to control agent behavior at runtime.\n\n"
        "## Lessons\n\n"
        "- Cache policy must be explicit when agents call tools repeatedly.\n"
        "- Human review should focus on irreversible actions first.\n\n"
        "## Playbook: Runtime review loop\n\n"
        "Use this when an agent workflow can make external changes.\n\n"
        "1. List every external action the agent can take.\n"
        "2. Put irreversible actions behind review.\n"
        "3. Record the review outcome back in the concept.\n"
    )


def _make_vault(tmp_path: Path) -> Path:
    (tmp_path / "brain" / "concepts").mkdir(parents=True)
    (tmp_path / "brain" / "lessons").mkdir(parents=True)
    (tmp_path / "brain" / "playbooks").mkdir(parents=True)
    (tmp_path / "pipeline" / "1-incoming").mkdir(parents=True)
    (tmp_path / "pipeline" / "3-synthesis").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "schedule.yaml").write_text(
        "digest:\n  lookback_days: 7\n", encoding="utf-8"
    )
    (tmp_path / "config" / "tags.yaml").write_text(
        "domains:\n  ai:\n    - agents\nsynonyms: {}\npending: []\n",
        encoding="utf-8",
    )
    (tmp_path / "brain" / "INDEX.md").write_text(
        "- [[concepts/runtime-governance]]\n"
        "- [[concepts/agent-risk]]\n",
        encoding="utf-8",
    )
    (tmp_path / "brain" / "concepts" / "agent-risk.md").write_text(
        "---\ntype: concept\ntags: [ai]\nsources:\n  - url: https://example.com/risk\n---\n\n"
        "# Agent Risk\n\n[[concepts/runtime-governance]]\n",
        encoding="utf-8",
    )
    (tmp_path / "brain" / "concepts" / "runtime-governance.md").write_text(
        _concept_note(), encoding="utf-8"
    )
    return tmp_path


def test_extracts_lessons_and_playbook_from_explicit_concept_sections(tmp_path: Path) -> None:
    root = _make_vault(tmp_path)

    result = evn.extract_vault_notes(root=root, today=TODAY)

    assert result.lessons_written == 2
    assert result.playbooks_written == 1
    lessons = sorted((root / "brain" / "lessons").glob("*.md"))
    playbooks = sorted((root / "brain" / "playbooks").glob("*.md"))
    assert len(lessons) == 2
    assert len(playbooks) == 1

    lesson_text = lessons[0].read_text(encoding="utf-8")
    assert "schema_version: 1" in lesson_text
    assert "type: lesson" in lesson_text
    assert "source: brain/concepts/runtime-governance.md" in lesson_text
    assert "url: \"https://example.com/runtime\"" in lesson_text
    # related_concept must be a QUOTED block-list item (like the playbook renderer) —
    # an unquoted inline `[[...]]` parses as a nested list and corrupts the link property.
    assert 'related_concept:\n  - "[[concepts/runtime-governance]]"' in lesson_text
    from scripts.fm import parse_frontmatter, split_frontmatter

    block, _ = split_frontmatter(lesson_text)
    assert parse_frontmatter(block)["related_concept"] == ["[[concepts/runtime-governance]]"]
    assert "- **Fact.** " in lesson_text

    playbook_text = playbooks[0].read_text(encoding="utf-8")
    assert "type: playbook" in playbook_text
    assert "status: draft" in playbook_text
    assert "source_concepts:" in playbook_text
    assert "  - brain/concepts/runtime-governance.md" in playbook_text
    assert "sources:" in playbook_text
    assert "archive: pipeline/2-curated/ai/runtime.md" in playbook_text
    assert "## Steps" in playbook_text
    assert "1. List every external action the agent can take." in playbook_text


def test_long_fact_title_clips_at_a_word_boundary_with_ellipsis() -> None:
    # The old hard `[:96]` cut produced mid-word titles like "…context disc"
    # (bit the live 2026-07-13 seeding). A clipped title must end on a whole
    # word plus an ellipsis, and stay within the budget.
    fact = (
        "Production reliability of AI coding agents is an architecture problem "
        "— guardrails, context discipline, and tight validation loops — not a "
        "bigger-model problem. Source: [arXiv](https://example.com) — 2026-06-19."
    )
    title = evn._title_from_fact(fact)
    assert len(title) <= 96
    assert title.endswith("…")
    body = title.rstrip("…").rstrip()
    # Every word in the clipped title is a whole word of the source sentence.
    assert body.split()[-1] in fact.split(), f"mid-word clip: {body[-20:]!r}"
    assert "context disc" not in title  # the exact live artifact


def test_short_fact_title_is_unclipped_and_has_no_ellipsis() -> None:
    fact = "Lists beat prose on extraction accuracy by 43%."
    title = evn._title_from_fact(fact)
    assert title == "Lists beat prose on extraction accuracy by 43%"
    assert "…" not in title


def test_title_does_not_split_inside_vs_abbreviation() -> None:
    # The live 2026-07-13 artifact: the sentence split fired at the period in
    # '"X vs. Y"' and shipped the broken frontmatter title '…"X vs'.
    fact = (
        'Title patterns are engine-specific: "What is X" wins AI Overviews/Gemini, '
        '"X vs. Y" wins ChatGPT/SearchGPT (comparison content at a 95% citation rate), '
        '"How to X" wins AI Mode/Perplexity. Source: HubSpot — 2026-06-20.'
    )
    title = evn._title_from_fact(fact)
    assert not title.rstrip("…").endswith("X vs")
    assert '"X vs. Y" wins' in title


def test_title_does_not_split_after_eg_abbreviation() -> None:
    fact = "Engines reward explicit comparisons, e.g. criteria tables beat prose. Source: X."
    assert evn._title_from_fact(fact) == (
        "Engines reward explicit comparisons, e.g. criteria tables beat prose"
    )


def test_title_still_splits_after_a_word_merely_ending_in_vs() -> None:
    # "Jarvis." ends with the letters "vs." but IS a sentence end — the
    # abbreviation guard must be word-bounded, not a bare suffix match.
    fact = "The tool beats Jarvis. A second sentence follows here."
    assert evn._title_from_fact(fact) == "The tool beats Jarvis"


def test_title_does_not_split_after_et_al_citation() -> None:
    # Research facts routinely cite "Wei et al. showed …" — "al." is a
    # citation abbreviation, not a sentence end.
    fact = "Wei et al. showed chain-of-thought emerges only at scale. Source: arXiv."
    assert evn._title_from_fact(fact) == (
        "Wei et al. showed chain-of-thought emerges only at scale"
    )


def test_title_does_not_split_after_other_common_abbreviations() -> None:
    # Regression pins for the rest of the guarded abbreviation set.
    cases = {
        "Latency targets, i.e. p95 under two seconds, gate the rollout.": (
            "Latency targets, i.e. p95 under two seconds, gate the rollout"
        ),
        "Guardrails, validators, etc. matter more than raw model size.": (
            "Guardrails, validators, etc. matter more than raw model size"
        ),
        "Costs shrank tenfold, cf. the 2025 inference pricing surveys.": (
            "Costs shrank tenfold, cf. the 2025 inference pricing surveys"
        ),
    }
    for fact, expected in cases.items():
        assert evn._title_from_fact(fact) == expected, f"fact: {fact!r}"


def test_extraction_is_additive_and_idempotent(tmp_path: Path) -> None:
    root = _make_vault(tmp_path)

    first = evn.extract_vault_notes(root=root, today=TODAY)
    second = evn.extract_vault_notes(root=root, today=TODAY)

    assert first.lessons_written == 2
    assert first.playbooks_written == 1
    assert second.lessons_written == 0
    assert second.playbooks_written == 0
    assert len(list((root / "brain" / "lessons").glob("*.md"))) == 2
    assert len(list((root / "brain" / "playbooks").glob("*.md"))) == 1


def test_same_slug_candidates_all_persist(tmp_path: Path) -> None:
    """Two candidates whose titles slugify identically must BOTH become notes.

    Regression: the second same-slug candidate hit the `dest.exists()`
    idempotency check and was silently dropped — permanently, since every
    rerun re-skipped the same name.
    """
    root = _make_vault(tmp_path)
    (root / "brain" / "concepts" / "runtime-governance.md").write_text(
        _concept_note().replace(
            "- Cache policy must be explicit when agents call tools repeatedly.\n"
            "- Human review should focus on irreversible actions first.\n",
            "- Retry backoff must be bounded. Detail alpha applies here.\n"
            "- Retry backoff MUST be bounded! Detail beta applies here.\n",
        )
        + (
            "\n## Playbook: Runtime Review Loop!\n\n"
            "Use this for the second review pass.\n\n"
            "1. Do the second pass.\n"
        ),
        encoding="utf-8",
    )

    result = evn.extract_vault_notes(root=root, today=TODAY)

    assert result.lessons_written == 2
    assert result.playbooks_written == 2
    lesson_texts = [
        path.read_text(encoding="utf-8")
        for path in sorted((root / "brain" / "lessons").glob("*.md"))
    ]
    assert len(lesson_texts) == 2
    assert any("Detail alpha" in text for text in lesson_texts)
    assert any("Detail beta" in text for text in lesson_texts)
    assert len(sorted((root / "brain" / "playbooks").glob("*.md"))) == 2

    # Disambiguated names are deterministic, so a rerun skips every one of them.
    again = evn.extract_vault_notes(root=root, today=TODAY)
    assert again.lessons_written == 0
    assert again.playbooks_written == 0
    assert again.lessons_skipped == 2
    assert again.playbooks_skipped == 2


def test_inserted_same_slug_candidate_is_extracted_not_swallowed(tmp_path: Path) -> None:
    """Idempotency must key on candidate CONTENT, not on positional filenames.

    A concept re-research routinely rewrites Lessons sections. If a new
    same-slug bullet lands ABOVE previously extracted ones, positional -2/-3
    renumbering would make the new bullet hit an existing file (silently
    dropped — the original bug resurfacing) and re-extract an old bullet as a
    duplicate under the shifted name.
    """
    root = _make_vault(tmp_path)
    concept = root / "brain" / "concepts" / "runtime-governance.md"
    base = _concept_note().replace(
        "- Cache policy must be explicit when agents call tools repeatedly.\n"
        "- Human review should focus on irreversible actions first.\n",
        "- Retry backoff must be bounded. Detail alpha applies here.\n"
        "- Retry backoff MUST be bounded! Detail beta applies here.\n",
    )
    concept.write_text(base, encoding="utf-8")
    first = evn.extract_vault_notes(root=root, today=TODAY)
    assert first.lessons_written == 2

    # Re-research inserts a NEW same-slug bullet ABOVE the existing ones.
    concept.write_text(
        base.replace(
            "- Retry backoff must be bounded. Detail alpha applies here.\n",
            "- Retry Backoff must be BOUNDED? Detail gamma applies here.\n"
            "- Retry backoff must be bounded. Detail alpha applies here.\n",
        ),
        encoding="utf-8",
    )
    second = evn.extract_vault_notes(root=root, today=TODAY)

    assert second.lessons_written == 1  # the NEW bullet, nothing else
    assert second.lessons_skipped == 2  # alpha and beta already extracted
    texts = [
        path.read_text(encoding="utf-8")
        for path in (root / "brain" / "lessons").glob("*.md")
    ]
    assert len(texts) == 3
    joined = "\n".join(texts)
    assert joined.count("Detail alpha") == 1
    assert joined.count("Detail beta") == 1
    assert joined.count("Detail gamma") == 1

    third = evn.extract_vault_notes(root=root, today=TODAY)
    assert third.lessons_written == 0
    assert third.lessons_skipped == 3


def test_same_slug_dry_run_counts_all_candidates(tmp_path: Path) -> None:
    """Dry-run must report the same per-candidate counts as a real run."""
    root = _make_vault(tmp_path)
    (root / "brain" / "concepts" / "runtime-governance.md").write_text(
        _concept_note().replace(
            "- Cache policy must be explicit when agents call tools repeatedly.\n"
            "- Human review should focus on irreversible actions first.\n",
            "- Retry backoff must be bounded. Detail alpha applies here.\n"
            "- Retry backoff MUST be bounded! Detail beta applies here.\n",
        ),
        encoding="utf-8",
    )

    result = evn.extract_vault_notes(root=root, today=TODAY, dry_run=True)

    assert result.lessons_written == 2
    assert len(result.lesson_paths) == len(set(result.lesson_paths)) == 2
    assert list((root / "brain" / "lessons").glob("*.md")) == []


def test_extracts_playbook_steps_from_nested_steps_heading(tmp_path: Path) -> None:
    root = _make_vault(tmp_path)
    concept_path = root / "brain" / "concepts" / "runtime-governance.md"
    concept_path.write_text(
        _concept_note().replace(
            "1. List every external action the agent can take.\n"
            "2. Put irreversible actions behind review.\n"
            "3. Record the review outcome back in the concept.\n",
            "### Steps\n\n"
            "1. List every external action the agent can take.\n"
            "2. Put irreversible actions behind review.\n"
            "3. Record the review outcome back in the concept.\n",
        ),
        encoding="utf-8",
    )

    result = evn.extract_vault_notes(root=root, today=TODAY)

    assert result.playbooks_written == 1
    playbook_text = next((root / "brain" / "playbooks").glob("*.md")).read_text(
        encoding="utf-8"
    )
    assert "1. List every external action the agent can take." in playbook_text
    assert "2. Put irreversible actions behind review." in playbook_text


def test_generated_notes_are_visible_to_digest_and_hygiene_clean(tmp_path: Path) -> None:
    root = _make_vault(tmp_path)
    evn.extract_vault_notes(root=root, today=TODAY)

    data = bd.gather(root, today=TODAY, lookback_days=7)
    health = vb.validate_brain(root, today=TODAY)

    assert sorted(lesson.title for lesson in data.lessons) == [
        "Cache policy must be explicit when agents call tools repeatedly",
        "Human review should focus on irreversible actions first",
    ]
    assert [playbook.title for playbook in data.playbooks] == ["Runtime review loop"]
    assert [warning for warning in health.warnings if warning.kind == "orphan"] == []


def test_cli_reports_created_counts(tmp_path: Path, capsys) -> None:
    root = _make_vault(tmp_path)

    rc = evn.main(["--root", str(root), "--today", TODAY.isoformat()])

    captured = capsys.readouterr()
    assert rc == 0
    assert "lessons: 2 written" in captured.out
    assert "playbooks: 1 written" in captured.out


def test_long_lesson_title_truncates_at_a_word_boundary(tmp_path: Path) -> None:
    """A >96-char fact sentence must not clip its last word mid-way.

    Regression: the hard `[:96]` cut turned "… and harness errors" into
    "… and harness error" — a different, misleading word — in the lesson's
    title, filename, and every digest that later surfaced it.
    """
    root = _make_vault(tmp_path)
    fact = (
        "Agent failure modes split into three classes — underspecification, "
        "capability, and harness errors — and each class takes a different "
        "mitigation (command classifier, retry caps, deterministic guardrails)."
    )
    (root / "brain" / "concepts" / "runtime-governance.md").write_text(
        _concept_note().replace(
            "- Cache policy must be explicit when agents call tools repeatedly.\n"
            "- Human review should focus on irreversible actions first.\n",
            f"- {fact}\n",
        ),
        encoding="utf-8",
    )

    result = evn.extract_vault_notes(root=root, today=TODAY)

    assert result.lessons_written == 1
    lesson_text = next((root / "brain" / "lessons").glob("*.md")).read_text(
        encoding="utf-8"
    )
    from scripts.fm import parse_frontmatter, split_frontmatter

    block, _ = split_frontmatter(lesson_text)
    title = str(parse_frontmatter(block)["title"])
    assert "harness error" not in title  # the clipped-word artifact
    assert title.endswith("harness…")  # backs off to the last whole word, marks elision
    assert len(title) <= 96  # the title budget, ellipsis included
