"""
test_validate_brain.py — offline tests for the brain-hygiene pass (§13).

Every test builds a self-contained fake vault under a tmp dir (its own
brain/concepts + config/tags.yaml) and drives `validate_brain` with a fixed
`today`, so they are deterministic and never touch the real vault. No network.
"""
from datetime import date
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

from scripts import validate_brain as vb  # noqa: E402

# Fixed "now" so TTL windows are reproducible.
TODAY = date(2026, 6, 15)

# A minimal controlled vocabulary matching config/tags.yaml's shape.
_TAGS_YAML = """\
domains:
  ai:
    - agents
    - rag
  pkm:
    - notes
synonyms:
  machine-learning: ai/ml
  note-taking: pkm/notes
pending:
  - ai/evals
"""


def _concept(
    *,
    title: str,
    tags: list[str],
    related: list[str] | None = None,
    contributors: list[str] | None = None,
    sources: bool = True,
    note_type: str = "concept",
    last_verified: str | None = None,
    ttl_days: int | None = None,
    body: str = "Body text.",
) -> str:
    """Build a concept note's markdown (CONVENTIONS §5.1)."""
    lines = ["---", f"title: {title}", f"type: {note_type}"]
    lines.append("tags: [" + ", ".join(tags) + "]")
    lines.append("created: 2026-01-01")
    lines.append("last_updated: 2026-06-13")
    if related:
        lines.append("related_concept:")
        for ref in related:
            lines.append(f'  - "{ref}"')
    if contributors:
        lines.append("contributors:")
        for ref in contributors:
            lines.append(f'  - "{ref}"')
    if sources:
        lines.append("sources:")
        lines.append('  - url: "https://example.com"')
        lines.append("    tier: high")
    if last_verified is not None:
        lines.append(f"last_verified: {last_verified}")
    if ttl_days is not None:
        lines.append(f"ttl_days: {ttl_days}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(body)
    return "\n".join(lines) + "\n"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """A minimal fake vault: brain/concepts + config/tags.yaml registry."""
    (tmp_path / "brain" / "concepts").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "tags.yaml").write_text(_TAGS_YAML, encoding="utf-8")
    return tmp_path


def _write_concept(vault: Path, stem: str, text: str) -> None:
    (vault / "brain" / "concepts" / f"{stem}.md").write_text(text, encoding="utf-8")


def _write_vault_note(vault: Path, subdir: str, stem: str, text: str) -> None:
    note_dir = vault / "brain" / subdir
    note_dir.mkdir(parents=True, exist_ok=True)
    (note_dir / f"{stem}.md").write_text(text, encoding="utf-8")


def _write_index(vault: Path, stems: list[str]) -> None:
    """Write a minimal brain/INDEX.md MOC listing the given concept stems."""
    lines = ["# MOC", ""] + [f"- [[{stem}]] — one line." for stem in stems]
    (vault / "brain" / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(vault: Path) -> vb.BrainHealth:
    return vb.validate_brain(vault, today=TODAY)


def test_frontmatter_fallback_strips_quotes_on_inline_tags() -> None:
    # The stdlib (no-PyYAML, headless) frontmatter reader must strip quotes from
    # an inline tag list, else quoted tags like ["ai/agents"] carry literal
    # quotes and never match the controlled vocabulary -> headless tag promotion
    # silently miscounts. (Regression guard: a duplicate helper once shadowed the
    # quote-stripping parser.)
    got = vb._parse_frontmatter_fallback('tags: ["ai/agents", "tech/news"]')
    assert got["tags"] == ["ai/agents", "tech/news"]


def test_clean_vault_no_warnings_with_headline(vault: Path) -> None:
    # Two concepts linked to each other, both with sources -> fully healthy.
    _write_concept(
        vault, "atomic-notes",
        _concept(title="Atomic Notes", tags=["pkm/notes"],
                 related=["[[concepts/linking-notes]]"]),
    )
    _write_concept(
        vault, "linking-notes",
        _concept(title="Linking Notes", tags=["pkm/notes"],
                 related=["[[concepts/atomic-notes]]"]),
    )
    health = _run(vault)
    assert health.warnings == []
    assert health.concept_count == 2
    # The headline line is always present and well-formed.
    assert health.headline == (
        "brain health: 2 concepts, 0 orphans, 0 broken links, "
        "0 missing-sources, 0 uncited-facts, 0 stale"
    )
    # The machine-matched `Health:` headline uses the exact prefix the digest
    # builder greps for, with `·`-separated fields (F5).
    assert health.health_headline == (
        "Health: 2 concepts · 0 orphans · 0 broken links · "
        "0 missing-sources · 0 uncited-facts · 0 stale"
    )
    assert health.health_headline.startswith("Health:")
    summary = vb.render_summary(health, today=TODAY)
    assert health.headline in summary
    assert health.health_headline in summary  # both lines land in the report
    assert "healthy" in summary.lower()


def test_orphan_detected(vault: Path) -> None:
    # No related_concept and a tag no other concept shares -> orphan.
    _write_concept(
        vault, "lonely",
        _concept(title="Lonely", tags=["ai/agents"]),
    )
    _write_concept(
        vault, "other",
        _concept(title="Other", tags=["pkm/notes"],
                 related=["[[concepts/lonely-ish]]"]),
    )
    health = _run(vault)
    orphans = [w for w in health.warnings if w.kind == "orphan"]
    assert any(w.concept == "lonely" for w in orphans)
    assert health.orphans >= 1


def test_shared_tag_is_weakly_linked_not_orphan(vault: Path) -> None:
    # W3: two concepts share a tag but neither links -> NOT true orphans, but
    # downgraded to "weakly-linked (tag-only)" because tags aren't graph edges.
    _write_concept(vault, "a", _concept(title="A", tags=["ai/agents"]))
    _write_concept(vault, "b", _concept(title="B", tags=["ai/agents"]))
    health = _run(vault)
    assert health.orphans == 0
    assert health.weakly_linked == 2
    weak = [w for w in health.warnings if w.kind == "weakly-linked"]
    assert {w.concept for w in weak} == {"a", "b"}
    assert all("tag-only" in w.message for w in weak)


def test_true_orphan_despite_shared_tag(vault: Path) -> None:
    # W3: a note with a shared tag but NO link is weakly-linked, while a note
    # with neither a link nor a shared tag is a true orphan — proving a shared
    # tag no longer rescues a note from the orphan check (it only softens it).
    _write_concept(vault, "tagged-1", _concept(title="T1", tags=["ai/agents"]))
    _write_concept(vault, "tagged-2", _concept(title="T2", tags=["ai/agents"]))
    _write_concept(vault, "alone", _concept(title="Alone", tags=["pkm/notes"]))
    health = _run(vault)
    orphans = {w.concept for w in health.warnings if w.kind == "orphan"}
    weak = {w.concept for w in health.warnings if w.kind == "weakly-linked"}
    assert orphans == {"alone"}  # unique tag + no link -> true orphan
    assert weak == {"tagged-1", "tagged-2"}  # shared tag only -> weakly-linked


def test_linked_note_is_not_orphan_or_weak(vault: Path) -> None:
    # A real [[link]] edge clears both ends (backlinks make it bidirectional),
    # even when the linked-to note has no outbound link of its own.
    _write_concept(vault, "src", _concept(title="Src", tags=["ai/agents"],
                                          related=["[[concepts/dst]]"]))
    _write_concept(vault, "dst", _concept(title="Dst", tags=["pkm/notes"]))
    health = _run(vault)
    assert health.orphans == 0
    assert health.weakly_linked == 0


def test_single_root_note_not_flagged_orphan(vault: Path) -> None:
    # Cold-start: a single root note in an otherwise-empty vault is a legitimate
    # cluster seed, not orphan debt -> no orphan/weakly-linked spam.
    _write_concept(vault, "root", _concept(title="Root", tags=["ai/agents"]))
    health = _run(vault)
    assert health.orphans == 0
    assert health.weakly_linked == 0


def test_broken_link_detected(vault: Path) -> None:
    _write_concept(
        vault, "has-broken",
        _concept(title="Has Broken", tags=["ai/agents"],
                 related=["[[concepts/does-not-exist]]"]),
    )
    health = _run(vault)
    broken = [w for w in health.warnings if w.kind == "broken-link"]
    assert len(broken) == 1
    assert "does-not-exist" in broken[0].message


def test_broken_link_in_body_detected(vault: Path) -> None:
    _write_concept(
        vault, "body-link",
        _concept(title="Body Link", tags=["ai/agents"],
                 related=["[[concepts/body-link]]"],  # self-link keeps it non-orphan
                 body="See [[concepts/ghost-note]] for more."),
    )
    health = _run(vault)
    broken = [w for w in health.warnings if w.kind == "broken-link"]
    assert any("ghost-note" in w.message for w in broken)


def test_lesson_without_concept_or_parent_playbook_is_orphan(vault: Path) -> None:
    _write_vault_note(
        vault,
        "lessons",
        "orphan-lesson",
        "---\n"
        "type: lesson\n"
        "tags: [ai/agents]\n"
        "confidence: medium\n"
        "---\n\n"
        "# Orphan lesson\n\n"
        "No related concept or parent playbook.\n",
    )

    health = _run(vault)

    orphans = [w for w in health.warnings if w.kind == "orphan"]
    assert any(w.concept == "orphan-lesson" for w in orphans)
    assert any("related_concept" in w.message for w in orphans)


def test_playbook_without_wiki_connection_is_orphan(vault: Path) -> None:
    _write_vault_note(
        vault,
        "playbooks",
        "orphan-playbook",
        "---\n"
        "type: playbook\n"
        "status: draft\n"
        "tags: [ai/agents]\n"
        "---\n\n"
        "# Orphan playbook\n\n"
        "A method with no vault links.\n",
    )

    health = _run(vault)

    orphans = [w for w in health.warnings if w.kind == "orphan"]
    assert any(w.concept == "orphan-playbook" for w in orphans)
    assert any("playbook" in w.message for w in orphans)


def test_linked_lesson_and_playbook_are_not_orphans(vault: Path) -> None:
    _write_vault_note(
        vault,
        "lessons",
        "linked-lesson",
        "---\n"
        "type: lesson\n"
        "tags: [ai/agents]\n"
        "parent_playbook: [[playbooks/linked-playbook]]\n"
        "confidence: high\n"
        "---\n\n"
        "# Linked lesson\n",
    )
    _write_vault_note(
        vault,
        "playbooks",
        "linked-playbook",
        "---\n"
        "type: playbook\n"
        "status: draft\n"
        "tags: [ai/agents]\n"
        "related_concept:\n"
        "  - \"[[concepts/future-concept]]\"\n"
        "---\n\n"
        "# Linked playbook\n",
    )

    health = _run(vault)

    assert not any(
        w.kind == "orphan" and w.concept in {"linked-lesson", "linked-playbook"}
        for w in health.warnings
    )


def test_missing_sources_detected(vault: Path) -> None:
    _write_concept(
        vault, "no-src",
        _concept(title="No Source", tags=["ai/agents"],
                 related=["[[concepts/no-src]]"], sources=False),
    )
    health = _run(vault)
    missing = [w for w in health.warnings if w.kind == "missing-sources"]
    assert len(missing) == 1
    assert missing[0].concept == "no-src"


def test_tag_synonym_merge_suggested(vault: Path) -> None:
    # `machine-learning` is an alias for `ai/ml` in the registry -> merge.
    _write_concept(
        vault, "ml-note",
        _concept(title="ML Note", tags=["machine-learning", "ai/agents"],
                 related=["[[concepts/ml-note]]"]),
    )
    health = _run(vault)
    tag_msgs = [w.message for w in health.warnings if w.kind == "tag"]
    assert any("merge to 'ai/ml'" in m for m in tag_msgs)


def test_tag_normalization_suggested(vault: Path) -> None:
    # `AI/Agents` (uppercase) folds to the registry's canonical `ai/agents`.
    _write_concept(
        vault, "norm",
        _concept(title="Norm", tags=["AI/Agents"],
                 related=["[[concepts/norm]]"]),
    )
    health = _run(vault)
    tag_msgs = [w.message for w in health.warnings if w.kind == "tag"]
    assert any("normalized to 'ai/agents'" in m for m in tag_msgs)


def test_tag_singularized_when_not_in_vocab(vault: Path) -> None:
    # A tag the registry never saw is singularized (`tech/projects`->`tech/project`).
    _write_concept(
        vault, "sing",
        _concept(title="Sing", tags=["tech/projects"],
                 related=["[[concepts/sing]]"]),
    )
    health = _run(vault)
    tag_msgs = [w.message for w in health.warnings if w.kind == "tag"]
    assert any("normalized to 'tech/project'" in m for m in tag_msgs)


def test_pending_promotion_suggested(vault: Path) -> None:
    # `ai/evals` is pending; used by 3 concepts -> suggest promotion.
    for i in range(3):
        _write_concept(
            vault, f"eval-{i}",
            _concept(title=f"Eval {i}", tags=["ai/evals", "ai/agents"],
                     related=[f"[[concepts/eval-{i}]]"]),
        )
    health = _run(vault)
    tag_msgs = [w.message for w in health.warnings if w.kind == "tag"]
    assert any("promote" in m and "ai/evals" in m for m in tag_msgs)


def test_oneoff_tag_flagged(vault: Path) -> None:
    # A single-use, non-vocabulary nested tag -> fold to domain.
    _write_concept(
        vault, "unique",
        _concept(title="Unique", tags=["ai/quantum-llm"],
                 related=["[[concepts/unique]]"]),
    )
    health = _run(vault)
    tag_msgs = [w.message for w in health.warnings if w.kind == "tag"]
    assert any("one-off tag 'ai/quantum-llm'" in m for m in tag_msgs)


def test_offvocab_tag_flagged(vault: Path) -> None:
    # W2: a domain not in the registry (`crypto/defi`) is off-vocabulary — not in
    # domains, synonyms, or pending -> flag "add to registry or fix".
    _write_concept(
        vault, "offvocab",
        _concept(title="Off Vocab", tags=["crypto/defi", "ai/agents"],
                 related=["[[concepts/offvocab]]"]),
    )
    health = _run(vault)
    tag_msgs = [w.message for w in health.warnings if w.kind == "tag"]
    assert any("off-vocabulary" in m and "crypto/defi" in m for m in tag_msgs)


def test_pending_tag_not_flagged_offvocab(vault: Path) -> None:
    # W2: a tag sitting in the registry's `pending:` quarantine is NOT
    # off-vocabulary (it's a known-quarantined proposal).
    _write_concept(
        vault, "pend",
        _concept(title="Pend", tags=["ai/evals", "ai/agents"],
                 related=["[[concepts/pend]]"]),
    )
    health = _run(vault)
    tag_msgs = [w.message for w in health.warnings if w.kind == "tag"]
    assert not any("off-vocabulary" in m and "ai/evals" in m for m in tag_msgs)


def test_offvocab_check_skipped_without_registry(tmp_path: Path) -> None:
    # W2: with no config/tags.yaml the registry is empty/permissive -> the
    # off-vocabulary check is suppressed (don't flag every tag).
    (tmp_path / "brain" / "concepts").mkdir(parents=True)
    (tmp_path / "brain" / "concepts" / "x.md").write_text(
        _concept(title="X", tags=["anything/goes"], related=["[[concepts/x]]"]),
        encoding="utf-8",
    )
    health = vb.validate_brain(tmp_path, today=TODAY)
    tag_msgs = [w.message for w in health.warnings if w.kind == "tag"]
    assert not any("off-vocabulary" in m for m in tag_msgs)


def test_missing_from_index_flagged(vault: Path) -> None:
    # W1: a concept absent from brain/INDEX.md (which lists only "a") -> warn.
    _write_concept(vault, "a", _concept(title="A", tags=["ai/agents"],
                                        related=["[[concepts/b]]"]))
    _write_concept(vault, "b", _concept(title="B", tags=["ai/agents"],
                                        related=["[[concepts/a]]"]))
    _write_index(vault, ["a"])  # "b" is missing from the MOC
    health = _run(vault)
    missing = [w for w in health.warnings if w.kind == "missing-from-index"]
    assert len(missing) == 1
    assert missing[0].concept == "b"


def test_all_in_index_no_warning(vault: Path) -> None:
    # W1: every concept listed in the MOC -> no missing-from-index warning.
    _write_concept(vault, "a", _concept(title="A", tags=["ai/agents"],
                                        related=["[[concepts/b]]"]))
    _write_concept(vault, "b", _concept(title="B", tags=["ai/agents"],
                                        related=["[[concepts/a]]"]))
    _write_index(vault, ["a", "b"])
    health = _run(vault)
    assert health.missing_from_index == 0


def test_missing_index_file_is_permissive(vault: Path) -> None:
    # W1: no brain/INDEX.md at all -> nothing to check against, no warnings.
    _write_concept(vault, "a", _concept(title="A", tags=["ai/agents"],
                                        related=["[[concepts/b]]"]))
    _write_concept(vault, "b", _concept(title="B", tags=["ai/agents"],
                                        related=["[[concepts/a]]"]))
    health = _run(vault)
    assert health.missing_from_index == 0


def test_stale_flagged(vault: Path) -> None:
    # last_verified + ttl_days expired well before TODAY.
    _write_concept(
        vault, "old-fact",
        _concept(title="Old Fact", tags=["ai/agents"],
                 related=["[[concepts/old-fact]]"],
                 last_verified="2026-01-01", ttl_days=30),
    )
    health = _run(vault)
    stale = [w for w in health.warnings if w.kind == "stale"]
    assert len(stale) == 1
    assert stale[0].concept == "old-fact"


def test_fresh_ttl_not_stale(vault: Path) -> None:
    # Verified recently, long TTL -> not stale.
    _write_concept(
        vault, "fresh",
        _concept(title="Fresh", tags=["ai/agents"],
                 related=["[[concepts/fresh]]"],
                 last_verified="2026-06-10", ttl_days=90),
    )
    health = _run(vault)
    assert health.stale == 0


def test_negative_ttl_not_stale(vault: Path) -> None:
    # FIX 4: a negative ttl_days is invalid — it must NOT make a freshly-verified
    # concept instantly "stale" (a negative ttl shifts the expiry BEFORE the
    # verification date). Verified today, ttl_days: -5 -> no stale warning.
    _write_concept(
        vault, "neg-ttl",
        _concept(title="Neg TTL", tags=["ai/agents"],
                 related=["[[concepts/neg-ttl]]"],
                 last_verified="2026-06-15", ttl_days=-5),
    )
    health = _run(vault)
    assert health.stale == 0


def test_seed_example_concept_skipped(vault: Path) -> None:
    # A seed-tagged note is not real knowledge -> excluded from hygiene.
    _write_concept(
        vault, "demo",
        _concept(title="Demo", tags=["seed", "example", "pkm/notes"], sources=False),
    )
    health = _run(vault)
    # The only note is a seed -> zero real concepts, zero warnings.
    assert health.concept_count == 0
    assert health.warnings == []


def test_report_written_with_headline(vault: Path) -> None:
    _write_concept(vault, "a", _concept(title="A", tags=["ai/agents"],
                                        related=["[[concepts/b]]"]))
    _write_concept(vault, "b", _concept(title="B", tags=["ai/agents"],
                                        related=["[[concepts/a]]"]))
    health = vb.validate_brain(vault, today=TODAY)
    path = vb.write_report(health, root=vault, today=TODAY)
    assert path == vault / "pipeline" / "3-synthesis" / "brain-health_2026-06-15.md"
    text = path.read_text(encoding="utf-8")
    assert health.headline in text
    # F5: the machine-matched `Health:` line is written to the report too.
    assert health.health_headline in text
    assert "Health:" in text


def test_main_exit_zero_and_strict(vault: Path, monkeypatch, capsys) -> None:
    # Two notes (past the single-note cold-start exception): one is a true
    # orphan (no links, unique tag) -> a warning exists.
    _write_concept(vault, "lonely", _concept(title="Lonely", tags=["ai/agents"]))
    _write_concept(vault, "other", _concept(title="Other", tags=["pkm/notes"],
                                            related=["[[concepts/other]]"]))
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)

    # Default: always exit 0 (advisory).
    assert vb.main([]) == 0
    out = capsys.readouterr().out
    assert "brain health:" in out
    assert "Health:" in out  # F5: the machine-matched line is on stdout too

    # --strict: exit 1 when any warning was raised.
    assert vb.main(["--strict"]) == 1


# --------------------------------------------------------------------------- #
# Write-time strict gate (`--strict --paths ...`) — fail unattended synthesis on
# a newly-written concept that violates the tagging/citation contract.
# --------------------------------------------------------------------------- #


def test_strict_paths_missing_sources_fails(vault: Path, monkeypatch) -> None:
    # A this-run concept with NO sources, scoped via --paths, must FAIL the gate
    # even though it is the only note (cold-start) — the contract is write-time.
    bad = vault / "brain" / "concepts" / "fresh-bad.md"
    bad.write_text(
        _concept(title="Fresh Bad", tags=["ai/agents"],
                 related=["[[concepts/fresh-bad]]"], sources=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    assert vb.main(["--strict", "--paths", str(bad)]) != 0


def test_strict_paths_offvocab_tag_fails(vault: Path, monkeypatch) -> None:
    # A this-run concept using an off-vocabulary LIVE tag must FAIL the gate.
    bad = vault / "brain" / "concepts" / "fresh-offvocab.md"
    bad.write_text(
        _concept(title="Fresh Offvocab", tags=["crypto/defi", "ai/agents"],
                 related=["[[concepts/fresh-offvocab]]"]),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    assert vb.main(["--strict", "--paths", str(bad)]) != 0


def test_strict_paths_clean_concept_passes(vault: Path, monkeypatch) -> None:
    # A this-run concept with sources and only in-vocab / pending tags is clean —
    # `ai/evals` lives in `pending:`, the sanctioned new-tag path -> gate PASSES.
    good = vault / "brain" / "concepts" / "fresh-good.md"
    good.write_text(
        _concept(title="Fresh Good", tags=["ai/agents", "ai/evals"],
                 related=["[[concepts/fresh-good]]"]),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    assert vb.main(["--strict", "--paths", str(good)]) == 0


def test_strict_quarantine_moves_failing_concept_out_of_brain(vault: Path, monkeypatch) -> None:
    # The unattended path's defense: a strict-gate failure must EVICT the offending
    # just-written concept from brain/concepts/ (into the quarantine dir) so a later
    # digest run can't surface an invalid, unsourced note. Exit stays non-zero.
    bad = vault / "brain" / "concepts" / "fresh-bad.md"
    bad.write_text(
        _concept(title="Fresh Bad", tags=["ai/agents"],
                 related=["[[concepts/fresh-bad]]"], sources=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    quarantine = vault / "pipeline" / "3-synthesis" / ".quarantine"
    rc = vb.main(["--strict", "--paths", str(bad), "--quarantine", str(quarantine)])
    assert rc != 0  # still a failure
    assert not bad.exists()  # evicted from the vault
    assert (quarantine / "fresh-bad.md").is_file()  # ...into quarantine


def test_strict_quarantine_restores_prior_version_on_failed_update(vault: Path, monkeypatch) -> None:
    # A failed UPDATE must not destroy a previously-valid concept: with a pre-write
    # backup, the strict gate rolls the live file back to the last-known-good version
    # (so links don't break / knowledge isn't lost) and sets the bad write aside.
    live = vault / "brain" / "concepts" / "vector-db.md"
    staging = vault / "pipeline" / "3-synthesis" / ".staging"
    staging.mkdir(parents=True)
    good = _concept(title="Vector DB", tags=["ai/agents"],
                    related=["[[concepts/vector-db]]"])  # has sources -> valid
    # Pre-write backup captured before wiki-ingest ran.
    (staging / "vector-db.md").write_text(good, encoding="utf-8")
    # wiki-ingest then CORRUPTED the live note (dropped its sources -> invalid).
    live.write_text(
        _concept(title="Vector DB", tags=["ai/agents"],
                 related=["[[concepts/vector-db]]"], sources=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    quarantine = vault / "pipeline" / "3-synthesis" / ".quarantine"
    rc = vb.main([
        "--strict", "--paths", str(live),
        "--quarantine", str(quarantine), "--restore-from", str(staging),
    ])
    assert rc != 0  # the update still failed (topic gets retried)
    assert live.exists()  # knowledge preserved
    assert live.read_text(encoding="utf-8") == good  # rolled back to last-known-good
    assert (quarantine / "vector-db.md").is_file()  # the bad write set aside


def test_strict_quarantine_evicts_new_concept_without_backup(vault: Path, monkeypatch) -> None:
    # A brand-new (never-valid) concept with no backup is still evicted entirely.
    live = vault / "brain" / "concepts" / "fresh-bad.md"
    live.write_text(
        _concept(title="Fresh Bad", tags=["ai/agents"],
                 related=["[[concepts/fresh-bad]]"], sources=False),
        encoding="utf-8",
    )
    staging = vault / "pipeline" / "3-synthesis" / ".staging"
    staging.mkdir(parents=True)  # exists, but holds no backup for this concept
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    quarantine = vault / "pipeline" / "3-synthesis" / ".quarantine"
    rc = vb.main([
        "--strict", "--paths", str(live),
        "--quarantine", str(quarantine), "--restore-from", str(staging),
    ])
    assert rc != 0
    assert not live.exists()  # evicted (nothing valid to restore)
    assert (quarantine / "fresh-bad.md").is_file()


def test_strict_quarantine_restore_from_absent_dir_just_evicts(vault: Path, monkeypatch) -> None:
    # --restore-from pointing at a non-existent dir must fall through to plain
    # eviction (no backup to restore), never crash with a traceback.
    live = vault / "brain" / "concepts" / "fresh-bad.md"
    live.write_text(
        _concept(title="Fresh Bad", tags=["ai/agents"],
                 related=["[[concepts/fresh-bad]]"], sources=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    quarantine = vault / "pipeline" / "3-synthesis" / ".quarantine"
    absent = vault / "pipeline" / "3-synthesis" / ".no-such-staging"
    rc = vb.main([
        "--strict", "--paths", str(live),
        "--quarantine", str(quarantine), "--restore-from", str(absent),
    ])
    assert rc != 0
    assert not live.exists()  # evicted (nothing to restore)
    assert (quarantine / "fresh-bad.md").is_file()


def test_quarantine_does_not_clobber_a_prior_same_named_entry(vault: Path) -> None:
    # Two evictions of the same filename in ONE process must each get a distinct
    # quarantine name — the quarantine must preserve every evicted file, never
    # overwrite an earlier one (the old pid-only fallback collided across calls).
    concepts = vault / "brain" / "concepts"
    dest = vault / "pipeline" / "3-synthesis" / ".quarantine"
    viol = [vb.Warning(kind="missing-sources", concept="foo", message="no sources")]

    (concepts / "foo.md").write_text("BAD-1", encoding="utf-8")
    vb.quarantine_failing_concepts([concepts / "foo.md"], viol, dest)
    (concepts / "foo.md").write_text("BAD-2", encoding="utf-8")
    vb.quarantine_failing_concepts([concepts / "foo.md"], viol, dest)

    quarantined = sorted(p.read_text(encoding="utf-8") for p in dest.glob("foo*"))
    assert quarantined == ["BAD-1", "BAD-2"]  # both preserved, neither clobbered


def test_strict_quarantine_leaves_clean_concept_in_place(vault: Path, monkeypatch) -> None:
    # A clean concept is never quarantined, even when the flag is set.
    good = vault / "brain" / "concepts" / "fresh-good.md"
    good.write_text(
        _concept(title="Fresh Good", tags=["ai/agents", "ai/evals"],
                 related=["[[concepts/fresh-good]]"]),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    quarantine = vault / "pipeline" / "3-synthesis" / ".quarantine"
    rc = vb.main(["--strict", "--paths", str(good), "--quarantine", str(quarantine)])
    assert rc == 0
    assert good.exists()  # untouched
    assert not quarantine.exists() or not any(quarantine.iterdir())


def test_strict_paths_unverifiable_source_fails(vault: Path, monkeypatch) -> None:
    # A non-empty sources list with NO verifiable URL (`sources: ["invalid"]`) must
    # FAIL the anti-hallucination gate — a placeholder is not provenance.
    bad = vault / "brain" / "concepts" / "fresh-bad.md"
    bad.write_text(
        "---\ntitle: Bad\ntype: concept\ntags: [ai/agents]\n"
        "created: 2026-01-01\nlast_updated: 2026-06-13\n"
        'related_concept:\n  - "[[concepts/fresh-bad]]"\n'
        'sources:\n  - "invalid"\n---\n\n# Bad\n\nbody\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    assert vb.main(["--strict", "--paths", str(bad)]) != 0


def test_strict_paths_real_url_source_passes(vault: Path, monkeypatch) -> None:
    # A source that DOES carry an http(s) URL still passes (no false positive).
    good = vault / "brain" / "concepts" / "fresh-good.md"
    good.write_text(
        "---\ntitle: Good\ntype: concept\ntags: [ai/agents]\n"
        "created: 2026-01-01\nlast_updated: 2026-06-13\n"
        'related_concept:\n  - "[[concepts/fresh-good]]"\n'
        'sources:\n  - url: "https://example.com/article"\n    tier: high\n---\n\n# Good\n\nbody\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    assert vb.main(["--strict", "--paths", str(good)]) == 0


def test_source_has_url_helper() -> None:
    # Verifiable URLs pass.
    assert vb._source_has_url({"url": "https://x.com/a", "tier": "high"}) is True
    assert vb._source_has_url("https://x.com/a") is True
    assert vb._source_has_url("http://x.com:8080/a") is True  # explicit valid port
    assert vb._source_has_url('url: "https://x.com/a"') is True  # fallback-flattened
    # Non-URLs and malformed URLs fail — a prefix alone is not provenance.
    assert vb._source_has_url("invalid") is False
    assert vb._source_has_url({"tier": "high"}) is False
    assert vb._source_has_url("ftp://x.com/a") is False
    assert vb._source_has_url("https://") is False  # scheme only, no host
    assert vb._source_has_url("https:///path") is False  # empty host
    assert vb._source_has_url("https://not a url") is False  # whitespace
    assert vb._source_has_url("https://h:99999/x") is False  # out-of-range port
    assert vb._source_has_url("https://h\x00/x") is False  # control character


def test_strict_paths_malformed_source_url_fails(vault: Path, monkeypatch) -> None:
    # A scheme-prefixed but malformed URL (`https://`) must FAIL the gate — it cites
    # nothing fetchable, so it is not verifiable provenance.
    bad = vault / "brain" / "concepts" / "fresh-bad.md"
    bad.write_text(
        "---\ntitle: Bad\ntype: concept\ntags: [ai/agents]\n"
        "created: 2026-01-01\nlast_updated: 2026-06-13\n"
        'related_concept:\n  - "[[concepts/fresh-bad]]"\n'
        'sources:\n  - url: "https://"\n    tier: high\n---\n\n# Bad\n\nbody\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    assert vb.main(["--strict", "--paths", str(bad)]) != 0


# --------------------------------------------------------------------------- #
# CHECK 1 — fact↔source binding: every `## Key facts` bullet must carry an
# inline source reference (a `Source:` token, a `[[wikilink]]`, or a URL). A
# key-fact bullet with no resolvable reference is a hallucination risk and fails
# the write-time gate (matching the seed/template convention in brain/concepts/).
# --------------------------------------------------------------------------- #

# A body with a `## Key facts` section whose bullets each cite a source — the
# exact convention the shipped seed concepts and wiki-ingest template follow.
_CITED_KEY_FACTS = (
    "## Key facts\n\n"
    "- Fact one is true. Source: https://example.com/a\n"
    "- Fact two relates to [[concepts/other]]. Source: https://example.com/b\n\n"
    "## Context\n\nMore text.\n"
)

_WRAPPED_CITED_KEY_FACTS = (
    "## Key facts\n\n"
    "- Fact one is true and the citation is wrapped for readability.\n"
    "  Source: https://example.com/a\n\n"
    "## Context\n\nMore text.\n"
)

# Same section, but the second bullet has NO inline source reference at all.
_UNCITED_KEY_FACT = (
    "## Key facts\n\n"
    "- Fact one is true. Source: https://example.com/a\n"
    "- Fact two is asserted with no provenance whatsoever.\n\n"
    "## Context\n\nMore text.\n"
)


def test_check_keyfacts_citation_helper_passes_cited() -> None:
    # Every key-fact bullet carries a Source:/wikilink/URL -> no warning.
    concept = vb.Concept(
        path=Path("c.md"), stem="c", note_type="concept", body=_CITED_KEY_FACTS,
    )
    assert vb.check_keyfacts_citation(concept) == []


def test_check_keyfacts_citation_helper_flags_uncited() -> None:
    # A bullet under `## Key facts` with no inline source -> a finding.
    concept = vb.Concept(
        path=Path("c.md"), stem="c", note_type="concept", body=_UNCITED_KEY_FACT,
    )
    warnings = vb.check_keyfacts_citation(concept)
    assert len(warnings) == 1
    assert warnings[0].kind == "uncited-fact"
    assert warnings[0].concept == "c"


def test_check_keyfacts_citation_allows_wrapped_source_line() -> None:
    # Markdown authors commonly wrap the `Source:` line under a long bullet.
    # That is still a citation for the bullet and must not become hygiene noise.
    concept = vb.Concept(
        path=Path("c.md"), stem="c", note_type="concept", body=_WRAPPED_CITED_KEY_FACTS,
    )
    assert vb.check_keyfacts_citation(concept) == []


def test_vault_wide_validate_brain_flags_uncited_keyfact(vault: Path) -> None:
    # The scheduled, vault-wide hygiene pass must surface uncited key facts too,
    # not only the write-time `--strict --paths` gate. Otherwise old/manual notes
    # can keep hallucination-prone bullets while the weekly health report stays green.
    _write_concept(
        vault,
        "uncited",
        _concept(
            title="Uncited",
            tags=["ai/agents"],
            related=["[[concepts/uncited]]"],
            body=_UNCITED_KEY_FACT,
        ),
    )
    health = _run(vault)
    findings = [w for w in health.warnings if w.kind == "uncited-fact"]
    assert len(findings) == 1
    assert findings[0].concept == "uncited"


def test_vault_wide_validate_brain_allows_cited_keyfacts(vault: Path) -> None:
    _write_concept(
        vault,
        "cited",
        _concept(
            title="Cited",
            tags=["ai/agents"],
            related=["[[concepts/cited]]"],
            body=_CITED_KEY_FACTS,
        ),
    )
    health = _run(vault)
    assert not any(w.kind == "uncited-fact" for w in health.warnings)


def test_json_includes_uncited_facts_count(vault: Path, monkeypatch, capsys) -> None:
    _write_concept(
        vault,
        "uncited",
        _concept(
            title="Uncited",
            tags=["ai/agents"],
            related=["[[concepts/uncited]]"],
            body=_UNCITED_KEY_FACT,
        ),
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    assert vb.main(["--json"]) == 0
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["uncited_facts"] == 1
    assert "Health:" in payload["health_headline"]


def test_check_keyfacts_citation_no_section_is_permissive() -> None:
    # No `## Key facts` section at all -> nothing to check (conservative: a note
    # without that section must never be flagged).
    concept = vb.Concept(
        path=Path("c.md"), stem="c", note_type="concept", body="# Title\n\nProse.\n",
    )
    assert vb.check_keyfacts_citation(concept) == []


def test_strict_paths_uncited_keyfact_fails(vault: Path, monkeypatch) -> None:
    # A this-run concept whose `## Key facts` has an uncited bullet must FAIL the
    # write-time gate — a fact with no traceable source is a hallucination risk.
    bad = vault / "brain" / "concepts" / "fresh-bad.md"
    bad.write_text(
        _concept(title="Fresh Bad", tags=["ai/agents"],
                 related=["[[concepts/fresh-bad]]"], body=_UNCITED_KEY_FACT),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    assert vb.main(["--strict", "--paths", str(bad)]) != 0


def test_strict_paths_cited_keyfacts_passes(vault: Path, monkeypatch) -> None:
    # The mirror: when every key-fact bullet cites a source, the gate PASSES
    # (no false positive against a correctly-authored concept).
    good = vault / "brain" / "concepts" / "fresh-good.md"
    good.write_text(
        _concept(title="Fresh Good", tags=["ai/agents"],
                 related=["[[concepts/fresh-good]]"], body=_CITED_KEY_FACTS),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    assert vb.main(["--strict", "--paths", str(good)]) == 0


def test_strict_quarantine_evicts_uncited_keyfact_concept(vault: Path, monkeypatch) -> None:
    # The uncited-fact failure participates in the SAME quarantine mechanism as the
    # other gate checks: the offending note is evicted from brain/concepts/.
    bad = vault / "brain" / "concepts" / "fresh-bad.md"
    bad.write_text(
        _concept(title="Fresh Bad", tags=["ai/agents"],
                 related=["[[concepts/fresh-bad]]"], body=_UNCITED_KEY_FACT),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    quarantine = vault / "pipeline" / "3-synthesis" / ".quarantine"
    rc = vb.main(["--strict", "--paths", str(bad), "--quarantine", str(quarantine)])
    assert rc != 0
    assert not bad.exists()
    assert (quarantine / "fresh-bad.md").is_file()


def test_seed_concepts_pass_keyfacts_citation() -> None:
    # Guard against false positives: the SHIPPED seed concepts already follow the
    # convention (every `## Key facts` bullet carries `Source:`), so the new check
    # must not flag them.
    concepts_dir = _PROJECT_ROOT / "brain" / "concepts"
    for path in concepts_dir.glob("*.md"):
        concept = vb.load_concept(path)
        assert vb.check_keyfacts_citation(concept) == [], path.name


# --------------------------------------------------------------------------- #
# CHECK 2 — bound the controlled-vocabulary escape hatch: a concept may
# introduce AT MOST ONE new `pending:` tag. More than one is silent vocabulary
# drift (promote_tags later auto-promotes), so the write-time gate fails it.
# --------------------------------------------------------------------------- #

# Registry with two pending tags so a concept can carry both at once.
_TWO_PENDING_TAGS_YAML = """\
domains:
  ai:
    - agents
synonyms: {}
pending:
  - ai/evals
  - ai/observability
"""


def _write_two_pending_registry(vault: Path) -> None:
    (vault / "config" / "tags.yaml").write_text(_TWO_PENDING_TAGS_YAML, encoding="utf-8")


def test_check_pending_cap_helper_allows_one() -> None:
    registry = vb.load_tag_registry(_SHIPPED_TAGS_YAML)  # has ai/evals pending
    concept = vb.Concept(
        path=Path("c.md"), stem="c", note_type="concept",
        tags=["ai/agents", "ai/evals"],
    )
    assert vb.check_pending_cap(concept, registry) is None


def test_check_pending_cap_helper_flags_two(vault: Path) -> None:
    _write_two_pending_registry(vault)
    registry = vb.load_tag_registry(vault / "config" / "tags.yaml")
    concept = vb.Concept(
        path=Path("c.md"), stem="c", note_type="concept",
        tags=["ai/agents", "ai/evals", "ai/observability"],
    )
    warning = vb.check_pending_cap(concept, registry)
    assert warning is not None
    assert warning.kind == "pending-cap"
    assert warning.concept == "c"


def test_strict_paths_two_pending_tags_fails(vault: Path, monkeypatch) -> None:
    # A this-run concept introducing TWO new pending tags must FAIL the gate —
    # the ≤1-new-pending-tag-per-concept rule is now enforced (no silent drift).
    _write_two_pending_registry(vault)
    bad = vault / "brain" / "concepts" / "fresh-bad.md"
    bad.write_text(
        _concept(title="Fresh Bad", tags=["ai/agents", "ai/evals", "ai/observability"],
                 related=["[[concepts/fresh-bad]]"], body=_CITED_KEY_FACTS),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    assert vb.main(["--strict", "--paths", str(bad)]) != 0


def test_strict_paths_one_pending_tag_passes(vault: Path, monkeypatch) -> None:
    # Exactly one new pending tag is the sanctioned escape hatch -> gate PASSES.
    _write_two_pending_registry(vault)
    good = vault / "brain" / "concepts" / "fresh-good.md"
    good.write_text(
        _concept(title="Fresh Good", tags=["ai/agents", "ai/evals"],
                 related=["[[concepts/fresh-good]]"], body=_CITED_KEY_FACTS),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    assert vb.main(["--strict", "--paths", str(good)]) == 0


def test_strict_quarantine_evicts_two_pending_concept(vault: Path, monkeypatch) -> None:
    # The pending-cap failure participates in the same quarantine mechanism.
    _write_two_pending_registry(vault)
    bad = vault / "brain" / "concepts" / "fresh-bad.md"
    bad.write_text(
        _concept(title="Fresh Bad", tags=["ai/agents", "ai/evals", "ai/observability"],
                 related=["[[concepts/fresh-bad]]"], body=_CITED_KEY_FACTS),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    quarantine = vault / "pipeline" / "3-synthesis" / ".quarantine"
    rc = vb.main(["--strict", "--paths", str(bad), "--quarantine", str(quarantine)])
    assert rc != 0
    assert not bad.exists()
    assert (quarantine / "fresh-bad.md").is_file()


def test_empty_vault_is_reported_as_empty_not_healthy(tmp_path: Path) -> None:
    # A brand-new vault with zero concepts must NOT claim "healthy" — that hides the
    # uninitialised state from a new user.
    (tmp_path / "brain" / "concepts").mkdir(parents=True)
    health = vb.validate_brain(tmp_path, today=TODAY)
    summary = vb.render_summary(health, today=TODAY)
    assert "The vault is healthy" not in summary
    assert "empty" in summary.lower()


def test_no_strict_keeps_advisory_exit_zero(vault: Path, monkeypatch) -> None:
    # WITHOUT --strict, the SAME contract-violating concept stays advisory: the
    # default behavior must be unchanged (always exit 0).
    bad = vault / "brain" / "concepts" / "fresh-bad.md"
    bad.write_text(
        _concept(title="Fresh Bad", tags=["crypto/defi"], sources=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    assert vb.main(["--paths", str(bad)]) == 0


def test_strict_paths_only_gates_in_scope_concepts(vault: Path, monkeypatch) -> None:
    # A pre-existing bad concept NOT in --paths must not fail the gate; only the
    # scoped (this-run) clean concept is evaluated -> exit 0.
    vault_bad = vault / "brain" / "concepts" / "old-bad.md"
    vault_bad.write_text(
        _concept(title="Old Bad", tags=["crypto/defi"], sources=False),
        encoding="utf-8",
    )
    good = vault / "brain" / "concepts" / "fresh-good.md"
    good.write_text(
        _concept(title="Fresh Good", tags=["ai/agents"],
                 related=["[[concepts/fresh-good]]"]),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    assert vb.main(["--strict", "--paths", str(good)]) == 0


def test_strict_paths_writes_no_brain_health_report(vault: Path, monkeypatch) -> None:
    # The write-time gate (`--strict --paths`) must NOT run the full-vault scan
    # or write pipeline/3-synthesis/brain-health_*.md — otherwise a per-topic
    # gate check during synthesis masquerades as a scheduled hygiene pass and
    # clobbers the report build_digest.latest_brain_health() surfaces.
    good = vault / "brain" / "concepts" / "fresh-good.md"
    good.write_text(
        _concept(title="Fresh Good", tags=["ai/agents", "ai/evals"],
                 related=["[[concepts/fresh-good]]"]),
        encoding="utf-8",
    )
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    report = vb.default_report_path(vault, date.today())
    assert not report.exists()  # precondition: nothing written yet

    assert vb.main(["--strict", "--paths", str(good)]) == 0
    assert not report.exists()  # gate path writes no report


def test_plain_run_still_writes_brain_health_report(vault: Path, monkeypatch) -> None:
    # The non-`--paths` path keeps its CURRENT behavior: a plain run runs the
    # full-vault scan AND writes the brain-health report (the scheduled pass).
    _write_concept(vault, "a", _concept(title="A", tags=["ai/agents"],
                                        related=["[[concepts/b]]"]))
    _write_concept(vault, "b", _concept(title="B", tags=["ai/agents"],
                                        related=["[[concepts/a]]"]))
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    report = vb.default_report_path(vault, date.today())
    assert not report.exists()

    assert vb.main([]) == 0
    assert report.exists()  # plain run still writes the scheduled report


def test_strict_paths_missing_file_fails_without_traceback(
    vault: Path, monkeypatch
) -> None:
    # Contract: a missing in-scope file (a concept that was supposed to be
    # written but isn't there) is a gate FAILURE — defined non-zero exit, never
    # an unhandled FileNotFoundError traceback.
    ghost = vault / "brain" / "concepts" / "ghost.md"
    assert not ghost.exists()
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    assert vb.main(["--strict", "--paths", str(ghost)]) != 0


def test_main_json_output(vault: Path, monkeypatch, capsys) -> None:
    _write_concept(vault, "a", _concept(title="A", tags=["ai/agents"],
                                        related=["[[concepts/a]]"]))
    monkeypatch.setattr(vb, "PROJECT_ROOT", vault)
    assert vb.main(["--json"]) == 0
    out = capsys.readouterr().out
    import json
    payload = json.loads(out)
    assert payload["concepts"] == 1
    assert "headline" in payload


def test_missing_tags_yaml_is_safe(tmp_path: Path) -> None:
    # No config/tags.yaml (parallel agent hasn't created it) -> still runs.
    (tmp_path / "brain" / "concepts").mkdir(parents=True)
    (tmp_path / "brain" / "concepts" / "x.md").write_text(
        _concept(title="X", tags=["ai/agents"], related=["[[concepts/x]]"]),
        encoding="utf-8",
    )
    health = vb.validate_brain(tmp_path, today=TODAY)
    # Synonym merges can't be suggested without the registry, but nothing crashes.
    assert health.concept_count == 1


def test_empty_vault_headline_present(tmp_path: Path) -> None:
    (tmp_path / "brain" / "concepts").mkdir(parents=True)
    health = vb.validate_brain(tmp_path, today=TODAY)
    assert health.concept_count == 0
    assert health.warnings == []
    assert "0 concepts" in health.headline


# --------------------------------------------------------------------------- #
# Dependency-free tag-registry parsing (headless `python3` has no PyYAML) — BUG 1
# --------------------------------------------------------------------------- #

# Path to the shipped registry — the line-based fallback must parse it exactly
# the way PyYAML would (same domains, synonyms, pending), since headless
# promote_tags reuses this loader as its "applier".
_SHIPPED_TAGS_YAML = _PROJECT_ROOT / "config" / "tags.yaml"


def test_parse_tag_registry_lines_matches_pyyaml_on_shipped_file():
    # The line-based parser (used when PyYAML is absent) must yield a registry
    # equivalent to the PyYAML fast path for the real, comment-rich tags.yaml.
    yaml = pytest.importorskip("yaml")
    text = _SHIPPED_TAGS_YAML.read_text(encoding="utf-8")

    line_based = vb._parse_tag_registry_lines(text)

    # Build the PyYAML-equivalent registry from the same bytes.
    data = yaml.safe_load(text)
    valid: set[str] = set()
    for domain, topics in (data.get("domains") or {}).items():
        valid.add(str(domain))
        for topic in topics or []:
            valid.add(f"{domain}/{topic}")
    synonyms = {str(k): str(v) for k, v in (data.get("synonyms") or {}).items()}
    pending = frozenset(str(p) for p in (data.get("pending") or []))

    assert line_based.valid == frozenset(valid)
    assert line_based.synonyms == synonyms
    assert line_based.pending == pending


def test_load_tag_registry_populated_without_pyyaml(tmp_path: Path, monkeypatch):
    # Simulate the headless runtime: PyYAML import fails. load_tag_registry must
    # STILL populate the registry from the file (not silently return empty),
    # otherwise promote_tags becomes a no-op headless (the real BUG 1).
    text = (
        "domains:\n"
        "  ai:\n"
        "    - agents\n"
        "    - rag\n"
        "  robotics: []\n"
        "synonyms:\n"
        "  ai-safety: ai/governance\n"
        "pending:\n"
        "  - ai/evals\n"
    )
    tags_path = tmp_path / "tags.yaml"
    tags_path.write_text(text, encoding="utf-8")

    import builtins

    real_import = builtins.__import__

    def no_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("simulated: no PyYAML in headless runtime")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_yaml)

    registry = vb.load_tag_registry(tags_path)
    # Domains + every domain/topic pair, including the inline `robotics: []`.
    assert {"ai", "ai/agents", "ai/rag", "robotics"}.issubset(registry.valid)
    assert registry.synonyms == {"ai-safety": "ai/governance"}
    assert registry.pending == frozenset({"ai/evals"})


def test_load_tag_registry_paths_equivalent(tmp_path: Path, monkeypatch):
    # The PyYAML path and the line-based fallback must produce equal registries.
    pytest.importorskip("yaml")
    text = _SHIPPED_TAGS_YAML.read_text(encoding="utf-8")
    tags_path = tmp_path / "tags.yaml"
    tags_path.write_text(text, encoding="utf-8")

    with_yaml = vb.load_tag_registry(tags_path)

    import builtins

    real_import = builtins.__import__

    def no_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("simulated headless")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_yaml)
    without_yaml = vb.load_tag_registry(tags_path)

    assert with_yaml.valid == without_yaml.valid
    assert with_yaml.synonyms == without_yaml.synonyms
    assert with_yaml.pending == without_yaml.pending


# --------------------------------------------------------------------------- #
# Author nodes (Stage 9, slice 1) — brain/authors/ is a recognised vault dir.
# Author nodes are backlink-only entities: exempt from the sources: rule and
# never flagged as orphans, but their body links are still broken-link checked.
# --------------------------------------------------------------------------- #


def _author_note(
    *,
    title: str,
    identity_key: str,
    body: str = "Identity node.",
    tags: list[str] | None = None,
) -> str:
    """Build an author node's markdown (Q1 frontmatter, no sources:)."""
    lines = [
        "---",
        f"title: {title}",
        "type: author",
        f"identity_key: {identity_key}",
        "tags: [" + ", ".join(tags or ["author"]) + "]",
        "created: 2026-07-22",
        "last_updated: 2026-07-22",
        "---",
        "",
        f"# {title}",
        "",
        body,
    ]
    return "\n".join(lines) + "\n"


def test_author_node_is_healthy_and_exempt_from_sources(vault: Path) -> None:
    """A lone author node raises no warning — not orphan, not missing-sources."""
    _write_concept(
        vault, "concept-a",
        _concept(title="A", tags=["ai/agents"], related=["[[concepts/concept-b]]"]))
    _write_concept(vault, "concept-b", _concept(title="B", tags=["pkm/notes"]))
    _write_vault_note(
        vault, "authors", "ada-lovelace",
        _author_note(title="Ada Lovelace", identity_key="orcid:0000-0002-1825-0097"))

    health = _run(vault)

    assert not any(w.concept == "ada-lovelace" for w in health.warnings)
    # Author nodes are not concepts — they must not inflate the concept count.
    assert health.concept_count == 2


def test_author_node_never_orphan_despite_no_links(vault: Path) -> None:
    """Author nodes are backlink-only by design — no outbound link is not orphan debt."""
    _write_concept(vault, "solo", _concept(title="Solo", tags=["ai/agents"]))
    _write_vault_note(
        vault, "authors", "jane-doe",
        _author_note(title="Jane Doe", identity_key="name:jane-doe"))

    health = _run(vault)

    assert not any(
        w.kind in {"orphan", "weakly-linked"} and w.concept == "jane-doe"
        for w in health.warnings
    )


def test_author_node_body_broken_concept_link_detected(vault: Path) -> None:
    """A dangling [[concepts/X]] in an author body is a broken-link finding."""
    _write_concept(vault, "real", _concept(title="Real", tags=["ai/agents"]))
    _write_vault_note(
        vault, "authors", "ada-lovelace",
        _author_note(
            title="Ada Lovelace", identity_key="name:ada",
            body="Wrote about [[concepts/ghost-concept]] which does not exist."))

    health = _run(vault)

    assert any(
        w.kind == "broken-link" and w.concept == "ada-lovelace"
        and "ghost-concept" in w.message
        for w in health.warnings
    )


# --------------------------------------------------------------------------- #
# Concept contributors (Stage 9, slice 2) — the author↔concept link lives ON
# the concept as `contributors: ["[[authors/<slug>]]"]` (modelled on
# related_concept:). A dangling contributor is a broken-link finding.
# --------------------------------------------------------------------------- #


def test_load_concept_parses_contributors(vault: Path) -> None:
    """`contributors:` is read into the Concept model as raw wikilink strings."""
    _write_concept(
        vault, "c",
        _concept(title="C", tags=["ai/agents"],
                 contributors=["[[authors/ada-lovelace]]", "[[authors/alan-turing]]"]))

    concept = vb.load_concept(vault / "brain" / "concepts" / "c.md")

    assert concept.contributors == ["[[authors/ada-lovelace]]", "[[authors/alan-turing]]"]


def test_contributor_resolves_to_existing_author_node(vault: Path) -> None:
    """A contributor pointing at a real author node raises no broken-link."""
    _write_concept(
        vault, "concept-a",
        _concept(title="A", tags=["ai/agents"], related=["[[concepts/concept-b]]"],
                 contributors=["[[authors/ada-lovelace]]"]))
    _write_concept(vault, "concept-b", _concept(title="B", tags=["pkm/notes"]))
    _write_vault_note(
        vault, "authors", "ada-lovelace",
        _author_note(title="Ada Lovelace", identity_key="name:ada"))

    health = _run(vault)

    assert not any(w.kind == "broken-link" for w in health.warnings)


def test_dangling_contributor_is_broken_link(vault: Path) -> None:
    """A contributor with no author node is flagged broken-link on the concept."""
    _write_concept(
        vault, "concept-a",
        _concept(title="A", tags=["ai/agents"], related=["[[concepts/concept-b]]"],
                 contributors=["[[authors/ghost-author]]"]))
    _write_concept(vault, "concept-b", _concept(title="B", tags=["pkm/notes"]))

    health = _run(vault)

    assert any(
        w.kind == "broken-link" and w.concept == "concept-a"
        and "ghost-author" in w.message
        for w in health.warnings
    )


def test_contributor_edge_does_not_rescue_concept_from_orphan(vault: Path) -> None:
    """A contributor links concept→author, not concept→concept — orphan status unchanged."""
    _write_concept(vault, "linked-a", _concept(title="LA", tags=["ai/agents"],
                   related=["[[concepts/linked-b]]"]))
    _write_concept(vault, "linked-b", _concept(title="LB", tags=["pkm/notes"]))
    # `alone` has only a contributor edge (to an author) and a unique tag — still
    # a true orphan concept (the author edge is not a concept-graph edge).
    _write_concept(vault, "alone", _concept(title="Alone", tags=["ai/rag"],
                   contributors=["[[authors/ada-lovelace]]"]))
    _write_vault_note(
        vault, "authors", "ada-lovelace",
        _author_note(title="Ada Lovelace", identity_key="name:ada"))

    health = _run(vault)

    assert any(
        w.kind == "orphan" and w.concept == "alone" for w in health.warnings
    )
