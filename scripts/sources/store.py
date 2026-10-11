"""store.py — the single loader/emitter for the sources/topics config, both formats.

The sources/topics config is YAML-only since 0.8.0 (docs/CONVENTIONS.md §2.3;
ADR 0023 era — BACKLOG item 1). The retired markdown tables survive ONLY as a
migration input: `python3 scripts/schema.py migrate-config` parses them via the
md parsers below and writes the YAML twins. Historical context:

  - **YAML (active when present):** ``config/sources.yaml`` + ``config/topics.yaml``
    — schema_version 2, parsed here with PyYAML.
  - **Markdown (legacy fallback):** ``config/sources.md`` + ``config/topics.md``
    — the original pipe-table format (schema_version 1), parsed here with the
    shared table helpers from ``scripts.sources.markdown``.

Every reader (collect, status, validators, manage_sources) resolves the active
file through :func:`active_sources_path` / :func:`prefer_yaml_twin` and parses it
through :func:`load_categories` / :func:`load_topics`, so the "YAML wins when
present, .md keeps working when absent" rule lives in exactly one place. The
deterministic emitters (:func:`dump_sources_yaml` / :func:`dump_topics_yaml`) are
what the schema migrator and the manage_sources YAML write path produce — the
files are machine-written: values are the user's, comments/formatting are
regenerated on every change (same contract as ``config/tags.yaml``).

Markdown parsing is stdlib; YAML parsing needs PyYAML (a hard runtime dep) and
raises a clear RuntimeError when it is missing rather than misreading config.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import ModuleType

from scripts._yaml import optional_yaml, yaml_scalar
from scripts.sources.markdown import (
    _EXAMPLE_MARKER,
    _iter_source_rows,
    _section_bounds,
)
from scripts.sources.model import Category, Source, Topic
from scripts.sources.validation import PRIORITIES, SOURCE_TYPES, TIERS

__all__ = [
    "SOURCES_MD",
    "SOURCES_YAML",
    "TOPICS_MD",
    "TOPICS_YAML",
    "active_sources_path",
    "active_topics_path",
    "dump_sources_yaml",
    "dump_topics_yaml",
    "load_categories",
    "load_topics",
    "parse_categories_md",
    "parse_sources_yaml_text",
    "parse_topics_md",
    "parse_topics_yaml_text",
    "prefer_yaml_twin",
    "ensure_yaml_config",
    "legacy_md_needs_migration",
]

SOURCES_YAML = "sources.yaml"
SOURCES_MD = "sources.md"
TOPICS_YAML = "topics.yaml"
TOPICS_MD = "topics.md"

_YAML_SUFFIXES = (".yaml", ".yml")

# Defaults for optional per-source YAML keys (documented in CONVENTIONS §2.3).
# RSS-first is the project's collection ethos (§12), so a minimal hand-added
# `- url: …` entry becomes an active medium/medium rss source instead of being
# silently dropped (the legacy table format's failure mode this migration kills).
_SOURCE_DEFAULTS = {"type": "rss", "tier": "medium", "priority": "medium", "filter": "—"}


# --------------------------------------------------------------------------- #
# Active-path resolution — "YAML wins when present, .md is the fallback"
# --------------------------------------------------------------------------- #


def active_sources_path(config_dir: Path) -> Path:
    """The active sources config file — always ``sources.yaml`` (YAML-only, 0.8.0).

    The returned path may not exist; callers keep their own exists()/error
    handling (and name the migrate-config pointer on an unmigrated legacy dir —
    see :func:`legacy_md_needs_migration`).
    """
    return Path(config_dir) / SOURCES_YAML


def active_topics_path(config_dir: Path) -> Path:
    """The active topics config file — always ``topics.yaml`` (YAML-only, 0.8.0)."""
    return Path(config_dir) / TOPICS_YAML


def prefer_yaml_twin(path: Path) -> Path:
    """Resolve a legacy ``…/sources.md`` spelling to the ``…/sources.yaml`` twin.

    YAML-only since 0.8.0: an ``.md`` config path ALWAYS resolves to its
    ``.yaml`` sibling (even when that file does not exist yet), so every
    downstream error names the file the runtime actually reads. Non-.md paths
    pass through unchanged.
    """
    path = Path(path)
    if path.suffix != ".md":
        return path
    return path.with_suffix(".yaml")


def legacy_md_needs_migration(config_dir: Path) -> bool:
    """True when the dir is an UNMIGRATED legacy install: real (non-EXAMPLE)
    ``.md`` config content with no YAML twin at all.

    This is the state every reader/writer must refuse LOUDLY (pointing at
    ``python3 scripts/schema.py migrate-config``) — reading nothing, or writing
    a fresh YAML next to the user's real .md, would silently orphan their
    config. A dir with any YAML twin is not a blocker (the .md is then a stale
    leftover the validator warns about); EXAMPLE-only templates are not user
    data and do not block either.
    """
    config_dir = Path(config_dir)
    if (config_dir / SOURCES_YAML).exists() or (config_dir / TOPICS_YAML).exists():
        return False
    for name, parser in ((SOURCES_MD, parse_categories_md), (TOPICS_MD, parse_topics_md)):
        path = config_dir / name
        if not path.exists():
            continue
        try:
            if parser(path.read_text(encoding="utf-8"), skip_examples=True):
                return True
        except OSError:
            continue
    return False


def ensure_yaml_config(config_dir: Path) -> bool:
    """Create the empty YAML twins on a fresh dir; True when anything was created.

    Refuses (ValueError with the migrate-config pointer) on an unmigrated
    legacy dir — seeding empties next to real .md content would orphan it.
    """
    config_dir = Path(config_dir)
    if legacy_md_needs_migration(config_dir):
        raise ValueError(
            "config is still in the retired .md format — run "
            "`python3 scripts/schema.py migrate-config` first (your sources.md/"
            "topics.md content becomes sources.yaml/topics.yaml; the .md files "
            "are left untouched)"
        )
    created = False
    sources = config_dir / SOURCES_YAML
    topics = config_dir / TOPICS_YAML
    if not sources.exists():
        sources.write_text(dump_sources_yaml([]), encoding="utf-8")
        created = True
    if not topics.exists():
        topics.write_text(dump_topics_yaml([]), encoding="utf-8")
        created = True
    return created


# --------------------------------------------------------------------------- #
# Markdown parsers (the legacy format — stdlib only)
# --------------------------------------------------------------------------- #

_CATEGORY_HEADER_RE = re.compile(r"^## Category: (.+)$", re.MULTILINE)
_TOPIC_HEADER_RE = re.compile(r"^## Topic: (.+)$", re.MULTILINE)

# Topic-section bullets whose values the YAML format carries as real fields.
_TAGS_BULLET_RE = re.compile(r"^- \*\*Frontmatter tags:\*\*\s*(.+)$")
_INCLUDE_BULLET_RE = re.compile(r"^- \*\*Include rules:\*\*\s*(.*)$")
_EXCLUDE_BULLET_RE = re.compile(r"^- \*\*Exclude rules:\*\*\s*(.*)$")


def parse_categories_md(text: str, *, skip_examples: bool = False) -> list[Category]:
    """Parse sources.md text into `Category` records (EXAMPLE rows always skipped).

    With ``skip_examples=True`` a category section that still carries the shipped
    ``# EXAMPLE — replace`` marker AND has no real source rows is dropped entirely
    (the migrator's view: placeholders are template furniture, not config). A
    marked section that gained a real row is kept — a live source must never be
    silently lost (mirrors ``manage_sources.strip_example_sections``).
    """
    lines = text.splitlines()
    categories: list[Category] = []
    for match in _CATEGORY_HEADER_RE.finditer(text):
        name = match.group(1).strip()
        bounds = _section_bounds(lines, f"## Category: {name}")
        cat = Category(name=name)
        section: list[str] = []
        if bounds is not None:
            start, end = bounds
            section = lines[start:end]
            # The shared row iterator already skips EXAMPLE placeholder rows, so
            # a fresh template parses to zero real sources.
            for _index, cells in _iter_source_rows(section):
                cat.sources.append(
                    Source(
                        url=cells[0],
                        type=cells[1],
                        tier=cells[2],
                        priority=cells[3],
                        filter_note=cells[4],
                        active=cells[5].lower() == "yes",
                    )
                )
        if skip_examples and not cat.sources and _EXAMPLE_MARKER in "\n".join(section):
            continue
        categories.append(cat)
    return categories


def _join_bullet(lines: list[str], start: int, first_value: str) -> str:
    """Join a wrapped bullet's continuation lines into one prose value.

    Continuations are the indented / plain-text lines that follow a bullet until
    the next bullet, heading, rule, or blank line — the shape the shipped
    topics.md template wraps its Include/Exclude prose in.
    """
    parts = [first_value.strip()]
    for line in lines[start + 1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith(("- ", "#", "---", ">", "|")):
            break
        parts.append(stripped)
    return " ".join(part for part in parts if part)


def _parse_tags_value(raw: str) -> list[str]:
    """Extract the tag list from a `` `[a, b]` `` bullet value."""
    inner = raw.strip().strip("`").strip()
    inner = inner.removeprefix("[").removesuffix("]")
    return [tag.strip() for tag in inner.split(",") if tag.strip()]


def parse_topics_md(text: str, *, skip_examples: bool = False) -> list[Topic]:
    """Parse topics.md text into `Topic` records (name + tags/include/exclude).

    With ``skip_examples=True`` a topic section still carrying the shipped
    ``# EXAMPLE — replace`` marker is dropped (the migrator's view).
    """
    lines = text.splitlines()
    topics: list[Topic] = []
    for match in _TOPIC_HEADER_RE.finditer(text):
        name = match.group(1).strip()
        bounds = _section_bounds(lines, f"## Topic: {name}")
        section = lines[bounds[0]:bounds[1]] if bounds is not None else []
        if skip_examples and _EXAMPLE_MARKER in "\n".join(section):
            continue
        topic = Topic(name=name)
        for index, line in enumerate(section):
            stripped = line.strip()
            if tags_match := _TAGS_BULLET_RE.match(stripped):
                topic.tags = _parse_tags_value(tags_match.group(1))
            elif include_match := _INCLUDE_BULLET_RE.match(stripped):
                topic.include = _join_bullet(section, index, include_match.group(1))
            elif exclude_match := _EXCLUDE_BULLET_RE.match(stripped):
                topic.exclude = _join_bullet(section, index, exclude_match.group(1))
        topics.append(topic)
    return topics


# --------------------------------------------------------------------------- #
# YAML parsers (the active format — needs PyYAML)
# --------------------------------------------------------------------------- #


def _require_yaml() -> ModuleType:
    yaml = optional_yaml()
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to read the YAML sources/topics config "
            "(config/sources.yaml / config/topics.yaml) — install it with: "
            "pip install pyyaml"
        )
    return yaml


def _as_mapping(data: object, what: str) -> dict[str, object]:
    if not isinstance(data, dict):
        raise ValueError(f"{what}: top level must be a mapping/object")
    return data


def _as_list(value: object, what: str) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{what} must be a list")
    return value


def _as_str(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} must be a non-empty string")
    return value.strip()


def _as_bool(value: object, what: str) -> bool:
    # PyYAML (YAML 1.1) already parses yes/no/true/false into bool; anything
    # else (a quoted "maybe", an int) is a config mistake to surface, not guess.
    if not isinstance(value, bool):
        raise ValueError(f"{what} (`active`) must be a boolean (true/false)")
    return value


def _parse_source_entry(entry: object, where: str) -> Source:
    if not isinstance(entry, dict):
        raise ValueError(f"{where}: each source must be a mapping")
    if "url" not in entry:
        raise ValueError(f"{where}: source is missing required key `url`")
    url = _as_str(entry["url"], f"{where}: `url`")
    return Source(
        url=url,
        type=_as_str(entry.get("type", _SOURCE_DEFAULTS["type"]), f"{where}: `type`"),
        tier=_as_str(entry.get("tier", _SOURCE_DEFAULTS["tier"]), f"{where}: `tier`"),
        priority=_as_str(
            entry.get("priority", _SOURCE_DEFAULTS["priority"]), f"{where}: `priority`"
        ),
        filter_note=str(entry.get("filter", _SOURCE_DEFAULTS["filter"])).strip() or "—",
        active=_as_bool(entry.get("active", True), where),
    )


def parse_sources_yaml_text(text: str) -> list[Category]:
    """Parse sources.yaml text into `Category` records; raise ValueError when malformed."""
    yaml = _require_yaml()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"sources.yaml: YAML parse error: {exc}") from exc
    mapping = _as_mapping(data if data is not None else {}, "sources.yaml")
    categories: list[Category] = []
    for i, raw in enumerate(_as_list(mapping.get("categories"), "sources.yaml: `categories`")):
        where = f"sources.yaml: categories[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} must be a mapping")
        if "name" not in raw:
            raise ValueError(f"{where} is missing required key `name`")
        cat = Category(name=_as_str(raw["name"], f"{where}: `name`"))
        for j, entry in enumerate(_as_list(raw.get("sources"), f"{where}: `sources`")):
            cat.sources.append(_parse_source_entry(entry, f"{where}: sources[{j}]"))
        categories.append(cat)
    return categories


def parse_topics_yaml_text(text: str) -> list[Topic]:
    """Parse topics.yaml text into `Topic` records; raise ValueError when malformed."""
    yaml = _require_yaml()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"topics.yaml: YAML parse error: {exc}") from exc
    mapping = _as_mapping(data if data is not None else {}, "topics.yaml")
    topics: list[Topic] = []
    for i, raw in enumerate(_as_list(mapping.get("topics"), "topics.yaml: `topics`")):
        where = f"topics.yaml: topics[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} must be a mapping")
        if "name" not in raw:
            raise ValueError(f"{where} is missing required key `name`")
        tags = _as_list(raw.get("tags"), f"{where}: `tags`")
        topics.append(
            Topic(
                name=_as_str(raw["name"], f"{where}: `name`"),
                tags=[_as_str(tag, f"{where}: tags entry") for tag in tags],
                include=str(raw.get("include", "")).strip(),
                exclude=str(raw.get("exclude", "")).strip(),
            )
        )
    return topics


# --------------------------------------------------------------------------- #
# Format-dispatching loaders
# --------------------------------------------------------------------------- #


_MD_RETIRED_MSG = (
    "the markdown config format is retired (0.8.0) — run "
    "`python3 scripts/schema.py migrate-config` to convert {name} to YAML"
)


def load_categories(path: Path) -> list[Category]:
    """Load `Category` records from a sources config file (YAML-only).

    An ``.md`` path is refused with the migrate-config pointer — the runtime
    never reads the retired markdown tables (the migrator parses their TEXT
    via :func:`parse_categories_md` directly).
    """
    path = Path(path)
    if path.suffix not in _YAML_SUFFIXES:
        raise ValueError(_MD_RETIRED_MSG.format(name=path.name))
    return parse_sources_yaml_text(path.read_text(encoding="utf-8"))


def load_topics(path: Path) -> list[Topic]:
    """Load `Topic` records from a topics config file (YAML-only)."""
    path = Path(path)
    if path.suffix not in _YAML_SUFFIXES:
        raise ValueError(_MD_RETIRED_MSG.format(name=path.name))
    return parse_topics_yaml_text(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Deterministic YAML emitters (stdlib string building — no PyYAML needed)
# --------------------------------------------------------------------------- #

# The scalar emitter is shared with the other deterministic config emitters
# (scripts/_yaml.py), so sources, topics and authors quote values identically.
_scalar = yaml_scalar


_SOURCES_YAML_HEADER = (
    "schema_version: 2\n"
    "# config/sources.yaml — collection sources by category (the ACTIVE config).\n"
    "# Machine-written by scripts/manage_sources.py / the setup-wizard: the VALUES are\n"
    "# yours to edit; comments and formatting are regenerated on every change.\n"
    "# Per-source keys: url (required) / type (rss|blog|medium-tag|webpage, default rss)\n"
    "#   / tier (high|medium|low — source credibility, default medium)\n"
    "#   / priority (high|medium|low — collection ordering, default medium)\n"
    "#   / filter (short note) / active (true|false, default true).\n"
    "# Category names stay in sync with config/topics.yaml (same name).\n"
    "# This is the ONLY config format (0.8.0+): legacy sources.md tables are\n"
    "# import-only via `python3 scripts/schema.py migrate-config`.\n"
)

_TOPICS_YAML_HEADER = (
    "schema_version: 2\n"
    "# config/topics.yaml — monitored topics (the ACTIVE config).\n"
    "# Machine-written by scripts/manage_sources.py / the setup-wizard: the VALUES are\n"
    "# yours to edit; comments and formatting are regenerated on every change.\n"
    "# Per-topic keys: name (slug, = the pipeline/1-incoming/<name>/ folder and the\n"
    "#   sources.yaml category) / tags (frontmatter tags for collected articles)\n"
    "#   / include (what belongs) / exclude (what to drop or route elsewhere).\n"
    "# This is the ONLY config format (0.8.0+): legacy topics.md sections are\n"
    "# import-only via `python3 scripts/schema.py migrate-config`.\n"
)


def dump_sources_yaml(categories: list[Category]) -> str:
    """Render categories as the canonical sources.yaml text (stable, round-trips)."""
    lines = [_SOURCES_YAML_HEADER.rstrip("\n")]
    if not categories:
        lines.append("categories: []")
        return "\n".join(lines) + "\n"
    lines.append("categories:")
    for cat in categories:
        lines.append(f"  - name: {_scalar(cat.name)}")
        if not cat.sources:
            lines.append("    sources: []")
            continue
        lines.append("    sources:")
        for src in cat.sources:
            lines.append(f"      - url: {_scalar(src.url)}")
            lines.append(f"        type: {_scalar(src.type)}")
            lines.append(f"        tier: {_scalar(src.tier)}")
            lines.append(f"        priority: {_scalar(src.priority)}")
            lines.append(f"        filter: {_scalar(src.filter_note)}")
            lines.append(f"        active: {'true' if src.active else 'false'}")
    return "\n".join(lines) + "\n"


def dump_topics_yaml(topics: list[Topic]) -> str:
    """Render topics as the canonical topics.yaml text (stable, round-trips)."""
    lines = [_TOPICS_YAML_HEADER.rstrip("\n")]
    if not topics:
        lines.append("topics: []")
        return "\n".join(lines) + "\n"
    lines.append("topics:")
    for topic in topics:
        lines.append(f"  - name: {_scalar(topic.name)}")
        if topic.tags:
            rendered = ", ".join(_scalar(tag) for tag in topic.tags)
            lines.append(f"    tags: [{rendered}]")
        if topic.include:
            lines.append(f"    include: {_scalar(topic.include)}")
        if topic.exclude:
            lines.append(f"    exclude: {_scalar(topic.exclude)}")
    return "\n".join(lines) + "\n"


def source_defaults_are_valid() -> bool:
    """True when the YAML per-source defaults are members of the shared enums.

    Pinned by a test so `_SOURCE_DEFAULTS` can never drift from the validation
    enums in `scripts.sources.validation` (the same values both formats allow).
    """
    return (
        _SOURCE_DEFAULTS["type"] in SOURCE_TYPES
        and _SOURCE_DEFAULTS["tier"] in TIERS
        and _SOURCE_DEFAULTS["priority"] in PRIORITIES
    )
