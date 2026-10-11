#!/usr/bin/env python3
"""
inbox.py - stable CLI/import facade for the `source-capture` inbox queue.

The deterministic queue implementation lives in `scripts/inbox_flow/`. Keep this
module thin and compatibility-oriented: existing callers import and monkeypatch
names here, so public wrappers pass the facade's current globals down into the
package implementation.

CLI:
    python3 scripts/inbox.py add --url U --title T --body-file F
    python3 scripts/inbox.py count
    python3 scripts/inbox.py pending
    python3 scripts/inbox.py route <article> <topic>
"""

from __future__ import annotations

import os  # noqa: F401 - compatibility: tests monkeypatch inbox.os.replace
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Make the `scripts` package importable when run directly as a script
# (`python3 scripts/inbox.py`), not only as a module. Mirrors build_digest.py.
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts import schema  # noqa: E402 - frontmatter schema-version stamp
from scripts._yaml import optional_yaml  # noqa: E402
from scripts.inbox_flow import cli as inbox_cli  # noqa: E402
from scripts.inbox_flow import frontmatter as inbox_frontmatter  # noqa: E402
from scripts.inbox_flow import model as inbox_model  # noqa: E402
from scripts.inbox_flow import paths as inbox_paths  # noqa: E402
from scripts.inbox_flow import queue as inbox_queue  # noqa: E402
from scripts.inbox_flow import registry_ops as inbox_registry_ops  # noqa: E402
from scripts.registry import (  # noqa: E402
    append_registry_row_if_absent,
    atomic_write_text,
    atomic_write_unique,
    set_registry_category,
)

# Compatibility constants and private aliases historically imported from here.
DEFAULT_INCOMING = _PROJECT_ROOT / "pipeline" / "1-incoming"
DEFAULT_CAPTURE_AUTHOR = inbox_model.DEFAULT_CAPTURE_AUTHOR
DEFAULT_CAPTURE_TAG = inbox_model.DEFAULT_CAPTURE_TAG
DEFAULT_PROCESS_THRESHOLD = inbox_model.DEFAULT_PROCESS_THRESHOLD
INBOX_TOPIC = inbox_model.INBOX_TOPIC
slugify = inbox_paths.slugify
_atomic_write_text = atomic_write_text
_atomic_write_unique = atomic_write_unique


def _load_yaml() -> ModuleType:
    """Import PyYAML lazily with a clear, actionable message on failure."""
    yaml = optional_yaml()
    if yaml is None:
        print(
            "ERROR: PyYAML is required to write inbox frontmatter.\n"
            "       Install it with: pip install pyyaml "
            "(or: pip install -r requirements.txt)",
            file=sys.stderr,
        )
        sys.exit(2)
    return yaml


def _inbox_dir(incoming_root: Path) -> Path:
    return inbox_paths.inbox_dir(incoming_root)


def _unique_path(directory: Path, stem: str, suffix: str = ".md") -> Path:
    """`{stem}{suffix}` in `directory`, disambiguated with -2/-3/... on collision."""
    return inbox_paths.unique_path(directory, stem, suffix)


def _yaml_scalar_line(key: str, value: str) -> str:
    """One valid `key: value` YAML line, correctly quoting `value`."""
    return inbox_frontmatter.yaml_scalar_line(key, value, _load_yaml)


def _frontmatter(
    *,
    source: str,
    url: str,
    title: str,
    author: str,
    when: date,
    category: str,
    tags: list[str] | None,
) -> str:
    """A CONVENTIONS §5 strict frontmatter block, emitted as valid YAML."""
    return inbox_frontmatter.article_frontmatter(
        schema_version=schema.CURRENT["article"],
        source=source,
        url=url,
        title=title,
        author=author,
        when=when,
        category=category,
        tags=tags,
        load_yaml=_load_yaml,
    )


def _default_registry(incoming_root: Path) -> Path:
    """`pipeline/registry.md`, the sibling of `pipeline/1-incoming/`."""
    return inbox_paths.default_registry(incoming_root)


def _article_field(path: Path, field: str) -> str:
    """A top-level frontmatter `field:` value of an article, empty when absent."""
    return inbox_registry_ops.article_field(path, field)


def _article_url(path: Path) -> str:
    """The `url:` frontmatter value of an inbox article, empty when absent."""
    return inbox_registry_ops.article_url(path)


def _url_in_registry(registry_path: Path, url: str) -> bool:
    """True when `url` already has a registry row."""
    return inbox_registry_ops.url_in_registry(registry_path, url)


def _safe_topic(topic: str) -> str:
    """Validate an agent-chosen topic as a single, contained path component."""
    return inbox_paths.safe_topic(topic)


def _ensure_inbox_article(incoming_root: Path, article: Path) -> None:
    """Require `article` to live inside the inbox dir before route() touches it."""
    inbox_paths.ensure_inbox_article(incoming_root, article)


def _queue_deps() -> inbox_queue.QueueDeps:
    """Build queue dependencies from current facade globals for monkeypatch support."""
    return inbox_queue.QueueDeps(
        article_field=_article_field,
        article_url=_article_url,
        url_in_registry=_url_in_registry,
        append_registry_row_if_absent=append_registry_row_if_absent,
        set_registry_category=set_registry_category,
        atomic_write_unique=_atomic_write_unique,
        frontmatter=_frontmatter,
        default_registry=_default_registry,
    )


def find_in_inbox_by_url(incoming_root: Path, url: str) -> Path | None:
    """Return the queued article whose URL matches `url`, or None."""
    return inbox_registry_ops.find_in_inbox_by_url(
        incoming_root,
        url,
        pending,
        article_url_reader=_article_url,
    )


def add_article(
    incoming_root: Path = DEFAULT_INCOMING,
    *,
    url: str,
    title: str,
    body: str,
    source: str = "web",
    author: str = "",
    when: date | None = None,
    tags: list[str] | None = None,
    category: str = INBOX_TOPIC,
    registry_path: Path | None = None,
) -> Path | None:
    """Capture an article into the inbox; return its path, or None on duplicate."""
    return inbox_queue.add_article(
        incoming_root,
        url=url,
        title=title,
        body=body,
        source=source,
        author=author,
        when=when,
        tags=tags,
        category=category,
        registry_path=registry_path,
        deps=_queue_deps(),
    )


def pending(incoming_root: Path = DEFAULT_INCOMING) -> list[Path]:
    """Captured-but-unprocessed article files, sorted."""
    return inbox_queue.pending(incoming_root)


def count(incoming_root: Path = DEFAULT_INCOMING) -> int:
    """How many articles are queued for processing."""
    return inbox_queue.count(incoming_root)


def threshold_reached(
    incoming_root: Path = DEFAULT_INCOMING,
    threshold: int = DEFAULT_PROCESS_THRESHOLD,
) -> bool:
    """True once the queue has reached the batch threshold."""
    return inbox_queue.threshold_reached(incoming_root, threshold)


def route(
    incoming_root: Path,
    article: Path,
    topic: str,
    *,
    when: date | None = None,
) -> Path:
    """Move an inbox article into its real topic dir, updating `category:`."""
    return inbox_queue.route(
        incoming_root,
        article,
        topic,
        when=when,
        deps=_queue_deps(),
    )


def _cli_ops() -> inbox_cli.CliOps:
    """Build CLI operations from current facade globals for monkeypatch support."""
    return inbox_cli.CliOps(
        add_article=add_article,
        pending=pending,
        count=count,
        route=lambda incoming_root, article, topic: route(incoming_root, article, topic),
        find_in_inbox_by_url=find_in_inbox_by_url,
    )


def _build_parser() -> object:
    """Compatibility wrapper for tests/callers that import the parser builder."""
    return inbox_cli.build_parser(DEFAULT_INCOMING)


def main(argv: list[str] | None = None) -> int:
    """Run the inbox CLI."""
    return inbox_cli.main(argv, default_incoming=DEFAULT_INCOMING, ops=_cli_ops())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
