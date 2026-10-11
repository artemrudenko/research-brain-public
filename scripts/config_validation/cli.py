from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from scripts import schema

if TYPE_CHECKING:
    from .api import ConfigValidationApi


def run(api: ConfigValidationApi, argv: Sequence[str] | None = None) -> int:
    """Run the config validator CLI through the stable facade API."""
    parser = argparse.ArgumentParser(
        description=api.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "config_dir",
        nargs="?",
        default=api.DEFAULT_CONFIG_DIR,
        help=f"config directory (default: {api.DEFAULT_CONFIG_DIR})",
    )
    parser.add_argument(
        "--check-feeds",
        action="store_true",
        help=(
            "also probe each configured feed URL over the network and WARN on any "
            "that are unreachable (opt-in; advisory, never changes the exit code)"
        ),
    )
    args = parser.parse_args(argv)

    config_dir = Path(args.config_dir)
    if not config_dir.is_absolute():
        config_dir = api.PROJECT_ROOT / config_dir

    yaml = api._load_yaml()

    # YAML-only since 0.8.0 (CONVENTIONS §2.3): the twins are THE config. An
    # unmigrated legacy dir (.md with real content, no YAML) is an ERROR with
    # the one-command pointer — the leftover-warning for migrated dirs stays
    # in check_config_format_sync below.
    sources_path = api.active_sources_path(config_dir)
    topics_path = api.active_topics_path(config_dir)

    errors = []
    if api.legacy_md_needs_migration(config_dir):
        errors.append(
            "sources.md/topics.md: the markdown config format is retired — run "
            "`python3 scripts/schema.py migrate-config` to convert your config "
            "to sources.yaml/topics.yaml (the .md files are left untouched)"
        )
    errors += api.validate_channels(config_dir / "channels.yaml", yaml)
    errors += api.validate_schedule(config_dir / "schedule.yaml", yaml)
    errors += api.validate_sources_yaml(sources_path, yaml)
    errors += api.validate_topics_yaml(topics_path, yaml)
    errors += api.validate_tags(config_dir / "tags.yaml", yaml)
    errors += api.validate_search(config_dir / "search.yaml", yaml)
    errors += api.validate_search(config_dir / "research.yaml", yaml)
    errors += api.validate_glossary(config_dir / "glossary.yaml", yaml)
    # Optional: absent means nobody is being followed (CONVENTIONS §2.4).
    errors += api.validate_authors_yaml(config_dir / "authors.yaml", yaml)
    errors += api.detect_inline_secrets(config_dir)

    print("# Config Validation\n")
    if errors:
        print(f"FAIL: {len(errors)} schema violation(s):\n")
        for error in errors:
            print(f"- {error}")
        print()
        return 1

    print(
        f"OK: channels.yaml, schedule.yaml, {sources_path.name}, "
        f"{topics_path.name}, tags.yaml valid.\n"
    )

    sync_warnings = api.check_topics_sources_sync(topics_path, sources_path)
    if sync_warnings:
        print(f"WARN: {topics_path.name} and {sources_path.name} are out of sync:")
        for warning in sync_warnings:
            print(f"- {warning}")
        print()

    format_warnings = api.check_config_format_sync(config_dir)
    if format_warnings:
        print("WARN: legacy .md / active YAML config drift:")
        for warning in format_warnings:
            print(f"- {warning}")
        print()

    placeholders = api.detect_placeholders(config_dir)
    if placeholders:
        print(
            "WARN: EXAMPLE placeholders still present (config is a template, "
            "not yet configured) in: " + ", ".join(placeholders)
        )
        print("      Run the setup-wizard skill or edit these by hand.\n")

    stamped = [
        config_dir / name
        for name in ("channels.yaml", "schedule.yaml")
        if (config_dir / name).exists()
    ]
    for drift in schema.scan_paths_for_drift(stamped, "config"):
        print(f"WARN: {drift}\n")
    # The sources/topics twins carry their own schema kinds (1 = .md, 2 = YAML):
    # warn when a file was written by a NEWER release than this code.
    for name, kind in (("sources.yaml", "sources"), ("topics.yaml", "topics")):
        path = config_dir / name
        if path.exists():
            for drift in schema.scan_paths_for_drift([path], kind):
                print(f"WARN: {drift}\n")

    if args.check_feeds:
        feed_urls = api.extract_source_urls(sources_path)
        dead_feeds = api.check_feed_liveness(feed_urls)
        if dead_feeds:
            print(
                f"WARN: {len(dead_feeds)} feed(s) unreachable "
                f"(checked {len(feed_urls)}):"
            )
            for warning in dead_feeds:
                print(f"- {warning}")
            print()
        else:
            print(f"OK: all {len(feed_urls)} feed(s) reachable.\n")

    return 0


__all__ = ["run"]
