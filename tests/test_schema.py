"""Tests for scripts/schema.py — the schema-version contract for future migrations.

Every frontmatter-bearing artifact (concept/lesson/playbook/author/article) and the YAML configs
carry a flat top-level `schema_version:`. A missing stamp means the baseline
version (1) — every file already deployed predates the stamp, so absence must NOT
read as "unknown / needs migration". The reader is deliberately FLAT (line-based)
so it works in the headless no-PyYAML path and never trips over nested frontmatter.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

from scripts import schema  # noqa: E402

# ── read_schema_version ───────────────────────────────────────────────────────


def test_reads_flat_stamp():
    text = "---\ntitle: X\nschema_version: 3\ntype: concept\n---\n\nbody\n"
    assert schema.read_schema_version(text) == 3


def test_missing_stamp_is_baseline():
    # A file with no stamp is the baseline (1) — NOT unknown. Every pre-stamp file
    # already deployed relies on this.
    text = "---\ntitle: X\ntype: concept\n---\n\nbody\n"
    assert schema.read_schema_version(text) == schema.BASELINE == 1


def test_ignores_nested_lookalike_key():
    # A `schema_version` that appears INDENTED (inside a nested block) is not the
    # top-level artifact stamp and must be ignored — only a column-0 key counts.
    text = "---\ntitle: X\nmeta:\n  schema_version: 9\n---\n\nbody\n"
    assert schema.read_schema_version(text) == schema.BASELINE


def test_reads_quoted_value():
    text = '---\nschema_version: "2"\n---\nbody\n'
    assert schema.read_schema_version(text) == 2


def test_no_frontmatter_is_baseline():
    assert schema.read_schema_version("just a body, no fences\n") == schema.BASELINE


def test_body_col0_lookalike_is_not_read_as_stamp():
    # A col-0 `schema_version:` in the BODY (e.g. a note discussing schemas in a
    # fenced code block) must NOT be read as the frontmatter stamp.
    text = "---\ntitle: X\n---\n\n```\nschema_version: 7\n```\n"
    assert schema.read_schema_version(text) == schema.BASELINE


def test_fenceless_config_reads_whole_text():
    # A config YAML has no `---` fences — its whole body is the scope.
    assert schema.read_schema_version("delivery:\n  x: 1\nschema_version: 4\n") == 4


def test_non_integer_stamp_is_baseline():
    # A malformed stamp degrades to the baseline rather than crashing a scan.
    text = "---\nschema_version: not-a-number\n---\nbody\n"
    assert schema.read_schema_version(text) == schema.BASELINE


# ── drift_warning ─────────────────────────────────────────────────────────────


def test_current_version_has_no_warning():
    assert schema.drift_warning("concept", schema.CURRENT["concept"]) is None


def test_missing_or_older_has_no_warning():
    # Older/baseline is fine — it will be migrated when a migrator exists; not a
    # warning today.
    assert schema.drift_warning("concept", 1) is None


def test_newer_than_code_warns():
    # A file stamped NEWER than this code understands is the risky direction (old
    # code silently misreading a new-schema file) — that must warn.
    newer = schema.CURRENT["concept"] + 1
    msg = schema.drift_warning("concept", newer)
    assert msg is not None
    assert "newer" in msg.lower()


def test_unknown_kind_raises():
    with pytest.raises(KeyError):
        schema.drift_warning("nonexistent-kind", 1)


# ── scan_paths_for_drift (the shared validator hook) ──────────────────────────


def test_scan_flags_only_newer_files(tmp_path: Path) -> None:
    newer = tmp_path / "future.md"
    baseline = tmp_path / "ok.md"
    missing_stamp = tmp_path / "legacy.md"
    newer.write_text(f"---\nschema_version: {schema.CURRENT['concept'] + 1}\n---\n", encoding="utf-8")
    baseline.write_text(f"---\nschema_version: {schema.CURRENT['concept']}\n---\n", encoding="utf-8")
    missing_stamp.write_text("---\ntitle: X\n---\n", encoding="utf-8")

    warnings = schema.scan_paths_for_drift(
        [newer, baseline, missing_stamp], "concept"
    )
    assert len(warnings) == 1
    assert warnings[0].startswith("future.md:")
    assert "newer" in warnings[0].lower()


def test_scan_skips_unreadable(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.md"
    assert schema.scan_paths_for_drift([missing], "config") == []


# ── CURRENT registry ──────────────────────────────────────────────────────────


def test_current_covers_the_artifact_classes():
    for kind in ("concept", "lesson", "playbook", "article", "config", "sources", "topics"):
        assert kind in schema.CURRENT
        assert schema.CURRENT[kind] >= 1


def test_sources_and_topics_are_at_schema_two():
    # Version 1 = the legacy .md pipe-table format; version 2 = the YAML twins.
    assert schema.CURRENT["sources"] == 2
    assert schema.CURRENT["topics"] == 2


# ── shipped artifacts carry a current, flat, readable stamp ───────────────────


@pytest.mark.parametrize(
    "relpath, kind",
    [
        ("templates/article-template.md", "article"),
        ("brain/concept-template.md", "concept"),
        ("brain/lesson-template.md", "lesson"),
        ("brain/playbook-template.md", "playbook"),
        ("brain/author-template.md", "author"),
        ("config/channels.yaml", "config"),
        ("config/schedule.yaml", "config"),
    ],
)
def test_shipped_files_carry_current_stamp(relpath: str, kind: str) -> None:
    # The templates new files inherit, and the fixed-schema configs, must carry a
    # flat stamp the reader resolves to the current version — the migration enabler
    # would be dead if a template shipped without it or nested it out of reach.
    text = (_PROJECT_ROOT / relpath).read_text(encoding="utf-8")
    assert schema.read_schema_version(text) == schema.CURRENT[kind]
    # And it must be an advisory-clean (not newer-than-code) stamp.
    assert schema.drift_warning(kind, schema.read_schema_version(text)) is None


# ── migration machinery (rehearsed while CURRENT is all-baseline) ─────────────
#
# No real migration ships yet (every CURRENT[kind] is 1). These tests register a
# synthetic (concept, 1) -> 2 transform to prove the wiring END TO END — stamping,
# chaining, idempotency, the missing-step guard, CLI — so the first real breaking
# change exercises battle-tested machinery instead of running it for the first
# time on user data.

_CONCEPT_V1 = (
    "---\n"
    "type: concept\n"
    "title: Example\n"
    "tags: [ai/agents]\n"
    "---\n\n"
    "Body.\n"
)


def _rename_type_to_kind(text: str) -> str:
    # A representative breaking transform: rename the `type:` key to `kind:`.
    return text.replace("type: concept", "kind: concept", 1)


@pytest.fixture()
def concept_v2_world(monkeypatch):
    """A world where concept schema 2 exists: CURRENT bumped + one migration step."""
    monkeypatch.setitem(schema.CURRENT, "concept", 2)
    monkeypatch.setitem(schema.MIGRATIONS, ("concept", 1), _rename_type_to_kind)


def test_stamp_inserts_into_fenced_frontmatter():
    stamped = schema.stamp_schema_version(_CONCEPT_V1, 2)
    assert schema.read_schema_version(stamped) == 2
    # The stamp lands INSIDE the frontmatter block, at column 0.
    fm = stamped.split("---")[1]
    assert "\nschema_version: 2\n" in fm


def test_stamp_replaces_existing_stamp():
    once = schema.stamp_schema_version(_CONCEPT_V1, 2)
    twice = schema.stamp_schema_version(once, 3)
    assert schema.read_schema_version(twice) == 3
    assert twice.count("schema_version:") == 1


def test_stamp_fenceless_config_prepends():
    text = "delivery:\n  language: en\n"
    stamped = schema.stamp_schema_version(text, 2)
    assert schema.read_schema_version(stamped) == 2
    assert stamped.startswith("schema_version: 2\n")


def test_migrate_text_applies_chain_and_stamps(concept_v2_world):
    new_text, from_v, to_v = schema.migrate_text(_CONCEPT_V1, "concept")
    assert (from_v, to_v) == (1, 2)
    assert "kind: concept" in new_text
    assert schema.read_schema_version(new_text) == 2
    # Post-migration the drift scan is clean.
    assert schema.drift_warning("concept", schema.read_schema_version(new_text)) is None


def test_migrate_text_is_idempotent(concept_v2_world):
    once, _, _ = schema.migrate_text(_CONCEPT_V1, "concept")
    again, from_v, to_v = schema.migrate_text(once, "concept")
    assert again == once
    assert from_v == to_v == 2


def test_migrate_text_missing_step_is_a_clear_error(monkeypatch):
    # CURRENT says 3 but only 1->2 is registered: refuse loudly, never guess.
    monkeypatch.setitem(schema.CURRENT, "concept", 3)
    monkeypatch.setitem(schema.MIGRATIONS, ("concept", 1), _rename_type_to_kind)
    with pytest.raises(schema.MigrationPathMissing) as exc:
        schema.migrate_text(_CONCEPT_V1, "concept")
    assert "(concept, 2)" in str(exc.value)


def test_migrate_text_newer_file_is_left_alone(concept_v2_world):
    newer = schema.stamp_schema_version(_CONCEPT_V1, 9)
    same, from_v, to_v = schema.migrate_text(newer, "concept")
    assert same == newer  # written by a newer release; drift_warning covers messaging
    assert from_v == to_v == 9


def test_migrate_file_writes_and_second_run_noops(tmp_path, concept_v2_world):
    note = tmp_path / "example.md"
    note.write_text(_CONCEPT_V1, encoding="utf-8")
    changed = schema.migrate_file(note, "concept")
    assert changed is True
    assert schema.read_schema_version(note.read_text(encoding="utf-8")) == 2
    assert schema.migrate_file(note, "concept") is False  # already current


def test_migrate_file_dry_run_writes_nothing(tmp_path, concept_v2_world):
    note = tmp_path / "example.md"
    note.write_text(_CONCEPT_V1, encoding="utf-8")
    changed = schema.migrate_file(note, "concept", dry_run=True)
    assert changed is True  # WOULD change
    assert note.read_text(encoding="utf-8") == _CONCEPT_V1  # untouched


def test_cli_migrate_dry_run_then_real(tmp_path, concept_v2_world, capsys):
    note = tmp_path / "example.md"
    note.write_text(_CONCEPT_V1, encoding="utf-8")
    rc = schema.main(["migrate", "concept", str(note), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "would migrate" in out and "1 -> 2" in out
    assert note.read_text(encoding="utf-8") == _CONCEPT_V1
    rc = schema.main(["migrate", "concept", str(note)])
    assert rc == 0
    assert schema.read_schema_version(note.read_text(encoding="utf-8")) == 2


def test_cli_migrate_unknown_kind_errors(tmp_path, capsys):
    note = tmp_path / "x.md"
    note.write_text(_CONCEPT_V1, encoding="utf-8")
    rc = schema.main(["migrate", "nonsense", str(note)])
    assert rc == 2
    assert "unknown kind" in capsys.readouterr().err


def test_shipped_migrations_are_exactly_the_config_format_steps():
    # The first real breaking change: the sources/topics config format moved
    # from .md pipe tables (1) to YAML (2). Nothing else ships a migration —
    # every other kind is still at its baseline (guarded so an accidental
    # registration can't hide here).
    assert set(schema.MIGRATIONS) == {("sources", 1), ("topics", 1)}
    for kind in ("concept", "lesson", "playbook", "article", "config"):
        assert schema.CURRENT[kind] == 1


# ── the first REAL migration: sources/topics .md → YAML twins ─────────────────
#
# Kind "sources"/"topics" version 1 is the legacy pipe-table markdown; version 2
# is config/sources.yaml + config/topics.yaml. The transform reads the old table
# via the shared store parser (its last duty) and emits the YAML twin, which is
# written NEXT TO the .md — the old file is never touched (read-only fallback).

_SOURCES_MD_V1 = (
    "# config/sources.md\n\n"
    "## Category: ai-agents\n\n"
    "### Active sources\n\n"
    "| URL | Type | Tier | Priority | Filter | Active |\n"
    "|-----|------|------|----------|--------|--------|\n"
    "| https://a.example/feed.xml | rss | high | medium | all posts | yes |\n"
)

_TOPICS_MD_V1 = (
    "# config/topics.md\n\n"
    "## Topic: ai-agents\n\n"
    "- **Name:** `ai-agents`\n"
    "- **Frontmatter tags:** `[ai, agents]`\n"
    "- **Include rules:** Substantive pieces about agents.\n"
    "- **Exclude rules:** Hype.\n"
)

_TEMPLATE_SOURCES_MD_V1 = (
    "## Category: example-topic\n\n"
    "> `# EXAMPLE — replace`\n\n"
    "### Active sources\n\n"
    "| URL | Type | Tier | Priority | Filter | Active |\n"
    "|-----|------|------|----------|--------|--------|\n"
    "| https://example.com/feed.xml | rss | high | high | all | yes |  <!-- # EXAMPLE — replace -->\n"
)


def _write_config_md(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "sources.md").write_text(_SOURCES_MD_V1, encoding="utf-8")
    (config_dir / "topics.md").write_text(_TOPICS_MD_V1, encoding="utf-8")


def test_sources_migration_emits_stamped_yaml_preserving_content():
    new_text, from_v, to_v = schema.migrate_text(_SOURCES_MD_V1, "sources")
    assert (from_v, to_v) == (1, 2)
    assert schema.read_schema_version(new_text) == 2
    from scripts.sources import store

    (cat,) = store.parse_sources_yaml_text(new_text)
    assert cat.name == "ai-agents"
    (src,) = cat.sources
    assert (src.url, src.type, src.tier, src.priority, src.filter_note, src.active) == (
        "https://a.example/feed.xml", "rss", "high", "medium", "all posts", True,
    )


def test_topics_migration_emits_stamped_yaml_preserving_content():
    new_text, from_v, to_v = schema.migrate_text(_TOPICS_MD_V1, "topics")
    assert (from_v, to_v) == (1, 2)
    assert schema.read_schema_version(new_text) == 2
    from scripts.sources import store

    (topic,) = store.parse_topics_yaml_text(new_text)
    assert topic.name == "ai-agents"
    assert topic.tags == ["ai", "agents"]
    assert topic.include == "Substantive pieces about agents."


def test_sources_migration_drops_shipped_example_placeholders():
    new_text, _, _ = schema.migrate_text(_TEMPLATE_SOURCES_MD_V1, "sources")
    from scripts.sources import store

    assert store.parse_sources_yaml_text(new_text) == []


def test_migrate_file_for_sources_writes_the_yaml_twin_and_keeps_the_md(tmp_path):
    md = tmp_path / "sources.md"
    md.write_text(_SOURCES_MD_V1, encoding="utf-8")
    assert schema.migrate_file(md, "sources") is True
    twin = tmp_path / "sources.yaml"
    assert twin.exists()
    assert md.read_text(encoding="utf-8") == _SOURCES_MD_V1  # NEVER rewritten
    assert schema.read_schema_version(twin.read_text(encoding="utf-8")) == 2
    # Second run: the twin already exists — nothing is overwritten.
    twin.write_text(twin.read_text(encoding="utf-8") + "# user edit\n", encoding="utf-8")
    assert schema.migrate_file(md, "sources") is False
    assert "# user edit" in twin.read_text(encoding="utf-8")


def test_migrate_file_sidecar_force_regenerates_the_twin(tmp_path):
    md = tmp_path / "sources.md"
    md.write_text(_SOURCES_MD_V1, encoding="utf-8")
    twin = tmp_path / "sources.yaml"
    twin.write_text("categories: []\n", encoding="utf-8")
    assert schema.migrate_file(md, "sources", force=True) is True
    assert "https://a.example/feed.xml" in twin.read_text(encoding="utf-8")


def test_migrate_file_sidecar_dry_run_writes_nothing(tmp_path):
    md = tmp_path / "sources.md"
    md.write_text(_SOURCES_MD_V1, encoding="utf-8")
    assert schema.migrate_file(md, "sources", dry_run=True) is True
    assert not (tmp_path / "sources.yaml").exists()


def test_cli_migrate_config_creates_both_twins_and_is_idempotent(tmp_path, capsys):
    config_dir = tmp_path / "config"
    _write_config_md(config_dir)

    rc = schema.main(["migrate-config", "--config-dir", str(config_dir)])
    out = capsys.readouterr().out
    assert rc == 0
    assert (config_dir / "sources.yaml").exists()
    assert (config_dir / "topics.yaml").exists()
    # The old files are untouched — kept as the read-only fallback.
    assert (config_dir / "sources.md").read_text(encoding="utf-8") == _SOURCES_MD_V1
    assert (config_dir / "topics.md").read_text(encoding="utf-8") == _TOPICS_MD_V1
    assert "sources.yaml" in out and "topics.yaml" in out
    assert "fallback" in out.lower()

    # Re-run: both twins exist — reported as already migrated, nothing rewritten.
    before = (config_dir / "sources.yaml").read_text(encoding="utf-8")
    rc = schema.main(["migrate-config", "--config-dir", str(config_dir)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "already" in out.lower()
    assert (config_dir / "sources.yaml").read_text(encoding="utf-8") == before


def test_cli_migrate_config_dry_run_writes_nothing(tmp_path, capsys):
    config_dir = tmp_path / "config"
    _write_config_md(config_dir)
    rc = schema.main(["migrate-config", "--config-dir", str(config_dir), "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "would" in out.lower()
    assert not (config_dir / "sources.yaml").exists()
    assert not (config_dir / "topics.yaml").exists()


def test_cli_migrate_config_missing_md_is_a_clean_note_not_an_error(tmp_path, capsys):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    rc = schema.main(["migrate-config", "--config-dir", str(config_dir)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "nothing to migrate" in out.lower()


def test_cli_migrate_sources_reports_the_twin_target(tmp_path, capsys):
    md = tmp_path / "sources.md"
    md.write_text(_SOURCES_MD_V1, encoding="utf-8")
    rc = schema.main(["migrate", "sources", str(md)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "sources.yaml" in out and "1 -> 2" in out
    assert (tmp_path / "sources.yaml").exists()
    assert md.read_text(encoding="utf-8") == _SOURCES_MD_V1


def test_cli_migrate_write_error_is_per_file_not_a_crash(
    tmp_path, concept_v2_world, capsys, monkeypatch
):
    # A write failure on one file must be reported and counted like a read
    # failure — never a traceback, and never abort the remaining files.
    bad = tmp_path / "bad.md"
    good = tmp_path / "good.md"
    bad.write_text(_CONCEPT_V1, encoding="utf-8")
    good.write_text(_CONCEPT_V1, encoding="utf-8")

    real_write = schema._write_atomic

    def failing_write(path, text):
        if path == bad:
            raise OSError(28, "No space left on device")
        real_write(path, text)

    monkeypatch.setattr(schema, "_write_atomic", failing_write)
    rc = schema.main(["migrate", "concept", str(bad), str(good)])
    captured = capsys.readouterr()
    assert rc == 1  # the failure is reflected in the exit code
    assert "bad.md" in captured.err
    assert "good.md: migrated 1 -> 2" in captured.out  # later files still processed
    assert schema.read_schema_version(good.read_text(encoding="utf-8")) == 2


def test_migrate_config_works_as_a_direct_script(tmp_path):
    # The documented invocation is `python3 scripts/schema.py migrate-config` —
    # run as a DIRECT script (sys.path[0] = scripts/, no repo root on the path),
    # exactly how update.sh's offer and the skills tell the user to run it. The
    # lazy store import must bootstrap the repo root like _write_atomic does.
    import subprocess

    config_dir = tmp_path / "config"
    _write_config_md(config_dir)
    result = subprocess.run(
        [
            sys.executable,
            str(_PROJECT_ROOT / "scripts" / "schema.py"),
            "migrate-config",
            "--config-dir",
            str(config_dir),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,  # deliberately NOT the repo root
    )
    assert result.returncode == 0, result.stderr
    assert (config_dir / "sources.yaml").exists()
    assert (config_dir / "topics.yaml").exists()
