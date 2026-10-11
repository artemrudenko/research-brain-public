"""Validation for the sources/topics config in BOTH formats (CONVENTIONS §2.3).

The YAML twins (config/sources.yaml + config/topics.yaml, schema_version 2) are
the active config when present; the .md pipe tables are the legacy fallback.
This module owns:

  - the schema validators for the YAML format (`validate_sources_yaml` /
    `validate_topics_yaml`) — strict about enums and types where the tolerant
    runtime loader (scripts/sources/store.py) fills defaults;
  - the format-aware topics<->sources name sync check (either format on either
    side);
  - `check_config_format_sync` — the advisory warnings for a half-migrated
    config (one YAML twin missing) and for a stale .md that no longer matches
    the active YAML (the classic trap: hand-editing the ignored fallback).
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

from scripts.config_validation.markdown import _category_names, _topic_names
from scripts.config_validation.yaml_helpers import URL_RE as _URL_RE
from scripts.config_validation.yaml_helpers import load_yaml_mapping
from scripts.normalize_url import normalize_or_raw
from scripts.sources import store
from scripts.sources.validation import _TOPIC_NAME_RE, PRIORITIES, SOURCE_TYPES, TIERS

_MIGRATE_HINT = "python3 scripts/schema.py migrate-config"


def _slug_error(where: str, value: object) -> str | None:
    if not isinstance(value, str) or not _TOPIC_NAME_RE.fullmatch(value):
        return f"{where}: `name` must be a lowercase slug like `ai-agents`, got {value!r}"
    return None


def _enum_error(where: str, entry: dict[str, object], key: str, allowed: tuple[str, ...]) -> str | None:
    if key in entry and entry[key] not in allowed:
        return f"{where}: `{key}` must be one of {', '.join(allowed)}, got {entry[key]!r}"
    return None


def validate_sources_yaml(path: Path, yaml: ModuleType) -> list[str]:
    """Return schema errors for a sources.yaml file (CONVENTIONS §2.3)."""
    errors, data = load_yaml_mapping(path, yaml)
    if data is None:
        return errors
    name = path.name
    categories = data.get("categories", [])
    if not isinstance(categories, list):
        return [f"{name}: `categories` must be a list"]
    for i, cat in enumerate(categories):
        where = f"{name}: categories[{i}]"
        if not isinstance(cat, dict):
            errors.append(f"{where} must be a mapping")
            continue
        if slug_error := _slug_error(where, cat.get("name")):
            errors.append(slug_error)
        sources = cat.get("sources", [])
        if sources is None:
            sources = []
        if not isinstance(sources, list):
            errors.append(f"{where}: `sources` must be a list")
            continue
        for j, src in enumerate(sources):
            swhere = f"{where}: sources[{j}]"
            if not isinstance(src, dict):
                errors.append(f"{swhere} must be a mapping")
                continue
            url = src.get("url")
            if not isinstance(url, str) or not _URL_RE.fullmatch(url.strip()):
                errors.append(
                    f"{swhere}: `url` must be a full http:// or https:// URL, got {url!r}"
                )
            for key, allowed in (
                ("type", SOURCE_TYPES), ("tier", TIERS), ("priority", PRIORITIES),
            ):
                if enum_error := _enum_error(swhere, src, key, allowed):
                    errors.append(enum_error)
            if "active" in src and not isinstance(src["active"], bool):
                errors.append(
                    f"{swhere}: `active` must be a boolean true/false, got {src['active']!r}"
                )
    return errors


def validate_topics_yaml(path: Path, yaml: ModuleType) -> list[str]:
    """Return schema errors for a topics.yaml file (CONVENTIONS §2.3)."""
    errors, data = load_yaml_mapping(path, yaml)
    if data is None:
        return errors
    name = path.name
    topics = data.get("topics", [])
    if not isinstance(topics, list):
        return [f"{name}: `topics` must be a list"]
    for i, topic in enumerate(topics):
        where = f"{name}: topics[{i}]"
        if not isinstance(topic, dict):
            errors.append(f"{where} must be a mapping")
            continue
        if slug_error := _slug_error(where, topic.get("name")):
            errors.append(slug_error)
        tags = topic.get("tags", [])
        if tags is not None and not isinstance(tags, list):
            errors.append(f"{where}: `tags` must be a list of tag strings")
        for key in ("include", "exclude"):
            if key in topic and not isinstance(topic[key], str):
                errors.append(f"{where}: `{key}` must be a string")
    return errors


# --------------------------------------------------------------------------- #
# Format-aware name extraction + the topics<->sources sync check
# --------------------------------------------------------------------------- #


def topic_names(path: Path) -> list[str]:
    """Topic names from either format (empty on a missing/unreadable file —
    the schema validators above report the loud errors)."""
    if path.suffix in (".yaml", ".yml"):
        try:
            return [t.name for t in store.load_topics(path)]
        except (OSError, ValueError, RuntimeError):
            return []
    return _topic_names(path)


def category_names(path: Path) -> list[str]:
    """Category names from either format (empty on a missing/unreadable file)."""
    if path.suffix in (".yaml", ".yml"):
        try:
            return [c.name for c in store.load_categories(path)]
        except (OSError, ValueError, RuntimeError):
            return []
    return _category_names(path)


def check_topics_sources_sync(topics_path: Path, sources_path: Path) -> list[str]:
    """Cross-check topic names against source category names, either format.

    A monitored topic with no matching source category has nothing to collect;
    a source category with no matching topic is an orphan. Neither is fatal (the
    rest of the config can still be valid), so these are WARN findings.
    """
    topics = set(topic_names(topics_path))
    categories = set(category_names(sources_path))
    warnings = []
    for topic in sorted(topics - categories):
        warnings.append(
            f"topic `{topic}` has no matching source category in {sources_path.name}"
        )
    for category in sorted(categories - topics):
        warnings.append(
            f"source category `{category}` has no matching topic in {topics_path.name}"
        )
    return warnings


# --------------------------------------------------------------------------- #
# Coexistence of the two formats — advisory warnings
# --------------------------------------------------------------------------- #


def _md_sources_view(path: Path) -> tuple[set[str], set[str]] | None:
    """(category names, normalized urls) of the REAL .md content, or None when
    the file has no real (non-EXAMPLE) content — a pristine template is
    furniture, not a disagreement."""
    try:
        categories = store.parse_categories_md(
            path.read_text(encoding="utf-8"), skip_examples=True
        )
    except OSError:
        return None
    if not categories:
        return None
    names = {c.name for c in categories}
    urls = {normalize_or_raw(s.url) for c in categories for s in c.sources}
    return names, urls


def _yaml_sources_view(path: Path) -> tuple[set[str], set[str]] | None:
    try:
        categories = store.load_categories(path)
    except (OSError, ValueError, RuntimeError):
        return None  # malformed YAML — the schema validator already reported it
    names = {c.name for c in categories}
    urls = {normalize_or_raw(s.url) for c in categories for s in c.sources}
    return names, urls


def check_config_format_sync(config_dir: Path) -> list[str]:
    """Advisory warnings for a config carrying both formats (or half of one).

    - exactly one YAML twin exists → half-migrated (the missing twin reads as
      empty; a mutation or the migrator recreates it);
    - a .md file with REAL content no longer matching the active YAML → the .md
      is a stale, ignored fallback (edits there change nothing).
    """
    config_dir = Path(config_dir)
    sources_yaml = config_dir / store.SOURCES_YAML
    topics_yaml = config_dir / store.TOPICS_YAML
    if not (sources_yaml.exists() or topics_yaml.exists()):
        return []  # pure legacy .md config — nothing to cross-check

    warnings: list[str] = []
    for present, missing in ((sources_yaml, topics_yaml), (topics_yaml, sources_yaml)):
        if present.exists() and not missing.exists():
            warnings.append(
                f"{missing.name}: missing while {present.name} exists (half-migrated "
                f"YAML config) — it reads as empty; recreate it with `{_MIGRATE_HINT}` "
                f"or by any topic edit"
            )

    sources_md = config_dir / store.SOURCES_MD
    if sources_yaml.exists() and sources_md.exists():
        md_view = _md_sources_view(sources_md)
        yaml_view = _yaml_sources_view(sources_yaml)
        if md_view is not None and yaml_view is not None and md_view != yaml_view:
            warnings.append(
                f"{sources_md.name}: differs from the active {sources_yaml.name} — the "
                f".md is a frozen fallback and its edits are IGNORED. Edit "
                f"{sources_yaml.name} (or `{_MIGRATE_HINT} --force` to regenerate it "
                f"from the .md); delete {sources_md.name} when the fallback is no "
                f"longer needed"
            )

    topics_md = config_dir / store.TOPICS_MD
    if topics_yaml.exists() and topics_md.exists():
        try:
            md_topics = {
                t.name
                for t in store.parse_topics_md(
                    topics_md.read_text(encoding="utf-8"), skip_examples=True
                )
            }
        except OSError:
            md_topics = set()
        yaml_topics = set(topic_names(topics_yaml))
        if md_topics and md_topics != yaml_topics:
            warnings.append(
                f"{topics_md.name}: differs from the active {topics_yaml.name} — the "
                f".md is a frozen fallback and its edits are IGNORED. Edit "
                f"{topics_yaml.name} (or `{_MIGRATE_HINT} --force` to regenerate it "
                f"from the .md)"
            )
    return warnings


__all__ = [
    "category_names",
    "check_config_format_sync",
    "check_topics_sources_sync",
    "topic_names",
    "validate_sources_yaml",
    "validate_topics_yaml",
]
