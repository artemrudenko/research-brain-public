#!/usr/bin/env python3
"""
collect.py — deterministic, stdlib-only RSS collector for the headless path.

The agent skill `schedule/collect-base.md` does the full collection contract
(rank a wide candidate pool, write LLM "Key takeaways", scrape JS pages with a
browser). A headless cron / Codex run has no LLM and no browser, so it cannot
invoke that skill — and the brain never auto-populates. This module fills that
gap by implementing the cheapest rungs of the RSS-first acquisition ladder
(CONVENTIONS §12, collect-base Step 3): **RSS / Atom feeds whose `<item>` /
`<entry>` already carries the full article body**, plus a static article-page
top-up when the entry is only a short summary. No LLM, no browser, no ranking —
just fetch → parse → dedup → optional top-up → quality gate → save → register, so
`pipeline/1-incoming/` gets populated on the pure-headless path.

It deliberately mirrors the existing pipeline scripts:
  - PyYAML is imported lazily via `_load_yaml()` (a friendly guard, like inbox.py)
    and the strict frontmatter block is built exactly like `inbox._frontmatter`;
  - the registry, URL-dedup and health-event writers are REUSED from
    `scripts.registry`, `scripts.normalize_url` and `scripts.health` — this module
    owns none of those schemas;
  - sources are loaded through `scripts.sources.store`, so it reads the same
    active config the agent path does — `config/sources.yaml` when present,
    (YAML-only since 0.8.0 — CONVENTIONS §2.3; legacy .md imports once via
    `schema.py migrate-config`).

Compared with the agent path it intentionally does NOT: rank/cap a candidate pool,
run browser/JS extraction, run near-dup detection, or fabricate a "## Key
takeaways" section (that needs an LLM — enrichment is left to curate/synthesis).
It does run a deterministic junk-wall / too-little-prose gate before writing, so
long cookie/paywall/login walls are not registered as articles. Each saved article
is a CONVENTIONS §5 strict file that the rest of the pipeline treats exactly like
an agent-collected one.

RSS `<category>` values are treated as untrusted seed labels: they are admitted
only when they resolve through `config/tags.yaml` (live vocabulary or synonyms);
unknown labels are dropped. The topic/category tag itself is kept for backward
compatibility.

CLI:
    python3 scripts/collect.py                       # all categories, defaults
    python3 scripts/collect.py --category ai-agents  # one category
    python3 scripts/collect.py --dry-run             # report would-save + RSS-lite coverage
"""

from __future__ import annotations

import argparse
import datetime
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Make the `scripts` package importable when run directly (`python3 scripts/collect.py`),
# not only as a module — mirrors inbox.py / health.py.
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.authors.collect import (  # noqa: E402
    author_item_filters as _author_item_filters,
)
from scripts.authors.collect import (  # noqa: E402
    author_sources_by_topic as _author_sources_by_topic,
)
from scripts.authors.collect import (  # noqa: E402
    withheld_author_warnings as _withheld_author_warnings,
)
from scripts.authors.plan import resolve_plans as _resolve_author_plans  # noqa: E402
from scripts.authors.store import AUTHORS_YAML as _AUTHORS_YAML  # noqa: E402
from scripts.authors.store import load_authors as _load_authors  # noqa: E402
from scripts.collection import fetch as _fetch_module  # noqa: E402
from scripts.collection.article import (  # noqa: E402
    DEFAULT_TAGS,
    _article_tags,
    _frontmatter,
    _load_seed_tag_registry,
    _load_yaml,
    _normalize_seed_label,
    _yaml_scalar_line,
    build_article,
)
from scripts.collection.feed import (  # noqa: E402
    _DOCTYPE_RE,
    _NS_ATOM,
    _NS_CONTENT,
    _NS_DC,
    _NS_RDF,
    FeedItem,
    FeedParseError,
    _atom_link,
    _find_text,
    _hardened_parse,
    _parse_atom_entry,
    _parse_rss_item,
    _text,
    parse_feed,
)
from scripts.collection.registry import (  # noqa: E402
    _is_valid_article_url,
    _source_domain,
    load_known_urls,
)
from scripts.collection.run import (  # noqa: E402
    DEFAULT_FETCH_WORKERS,
    DEFAULT_MIN_BODY_CHARS,
    TOP_UP_ATTEMPT_BUDGET_MULTIPLIER,
    CollectResult,
    ItemFilter,
)
from scripts.collection.run import _record_health as _record_health_impl  # noqa: E402
from scripts.collection.run import collect_category as _collect_category_impl  # noqa: E402
from scripts.collection.text import (  # noqa: E402
    _NO_SUMMARY_NOTE,
    _article_body_reject_reason,
    _extract_static_article_text,
    _top_up_short_body,
    slugify,
    strip_html,
    to_iso_date,
)
from scripts.manage_sources import Category, Source  # noqa: E402
from scripts.normalize_url import normalize  # noqa: E402
from scripts.registry import append_registry_row_if_absent, atomic_write_unique  # noqa: E402
from scripts.run_lock import acquire as _lock_acquire  # noqa: E402
from scripts.run_lock import release as _lock_release  # noqa: E402
from scripts.source_report.events import record_decision  # noqa: E402
from scripts.sources import store as _sources_store  # noqa: E402
from scripts.state import state_root as _state_root  # noqa: E402

# Re-export fetch-layer modules/objects that tests and older callers reached via
# scripts.collect. The wrapper keeps monkeypatching `collect._opener` effective.
socket = _fetch_module.socket
urllib = _fetch_module.urllib
DEFAULT_FETCH_TIMEOUT = _fetch_module.DEFAULT_FETCH_TIMEOUT
MAX_FEED_BYTES = _fetch_module.MAX_FEED_BYTES
_SafeRedirectHandler = _fetch_module._SafeRedirectHandler
_assert_public_host = _fetch_module._assert_public_host
_fetch_opener_impl = _fetch_module._opener

# Defaults resolve relative to the project root regardless of cwd (CONVENTIONS §1).
DEFAULT_SOURCES = _PROJECT_ROOT / "config" / "sources.yaml"
DEFAULT_INCOMING = _PROJECT_ROOT / "pipeline" / "1-incoming"
DEFAULT_REGISTRY = _PROJECT_ROOT / "pipeline" / "registry.md"
DEFAULT_SCHEDULE = _PROJECT_ROOT / "config" / "schedule.yaml"

# Per-category save cap fallback when schedule.yaml has no `collect.max_articles_per_topic`.
DEFAULT_MAX_ARTICLES = 10

# The unique-name atomic write lives once in registry.py (the shared leaf); keep the
# private name this module + its tests reference.
_atomic_write_unique = atomic_write_unique

__all__ = [
    "DEFAULT_FETCH_TIMEOUT",
    "DEFAULT_FETCH_WORKERS",
    "DEFAULT_INCOMING",
    "DEFAULT_MAX_ARTICLES",
    "DEFAULT_MIN_BODY_CHARS",
    "DEFAULT_REGISTRY",
    "DEFAULT_SCHEDULE",
    "DEFAULT_SOURCES",
    "DEFAULT_TAGS",
    "FeedItem",
    "FeedParseError",
    "CollectResult",
    "MAX_FEED_BYTES",
    "TOP_UP_ATTEMPT_BUDGET_MULTIPLIER",
    "_DOCTYPE_RE",
    "_NO_SUMMARY_NOTE",
    "_NS_ATOM",
    "_NS_CONTENT",
    "_NS_DC",
    "_NS_RDF",
    "_SafeRedirectHandler",
    "_article_body_reject_reason",
    "_article_tags",
    "_assert_public_host",
    "_atom_link",
    "_extract_static_article_text",
    "_find_text",
    "_frontmatter",
    "_hardened_parse",
    "_is_valid_article_url",
    "_load_seed_tag_registry",
    "_load_yaml",
    "_normalize_seed_label",
    "_opener",
    "_parse_atom_entry",
    "_parse_rss_item",
    "_record_health",
    "_source_domain",
    "_text",
    "_top_up_short_body",
    "_yaml_scalar_line",
    "build_article",
    "collect_category",
    "fetch",
    "load_known_urls",
    "main",
    "normalize",
    "parse_feed",
    "slugify",
    "socket",
    "strip_html",
    "to_iso_date",
    "urllib",
]


def _opener() -> _fetch_module.urllib.request.OpenerDirector:
    """Compatibility hook for tests/callers that patch scripts.collect._opener."""
    return _fetch_opener_impl()


def fetch(url: str, *, timeout: float = DEFAULT_FETCH_TIMEOUT) -> str:
    """Compatibility wrapper around the collection fetch implementation."""
    _fetch_module._opener = _opener
    return _fetch_module.fetch(url, timeout=timeout)


# --------------------------------------------------------------------------- #
# Per-category collection
# --------------------------------------------------------------------------- #


def _record_health(registry_path: Path, *, source: str, items: int, status: str) -> None:
    """Compatibility wrapper: tests monkeypatch `collect._record_health` directly.

    Delegates to the real implementation in `scripts.collection.run`; kept as a
    plain module-level function (not a re-exported alias) so
    `monkeypatch.setattr(collect, "_record_health", ...)` replaces what
    `collect_category` actually calls, not a copy.
    """
    _record_health_impl(registry_path, source=source, items=items, status=status)


def collect_category(
    *,
    category: str,
    sources: list[Source],
    incoming_dir: Path,
    registry_path: Path,
    today: str,
    known_urls: set[str],
    min_body_chars: int = DEFAULT_MIN_BODY_CHARS,
    max_articles: int | None = None,
    dry_run: bool = False,
    fetch_fn: Callable[[str], str] | None = None,
    fetch_workers: int = DEFAULT_FETCH_WORKERS,
    tags_path: Path = DEFAULT_TAGS,
    journal_root: Path | None = None,
    run_id: str = "",
    item_filters: dict[str, ItemFilter] | None = None,
) -> CollectResult:
    """Collect RSS articles for one category (facade over `scripts.collection.run`).

    The implementation lives in `scripts.collection.run.collect_category` (split
    out per ADR 0021, mirroring the rest of the `scripts.collection` package);
    this facade's only job is resolving `fetch_fn` at CALL time — not as a
    default expression — so a test/caller that monkeypatches `collect.fetch`
    (this module's compatibility wrapper) is honoured rather than a stale
    binding captured when this module was imported.
    """
    fetcher = fetch_fn if fetch_fn is not None else fetch
    return _collect_category_impl(
        category=category,
        sources=sources,
        incoming_dir=incoming_dir,
        registry_path=registry_path,
        today=today,
        known_urls=known_urls,
        min_body_chars=min_body_chars,
        max_articles=max_articles,
        dry_run=dry_run,
        fetch_fn=fetcher,
        fetch_workers=fetch_workers,
        tags_path=tags_path,
        journal_root=journal_root,
        run_id=run_id,
        item_filters=item_filters,
        record_health_fn=_record_health,
        record_decision_fn=record_decision,
        append_registry_row_fn=append_registry_row_if_absent,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _merge_author_sources(
    config_dir: Path, categories: list[Category], selected: list[Category]
) -> tuple[dict[str, ItemFilter], list[str]]:
    """Append monitored authors' feeds to the categories being collected.

    Returns `(item_filters, problems)` — the per-feed predicates a
    `publication-filter` author needs, and the roster's unresolvable entries as
    human-readable strings for the caller to surface. The two are built together
    on purpose: a merged publication feed WITHOUT its predicate would collect the
    whole publication under one author's name.

    An empty/absent `authors.yaml` is a clean no-op: nobody is followed, which is
    the default (CONVENTIONS §2.4).

    Authors are merged into `selected` ONLY — a `--category` run must not start
    fetching an author who writes on some other topic. `categories` (the full
    set) is still passed to the resolver, because a `publication-filter` author
    is followed through a feed that may live under any category, collected in
    this run or not.
    """
    try:
        authors = _load_authors(config_dir / _AUTHORS_YAML)
    except (ValueError, RuntimeError) as exc:
        # A malformed roster must not take collection down with it: the sources
        # config is still valid and its feeds are still worth collecting.
        return {}, [f"cannot read {_AUTHORS_YAML}: {exc}"]

    plans, problems = _resolve_author_plans(authors, categories)
    # A resolved-but-uncollectable variant (scholarly / search) is WARNED about,
    # never silently skipped — a followed author who quietly collects nothing reads
    # as "published nothing lately" (review 2026-07-22, P1).
    problems.extend(_withheld_author_warnings(plans))
    by_topic = _author_sources_by_topic(plans, existing=categories)
    item_filters = _author_item_filters(plans, authors)
    by_name = {c.name: c for c in selected}
    for topic, sources in sorted(by_topic.items()):
        category = by_name.get(topic)
        if category is None:
            # Either an unknown topic, or one this run did not select. Say which,
            # so a real config error is not read as a --category side effect.
            known = {c.name for c in categories}
            problems.append(
                f"topic {topic!r} is not a source category — add it with "
                f"source-manage before following authors into it"
                if topic not in known
                else f"topic {topic!r} is not part of this run (--category), "
                f"so its authors were not collected"
            )
            continue
        category.sources.extend(sources)
    return item_filters, problems


def _select_categories(categories: list[Category], wanted: str | None) -> list[Category]:
    """All categories, or just the one named `wanted` (empty list when unknown)."""
    if wanted is None:
        return categories
    return [c for c in categories if c.name == wanted]


def _read_max_articles(schedule_path: Path) -> int:
    """`collect.max_articles_per_topic` from schedule.yaml (DEFAULT_MAX_ARTICLES fallback)."""
    try:
        data = _load_yaml().safe_load(schedule_path.read_text(encoding="utf-8"))
    except OSError:
        return DEFAULT_MAX_ARTICLES
    if isinstance(data, dict):
        collect_cfg = data.get("collect")
        if isinstance(collect_cfg, dict):
            value = collect_cfg.get("max_articles_per_topic")
            if isinstance(value, int) and value > 0:
                return value
    return DEFAULT_MAX_ARTICLES


def _active_source_type_counts(sources: list[Source]) -> Counter[str]:
    """Active source counts by type, for RSS-lite capability diagnostics."""
    return Counter(s.type for s in sources if s.active)


def _format_non_rss_counts(counts: Counter[str]) -> str:
    """Stable `blog=1, medium-tag=2` text for non-RSS source diagnostics."""
    parts = [
        f"{name}={count}"
        for name, count in sorted(counts.items())
        if name != "rss" and count
    ]
    return ", ".join(parts)


def _default_collect_date() -> str:
    """Today's date on the UTC axis (YYYY-MM-DD).

    Collect must stamp `collected:` on the SAME axis the digest/health windows use
    (`datetime.now(UTC).date()` in build_digest.py). Using the local `date.today()`
    made an eastern-timezone run near local midnight stamp a date ahead of UTC, so the
    digest's `value <= today (UTC)` window silently excluded the run's own articles.
    """
    return datetime.datetime.now(datetime.UTC).date().isoformat()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns 0, or non-zero only on a usage/config error."""
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic, stdlib-only RSS collector "
            "(feed bodies plus static article-page top-up)."
        )
    )
    parser.add_argument(
        "--sources",
        default=str(DEFAULT_SOURCES),
        help="sources config (a sources.md path resolves to its sources.yaml twin when present)",
    )
    parser.add_argument("--incoming", default=str(DEFAULT_INCOMING), help="pipeline/1-incoming")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="pipeline/registry.md")
    parser.add_argument("--schedule", default=str(DEFAULT_SCHEDULE), help="config/schedule.yaml")
    parser.add_argument("--category", default=None, help="one category (default: all)")
    parser.add_argument(
        "--today", default=_default_collect_date(), help="collection date (UTC, YYYY-MM-DD)"
    )
    parser.add_argument(
        "--min-body-chars", type=int, default=DEFAULT_MIN_BODY_CHARS,
        help="skip articles whose stripped body is shorter than this",
    )
    parser.add_argument(
        "--max-articles", type=int, default=None,
        help="per-category save cap (default: collect.max_articles_per_topic from schedule.yaml)",
    )
    parser.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    parser.add_argument(
        "--authors-only",
        action="store_true",
        help=(
            "collect ONLY monitored authors' feeds (config/authors.yaml), not the "
            "topic's ordinary sources — the weekly-run roster pass alongside the "
            "agentic collect-topic sweep"
        ),
    )
    parser.add_argument(
        "--lock-held",
        action="store_true",
        help=(
            "the caller already holds the single run lock (weekly-run) — do not "
            "acquire or release it here, just collect under it"
        ),
    )
    args = parser.parse_args(argv)

    # Validate --today up front: a garbage value must never reach `date_published`.
    try:
        datetime.date.fromisoformat(args.today)
    except ValueError:
        print(f"ERROR: --today must be YYYY-MM-DD, got {args.today!r}", file=sys.stderr)
        return 2

    # Reject nonsensical bounds: a non-positive cap would silently save nothing, and
    # a negative floor would let empty-body items through — both are usage errors.
    if args.max_articles is not None and args.max_articles <= 0:
        print(
            f"ERROR: --max-articles must be a positive integer, got {args.max_articles}",
            file=sys.stderr,
        )
        return 2
    if args.min_body_chars < 0:
        print(
            f"ERROR: --min-body-chars must be >= 0, got {args.min_body_chars}",
            file=sys.stderr,
        )
        return 2

    # YAML-only (CONVENTIONS §2.3, 0.8.0): a legacy `--sources …/sources.md`
    # spelling resolves to the `sources.yaml` twin — the file the runtime reads.
    sources_path = _sources_store.prefer_yaml_twin(Path(args.sources))
    tags_path = sources_path.parent / "tags.yaml"
    if not sources_path.exists():
        hint = ""
        if _sources_store.legacy_md_needs_migration(sources_path.parent):
            hint = (
                " — your config is still in the retired .md format; run "
                "`python3 scripts/schema.py migrate-config` first"
            )
        print(f"ERROR: sources file not found: {sources_path}{hint}", file=sys.stderr)
        return 1

    try:
        categories = _sources_store.load_categories(sources_path)
    except (ValueError, RuntimeError) as exc:
        # Malformed YAML config (or missing PyYAML) must fail loudly with the
        # parse error, never silently collect nothing.
        print(f"ERROR: cannot read {sources_path}: {exc}", file=sys.stderr)
        return 1
    selected = _select_categories(categories, args.category)
    # A typo'd --category must fail loudly, not silently collect nothing.
    if args.category is not None and not selected:
        print(f"ERROR: unknown category {args.category!r} (not in {sources_path})", file=sys.stderr)
        return 1

    # Monitored authors (CONVENTIONS §2.4) join as ORDINARY sources on their
    # topic's category, so everything below — dedup, ordering, budget, journal —
    # applies to them with no author-specific branch. Absent roster → no-op.
    # `problems` is PRINTED rather than swallowed: an author who silently drops
    # out reads as "published nothing lately", which nobody can debug.
    # Snapshot each selected category's source count BEFORE the merge appends the
    # roster's feeds at the tail, so --authors-only can keep exactly those.
    base_counts = {id(category): len(category.sources) for category in selected}
    author_filters, author_problems = _merge_author_sources(
        sources_path.parent, categories, selected
    )
    for problem in author_problems:
        print(f"WARN: author monitoring: {problem}", file=sys.stderr)

    if args.authors_only:
        # The weekly-run roster pass: collect ONLY the followed authors' feeds,
        # never the ordinary sources (the agentic collect-topic pass owns those).
        # Keep just the tail the merge appended; a category with no followed
        # author is dropped so the run never fetches or prints an empty topic.
        # An absent/empty roster leaves nothing selected — a clean no-op, not a
        # fall-through to the ordinary feeds.
        trimmed: list[Category] = []
        for category in selected:
            author_sources = category.sources[base_counts[id(category)]:]
            if author_sources:
                category.sources = author_sources
                trimmed.append(category)
        selected = trimmed

    incoming_dir = Path(args.incoming)
    registry_path = Path(args.registry)
    max_articles = args.max_articles
    if max_articles is None:
        max_articles = _read_max_articles(Path(args.schedule))

    # Serialise against weekly-run / a concurrent collect: collection writes shared
    # state (1-incoming + registry), so it must run under the single run lock. A held
    # lock means another run already owns the pipeline — skip cleanly (not an error).
    #
    # The lock co-locates with the registry it guards: `registry.parent/.run.lock`,
    # then routed through the durable-state resolver so a RESEARCH_BRAIN_STATE_DIR
    # deployment relocates the lock onto the SAME persistent volume as the rest of
    # the runtime state. This keeps the lock on one filesystem with the state it
    # serializes, so run_lock's os.replace/os.rename swaps stay atomic (atomicity
    # only holds within a single FS). With the env unset this is the exact in-repo
    # `registry.parent/.run.lock` — byte-for-byte identity, no behavior change.
    lock_path = _state_root(registry_path.parent / ".run.lock")
    # --lock-held: the caller (weekly-run's roster pass) already owns the single run
    # lock, so re-acquiring would find it held and self-skip — collecting nothing.
    # Skip acquisition here and, symmetrically, never release it: the orchestrator
    # releases at the end of its own run (mirrors collect-topic.md's Step 0a/0b).
    lock = None if args.lock_held else _lock_acquire(lock_path, note="collect.py")
    if lock is not None and not lock.acquired:
        print(
            f"a run is already in progress (pid {lock.holder_pid}) — skipping collect",
            file=sys.stderr,
        )
        return 0

    total_attempted = 0
    total_source_errors = 0
    total_active_non_rss = 0
    # One correlator for every decision this invocation journals, so a report can
    # group by run without inferring boundaries from timestamps. ADR 0009 records
    # the absence of a run id as a known gap; this is a first, local step — it does
    # not yet span the orchestrator's other stages.
    run_id = f"collect-{datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%SZ')}"
    # The journal belongs beside a REAL pipeline, so the root is derived from the
    # registry's own location rather than assumed to be this checkout. An unusual
    # `--registry` means we cannot tell where the project root is, and guessing
    # would scatter journal files (or write into the developer's checkout during
    # a test run — which is exactly what a hardcoded root did).
    journal_root = (
        registry_path.parent.parent if registry_path.parent.name == "pipeline" else None
    )
    try:
        known_urls = load_known_urls(registry_path)
        for category in selected:
            type_counts = _active_source_type_counts(category.sources)
            active_non_rss = sum(
                count for source_type, count in type_counts.items() if source_type != "rss"
            )
            total_active_non_rss += active_non_rss
            result = collect_category(
                category=category.name,
                sources=category.sources,
                incoming_dir=incoming_dir,
                registry_path=registry_path,
                today=args.today,
                known_urls=known_urls,
                min_body_chars=args.min_body_chars,
                max_articles=max_articles,
                dry_run=args.dry_run,
                tags_path=tags_path,
                journal_root=journal_root,
                run_id=run_id,
                item_filters=author_filters,
            )
            total_attempted += result.sources_attempted
            total_source_errors += result.source_errors
            prefix = "dry-run OK" if args.dry_run else "OK"
            print(
                f"{prefix}: {result.saved} saved, {result.skipped_dup} dup, "
                f"{result.skipped_short} short, {result.skipped_junk} junk, "
                f"{result.errors} errors for {category.name}"
            )
            if args.dry_run:
                print(
                    "DRY-RUN: counts above are would-save counts; no files or "
                    "registry rows were written."
                )
                if result.top_up_attempted:
                    print(
                        "DRY-RUN: static top-up "
                        f"{result.top_up_attempted} attempted, "
                        f"{result.top_up_saved} usable, "
                        f"{result.top_up_failed} failed, "
                        f"{result.top_up_still_short} still short."
                    )
                non_rss_counts = _format_non_rss_counts(type_counts)
                rss_count = type_counts.get("rss", 0)
                noun = "source" if rss_count == 1 else "sources"
                print(
                    f"DRY-RUN: {category.name} headless coverage: "
                    f"{rss_count} active RSS {noun} attempted."
                )
                if active_non_rss:
                    skipped_noun = "source" if active_non_rss == 1 else "sources"
                    print(
                        f"RSS-lite: {active_non_rss} active non-RSS {skipped_noun} "
                        f"skipped by collect.py"
                        + (f": {non_rss_counts}." if non_rss_counts else "."),
                        file=sys.stderr,
                    )
                    print(
                        "RSS-lite: full agentic collection can use these via "
                        "schedule/weekly-run.md.",
                        file=sys.stderr,
                    )
    finally:
        # Only release a lock this process acquired; under --lock-held the
        # orchestrator owns it and releases it at the end of its own run.
        if lock is not None:
            _lock_release(lock_path, token=lock.token)

    # Zero active RSS sources selected → nothing was even attempted. Without a
    # diagnostic this looks like a healthy but "quiet week" (exit 0, no output to
    # stderr); warn explicitly so an all-inactive or empty selection is visible.
    # `total_attempted` counts only the active rss sources collect_category fetched,
    # so 0 here means the selection yielded none. Exit-code semantics are unchanged.
    if total_attempted == 0:
        scope = args.category if args.category is not None else "all"
        if args.authors_only:
            # Roster pass: the ordinary RSS sources were deliberately excluded, so
            # blaming "no active RSS sources" misattributes the cause. Nothing was
            # attempted because the roster yielded no collectable author feed.
            print(
                f"WARNING: no monitored authors with a collectable feed in {scope} "
                "— nothing to collect (roster empty, or all authors paused/non-RSS)",
                file=sys.stderr,
            )
        else:
            print(
                f"WARNING: no active RSS sources in {scope} — nothing to collect",
                file=sys.stderr,
            )
    elif args.dry_run and total_active_non_rss:
        skipped_noun = "source" if total_active_non_rss == 1 else "sources"
        print(
            f"RSS-lite: {total_active_non_rss} active non-RSS {skipped_noun} "
            "were visible but not collected by collect.py.",
            file=sys.stderr,
        )

    # Fail loudly ONLY on a TRUE total collection failure: every attempted source
    # failed to fetch/parse. This is keyed on source-level outcomes, not on the
    # saved count — a feed that responded but yielded only duplicates is a success
    # (so it must NOT trip the failure), and one saved item must NOT mask the fact
    # that every OTHER feed was down. If even one source responded, cron may proceed.
    if total_attempted > 0 and total_source_errors == total_attempted:
        print(
            "ERROR: collection failed — every attempted source errored",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
