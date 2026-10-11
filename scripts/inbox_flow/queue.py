"""Queue operations for the ad-hoc article-capture inbox."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from scripts import schema
from scripts.inbox_flow import frontmatter
from scripts.inbox_flow.model import DEFAULT_PROCESS_THRESHOLD, INBOX_TOPIC, capture_defaults
from scripts.inbox_flow.paths import (
    default_registry,
    ensure_inbox_article,
    inbox_dir,
    safe_topic,
    slugify,
)
from scripts.inbox_flow.registry_ops import (
    article_field,
    article_url,
    find_by_url,
    find_in_inbox_by_url,
    url_in_registry,
)
from scripts.registry import (
    advisory_lock,
    append_registry_row_if_absent,
    atomic_write_unique,
    set_registry_category,
)
from scripts.sanitize_incoming import COMPANION_DIRNAME


class FrontmatterBuilder(Protocol):
    """Callable that renders article frontmatter."""

    def __call__(
        self,
        *,
        source: str,
        url: str,
        title: str,
        author: str,
        when: date,
        category: str,
        tags: list[str] | None,
    ) -> str:
        """Render a strict article frontmatter block."""


class AtomicWriteUnique(Protocol):
    """Callable that writes text to a unique path."""

    def __call__(
        self,
        directory: Path,
        stem: str,
        text: str,
        suffix: str = ".md",
    ) -> Path:
        """Write `text` to a unique file under `directory`."""


class AppendRegistryRowIfAbsent(Protocol):
    """Callable that appends a registry row unless the URL is already present."""

    def __call__(
        self,
        path: Path,
        *,
        collected: str,
        category: str,
        url: str,
        title: str,
        status: str = "",
    ) -> bool:
        """Return True when a row was inserted."""


class SetRegistryCategory(Protocol):
    """Callable that retargets an existing registry row's category."""

    def __call__(self, path: Path, *, url: str, category: str) -> bool:
        """Return True when a row was changed."""


@dataclass(frozen=True)
class QueueDeps:
    """Injectable operations used by queue mutations."""

    article_field: Callable[[Path, str], str]
    article_url: Callable[[Path], str]
    url_in_registry: Callable[[Path, str], bool]
    append_registry_row_if_absent: AppendRegistryRowIfAbsent
    set_registry_category: SetRegistryCategory
    atomic_write_unique: AtomicWriteUnique
    frontmatter: FrontmatterBuilder
    default_registry: Callable[[Path], Path] = default_registry


def _load_yaml_default() -> object:
    import yaml  # noqa: PLC0415

    return yaml


def _default_frontmatter(
    *,
    source: str,
    url: str,
    title: str,
    author: str,
    when: date,
    category: str,
    tags: list[str] | None,
) -> str:
    return frontmatter.article_frontmatter(
        schema_version=schema.CURRENT["article"],
        source=source,
        url=url,
        title=title,
        author=author,
        when=when,
        category=category,
        tags=tags,
        load_yaml=_load_yaml_default,
    )


def default_deps() -> QueueDeps:
    """Runtime dependencies for direct package use."""
    return QueueDeps(
        article_field=article_field,
        article_url=article_url,
        url_in_registry=url_in_registry,
        append_registry_row_if_absent=append_registry_row_if_absent,
        set_registry_category=set_registry_category,
        atomic_write_unique=atomic_write_unique,
        frontmatter=_default_frontmatter,
    )


def pending(incoming_root: Path) -> list[Path]:
    """Captured-but-unprocessed article files, sorted, excluding companions."""
    root = inbox_dir(incoming_root)
    if not root.is_dir():
        return []
    return sorted(
        p
        for p in root.glob("*.md")
        if p.is_file() and not p.name.startswith(".") and COMPANION_DIRNAME not in p.parts
    )


def count(incoming_root: Path) -> int:
    """How many articles are queued for processing."""
    return len(pending(incoming_root))


def threshold_reached(incoming_root: Path, threshold: int = DEFAULT_PROCESS_THRESHOLD) -> bool:
    """True once the queue has reached the batch threshold."""
    return count(incoming_root) >= threshold


def add_article(
    incoming_root: Path,
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
    deps: QueueDeps | None = None,
) -> Path | None:
    """Capture an article into the inbox; return its path, or None on duplicate."""
    ops = deps or default_deps()
    when = when or date.today()
    registry_path = registry_path or ops.default_registry(incoming_root)
    metadata = capture_defaults(author, tags)
    author = metadata.author
    tags = metadata.tags

    existing = find_in_inbox_by_url(
        incoming_root,
        url,
        pending,
        article_url_reader=ops.article_url,
    )
    if existing is not None:
        if not ops.url_in_registry(registry_path, url):
            ops.append_registry_row_if_absent(
                registry_path,
                collected=ops.article_field(existing, "collected") or when.isoformat(),
                category=ops.article_field(existing, "category") or category,
                url=ops.article_url(existing) or url,
                title=ops.article_field(existing, "title").strip('"') or title,
            )
        return existing
    if ops.url_in_registry(registry_path, url):
        return None

    article_frontmatter = ops.frontmatter(
        source=source,
        url=url,
        title=title,
        author=author,
        when=when,
        category=category,
        tags=tags,
    )
    dest = ops.atomic_write_unique(
        inbox_dir(incoming_root),
        f"{when.isoformat()}_{slugify(title)}",
        f"{article_frontmatter}\n\n{body.rstrip()}\n",
    )
    try:
        inserted = ops.append_registry_row_if_absent(
            registry_path,
            collected=when.isoformat(),
            category=category,
            url=url,
            title=title,
        )
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    if not inserted:
        dest.unlink(missing_ok=True)
        return None
    return dest


# Serializes route()'s check-write-cleanup sequence across processes. Lives in
# the inbox dir as a dotfile so pending()'s `*.md` glob can never list it.
_ROUTE_LOCK_FILENAME = ".route.lock"


def _routed_articles(topic_dir: Path) -> list[Path]:
    """Articles already routed into `topic_dir` (dotfiles/companions excluded)."""
    if not topic_dir.is_dir():
        return []
    return sorted(
        path
        for path in topic_dir.glob("*.md")
        if path.is_file() and not path.name.startswith(".")
    )


def _find_routed_copy(incoming_root: Path, url: str, ops: QueueDeps) -> Path | None:
    """First topic copy anywhere under `incoming_root` carrying `url`.

    Scans EVERY topic dir, not just the route's requested destination: a
    crashed route's copy must be adopted even when the retry (LLM-driven
    curation) picks a different topic — otherwise the retry writes a second
    copy and the first is double-counted downstream. The inbox queue itself is
    excluded so a route can never "adopt" its own source article.
    """
    if not incoming_root.is_dir():
        return None
    for topic_dir in sorted(incoming_root.iterdir()):
        if (
            not topic_dir.is_dir()
            or topic_dir.name == INBOX_TOPIC
            or topic_dir.name == COMPANION_DIRNAME
            or topic_dir.name.startswith(".")
        ):
            continue
        found = find_by_url(
            _routed_articles(topic_dir), url, article_url_reader=ops.article_url
        )
        if found is not None:
            return found
    return None


def route(
    incoming_root: Path,
    article: Path,
    topic: str,
    *,
    when: date | None = None,  # noqa: ARG001 - reserved for future re-stamp.
    deps: QueueDeps | None = None,
) -> Path:
    """Move an inbox article into its real topic dir, updating `category:`.

    Crash- and race-safe: the copy is written before the source is unlinked (a
    crash duplicates rather than loses), and the duplicate window is closed on
    both sides — a copy already carrying this article's URL in ANY topic dir
    (a route that died between write and cleanup, even one retried under a
    different topic) is ADOPTED and the cleanup finished instead of a second
    copy being written, while an advisory lock keeps two concurrent routes
    from racing through the check-write-cleanup sequence together.
    """
    ops = deps or default_deps()
    topic = safe_topic(topic)
    ensure_inbox_article(incoming_root, article)
    topic_dir = incoming_root / topic
    # Read the URL before taking the lock: a concurrent route may consume the
    # source while we wait, and the URL is what resolves its destination then.
    article_url_value = ops.article_url(article)
    with advisory_lock(inbox_dir(incoming_root) / _ROUTE_LOCK_FILENAME):
        if article_url_value:
            existing = _find_routed_copy(incoming_root, article_url_value, ops)
            if existing is not None:
                # Adopt wherever the earlier route landed it — the first
                # completed write wins, including its topic choice.
                return _finish_route(
                    ops,
                    incoming_root,
                    article,
                    article_url_value,
                    existing.parent.name,
                    existing,
                )
        if not article.exists():
            raise FileNotFoundError(article)
        text = article.read_text(encoding="utf-8")
        text = _replace_category(text, topic)
        dest = ops.atomic_write_unique(topic_dir, article.stem, text)
        return _finish_route(
            ops, incoming_root, article, article_url_value, topic, dest
        )


def _finish_route(
    ops: QueueDeps,
    incoming_root: Path,
    article: Path,
    article_url_value: str,
    topic: str,
    dest: Path,
) -> Path:
    """Complete a route whose topic copy exists: retarget registry, drop source."""
    if article_url_value:
        ops.set_registry_category(
            ops.default_registry(incoming_root),
            url=article_url_value,
            category=topic,
        )
    companion = article.parent / COMPANION_DIRNAME / article.name
    companion.unlink(missing_ok=True)
    article.unlink(missing_ok=True)
    return dest


def _replace_category(text: str, topic: str) -> str:
    lines = text.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        if line.startswith("category:"):
            ending = "\n" if line.endswith("\n") else ""
            lines[idx] = f"category: {topic}{ending}"
            return "".join(lines)
    return text


__all__ = [
    "AppendRegistryRowIfAbsent",
    "AtomicWriteUnique",
    "FrontmatterBuilder",
    "QueueDeps",
    "SetRegistryCategory",
    "add_article",
    "count",
    "default_deps",
    "pending",
    "route",
    "threshold_reached",
]
