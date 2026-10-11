"""Validator coverage for the YAML sources/topics config format (CONVENTIONS §2.3).

YAML-only since 0.8.0: config/sources.yaml + config/topics.yaml are THE config
(schema_version 2); the retired .md tables survive only as migrate-config input.
validate_config must (a) validate the YAML twins, (b) ERROR on an unmigrated
legacy dir (real .md content, no YAML) naming `schema.py migrate-config`,
(c) WARN when a leftover .md next to the YAML disagrees with it (a hand-edited
stale fallback is the classic trap), and (d) WARN on a half-state (exactly one
YAML twin). Skips cleanly without PyYAML.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

yaml = pytest.importorskip("yaml", reason="PyYAML required for config schema tests")

from scripts import schema, validate_config  # noqa: E402
from scripts.config_validation import cli as config_cli  # noqa: E402

SHIPPED_CONFIG = _PROJECT_ROOT / "config"

_SOURCES_YAML = """schema_version: 2
categories:
  - name: ai-agents
    sources:
      - url: "https://a.example/feed.xml"
        type: rss
        tier: high
        priority: medium
        filter: "all posts"
        active: true
"""

_TOPICS_YAML = """schema_version: 2
topics:
  - name: ai-agents
    tags: [ai, agents]
    include: "Agent things."
    exclude: "Hype."
"""

# The md view of the SAME config (agreeing names + urls).
_SOURCES_MD = (
    "## Category: ai-agents\n\n"
    "### Active sources\n\n"
    "| URL | Type | Tier | Priority | Filter | Active |\n"
    "|-----|------|------|----------|--------|--------|\n"
    "| https://a.example/feed.xml | rss | high | medium | all posts | yes |\n"
)
_TOPICS_MD = "## Topic: ai-agents\n\n- **Name:** `ai-agents`\n"

# Template-only .md furniture (the shape the pre-0.8.0 archives shipped and the
# `*.example-starter.md` packs still use): EXAMPLE-marked rows, no real source.
_TEMPLATE_SOURCES_MD = (
    "## Category: example-topic\n\n"
    "### Active sources\n\n"
    "| URL | Type | Tier | Priority | Filter | Active |\n"
    "|-----|------|------|----------|--------|--------|\n"
    "| https://example.com/feed.xml | rss | high | medium | all | yes |"
    "  <!-- # EXAMPLE — replace -->\n"
)
_TEMPLATE_TOPICS_MD = (
    "## Topic: example-topic\n\n"
    "<!-- # EXAMPLE — replace -->\n\n"
    "- **Name:** `example-topic`\n"
)


def _write_yaml_pair(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "sources.yaml").write_text(_SOURCES_YAML, encoding="utf-8")
    (config_dir / "topics.yaml").write_text(_TOPICS_YAML, encoding="utf-8")


def _full_yaml_config(tmp_path: Path) -> Path:
    """A complete config dir in YAML mode (shipped channels/schedule/tags)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in ("channels.yaml", "schedule.yaml", "tags.yaml"):
        (config_dir / name).write_text(
            (SHIPPED_CONFIG / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    _write_yaml_pair(config_dir)
    return config_dir


# ── validate_sources_yaml / validate_topics_yaml ──────────────────────────────


def test_valid_sources_yaml_passes(tmp_path: Path) -> None:
    _write_yaml_pair(tmp_path)
    assert validate_config.validate_sources_yaml(tmp_path / "sources.yaml", yaml) == []
    assert validate_config.validate_topics_yaml(tmp_path / "topics.yaml", yaml) == []


def test_missing_sources_yaml_is_an_error(tmp_path: Path) -> None:
    errors = validate_config.validate_sources_yaml(tmp_path / "sources.yaml", yaml)
    assert any("not found" in e for e in errors), errors


@pytest.mark.parametrize(
    "body, fragment",
    [
        ("categories: 3\n", "list"),
        ("categories:\n  - sources: []\n", "name"),
        (
            "categories:\n  - name: t\n    sources:\n      - type: rss\n",
            "url",
        ),
        (
            "categories:\n  - name: t\n    sources:\n"
            "      - url: \"ftp://x/f\"\n        type: rss\n",
            "http",
        ),
        (
            "categories:\n  - name: t\n    sources:\n"
            "      - url: \"https://x/f\"\n        type: telegraph\n",
            "type",
        ),
        (
            "categories:\n  - name: t\n    sources:\n"
            "      - url: \"https://x/f\"\n        tier: platinum\n",
            "tier",
        ),
        (
            "categories:\n  - name: t\n    sources:\n"
            "      - url: \"https://x/f\"\n        priority: urgent\n",
            "priority",
        ),
        (
            "categories:\n  - name: t\n    sources:\n"
            "      - url: \"https://x/f\"\n        active: \"yes\"\n",
            "active",
        ),
        ("categories:\n  - name: Bad Name\n    sources: []\n", "name"),
    ],
)
def test_malformed_sources_yaml_fails(tmp_path: Path, body: str, fragment: str) -> None:
    (tmp_path / "sources.yaml").write_text(body, encoding="utf-8")
    errors = validate_config.validate_sources_yaml(tmp_path / "sources.yaml", yaml)
    assert errors, f"expected errors for: {body!r}"
    assert any(fragment in e for e in errors), (fragment, errors)


@pytest.mark.parametrize(
    "body, fragment",
    [
        ("topics: 3\n", "list"),
        ("topics:\n  - tags: [x]\n", "name"),
        ("topics:\n  - name: t\n    tags: not-a-list\n", "tags"),
        ("topics:\n  - name: Bad Name\n", "name"),
    ],
)
def test_malformed_topics_yaml_fails(tmp_path: Path, body: str, fragment: str) -> None:
    (tmp_path / "topics.yaml").write_text(body, encoding="utf-8")
    errors = validate_config.validate_topics_yaml(tmp_path / "topics.yaml", yaml)
    assert errors and any(fragment in e for e in errors), (fragment, errors)


def test_empty_yaml_config_is_schema_valid(tmp_path: Path) -> None:
    # `categories: []` / `topics: []` is the freshly-initialized (pre-wizard)
    # state — schema-valid; "nothing monitored yet" is doctor/status's message.
    (tmp_path / "sources.yaml").write_text("categories: []\n", encoding="utf-8")
    (tmp_path / "topics.yaml").write_text("topics: []\n", encoding="utf-8")
    assert validate_config.validate_sources_yaml(tmp_path / "sources.yaml", yaml) == []
    assert validate_config.validate_topics_yaml(tmp_path / "topics.yaml", yaml) == []


# ── the topics<->sources name sync check is format-aware ─────────────────────


def test_sync_check_works_across_yaml_files(tmp_path: Path) -> None:
    (tmp_path / "sources.yaml").write_text(
        "categories:\n  - name: only-in-sources\n    sources: []\n", encoding="utf-8"
    )
    (tmp_path / "topics.yaml").write_text(
        "topics:\n  - name: only-in-topics\n", encoding="utf-8"
    )
    warnings = validate_config.check_topics_sources_sync(
        tmp_path / "topics.yaml", tmp_path / "sources.yaml"
    )
    assert any("only-in-topics" in w for w in warnings)
    assert any("only-in-sources" in w for w in warnings)


# ── both-formats coexistence warnings ─────────────────────────────────────────


def test_agreeing_md_and_yaml_produce_no_format_warning(tmp_path: Path) -> None:
    _write_yaml_pair(tmp_path)
    (tmp_path / "sources.md").write_text(_SOURCES_MD, encoding="utf-8")
    (tmp_path / "topics.md").write_text(_TOPICS_MD, encoding="utf-8")
    assert validate_config.check_config_format_sync(tmp_path) == []


def test_disagreeing_md_is_warned_as_stale(tmp_path: Path) -> None:
    _write_yaml_pair(tmp_path)
    (tmp_path / "sources.md").write_text(
        _SOURCES_MD + "| https://only-in-md.example/f | rss | low | low | x | yes |\n",
        encoding="utf-8",
    )
    (tmp_path / "topics.md").write_text(_TOPICS_MD, encoding="utf-8")
    warnings = validate_config.check_config_format_sync(tmp_path)
    assert any("sources.md" in w and "sources.yaml" in w for w in warnings), warnings


def test_pristine_template_md_next_to_yaml_is_not_stale(tmp_path: Path) -> None:
    # A migrated install may keep pristine template .md files next to the active
    # YAML (pre-0.8.0 leftovers) — template placeholders are furniture, not a
    # disagreement.
    _write_yaml_pair(tmp_path)
    (tmp_path / "sources.md").write_text(_TEMPLATE_SOURCES_MD, encoding="utf-8")
    (tmp_path / "topics.md").write_text(_TEMPLATE_TOPICS_MD, encoding="utf-8")
    # The template only carries EXAMPLE sections → no real md view.
    warnings = validate_config.check_config_format_sync(tmp_path)
    assert warnings == [], warnings


def test_half_state_is_warned(tmp_path: Path) -> None:
    (tmp_path / "sources.yaml").write_text(_SOURCES_YAML, encoding="utf-8")
    warnings = validate_config.check_config_format_sync(tmp_path)
    assert any("topics.yaml" in w for w in warnings), warnings


# ── feed-URL extraction reads the active format ───────────────────────────────


def test_extract_source_urls_from_yaml(tmp_path: Path) -> None:
    (tmp_path / "sources.yaml").write_text(
        "categories:\n"
        "  - name: t\n"
        "    sources:\n"
        "      - url: \"https://live.example/feed\"\n"
        "        active: true\n"
        "      - url: \"https://paused.example/feed\"\n"
        "        active: false\n",
        encoding="utf-8",
    )
    urls = validate_config.extract_source_urls(tmp_path / "sources.yaml")
    assert urls == ["https://live.example/feed"]


# ── the CLI validates whichever format is active ──────────────────────────────


def test_cli_validates_yaml_mode_config(tmp_path: Path, capsys) -> None:
    config_dir = _full_yaml_config(tmp_path)
    code = config_cli.run(validate_config, [str(config_dir)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "sources.yaml" in out and "topics.yaml" in out


def test_cli_fails_on_malformed_yaml_sources(tmp_path: Path, capsys) -> None:
    config_dir = _full_yaml_config(tmp_path)
    (config_dir / "sources.yaml").write_text("categories: 3\n", encoding="utf-8")
    code = config_cli.run(validate_config, [str(config_dir)])
    out = capsys.readouterr().out
    assert code == 1
    assert "sources.yaml" in out


def test_cli_warns_on_stale_md_next_to_yaml(tmp_path: Path, capsys) -> None:
    config_dir = _full_yaml_config(tmp_path)
    (config_dir / "sources.md").write_text(
        _SOURCES_MD + "| https://only-in-md.example/f | rss | low | low | x | yes |\n",
        encoding="utf-8",
    )
    (config_dir / "topics.md").write_text(_TOPICS_MD, encoding="utf-8")
    code = config_cli.run(validate_config, [str(config_dir)])
    out = capsys.readouterr().out
    assert code == 0  # advisory, never fatal
    assert "WARN" in out and "sources.md" in out


def test_cli_warns_when_sources_yaml_is_stamped_newer(tmp_path: Path, capsys) -> None:
    config_dir = _full_yaml_config(tmp_path)
    newer = schema.CURRENT["sources"] + 1
    (config_dir / "sources.yaml").write_text(
        _SOURCES_YAML.replace("schema_version: 2", f"schema_version: {newer}"),
        encoding="utf-8",
    )
    code = config_cli.run(validate_config, [str(config_dir)])
    out = capsys.readouterr().out
    assert code == 0
    assert "NEWER" in out


def test_cli_rejects_unmigrated_legacy_md_config(tmp_path: Path, capsys) -> None:
    # Real .md content with no YAML twins is an unmigrated legacy install: since
    # 0.8.0 the CLI must FAIL loudly with the one-command migrate-config pointer
    # (never silently validate config the runtime no longer reads).
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in ("channels.yaml", "schedule.yaml", "tags.yaml"):
        (config_dir / name).write_text(
            (SHIPPED_CONFIG / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (config_dir / "sources.md").write_text(_SOURCES_MD, encoding="utf-8")
    (config_dir / "topics.md").write_text(_TOPICS_MD, encoding="utf-8")
    code = config_cli.run(validate_config, [str(config_dir)])
    out = capsys.readouterr().out
    assert code == 1, out
    assert "migrate-config" in out
    assert "sources.md" in out
    # Surfaced only — validation never auto-writes the YAML twins.
    assert not (config_dir / "sources.yaml").exists()
    assert not (config_dir / "topics.yaml").exists()


# ── placeholder scan ignores the dormant md fallback ──────────────────────────


def test_placeholder_scan_skips_md_when_yaml_twin_exists(tmp_path: Path) -> None:
    # A migrated install may keep its template-ish .md leftover; the "config is
    # still a template" WARN must key on the ACTIVE format only.
    (tmp_path / "sources.md").write_text(_TEMPLATE_SOURCES_MD, encoding="utf-8")
    (tmp_path / "sources.yaml").write_text(_SOURCES_YAML, encoding="utf-8")
    assert "sources.md" not in validate_config.detect_placeholders(tmp_path)
    # Without the twin the template markers surface again (a pre-0.8.0 template
    # dir — the CLI errors on it via the legacy check before this WARN matters).
    (tmp_path / "sources.yaml").unlink()
    assert "sources.md" in validate_config.detect_placeholders(tmp_path)


def test_inline_secret_scan_covers_yaml_config(tmp_path: Path) -> None:
    (tmp_path / "sources.yaml").write_text(
        'categories: []\napi_key: "' + 'abcdefghijklmnop' + '123456"\n', encoding="utf-8"
    )
    errors = validate_config.detect_inline_secrets(tmp_path)
    assert any("sources.yaml" in e for e in errors), errors
