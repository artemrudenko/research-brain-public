"""Tests for scripts/sources/store.py — the single loader for the sources/topics
config in BOTH formats (config/sources.yaml + config/topics.yaml preferred,
config/sources.md + config/topics.md legacy fallback).

The store is the one seam every reader flips through for the YAML migration
(BACKLOG: "sources.md/topics.md → YAML"): format resolution (YAML wins when
present), format-dispatching parsers, and the deterministic YAML emitters the
migrator + manage_sources write with.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml as pyyaml

from scripts.sources import store  # noqa: E402
from scripts.sources.model import Category, Source, Topic  # noqa: E402

# ── fixtures: one config in each format, same semantic content ────────────────

_SOURCES_MD = """# config/sources.md

## Category: ai-agents

**Save folder:** `pipeline/1-incoming/ai-agents/`

### Active sources

| URL | Type | Tier | Priority | Filter | Active |
|-----|------|------|----------|--------|--------|
| https://a.example/feed.xml | rss | high | medium | all posts | yes |
| https://b.example/feed.xml | rss | low | low | mixed quality | no |

### Filter rules
Include: agent things.
Exclude: everything else.

## Category: tech-news

### Active sources

| URL | Type | Tier | Priority | Filter | Active |
|-----|------|------|----------|--------|--------|
| https://c.example/rss | rss | medium | high | news | yes |
"""

_TOPICS_MD = """# config/topics.md

## Topic: ai-agents

- **Name:** `ai-agents`
- **Save folder:** `pipeline/1-incoming/ai-agents/`
- **Frontmatter tags:** `[ai, agents]`
- **Include rules:** Substantive pieces directly about agents — deep dives,
  announcements with real content.
- **Exclude rules:** Hype with no substance.

## Topic: tech-news

- **Name:** `tech-news`
- **Frontmatter tags:** `[tech]`
- **Include rules:** Tech industry news.
- **Exclude rules:** Marketing.
"""

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
      - url: "https://b.example/feed.xml"
        type: rss
        tier: low
        priority: low
        filter: "mixed quality"
        active: false
  - name: tech-news
    sources:
      - url: "https://c.example/rss"
        type: rss
        tier: medium
        priority: high
        filter: "news"
        active: true
"""

_TOPICS_YAML = """schema_version: 2
topics:
  - name: ai-agents
    tags: [ai, agents]
    include: "Substantive pieces directly about agents — deep dives, announcements with real content."
    exclude: "Hype with no substance."
  - name: tech-news
    tags: [tech]
    include: "Tech industry news."
    exclude: "Marketing."
"""

# The shipped template shape: EXAMPLE-marked section + example rows only.
_TEMPLATE_SOURCES_MD = """# config/sources.md — Source registry

## Category: example-topic

> `# EXAMPLE — replace`

### Active sources

| URL | Type | Tier | Priority | Filter | Active |
|-----|------|------|----------|--------|--------|
| https://example.com/feed.xml | rss | high | high | all articles | yes |  <!-- # EXAMPLE — replace -->
"""

_TEMPLATE_TOPICS_MD = """# config/topics.md — Monitored topics

## Topic: example-topic

> `# EXAMPLE — replace`

- **Name:** `example-topic`
- **Frontmatter tags:** `[example, replace-me]`
- **Include rules:** Articles about the subject you want to track.
- **Exclude rules:** Off-topic content.
"""


# ── active-path resolution (YAML wins when present) ───────────────────────────


def test_active_paths_prefer_yaml_when_present(tmp_path: Path) -> None:
    (tmp_path / "sources.md").write_text(_SOURCES_MD, encoding="utf-8")
    (tmp_path / "sources.yaml").write_text(_SOURCES_YAML, encoding="utf-8")
    (tmp_path / "topics.yaml").write_text(_TOPICS_YAML, encoding="utf-8")
    assert store.active_sources_path(tmp_path) == tmp_path / "sources.yaml"
    assert store.active_topics_path(tmp_path) == tmp_path / "topics.yaml"


# ── parsers: the md parser (migrator-only) matches the YAML model ─────────────


def test_md_parser_and_yaml_loader_produce_the_same_categories(tmp_path: Path) -> None:
    # The retired-format PARSER stays correct — schema.py migrate-config depends
    # on it producing exactly what the YAML loader reads back.
    yml = tmp_path / "sources.yaml"
    yml.write_text(_SOURCES_YAML, encoding="utf-8")
    assert store.parse_categories_md(_SOURCES_MD) == store.load_categories(yml)


def test_load_categories_yaml_shape(tmp_path: Path) -> None:
    yml = tmp_path / "sources.yaml"
    yml.write_text(_SOURCES_YAML, encoding="utf-8")
    cats = store.load_categories(yml)
    assert [c.name for c in cats] == ["ai-agents", "tech-news"]
    first = cats[0].sources[0]
    assert first == Source(
        url="https://a.example/feed.xml",
        type="rss",
        tier="high",
        priority="medium",
        filter_note="all posts",
        active=True,
    )
    assert cats[0].sources[1].active is False


def test_load_topics_yaml_shape(tmp_path: Path) -> None:
    yml = tmp_path / "topics.yaml"
    yml.write_text(_TOPICS_YAML, encoding="utf-8")
    topics = store.load_topics(yml)
    assert [t.name for t in topics] == ["ai-agents", "tech-news"]
    assert topics[0].tags == ["ai", "agents"]
    assert topics[0].include.startswith("Substantive pieces")
    assert topics[0].exclude == "Hype with no substance."


def test_md_topics_parser_extracts_tags_and_rules(tmp_path: Path) -> None:
    topics = store.parse_topics_md(_TOPICS_MD)
    assert [t.name for t in topics] == ["ai-agents", "tech-news"]
    assert topics[0].tags == ["ai", "agents"]
    # Wrapped bullet lines are joined into one prose value.
    assert "deep dives, announcements with real content." in topics[0].include
    assert "\n" not in topics[0].include


def test_yaml_source_defaults_are_filled_for_minimal_entries(tmp_path: Path) -> None:
    # Additive-friendly: a minimal hand-added entry gets the documented defaults
    # (rss / medium / medium / active) rather than being silently dropped.
    yml = tmp_path / "sources.yaml"
    yml.write_text(
        "categories:\n  - name: t\n    sources:\n      - url: https://x.example/f\n",
        encoding="utf-8",
    )
    (src,) = store.load_categories(yml)[0].sources
    assert (src.type, src.tier, src.priority, src.active) == ("rss", "medium", "medium", True)
    assert src.filter_note == "—"


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("categories: 3\n", "categories"),
        ("categories:\n  - sources: []\n", "name"),
        ("categories:\n  - name: t\n    sources:\n      - type: rss\n", "url"),
        ("categories:\n  - name: t\n    sources:\n      - url: https://x/f\n        active: maybe\n", "active"),
        ("- just\n- a list\n", "mapping"),
    ],
)
def test_malformed_sources_yaml_raises_value_error(tmp_path: Path, text: str, fragment: str) -> None:
    yml = tmp_path / "sources.yaml"
    yml.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=fragment):
        store.load_categories(yml)


def test_malformed_topics_yaml_raises_value_error(tmp_path: Path) -> None:
    yml = tmp_path / "topics.yaml"
    yml.write_text("topics:\n  - tags: [x]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="name"):
        store.load_topics(yml)


def test_skip_examples_drops_shipped_placeholders_only() -> None:
    cats = store.parse_categories_md(_TEMPLATE_SOURCES_MD, skip_examples=True)
    assert cats == []
    topics = store.parse_topics_md(_TEMPLATE_TOPICS_MD, skip_examples=True)
    assert topics == []
    # Real sections (no EXAMPLE marker) always survive the skip.
    real = store.parse_categories_md(_SOURCES_MD, skip_examples=True)
    assert [c.name for c in real] == ["ai-agents", "tech-news"]


def test_skip_examples_keeps_example_category_that_gained_real_rows() -> None:
    # A real row added under the shipped example heading must never be dropped.
    text = _TEMPLATE_SOURCES_MD + "| https://real.example/feed | rss | high | high | mine | yes |\n"
    cats = store.parse_categories_md(text, skip_examples=True)
    assert [c.name for c in cats] == ["example-topic"]
    assert [s.url for s in cats[0].sources] == ["https://real.example/feed"]


# ── emitters: deterministic YAML that round-trips ─────────────────────────────


def test_dump_sources_yaml_round_trips(tmp_path: Path) -> None:
    original = store.parse_categories_md(_SOURCES_MD)
    text = store.dump_sources_yaml(original)
    out = tmp_path / "sources.yaml"
    out.write_text(text, encoding="utf-8")
    assert store.load_categories(out) == original
    # The emitted text is real YAML (PyYAML agrees) and carries the format stamp.
    data = pyyaml.safe_load(text)
    assert data["schema_version"] == 2
    assert [c["name"] for c in data["categories"]] == ["ai-agents", "tech-news"]


def test_dump_topics_yaml_round_trips(tmp_path: Path) -> None:
    original = store.parse_topics_md(_TOPICS_MD)
    text = store.dump_topics_yaml(original)
    out = tmp_path / "topics.yaml"
    out.write_text(text, encoding="utf-8")
    assert store.load_topics(out) == original
    assert pyyaml.safe_load(text)["schema_version"] == 2


def test_dump_sources_yaml_escapes_hostile_scalars(tmp_path: Path) -> None:
    # A filter note with YAML-significant characters must not corrupt the file.
    hostile = Category(
        name="t",
        sources=[
            Source(
                url="https://x.example/f?a=1&b=2",
                type="rss",
                tier="high",
                priority="low",
                filter_note='note: with "quotes", #hash and: colons',
                active=True,
            )
        ],
    )
    out = tmp_path / "sources.yaml"
    out.write_text(store.dump_sources_yaml([hostile]), encoding="utf-8")
    (parsed,) = store.load_categories(out)
    assert parsed == hostile


def test_dump_empty_config_is_valid_yaml(tmp_path: Path) -> None:
    src = tmp_path / "sources.yaml"
    src.write_text(store.dump_sources_yaml([]), encoding="utf-8")
    assert store.load_categories(src) == []
    top = tmp_path / "topics.yaml"
    top.write_text(store.dump_topics_yaml([]), encoding="utf-8")
    assert store.load_topics(top) == []


def test_topic_model_defaults_keep_old_constructor_working() -> None:
    # Existing callers construct Topic(name=...) — the YAML fields are additive.
    topic = Topic(name="x")
    assert (topic.tags, topic.include, topic.exclude) == ([], "", "")


def test_yaml_source_defaults_stay_inside_the_shared_enums() -> None:
    # The minimal-entry defaults must be values the validators accept.
    assert store.source_defaults_are_valid()


# --------------------------------------------------------------------------- #
# 0.8.0: the .md read path is RETIRED (BACKLOG item 1 — the 0.7.0 migration
# kept it "for one minor version"). YAML is the only config format the runtime
# reads; the .md parsers survive solely inside the migrator; an unmigrated
# legacy install fails LOUDLY with the migrate-config pointer, never silently.
# --------------------------------------------------------------------------- #

REAL_SOURCES_MD = """## Category: ai-agents

| URL | Type | Tier | Priority | Filter | Active |
|---|---|---|---|---|---|
| https://example.com/feed.xml | rss | high | medium | all | yes |
"""

REAL_TOPICS_MD = """## Topic: ai-agents

- **Frontmatter tags:** [ai/agents]
- **Include rules:** everything
- **Exclude rules:** nothing
"""


def test_active_paths_are_always_yaml(tmp_path):
    # No files at all -> still the YAML names (there is no other mode).
    assert store.active_sources_path(tmp_path).name == "sources.yaml"
    assert store.active_topics_path(tmp_path).name == "topics.yaml"
    # Even with a legacy .md present and no twin.
    (tmp_path / "sources.md").write_text(REAL_SOURCES_MD, encoding="utf-8")
    assert store.active_sources_path(tmp_path).name == "sources.yaml"


def test_prefer_yaml_twin_always_resolves_md_to_yaml(tmp_path):
    md = tmp_path / "sources.md"
    md.write_text(REAL_SOURCES_MD, encoding="utf-8")
    # No twin on disk: STILL the yaml path, so every downstream error names
    # the file the runtime actually reads.
    assert store.prefer_yaml_twin(md).name == "sources.yaml"


def test_loaders_refuse_md_with_migrate_pointer(tmp_path):
    md = tmp_path / "sources.md"
    md.write_text(REAL_SOURCES_MD, encoding="utf-8")
    with pytest.raises(ValueError, match="migrate-config"):
        store.load_categories(md)
    tmd = tmp_path / "topics.md"
    tmd.write_text(REAL_TOPICS_MD, encoding="utf-8")
    with pytest.raises(ValueError, match="migrate-config"):
        store.load_topics(tmd)


def test_legacy_md_needs_migration_detection(tmp_path):
    # Nothing at all -> fresh install, no migration needed.
    assert store.legacy_md_needs_migration(tmp_path) is False
    # Real .md content, no YAML -> the unmigrated-legacy state.
    (tmp_path / "sources.md").write_text(REAL_SOURCES_MD, encoding="utf-8")
    assert store.legacy_md_needs_migration(tmp_path) is True
    # Once the YAML twins exist the .md is a stale leftover, not a blocker.
    (tmp_path / "sources.yaml").write_text("schema_version: 2\ncategories: []\n", encoding="utf-8")
    (tmp_path / "topics.yaml").write_text("schema_version: 2\ntopics: []\n", encoding="utf-8")
    assert store.legacy_md_needs_migration(tmp_path) is False


def test_example_only_md_is_not_a_migration_blocker(tmp_path):
    # The shipped template's EXAMPLE rows are not user data — a dir that still
    # carries the old template (real markers and all) must read as fresh.
    template = (
        Path(__file__).resolve().parent / "fixtures" / "example_config" / "sources.md"
    ).read_text(encoding="utf-8")
    (tmp_path / "sources.md").write_text(template, encoding="utf-8")
    assert store.legacy_md_needs_migration(tmp_path) is False


def test_ensure_yaml_config_seeds_empty_twins(tmp_path):
    created = store.ensure_yaml_config(tmp_path)
    assert created is True
    cats = store.load_categories(tmp_path / "sources.yaml")
    topics = store.load_topics(tmp_path / "topics.yaml")
    assert cats == [] and topics == []
    # Idempotent: second call changes nothing and reports False.
    assert store.ensure_yaml_config(tmp_path) is False


def test_ensure_yaml_config_refuses_unmigrated_legacy(tmp_path):
    # Seeding empty twins OVER an unmigrated real .md would silently orphan the
    # user's config — refuse with the pointer instead.
    (tmp_path / "sources.md").write_text(REAL_SOURCES_MD, encoding="utf-8")
    with pytest.raises(ValueError, match="migrate-config"):
        store.ensure_yaml_config(tmp_path)
    assert not (tmp_path / "sources.yaml").exists()
