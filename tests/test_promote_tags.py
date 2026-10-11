"""
test_promote_tags.py — offline tests for the tag auto-promoter (FEATURE 2).

`scripts/promote_tags.py` is the *real* counterpart to validate_brain's advisory
"promote this pending tag" warning: it actually moves a `pending:` tag into
`domains:` once that tag recurs across ≥ PENDING_PROMOTION_THRESHOLD concepts in
`brain/concepts/`.

Every test builds a self-contained fake vault under a tmp dir (its own
brain/concepts + config/tags.yaml) and runs the promoter against it, so the real
vault and config/ are never touched. No network.
"""
from pathlib import Path

import pytest
import yaml  # noqa: E402

from scripts import promote_tags as pt  # noqa: E402
from scripts import validate_brain as vb  # noqa: E402

# A controlled vocabulary with two pending candidates of each shape: a
# `domain/topic` pending (`ai/evals`) and a bare-domain pending (`robotics`).
_TAGS_YAML = """\
# config/tags.yaml — controlled tag vocabulary (the FIXED registry)
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
  - robotics
"""


def _concept(*, title: str, tags: list[str]) -> str:
    """Minimal concept note carrying the given tags (CONVENTIONS §5.1)."""
    return (
        "---\n"
        f"title: {title}\n"
        "type: concept\n"
        f"tags: [{', '.join(tags)}]\n"
        "sources:\n"
        '  - url: "https://example.com"\n'
        "---\n\n"
        f"# {title}\n\nBody.\n"
    )


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """A fake vault: brain/concepts + config/tags.yaml registry."""
    (tmp_path / "brain" / "concepts").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "tags.yaml").write_text(_TAGS_YAML, encoding="utf-8")
    return tmp_path


def _write_concept(vault: Path, stem: str, tags: list[str]) -> None:
    (vault / "brain" / "concepts" / f"{stem}.md").write_text(
        _concept(title=stem, tags=tags), encoding="utf-8"
    )


def _tags(vault: Path) -> dict:
    return yaml.safe_load((vault / "config" / "tags.yaml").read_text(encoding="utf-8"))


def _seed_uses(vault: Path, tag: str, count: int, *, prefix: str) -> None:
    """Write `count` distinct concepts that each carry `tag`."""
    for i in range(count):
        _write_concept(vault, f"{prefix}-{i}", ["pkm/notes", tag])


# --------------------------------------------------------------------------- #
# Threshold sanity
# --------------------------------------------------------------------------- #


def test_threshold_matches_validate_brain():
    # The promoter must use the SAME threshold validate_brain warns on (DRY), so
    # "the warning fired" and "the promoter acts" never disagree.
    assert pt.PENDING_PROMOTION_THRESHOLD == vb.PENDING_PROMOTION_THRESHOLD


# --------------------------------------------------------------------------- #
# Promotion of a `domain/topic` pending tag
# --------------------------------------------------------------------------- #


def test_pending_domain_topic_at_threshold_is_promoted(vault: Path):
    # `ai/evals` used by exactly threshold concepts -> promoted under domain `ai`
    # as a topic, and removed from pending:.
    _seed_uses(vault, "ai/evals", pt.PENDING_PROMOTION_THRESHOLD, prefix="ev")
    result = pt.promote_tags(vault)

    tags = _tags(vault)
    assert "evals" in tags["domains"]["ai"]  # added under its domain as a topic
    assert "ai/evals" not in (tags.get("pending") or [])  # removed from pending
    assert "ai/evals" in result.promoted


def test_promote_writes_tags_yaml_atomically(vault: Path, monkeypatch):
    # The tags.yaml write must go through registry.atomic_write_text (same-dir temp
    # + os.replace) so a crash mid-write can't truncate the controlled vocabulary.
    calls: list[Path] = []
    real = pt.atomic_write_text

    def _spy(path: Path, text: str) -> None:
        calls.append(path)
        real(path, text)

    monkeypatch.setattr(pt, "atomic_write_text", _spy)
    _seed_uses(vault, "ai/evals", pt.PENDING_PROMOTION_THRESHOLD, prefix="ev")
    pt.promote_tags(vault)

    assert any(p.name == "tags.yaml" for p in calls)  # written via the helper
    assert "evals" in _tags(vault)["domains"]["ai"]  # content still correct


def test_pending_bare_tag_at_threshold_becomes_domain(vault: Path):
    # A bare pending tag (`robotics`) becomes a new top-level domain key.
    _seed_uses(vault, "robotics", pt.PENDING_PROMOTION_THRESHOLD, prefix="rob")
    pt.promote_tags(vault)

    tags = _tags(vault)
    assert "robotics" in tags["domains"]
    assert tags["domains"]["robotics"] in ([], None)
    assert "robotics" not in (tags.get("pending") or [])


# --------------------------------------------------------------------------- #
# Below-threshold pending tags stay
# --------------------------------------------------------------------------- #


def test_pending_below_threshold_stays(vault: Path):
    # One short of the threshold -> NOT promoted, stays in pending:.
    _seed_uses(vault, "ai/evals", pt.PENDING_PROMOTION_THRESHOLD - 1, prefix="ev")
    result = pt.promote_tags(vault)

    tags = _tags(vault)
    assert "ai/evals" in tags["pending"]
    assert "evals" not in tags["domains"]["ai"]
    assert "ai/evals" not in result.promoted
    assert "ai/evals" in result.stayed


def test_unused_pending_tag_stays(vault: Path):
    # A pending tag used by zero concepts is never promoted.
    _seed_uses(vault, "ai/evals", pt.PENDING_PROMOTION_THRESHOLD, prefix="ev")
    pt.promote_tags(vault)
    tags = _tags(vault)
    # `robotics` had no users -> remains pending.
    assert "robotics" in tags["pending"]


# --------------------------------------------------------------------------- #
# --dry-run writes nothing
# --------------------------------------------------------------------------- #


def test_dry_run_writes_nothing(vault: Path):
    _seed_uses(vault, "ai/evals", pt.PENDING_PROMOTION_THRESHOLD, prefix="ev")
    before = (vault / "config" / "tags.yaml").read_text(encoding="utf-8")
    result = pt.promote_tags(vault, dry_run=True)
    after = (vault / "config" / "tags.yaml").read_text(encoding="utf-8")

    assert after == before  # file untouched
    # …but the result still REPORTS what would be promoted.
    assert "ai/evals" in result.promoted


# --------------------------------------------------------------------------- #
# Idempotency / safety
# --------------------------------------------------------------------------- #


def test_idempotent_second_run_is_noop(vault: Path):
    _seed_uses(vault, "ai/evals", pt.PENDING_PROMOTION_THRESHOLD, prefix="ev")
    pt.promote_tags(vault)
    after_first = (vault / "config" / "tags.yaml").read_text(encoding="utf-8")
    result = pt.promote_tags(vault)
    after_second = (vault / "config" / "tags.yaml").read_text(encoding="utf-8")

    assert after_second == after_first  # nothing left to promote
    assert result.promoted == []


def test_existing_domains_and_synonyms_preserved(vault: Path):
    before = _tags(vault)
    _seed_uses(vault, "ai/evals", pt.PENDING_PROMOTION_THRESHOLD, prefix="ev")
    pt.promote_tags(vault)
    after = _tags(vault)

    # Pre-existing topics under `ai` survive (we appended, didn't replace).
    assert set(before["domains"]["ai"]).issubset(set(after["domains"]["ai"]))
    assert after["domains"]["pkm"] == before["domains"]["pkm"]
    assert after["synonyms"] == before["synonyms"]


def test_promoted_tag_is_valid_in_registry(vault: Path):
    # After promotion, validate_brain's loader must recognize the tag as valid
    # vocabulary (no longer pending / off-vocabulary).
    _seed_uses(vault, "ai/evals", pt.PENDING_PROMOTION_THRESHOLD, prefix="ev")
    pt.promote_tags(vault)
    registry = vb.load_tag_registry(vault / "config" / "tags.yaml")
    assert "ai/evals" in registry.valid
    assert "ai/evals" not in registry.pending


def test_never_promotes_a_tag_already_in_domains(vault: Path):
    # If a pending entry duplicates an existing domain/topic, it must not be
    # double-added; the topic list stays free of duplicates.
    # Make `ai/agents` (already a domain/topic) also appear in pending.
    text = (vault / "config" / "tags.yaml").read_text(encoding="utf-8")
    text = text.replace("  - ai/evals\n", "  - ai/evals\n  - ai/agents\n")
    (vault / "config" / "tags.yaml").write_text(text, encoding="utf-8")
    _seed_uses(vault, "ai/agents", pt.PENDING_PROMOTION_THRESHOLD, prefix="ag")
    pt.promote_tags(vault)

    tags = _tags(vault)
    assert tags["domains"]["ai"].count("agents") == 1  # no duplicate topic
    assert "ai/agents" not in (tags.get("pending") or [])  # cleaned from pending


# --------------------------------------------------------------------------- #
# Malformed / empty inputs degrade gracefully
# --------------------------------------------------------------------------- #


def test_missing_tags_yaml_is_graceful(tmp_path: Path):
    # No config/tags.yaml at all -> no crash, nothing promoted.
    (tmp_path / "brain" / "concepts").mkdir(parents=True)
    result = pt.promote_tags(tmp_path)
    assert result.promoted == []


def test_empty_pending_is_graceful(vault: Path):
    # An empty pending list -> nothing to do, file unchanged.
    (vault / "config" / "tags.yaml").write_text(
        "domains:\n  ai:\n    - agents\npending: []\n", encoding="utf-8"
    )
    before = (vault / "config" / "tags.yaml").read_text(encoding="utf-8")
    result = pt.promote_tags(vault)
    after = (vault / "config" / "tags.yaml").read_text(encoding="utf-8")
    assert after == before
    assert result.promoted == []


def test_empty_concepts_dir_is_graceful(vault: Path):
    # No concepts at all -> no tag reaches threshold, nothing promoted.
    result = pt.promote_tags(vault)
    assert result.promoted == []
    assert set(result.stayed) == {"ai/evals", "robotics"}


def test_malformed_tags_yaml_is_graceful(vault: Path):
    # Unparseable YAML -> degrade to a no-op rather than raising.
    (vault / "config" / "tags.yaml").write_text("domains: [: :\n", encoding="utf-8")
    result = pt.promote_tags(vault)
    assert result.promoted == []


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_dry_run_writes_nothing(vault: Path, capsys):
    _seed_uses(vault, "ai/evals", pt.PENDING_PROMOTION_THRESHOLD, prefix="ev")
    before = (vault / "config" / "tags.yaml").read_text(encoding="utf-8")
    rc = pt.main(["--dry-run", "--root", str(vault)])
    after = (vault / "config" / "tags.yaml").read_text(encoding="utf-8")
    assert rc == 0
    assert after == before
    out = capsys.readouterr().out
    assert "ai/evals" in out


def test_cli_default_writes(vault: Path):
    _seed_uses(vault, "ai/evals", pt.PENDING_PROMOTION_THRESHOLD, prefix="ev")
    rc = pt.main(["--root", str(vault)])
    assert rc == 0
    assert "evals" in _tags(vault)["domains"]["ai"]


# --------------------------------------------------------------------------- #
# Inline `domain: []` form must not create a duplicate key — BUG 2
# --------------------------------------------------------------------------- #


def test_promote_topic_into_inline_empty_domain_no_duplicate(vault: Path):
    # manage_sources seeds a bare domain as `robotics: []` (inline). Promoting a
    # `robotics/humanoid` pending tag must convert that line to block form and
    # nest the topic under it — NOT append a SECOND `robotics:` key (duplicate
    # mapping key that PyYAML silently collapses, corrupting the registry).
    text = (vault / "config" / "tags.yaml").read_text(encoding="utf-8")
    # Add an inline-empty domain and a matching pending topic.
    text = text.replace("domains:\n", "domains:\n  robotics: []\n")
    text = text.replace("  - robotics\n", "  - robotics/humanoid\n")
    (vault / "config" / "tags.yaml").write_text(text, encoding="utf-8")

    _seed_uses(vault, "robotics/humanoid", pt.PENDING_PROMOTION_THRESHOLD, prefix="hum")
    pt.promote_tags(vault)

    raw = (vault / "config" / "tags.yaml").read_text(encoding="utf-8")
    # Exactly one `robotics:` key (whether `robotics:` or `robotics: []`).
    import re

    assert len(re.findall(r"^  robotics:", raw, re.M)) == 1
    tags = _tags(vault)
    assert "humanoid" in tags["domains"]["robotics"]


def test_repromote_bare_tag_into_inline_empty_domain_is_noop(vault: Path):
    # `robotics: []` already exists as a domain; a bare `robotics` pending tag
    # must be recognized as already-present and NOT append a duplicate key.
    text = (vault / "config" / "tags.yaml").read_text(encoding="utf-8")
    text = text.replace("domains:\n", "domains:\n  robotics: []\n")
    (vault / "config" / "tags.yaml").write_text(text, encoding="utf-8")

    _seed_uses(vault, "robotics", pt.PENDING_PROMOTION_THRESHOLD, prefix="rob")
    pt.promote_tags(vault)

    raw = (vault / "config" / "tags.yaml").read_text(encoding="utf-8")
    import re

    assert len(re.findall(r"^  robotics:", raw, re.M)) == 1
    # The bare tag is cleaned from pending (it was already vocabulary).
    assert "robotics" not in (_tags(vault).get("pending") or [])


# --------------------------------------------------------------------------- #
# Insertion must land under the last domain, not inside the synonyms comment
# block that precedes `synonyms:` — BUG 3
# --------------------------------------------------------------------------- #

_TAGS_YAML_WITH_COMMENT = """\
domains:
  ai:
    - agents
  pkm:
    - notes

# ── synonyms: alias → canonical ──────────────────────────────────────────────
# RSS <category> values normalize through this map.
synonyms:
  machine-learning: ai/ml
pending:
  - robotics
"""


def test_promote_bare_tag_lands_under_last_domain_not_in_comment(tmp_path: Path):
    # The shipped file has a blank line + 2 comment lines before `synonyms:`. A
    # new domain key must sit flush under the last real domain entry, NOT between
    # the `# synonyms` header and `synonyms:`.
    vault = tmp_path
    (vault / "brain" / "concepts").mkdir(parents=True)
    (vault / "config").mkdir()
    (vault / "config" / "tags.yaml").write_text(
        _TAGS_YAML_WITH_COMMENT, encoding="utf-8"
    )
    _seed_uses(vault, "robotics", pt.PENDING_PROMOTION_THRESHOLD, prefix="rob")
    pt.promote_tags(vault)

    raw = (vault / "config" / "tags.yaml").read_text(encoding="utf-8")
    lines = raw.splitlines()
    rob_idx = next(i for i, ln in enumerate(lines) if ln.rstrip() == "  robotics: []")
    syn_idx = next(i for i, ln in enumerate(lines) if ln.rstrip() == "synonyms:")
    notes_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "- notes")
    # The new key sits immediately after the last domain entry (`- notes`),
    # BEFORE any comment / the synonyms block.
    assert rob_idx == notes_idx + 1
    assert rob_idx < syn_idx
    # Comment header still precedes `synonyms:` (not orphaned above the new key).
    assert any(lines[i].strip().startswith("#") for i in range(rob_idx + 1, syn_idx))
    # The registry still parses with the new domain present.
    tags = _tags(vault)
    assert "robotics" in tags["domains"]
    assert tags["synonyms"] == {"machine-learning": "ai/ml"}


# --------------------------------------------------------------------------- #
# Regression: review cycle hardening (C2 / C3 / C4)
# --------------------------------------------------------------------------- #

_TAGS_YAML_COMMENTED_TOPIC = """\
domains:
  ai:
    - agents        # autonomous / multi-agent systems
    - rag
synonyms:
  machine-learning: ai/ml
pending:
  - ai/agents
"""


def test_c2_existing_commented_topic_is_not_duplicated(tmp_path: Path):
    # BUG C2: the shipped registry annotates every topic (`- agents   # ...`).
    # Promoting a pending tag whose topic already exists must clean it out of
    # pending WITHOUT appending a duplicate bare `- agents`.
    vault = tmp_path
    (vault / "brain" / "concepts").mkdir(parents=True)
    (vault / "config").mkdir()
    (vault / "config" / "tags.yaml").write_text(
        _TAGS_YAML_COMMENTED_TOPIC, encoding="utf-8"
    )
    _seed_uses(vault, "ai/agents", pt.PENDING_PROMOTION_THRESHOLD, prefix="ag")

    pt.promote_tags(vault)

    raw = (vault / "config" / "tags.yaml").read_text(encoding="utf-8")
    # Exactly one `agents` topic line under domain ai (the commented original).
    agent_lines = [ln for ln in raw.splitlines() if ln.strip().startswith("- agents")]
    assert len(agent_lines) == 1, f"duplicate topic appended: {agent_lines}"
    tags = _tags(vault)
    assert tags["domains"]["ai"].count("agents") == 1
    assert "ai/agents" not in (tags.get("pending") or [])


_TAGS_YAML_QUOTED_PENDING = """\
domains:
  ai:
    - agents
synonyms:
  machine-learning: ai/ml
pending:
  - "ai/evals"
"""


def test_c3_quoted_pending_entry_is_removed_after_promotion(tmp_path: Path):
    # BUG C3: a quoted pending item (`- "ai/evals"`) must be removed from
    # pending: when promoted, not left orphaned in both blocks.
    vault = tmp_path
    (vault / "brain" / "concepts").mkdir(parents=True)
    (vault / "config").mkdir()
    (vault / "config" / "tags.yaml").write_text(
        _TAGS_YAML_QUOTED_PENDING, encoding="utf-8"
    )
    _seed_uses(vault, "ai/evals", pt.PENDING_PROMOTION_THRESHOLD, prefix="ev")

    pt.promote_tags(vault)

    tags = _tags(vault)
    assert "evals" in tags["domains"]["ai"]
    assert not (tags.get("pending") or []), "quoted pending entry left behind"


def test_c3_headless_parser_strips_quotes_from_pending():
    # BUG C3 (headless path): the no-PyYAML fallback parser must yield the same
    # unquoted token PyYAML would, so promotion counting/removal stays in lockstep.
    reg = vb._parse_tag_registry_lines(_TAGS_YAML_QUOTED_PENDING)
    assert "ai/evals" in reg.pending
    assert '"ai/evals"' not in reg.pending


_TAGS_YAML_ALIAS_PENDING = """\
domains:
  ai:
    - agents
synonyms:
  agentic: ai/agents
pending:
  - agentic
"""


def test_c4_synonym_alias_is_never_promoted(tmp_path: Path):
    # BUG C4: a pending tag that is also a synonyms alias must NOT be promoted
    # into a bogus top-level domain that contradicts the synonyms map.
    vault = tmp_path
    (vault / "brain" / "concepts").mkdir(parents=True)
    (vault / "config").mkdir()
    (vault / "config" / "tags.yaml").write_text(
        _TAGS_YAML_ALIAS_PENDING, encoding="utf-8"
    )
    # Even if the alias recurs across many concepts, it stays put.
    _seed_uses(vault, "agentic", pt.PENDING_PROMOTION_THRESHOLD + 1, prefix="agc")

    result = pt.promote_tags(vault)

    tags = _tags(vault)
    assert "agentic" not in tags["domains"], "alias forked into a new domain"
    assert "agentic" not in result.promoted
    assert tags["synonyms"] == {"agentic": "ai/agents"}


# A bare pending tag whose name COINCIDES with an existing domain topic. The
# domain topic line (`    - robotics` under `ai`) sits ABOVE the pending block,
# so an unscoped "delete the first `- robotics`" removes the wrong line.
_TAGS_YAML_TOPIC_NAME_COLLIDES_PENDING = """\
domains:
  ai:
    - agents
    - robotics
  pkm:
    - notes
synonyms:
  machine-learning: ai/ml
pending:
  - robotics
"""


def test_bare_pending_does_not_delete_homonymous_domain_topic(tmp_path: Path):
    # BUG (BACKLOG latent edge): _remove_pending_entry must scope its deletion to
    # the `pending:` block. A bare pending tag (`robotics`) whose name equals an
    # existing domain *topic* (`ai/robotics`) previously deleted that topic line —
    # the first `- robotics` ANYWHERE in the file — instead of the pending entry.
    vault = tmp_path
    (vault / "brain" / "concepts").mkdir(parents=True)
    (vault / "config").mkdir()
    (vault / "config" / "tags.yaml").write_text(
        _TAGS_YAML_TOPIC_NAME_COLLIDES_PENDING, encoding="utf-8"
    )
    _seed_uses(vault, "robotics", pt.PENDING_PROMOTION_THRESHOLD, prefix="rob")

    pt.promote_tags(vault)

    tags = _tags(vault)
    # The pre-existing domain topic must survive the promotion.
    assert "robotics" in tags["domains"]["ai"], "homonymous domain topic deleted"
    # The bare tag is still promoted to a new top-level domain.
    assert "robotics" in tags["domains"]
    # And the pending entry itself is gone (removed from the pending block).
    assert "robotics" not in (tags.get("pending") or [])
