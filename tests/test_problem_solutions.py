"""Governed reusable findings: real validation and exact approved save boundaries."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from scripts.problem_solutions.profile import validate_record
from scripts.problem_solutions.workflow import apply_proposal, propose, review_proposal

ARTIFACT = "pipeline/3-synthesis/retry-evidence.md"


def record(**changes: object) -> str:
    meta = dict(
        schema_version=1,
        title="Bounded retry",
        type="concept",
        knowledge_kind="problem_solution",
        content_language="en",
        programming_languages=["python"],
        technologies=["httpx"],
        problem_types=["http-retry"],
        evidence_scope="observed_in_one_context",
        visibility="private",
        tags=["tech", "tech/dev"],
        created=date.today().isoformat(),
        last_updated=date.today().isoformat(),
        related_concept=[],
        sources=[dict(archive=ARTIFACT, date=date.today().isoformat())],
    )
    meta.update(changes)
    sections = {
        "What it is": "Honor the full valid server pause.",
        "Why it matters": "A premature retry can hit the same busy source.",
        "Key facts": f"- Over-budget pauses stop the call. Source: {ARTIFACT}",
        "Problem and symptoms": "A local sleep cap shortened the server pause.",
        "Applicability": "Read requests only; exclude non-idempotent writes.",
        "Solution and alternatives": "Stop instead of shortening a valid wait.",
        "Verification": f"Offline failing/passing regression retained in {ARTIFACT}.",
        "How to apply it": "Recheck the caller's clock and deadline.",
        "Reuse observations": "No second use recorded.",
        "Open questions / gaps": "Persistence across restarts is not checked.",
        "Change history": "[lesson:2026-10-15] Checked local correction.",
    }
    return (
        "---\n"
        + yaml.safe_dump(meta, sort_keys=False)
        + "---\n# Bounded retry\n\n> **Confidence:** medium\n\n"
        + "\n\n".join(f"## {k}\n\n{v}" for k, v in sections.items())
        + "\n"
    )


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    (tmp_path / "brain/concepts").mkdir(parents=True)
    (tmp_path / "brain/INDEX.md").write_text("# Knowledge\n\n- [[existing]]\n")
    (tmp_path / "brain/concepts/existing.md").write_text("---\ntype: concept\n---\n# Existing\n")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/tags.yaml").write_text(
        "domains:\n  tech: [dev]\nsynonyms: {}\npending: []\n"
    )
    return tmp_path


def proposal(vault: Path) -> dict:
    return propose(
        vault,
        "bounded-retry",
        record(),
        {ARTIFACT: "# Evidence\nOffline RED/GREEN; no live claim.\n"},
    )


def test_complete_record_and_legacy_profile_are_valid() -> None:
    assert validate_record(record()) == []
    assert validate_record(record(technologies=None, frameworks=["urllib"])) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"type": "lesson"},
        {"programming_languages": "python"},
        {"programming_languages": ["Python"]},
        {"problem_types": []},
        {"problem_types": ["http retry"]},
        {"evidence_scope": "universally_proven"},
        {"visibility": "public"},
        {"sources": []},
        {"content_language": ""},
        {"last_verified": "2999-01-01"},
        {"schema_version": 99},
        {"evidence_scope": "reused_in_another_context"},
    ],
)
def test_invalid_profile_is_rejected(changes: dict) -> None:
    assert validate_record(record(**changes))


@pytest.mark.parametrize("section", ["Applicability", "Verification", "Reuse observations"])
def test_required_sections_cannot_disappear(section: str) -> None:
    assert validate_record(record().replace(f"## {section}", "### Removed"))


def test_facts_must_reference_declared_sources() -> None:
    assert validate_record(record().replace(f"Source: {ARTIFACT}", "Source: invented.md"))


def test_proposal_is_not_saved_or_indexed_and_requires_exact_approval(vault: Path) -> None:
    p = proposal(vault)
    before = (vault / "brain/INDEX.md").read_bytes()
    assert not (vault / "brain/concepts/bounded-retry.md").exists()
    assert not (vault / ARTIFACT).exists()
    review = review_proposal(vault, p["id"])
    assert "brain/concepts/bounded-retry.md" in review["review"]
    with pytest.raises(ValueError, match="approval"):
        apply_proposal(vault, p["id"], "", "")
    with pytest.raises(ValueError, match="digest"):
        apply_proposal(vault, p["id"], "0" * 64, "owner replied yes")
    assert (vault / "brain/INDEX.md").read_bytes() == before
    saved = apply_proposal(
        vault, p["id"], p["digest"], "owner approved this exact synthetic package"
    )
    assert saved["status"] == "applied"
    assert (vault / "brain/concepts/bounded-retry.md").read_text() == record()
    assert "[[bounded-retry]]" in (vault / "brain/INDEX.md").read_text()
    assert (vault / ARTIFACT).exists()
    assert (
        apply_proposal(vault, p["id"], p["digest"], "owner approved this exact synthetic package")[
            "status"
        ]
        == "already_applied"
    )


def test_changed_base_blocks_every_write(vault: Path) -> None:
    p = proposal(vault)
    (vault / "brain/INDEX.md").write_text("# Concurrent edit\n")
    with pytest.raises(ValueError, match="changed"):
        apply_proposal(vault, p["id"], p["digest"], "explicit owner approval")
    assert not (vault / ARTIFACT).exists()
    assert not (vault / "brain/concepts/bounded-retry.md").exists()


def test_candidate_tampering_invalidates_review_digest(vault: Path) -> None:
    p = proposal(vault)
    path = vault / "pipeline/.learning/proposals" / p["id"] / "proposal.json"
    path.write_text(path.read_text().replace("Read requests only", "Retry writes blindly"))
    with pytest.raises(ValueError, match="digest"):
        apply_proposal(vault, p["id"], p["digest"], "explicit owner approval")
    assert not (vault / ARTIFACT).exists()


@pytest.mark.parametrize("slug", ["../escape", "/outside", "a/b", ".", ""])
def test_unsafe_slugs_rejected(vault: Path, slug: str) -> None:
    with pytest.raises(ValueError):
        propose(vault, slug, record(), {ARTIFACT: "evidence"})


def test_symlink_and_unretained_evidence_rejected(vault: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="evidence"):
        propose(vault, "bounded-retry", record(), {})
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (vault / "pipeline").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        proposal(vault)
    assert list(outside.iterdir()) == []


def test_update_retains_old_base_and_invalid_record_never_applies(vault: Path) -> None:
    old = record().replace("Honor the full valid", "Consider the valid")
    (vault / "brain/concepts/bounded-retry.md").write_text(old)
    p = proposal(vault)
    assert (vault / "brain/concepts/bounded-retry.md").read_text() == old
    apply_proposal(vault, p["id"], p["digest"], "explicit owner approval")
    assert (vault / "brain/concepts/bounded-retry.md").read_text() == record()
    with pytest.raises(ValueError):
        propose(vault, "bad", record(tags=["made/up"]), {ARTIFACT: "evidence"})


def test_legacy_writer_cannot_bypass_profile_approval(vault: Path) -> None:
    from scripts.concept_write import main

    candidate = vault / "candidate.md"
    candidate.write_text(record())
    assert (
        main(
            [
                str(vault / "brain/concepts/bypass.md"),
                "--body-file",
                str(candidate),
                "--root",
                str(vault),
            ]
        )
        == 2
    )
    assert not (vault / "brain/concepts/bypass.md").exists()


def test_partial_save_recovers_only_exact_approved_files(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.problem_solutions import workflow

    p = proposal(vault)
    original = workflow.atomic_write_text
    broken = False

    def interrupted(path, content):
        nonlocal broken
        if path.name == "bounded-retry.md" and not broken:
            broken = True
            raise OSError("simulated crash after evidence write")
        original(path, content)

    monkeypatch.setattr(workflow, "atomic_write_text", interrupted)
    with pytest.raises(OSError):
        apply_proposal(vault, p["id"], p["digest"], "exact synthetic owner approval")
    assert (vault / ARTIFACT).exists()
    assert not (vault / "brain/concepts/bounded-retry.md").exists()
    assert (
        apply_proposal(vault, p["id"], p["digest"], "same exact owner approval")["status"]
        == "applied"
    )


def test_existing_evidence_and_index_are_bound_even_when_unchanged(vault: Path) -> None:
    (vault / ARTIFACT).parent.mkdir(parents=True)
    (vault / ARTIFACT).write_text("retained evidence")
    (vault / "brain/INDEX.md").write_text("# MOC\n- [[bounded-retry]]\n")
    p = propose(vault, "bounded-retry", record(), {})
    (vault / ARTIFACT).write_text("concurrent replacement")
    with pytest.raises(ValueError, match="changed"):
        apply_proposal(vault, p["id"], p["digest"], "owner approval")
    assert not (vault / "brain/concepts/bounded-retry.md").exists()


def test_duplicate_and_unrelated_artifact_are_not_silently_saved(vault: Path) -> None:
    (vault / "brain/concepts/same-mechanism.md").write_text(record())
    with pytest.raises(ValueError, match="duplicate"):
        proposal(vault)
    (vault / "brain/concepts/same-mechanism.md").unlink()
    with pytest.raises(ValueError, match="not declared"):
        propose(
            vault,
            "bounded-retry",
            record(),
            {ARTIFACT: "evidence", "pipeline/3-synthesis/unrelated.md": "unrelated"},
        )


@pytest.mark.parametrize(
    "replacement", ["Source: pipeline/3-synthesis/retry-evidence.md.evil", "Uncited speculation"]
)
def test_citation_prefix_is_not_a_declared_source(replacement: str) -> None:
    assert validate_record(record().replace("Source: " + ARTIFACT, replacement))


def test_cli_prepares_reviews_and_applies_synthetic_package(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from scripts.problem_solution import main

    note = vault / "candidate.md"
    note.write_text(record())
    evidence = vault / "evidence.md"
    evidence.write_text("# Checked evidence\n")
    assert main(["validate", str(note)]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "propose",
                "--root",
                str(vault),
                "--slug",
                "bounded-retry",
                "--body-file",
                str(note),
                "--artifact",
                ARTIFACT,
                str(evidence),
            ]
        )
        == 0
    )
    p = json.loads(capsys.readouterr().out)
    assert main(["review", p["id"], "--root", str(vault)]) == 0
    assert p["digest"] in capsys.readouterr().out
    assert (
        main(
            [
                "apply",
                p["id"],
                "--root",
                str(vault),
                "--approved-digest",
                p["digest"],
                "--approval-reference",
                "direct synthetic approval",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(["validate", str(vault / "brain/concepts/bounded-retry.md"), "--root", str(vault)])
        == 0
    )
    assert (
        main(
            [
                "apply",
                p["id"],
                "--root",
                str(vault),
                "--approved-digest",
                "bad",
                "--approval-reference",
                "yes",
            ]
        )
        == 2
    )


@pytest.mark.parametrize(
    "text",
    [
        "no metadata",
        "---\n[]\n---\n",
        "---\ntype: [\n---\n",
        "---\ntype: concept\ntype: lesson\n---\n",
    ],
)
def test_ambiguous_metadata_is_not_valid(text: str) -> None:
    assert validate_record(text)


def test_hygiene_accepts_retained_project_evidence_and_flags_broken_profile(vault: Path) -> None:
    from scripts.hygiene.checks import check_missing_sources, check_problem_solution, gate_concepts
    from scripts.hygiene.load import load_concept
    from scripts.hygiene.tags import load_tag_registry

    path = vault / "brain/concepts/bounded-retry.md"
    path.write_text(record())
    (vault / ARTIFACT).parent.mkdir(parents=True)
    (vault / ARTIFACT).write_text("# Retained offline evidence\n")
    assert check_missing_sources(load_concept(path)) is None
    assert check_problem_solution(load_concept(path)) == []
    assert gate_concepts([path], load_tag_registry(vault / "config/tags.yaml")) == []
    path.write_text(record().replace("## Applicability", "### Removed"))
    assert any(w.kind == "problem-solution" for w in check_problem_solution(load_concept(path)))
    assert any(
        w.kind == "problem-solution"
        for w in gate_concepts([path], load_tag_registry(vault / "config/tags.yaml"))
    )


def test_profile_findings_appear_in_human_and_digest_health(vault: Path) -> None:
    from scripts.hygiene.model import BrainHealth, Warning
    from scripts.hygiene.report import health_to_dict, render_summary

    health = BrainHealth(1, [Warning("problem-solution", "broken", "missing Applicability")])
    assert "missing Applicability" in render_summary(health, today=date.today())
    assert "1 problem-solution" in health.health_headline
    assert health_to_dict(health)["problem_solution_findings"] == 1


def test_approval_package_cannot_be_applied_to_another_vault(vault: Path, tmp_path: Path) -> None:
    import shutil

    p = proposal(vault)
    other = tmp_path / "other-vault"
    (other / "brain").mkdir(parents=True)
    shutil.copytree(vault / "brain", other / "brain", dirs_exist_ok=True)
    shutil.copytree(vault / "config", other / "config")
    shutil.copytree(vault / "pipeline/.learning/proposals", other / "pipeline/.learning/proposals")
    with pytest.raises(ValueError, match="vault"):
        apply_proposal(other, p["id"], p["digest"], "approval was for the original vault")
    assert not (other / ARTIFACT).exists()
    assert not (other / "brain/concepts/bounded-retry.md").exists()


def test_review_regenerates_from_bound_package_not_a_changed_display_file(vault: Path) -> None:
    p = proposal(vault)
    (vault / p["review_path"]).write_text("Fake review: nothing changes")
    regenerated = review_proposal(vault, p["id"])
    assert "Read requests only" in regenerated["review"]
    assert regenerated["digest"] == p["digest"]


def test_yaml_constructor_cannot_execute_python(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    called = []
    monkeypatch.setattr(os, "system", lambda value: called.append(value))
    assert validate_record('---\ntype: !!python/object/apply:os.system ["untrusted"]\n---\n')
    assert called == []
