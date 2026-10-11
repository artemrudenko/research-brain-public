#!/usr/bin/env python3
"""
manage_sources.py — deterministic backend for the `source-manage` skill.

The conversational `source-manage` skill parses a single user intent ("watch
this blog", "stop monitoring topic Z", "pause that feed") and calls into this
module to mutate the two config files that drive collection. The config exists
in two formats (CONVENTIONS §2.3); this module reads/writes whichever is ACTIVE
and never writes both:

  - **YAML (preferred, active when present):** `config/topics.yaml` +
    `config/sources.yaml` — machine-written via the canonical emitters in
    `scripts/sources/store.py` (values are the user's; comments/formatting are
    regenerated on each change).
  - **Markdown (retired 0.8.0):** `config/topics.md` (one `## Topic: <name>`
    section per topic) + `config/sources.md` (one `## Category: <name>` block
    with a 6-column **Active sources** table). Edited surgically (append/
    toggle/drop a section or a single row) so existing formatting, EXAMPLE
    blocks, header notes and unrelated rows are preserved.

Every operation is **idempotent**, validates identically in both formats, and
keeps topic names in sync between the two files (CONVENTIONS §2, §11).

Layout: this file is the CLI + stable import surface. Shared models, validation,
markdown-table helpers, and tag-key parsers live in `scripts/sources/`, while
the mutation functions remain here so existing callers and monkeypatch-based
tests keep working unchanged during the transition.

The skill supplies already-resolved fields (it does the asking / clarify-don't-
invent); this module validates and writes. It never invents a value.

CLI (machine-friendly; the skill normally imports the functions directly):

    python3 scripts/manage_sources.py add-topic ai-agents
    python3 scripts/manage_sources.py add-source ai-agents https://x/feed.xml \
        --type rss --tier high --priority medium --filter "all" --active yes
    python3 scripts/manage_sources.py pause  https://x/feed.xml
    python3 scripts/manage_sources.py resume https://x/feed.xml
    python3 scripts/manage_sources.py remove-source https://x/feed.xml
    python3 scripts/manage_sources.py remove-topic ai-agents
    python3 scripts/manage_sources.py list [--json]

All paths resolve relative to the project root regardless of cwd (CONVENTIONS §1).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

# Resolve the project root from this file's location (scripts/ -> root), so the
# module works no matter the current working directory (CONVENTIONS §1).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"

# Make the `scripts` package importable when run directly as a script, so the
# shared tags.yaml text-surgery helpers (DRY with promote_tags) resolve.
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

# Compare feed URLs by the dedup-contract key (normalize_url), so an http/https,
# www or trailing-slash variant of an existing source matches instead of duplicating.
from scripts.normalize_url import normalize_or_raw  # noqa: E402

# Atomic same-path write (same-dir temp + os.replace) so a crash mid-write can't
# leave a truncated config file; the single source of truth lives in registry.py.
from scripts.registry import atomic_write_text  # noqa: E402
from scripts.sources import store  # noqa: E402
from scripts.sources.markdown import (  # noqa: E402
    _EXAMPLE_MARKER,
    _ROW_COMMENT_RE,
    _TABLE_HEADER,
    _TABLE_SEP,
    _append_section,
    _category_block,
    _is_example_row,
    _iter_source_rows,
    _read,
    _remove_section,
    _section_bounds,
    _set_active_cell,
    _strip_row_comment,
    _table_insert_index,
    _topic_block,
)
from scripts.sources.model import Category, Source, State, Topic  # noqa: E402
from scripts.sources.tags import _block_child_keys, _domain_keys, _synonym_aliases  # noqa: E402
from scripts.sources.validation import (  # noqa: E402
    PRIORITIES,
    SOURCE_TYPES,
    TIERS,
    _reject_table_breakers,
    _validate_enum,
    _validate_topic_name,
    _validate_url,
)

# Shared, comment-preserving insertion logic for the domains: block (BUG 3) so
# manage_sources and promote_tags place new domain keys identically.
from scripts.validate_brain import domains_insert_index  # noqa: E402

__all__ = [
    "_iter_source_rows",
    "_section_bounds",
    "_set_active_cell",
    "_table_insert_index",
    "DEFAULT_CONFIG_DIR",
    "PRIORITIES",
    "PROJECT_ROOT",
    "SOURCE_TYPES",
    "TIERS",
    "Category",
    "Source",
    "State",
    "Topic",
    "_EXAMPLE_MARKER",
    "_ROW_COMMENT_RE",
    "_TABLE_HEADER",
    "_TABLE_SEP",
    "_append_section",
    "_block_child_keys",
    "_bool_arg",
    "_category_block",
    "_config_paths",
    "_domain_keys",
    "_is_example_row",
    "_read",
    "_reject_table_breakers",
    "_remove_section",
    "_seed_tag",
    "_strip_row_comment",
    "_synonym_aliases",
    "_tags_path",
    "_topic_block",
    "_validate_enum",
    "_validate_topic_name",
    "_validate_url",
    "add_source",
    "add_topic",
    "atomic_write_text",
    "human_summary",
    "list_state",
    "main",
    "remove_source",
    "remove_topic",
    "set_source_active",
    "strip_example_sections",
]


def strip_example_sections(config_dir: Path) -> int:
    """Remove the shipped EXAMPLE `## Topic:` / `## Category:` sections; return count.

    The template ships an `example-topic` topic + category marked
    `# EXAMPLE — replace`. The headless parser already ignores EXAMPLE *source rows*,
    but the recommended agentic weekly-run enumerates every literal `## Topic:`
    heading — so a left-behind example-topic would trigger a pointless collection /
    digest section. Once the user has configured real topics, drop any topic/category
    section whose body still carries the EXAMPLE marker (a real section never does,
    since the backend renders clean blocks). A user-named real section is untouched.
    """
    topics_path, sources_path = _config_paths(config_dir)
    removed = 0
    for path, prefix in ((topics_path, "## Topic: "), (sources_path, "## Category: ")):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        lines = [ln.rstrip("\n") for ln in text.splitlines()]
        to_remove: list[str] = []
        for line in lines:
            if not line.startswith(prefix):
                continue
            bounds = _section_bounds(lines, line.strip())
            if not bounds:
                continue
            section = lines[bounds[0]:bounds[1]]
            if _EXAMPLE_MARKER not in "\n".join(section):
                continue
            # NEVER delete a section that has gained a REAL (non-example) source row:
            # an agent may have added a live source into the shipped example category
            # before stripping. Removing it would silently lose that source. Only the
            # untouched placeholder (marker present, no real rows) is safe to drop.
            if any(True for _ in _iter_source_rows(section)):
                continue
            to_remove.append(line.strip())
        for heading in to_remove:
            text = _remove_section(text, heading)
            removed += 1
        if to_remove:
            atomic_write_text(path, text)
    return removed


# --------------------------------------------------------------------------- #
# Public mutation API
# --------------------------------------------------------------------------- #


def _config_paths(config_dir: Path) -> tuple[Path, Path]:
    """The ACTIVE (topics, sources) config files — the YAML twins (YAML-only, 0.8.0)."""
    config_dir = Path(config_dir)
    return store.active_topics_path(config_dir), store.active_sources_path(config_dir)


def _require_yaml_config(config_dir: Path) -> None:
    """Refuse an UNMIGRATED legacy dir loudly (YAML-only since 0.8.0).

    Writing YAML next to real un-migrated .md content would silently orphan the
    user's config; reading would silently see nothing. Both must instead point
    at the one-command migration.
    """
    if store.legacy_md_needs_migration(config_dir):
        raise ValueError(
            "config is still in the retired .md format — run "
            "`python3 scripts/schema.py migrate-config` first"
        )



# --------------------------------------------------------------------------- #
# YAML-mode plumbing — model in, canonical emit out (see scripts/sources/store.py)
# --------------------------------------------------------------------------- #

# The default include/exclude prose a fresh topic gets — the same wording the
# legacy `_topic_block` writes into topics.md, so both formats stay 1:1.
_DEFAULT_INCLUDE = "Substantive pieces directly about {name}."
_DEFAULT_EXCLUDE = (
    "Off-topic content, low-signal hype, and items that belong to a different topic."
)


def _yaml_topics(config_dir: Path) -> list[Topic]:
    """The YAML topics list; a missing twin (half-state) reads as empty and is
    recreated by the next write — the config never falls back to a stale .md."""
    path = Path(config_dir) / store.TOPICS_YAML
    return store.load_topics(path) if path.exists() else []


def _yaml_categories(config_dir: Path) -> list[Category]:
    path = Path(config_dir) / store.SOURCES_YAML
    return store.load_categories(path) if path.exists() else []


def _write_yaml_topics(config_dir: Path, topics: list[Topic]) -> None:
    atomic_write_text(Path(config_dir) / store.TOPICS_YAML, store.dump_topics_yaml(topics))


def _write_yaml_categories(config_dir: Path, categories: list[Category]) -> None:
    atomic_write_text(
        Path(config_dir) / store.SOURCES_YAML, store.dump_sources_yaml(categories)
    )


def _tags_path(config_dir: Path) -> Path:
    """The controlled-vocabulary registry edited when a topic is seeded."""
    return Path(config_dir) / "tags.yaml"


def _seed_tag(config_dir: Path, name: str) -> bool:
    """Seed `name` as a top-level domain key in tags.yaml (idempotent).

    A brand-new topic gets `Frontmatter tags: [<slug>]` (see `_topic_block`), so
    the same slug must exist in the controlled vocabulary or every concept
    synthesized for it is forced into `pending:` (CONVENTIONS §11). We add the
    slug under `domains:` with an EMPTY topic list (`<slug>: []`) — the bare
    domain is itself a valid tag (Obsidian nested-tag behaviour).

    Done by surgical text insertion (NOT a PyYAML round-trip) so the registry's
    comments, key ordering and synonyms/pending blocks are preserved byte-for-
    byte. Returns True only when the file was actually changed. A missing or
    malformed tags.yaml is tolerated (the file is created by a sibling skill and
    may not exist yet) — seeding is then a no-op rather than an error.
    """
    tags_path = _tags_path(config_dir)
    if not tags_path.exists():
        return False  # registry not created yet -> nothing to seed into
    tags_text = tags_path.read_text(encoding="utf-8")

    # Never duplicate: if the slug is already a domain key, leave the file alone
    # (this also preserves any existing topic list under that domain).
    if name in _domain_keys(tags_text):
        return False

    # Never shadow a synonym: if the slug is already an alias (e.g. `ai-safety`
    # -> `ai/governance`), it normalizes to a canonical tag on its own, so a
    # same-named bare domain would conflict. Leave the registry untouched.
    if name in _synonym_aliases(tags_text):
        return False

    lines = tags_text.splitlines()
    # Locate the `domains:` mapping and the end of its block (the first line at
    # column 0 that is not blank/comment after it — i.e. the next top-level key
    # such as `synonyms:`). The new domain is inserted at that boundary so it
    # becomes the last entry under `domains:`.
    domains_idx = next(
        (i for i, ln in enumerate(lines) if ln.rstrip() == "domains:"), None
    )
    if domains_idx is None:
        return False  # no domains: block -> respect the schema, add nothing

    # Shared insertion logic: lands flush under the last real domain entry,
    # trimming back over trailing blank AND comment lines that belong to the
    # next block (e.g. the `# synonyms` header above `synonyms:`) — BUG 3.
    insert_at = domains_insert_index(lines, domains_idx)

    # Two-space indent matches the shipped `domains:` entries; empty inline list.
    lines.insert(insert_at, f"  {name}: []")
    atomic_write_text(tags_path, "\n".join(lines) + "\n")
    return True


def add_topic(config_dir: Path, name: str) -> bool:
    """Add a topic to topics.md, a matching category to sources.md, and seed its
    tag into config/tags.yaml.

    Idempotent: re-adding an existing topic is a no-op. Returns True when any
    file was changed.

    Note: the inverse (`remove_topic`) deliberately does NOT remove the seeded
    tag — tags are sticky knowledge; pruning the vocabulary is hygiene's job
    (validate_brain), not source-manage's.
    """
    name = _validate_topic_name(name)
    changed = False
    _require_yaml_config(config_dir)
    topics = _yaml_topics(config_dir)
    if name not in {t.name for t in topics}:
        topics.append(
            Topic(
                name=name,
                tags=[name],
                include=_DEFAULT_INCLUDE.format(name=name),
                exclude=_DEFAULT_EXCLUDE,
            )
        )
        _write_yaml_topics(config_dir, topics)
        changed = True
    categories = _yaml_categories(config_dir)
    if name not in {c.name for c in categories}:
        categories.append(Category(name=name))
        _write_yaml_categories(config_dir, categories)
        changed = True
    # Seed the topic's tag so closed-book tagging can use it immediately. Done
    # last so a tags.yaml hiccup never blocks the (more important) source config.
    if _seed_tag(config_dir, name):
        changed = True
    return changed


def add_source(
    config_dir: Path,
    topic: str,
    url: str,
    source_type: str,
    tier: str,
    priority: str,
    filter_note: str,
    active: bool,
) -> bool:
    """Append a source row to a topic's Active-sources table.

    Creates the topic+category first if missing (never writes an orphan source).
    Idempotent on the URL: re-adding the same URL within the category is a no-op.
    Returns True when a row was written.
    """
    topic = _validate_topic_name(topic)
    url = _validate_url(url)
    source_type = _validate_enum(source_type, SOURCE_TYPES, "type")
    tier = _validate_enum(tier, TIERS, "tier")
    priority = _validate_enum(priority, PRIORITIES, "priority")
    note = (filter_note or "").strip() or "—"
    # The filter note is written into a table cell, so it must not carry table-
    # breaking characters either (clarify-don't-invent: reject, never mangle).
    _reject_table_breakers(note, "filter")

    # Ensure the topic/category exists and the two files stay in sync.
    add_topic(config_dir, topic)

    # Idempotency (both formats): dedup against PARSED URLs via the normalize_url
    # key (not raw text containment, and not a raw-string match) — so `.../feed2`
    # is not a false hit on `.../feed`, AND an http/https/www/trailing-slash
    # variant of an existing feed is recognised as already-present (FIX 1).
    key = normalize_or_raw(url)

    _require_yaml_config(config_dir)
    categories = _yaml_categories(config_dir)
    if any(normalize_or_raw(s.url) == key for c in categories for s in c.sources):
        return False
    target = next(c for c in categories if c.name == topic)  # add_topic guarantees it
    target.sources.append(
        Source(
            url=url, type=source_type, tier=tier, priority=priority,
            filter_note=note, active=active,
        )
    )
    _write_yaml_categories(config_dir, categories)
    return True



def set_source_active(config_dir: Path, url: str, active: bool) -> bool:
    """Flip a source row's Active cell to yes/no (pause / resume).

    Returns True when the row changed, False when it already had the target
    state (idempotent). Raises LookupError when the URL is not registered.
    """
    url = _validate_url(url)
    # Match the URL against PARSED URLs via the normalize_url key (the dedup
    # contract), so a variant of the stored feed still resolves — never raw text
    # containment or a raw-string match (FIX 1 + URL-variant).
    key = normalize_or_raw(url)

    _require_yaml_config(config_dir)
    categories = _yaml_categories(config_dir)
    for cat in categories:
        for i, src in enumerate(cat.sources):
            if normalize_or_raw(src.url) != key:
                continue
            if src.active == active:
                return False
            cat.sources[i] = replace(src, active=active)
            _write_yaml_categories(config_dir, categories)
            return True
    raise LookupError(f"no source row found for URL {url!r}")



def remove_source(config_dir: Path, url: str) -> bool:
    """Delete exactly the source row matching `url` from sources.md.

    Removes only that one row, leaving every other row and the surrounding
    topic/category section intact. Idempotent: removing an absent URL is a clean
    no-op returning False (consistent with the other mutators' return-style).
    Returns True when a row was deleted.
    """
    url = _validate_url(url)
    # Match the URL against PARSED URLs via the normalize_url key (the dedup
    # contract), so a variant of the stored feed still resolves — never raw text
    # containment or a raw-string match (FIX 1 + URL-variant).
    key = normalize_or_raw(url)

    _require_yaml_config(config_dir)
    categories = _yaml_categories(config_dir)
    for cat in categories:
        for i, src in enumerate(cat.sources):
            if normalize_or_raw(src.url) != key:
                continue
            del cat.sources[i]
            _write_yaml_categories(config_dir, categories)
            return True
    return False  # URL absent — nothing to remove (idempotent no-op)



def remove_topic(config_dir: Path, name: str) -> bool:
    """Remove a topic's section from topics.md and its category from sources.md.

    Idempotent: removing an absent topic is a clean no-op. Returns True when a
    file changed.
    """
    name = _validate_topic_name(name)
    _require_yaml_config(config_dir)
    changed = False
    topics = _yaml_topics(config_dir)
    kept_topics = [t for t in topics if t.name != name]
    if len(kept_topics) != len(topics):
        _write_yaml_topics(config_dir, kept_topics)
        changed = True
    categories = _yaml_categories(config_dir)
    kept_categories = [c for c in categories if c.name != name]
    if len(kept_categories) != len(categories):
        _write_yaml_categories(config_dir, kept_categories)
        changed = True
    return changed



# --------------------------------------------------------------------------- #
# Read API (list / summary)
# --------------------------------------------------------------------------- #


# The markdown parsers now live in scripts/sources/store.py (shared with the
# schema migrator and every other reader); these aliases keep the long-standing
# import surface (`collect.py`, tests) stable.
_parse_topics = store.parse_topics_md
_parse_categories = store.parse_categories_md


def list_state(config_dir: Path) -> State:
    """Return the parsed, machine-readable view of the ACTIVE config files."""
    _require_yaml_config(config_dir)
    return State(
        topics=_yaml_topics(config_dir),
        categories=_yaml_categories(config_dir),
    )


def human_summary(config_dir: Path) -> str:
    """Render a plain-language summary of what is monitored (for the user)."""
    state = list_state(config_dir)
    if not state.categories:
        return "Nothing is being monitored yet."
    lines = ["You are monitoring these topics:"]
    for cat in state.categories:
        active = sum(1 for s in cat.sources if s.active)
        total = len(cat.sources)
        paused = total - active
        detail = f"{total} source(s)" if total else "no sources yet"
        if paused:
            detail += f" ({paused} paused)"
        lines.append(f"- {cat.name}: {detail}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _bool_arg(value: str) -> bool:
    return value.strip().lower() in ("yes", "true", "1", "on", "y")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument(
        "--config-dir",
        default=str(DEFAULT_CONFIG_DIR),
        help="config directory (default: project config/)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_topic = sub.add_parser("add-topic", help="add a monitored topic")
    p_topic.add_argument("name")

    p_src = sub.add_parser("add-source", help="add a source row to a topic")
    p_src.add_argument("topic")
    p_src.add_argument("url")
    p_src.add_argument("--type", required=True, choices=SOURCE_TYPES)
    p_src.add_argument("--tier", default="medium", choices=TIERS)
    p_src.add_argument("--priority", default="medium", choices=PRIORITIES)
    p_src.add_argument("--filter", default="", dest="filter_note")
    p_src.add_argument("--active", default="yes")

    p_pause = sub.add_parser("pause", help="set a source inactive")
    p_pause.add_argument("url")
    p_resume = sub.add_parser("resume", help="set a source active")
    p_resume.add_argument("url")

    p_rm_src = sub.add_parser("remove-source", help="delete one source row by URL")
    p_rm_src.add_argument("url")

    p_rm = sub.add_parser("remove-topic", help="remove a topic + its category")
    p_rm.add_argument("name")

    p_list = sub.add_parser("list", help="show monitored topics + sources")
    p_list.add_argument("--json", action="store_true", help="emit JSON")

    args = parser.parse_args(argv)
    config_dir = Path(args.config_dir)

    try:
        if args.command == "add-topic":
            changed = add_topic(config_dir, args.name)
            print(f"add-topic {args.name}: {'changed' if changed else 'no-op'}")
        elif args.command == "add-source":
            changed = add_source(
                config_dir,
                topic=args.topic,
                url=args.url,
                source_type=args.type,
                tier=args.tier,
                priority=args.priority,
                filter_note=args.filter_note,
                active=_bool_arg(args.active),
            )
            print(f"add-source {args.url}: {'added' if changed else 'already present'}")
        elif args.command in ("pause", "resume"):
            changed = set_source_active(
                config_dir, args.url, active=args.command == "resume"
            )
            print(f"{args.command} {args.url}: {'changed' if changed else 'no-op'}")
        elif args.command == "remove-source":
            changed = remove_source(config_dir, args.url)
            print(
                f"remove-source {args.url}: "
                f"{'removed' if changed else 'not found (already absent)'}"
            )
        elif args.command == "remove-topic":
            changed = remove_topic(config_dir, args.name)
            print(f"remove-topic {args.name}: {'removed' if changed else 'no-op'}")
        elif args.command == "list":
            if args.json:
                state = list_state(config_dir)
                print(
                    json.dumps(
                        {
                            "topics": [t.name for t in state.topics],
                            "categories": [
                                {
                                    "name": c.name,
                                    "sources": [vars(s) for s in c.sources],
                                }
                                for c in state.categories
                            ],
                        },
                        indent=2,
                    )
                )
            else:
                print(human_summary(config_dir))
    except (ValueError, LookupError, FileNotFoundError, RuntimeError) as exc:
        # RuntimeError covers the store's "PyYAML required for the YAML config"
        # refusal — a clean ERROR line, never a traceback.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
