"""run.py — the per-category collection loop (fetch → parse → dedup → write).

Split out of `collect.py` (was ~1,600 lines pre-split into `scripts/collection/`;
still 1,006 lines after that split with this loop still inline). `collect_category`
is the largest single piece of logic in the headless collector and the one part
genuinely independent of the CLI (`main`, argparse, `--category`/`--authors-only`
selection): it takes already-resolved sources/config values as plain arguments
and returns a `CollectResult`, with no argparse or process-exit concern of its
own. Moving it here mirrors the existing `scripts/collection/{article,feed,
fetch,registry,text}.py` split (ADR 0021 style: one stable CLI/import-surface
facade, package internals split by concern).

`collect.py` re-exports `CollectResult` and `collect_category` unchanged, so
`from scripts.collect import collect_category` (tests, `setup_check.py`,
`weekly-run` health probes) keeps working exactly as before the split.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from scripts.authors.collect import FeedItemLike as _FeedItemLike
from scripts.collection.article import DEFAULT_TAGS, _article_tags, build_article
from scripts.collection.feed import FeedItem, FeedParseError, parse_feed
from scripts.collection.registry import _is_valid_article_url, _source_domain
from scripts.collection.text import (
    _article_body_reject_reason,
    _top_up_short_body,
    slugify,
    strip_html,
)
from scripts.content_metadata import AuthorIdentity, ContentMetadata, from_html, merge_feed_author
from scripts.health import record_event  # DRY reuse
from scripts.manage_sources import Source
from scripts.normalize_url import normalize
from scripts.registry import append_registry_row_if_absent, atomic_write_unique
from scripts.source_report.events import record_decision
from scripts.source_report.model import CandidateDecision

# A per-feed predicate: "is this item one we want from this source?". Used only
# by author monitoring; absent for every ordinary source, so the default path is
# unchanged. Typed against the structural `FeedItemLike` rather than `FeedItem`
# so this alias and the one `scripts/authors/collect.py` builds are the SAME
# type — `dict` is invariant in its value, so two compatible-but-distinct
# Callable types would not interchange.
ItemFilter = Callable[[_FeedItemLike], bool]

DEFAULT_MIN_BODY_CHARS = 500
DEFAULT_FETCH_WORKERS = 8
TOP_UP_ATTEMPT_BUDGET_MULTIPLIER = 3

_atomic_write_unique = atomic_write_unique


@dataclass
class CollectResult:
    """Tallies for one `collect_category` run (so callers/tests can assert counts)."""

    saved: int = 0
    skipped_dup: int = 0
    skipped_short: int = 0
    skipped_junk: int = 0
    errors: int = 0
    # Source-level fetch/parse outcome (distinct from `errors`, which also counts
    # per-item registry failures): used to decide a TRUE total-collection failure.
    sources_attempted: int = 0
    source_errors: int = 0
    active_non_rss_sources: int = 0
    top_up_attempted: int = 0
    top_up_saved: int = 0
    top_up_failed: int = 0
    top_up_still_short: int = 0


def _record_health(registry_path: Path, *, source: str, items: int, status: str) -> None:
    """Best-effort per-source collect event (a logging failure never aborts collection).

    `record_event` is itself best-effort (never raises), but the root resolution is
    wrapped too so a surprising failure can't break the run. The health log lives
    under the project root, derived from the registry's `pipeline/` parent.
    """
    try:
        root = registry_path.resolve().parent.parent
        record_event(root, "collect", status=status, source=source, items=items)
    except Exception:  # noqa: BLE001 — health logging is strictly best-effort  # nosec B110
        pass


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
    record_health_fn: Callable[..., None] | None = None,
    record_decision_fn: Callable[..., bool] | None = None,
    append_registry_row_fn: Callable[..., bool] | None = None,
) -> CollectResult:
    """Collect RSS articles for one category, with static top-up for summaries.

    `fetch_fn` MUST be supplied by the caller — this module has no compatibility-
    wrapper import of its own, to avoid a `collect.py` <-> here import cycle.
    `collect.py.collect_category` is the public, zero-arg-default-friendly facade
    that resolves its own module-level `fetch` as the default before delegating
    here; call this function directly only when you already have a fetcher.

    `record_health_fn`, `record_decision_fn`, and `append_registry_row_fn` are
    resolved the same way (defaulting to this module's own `_record_health`,
    `record_decision`, `append_registry_row_if_absent`) so `collect.py`'s facade
    can pass ITS module-level bindings through unchanged — the names tests
    monkeypatch (`monkeypatch.setattr(collect, "record_decision", ...)` etc.).

    Fetching runs in two phases so only the network I/O is parallel: **Phase A**
    fetches every active feed's body CONCURRENTLY (a `ThreadPoolExecutor` bounded by
    `fetch_workers`, each task calling the same guarded `fetch`), then **Phase B**
    consumes those bodies SEQUENTIALLY in the original source order to parse/dedup/
    write. Because every write stays single-threaded and in source order, the outputs
    and registry-row order are byte-identical to the pre-parallel sequential run —
    only the wall-clock of the fetch phase changes.

    For each active `rss` source: fetch → parse → for each item, dedup on the
    normalized URL (cross-run, via `known_urls`) AND on an in-run set keyed by both
    the normalized URL and the feed guid (collapsing the same item twice within one
    fetch); when the feed body is short, try a static fetch of the article page;
    skip items still under `min_body_chars`; reject obvious junk-wall / low-prose
    bodies; otherwise (unless `dry_run`) write a strict article, append a registry
    row, and mark the URL known. One health event is recorded per source (item
    count after dedup; `status="error", items=0` on a fetch/parse failure). A
    per-source error is caught and logged to stdout — it never aborts the category.
    """
    # `fetch_fn` must always be provided by the caller (`collect.py.collect_category`
    # resolves its own module-level `fetch` as the default) — this module has no
    # compatibility-wrapper import of its own, avoiding a `collect.py` <-> here cycle.
    if fetch_fn is None:
        raise ValueError("collect_category requires fetch_fn (collect.py supplies its default)")
    fetcher = fetch_fn
    record_health = record_health_fn if record_health_fn is not None else _record_health
    record_decision_impl = record_decision_fn if record_decision_fn is not None else record_decision
    append_registry_row = (
        append_registry_row_fn if append_registry_row_fn is not None else append_registry_row_if_absent
    )
    result = CollectResult()
    seen: set[str] = set()  # in-run keys accepted for save / would-save
    top_up_tried: set[str] = set()  # normalized URLs already static-fetched once
    # Defense-in-depth: `category` is a trusted-config value, but a hand-corrupted
    # the sources config could carry `../…`; never let it escape the incoming dir as a path.
    incoming_root = incoming_dir.resolve()
    category_dir = (incoming_dir / category).resolve()
    if not category_dir.is_relative_to(incoming_root):
        raise ValueError(f"category {category!r} escapes the incoming dir")

    # Only active RSS sources are collected; resolve them up front so the cap can be
    # shared FAIRLY across them (not consumed entirely by whichever feed is first).
    active_sources = [s for s in sources if s.type == "rss" and s.active]
    result.active_non_rss_sources = sum(1 for s in sources if s.active and s.type != "rss")

    # --- Phase A (concurrent I/O): fetch every active feed body IN PARALLEL. ------
    # ONLY the network fetch is parallelised, bounded by `fetch_workers`; each task
    # calls the SAME guarded `fetcher` (its SSRF/scheme/socket guards are untouched).
    # A task that raises has its exception CAPTURED in its Future and re-raised in
    # Phase B via `.result()`, so a failed/slow feed is tolerated per-source exactly
    # as the sequential code did — one bad feed never poisons the others. `max(1, …)`
    # keeps the worker count valid even when there are zero active sources.
    workers = max(1, min(fetch_workers, len(active_sources)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="collect-fetch") as pool:
        fetch_futures = [pool.submit(fetcher, source.url) for source in active_sources]

    # --- Phase B (sequential, deterministic): parse/dedup/WRITE in SOURCE ORDER. --
    # Every futures result is ready here (the `with` block joined all fetches), so
    # `.result()` returns each already-fetched body or re-raises its captured error
    # WITHOUT blocking. Iterating `enumerate(active_sources)` in the original order
    # keeps all file/registry writes single-threaded and identically ordered — the
    # outputs are byte-identical to the pre-parallel sequential implementation.
    for source_index, source in enumerate(active_sources):
        result.sources_attempted += 1
        # Fair per-source budget: split the REMAINING category cap across the sources
        # still to come (ceil, so leftover carries forward to later feeds). Without
        # this, a busy first feed eats the whole cap and every later feed saves zero
        # despite being read — systematic starvation. `None` cap means unlimited.
        if max_articles is None:
            per_source_cap: int | None = None
            top_up_attempt_cap: int | None = None
        else:
            remaining = max_articles - result.saved
            sources_left = len(active_sources) - source_index
            per_source_cap = -(-remaining // sources_left) if remaining > 0 else 0
            # Static top-up fetches are network work, not saved articles. Keep them
            # bounded, but give summary-heavy feeds a few chances to find usable
            # article pages before the save cap is spent.
            top_up_attempt_cap = per_source_cap * TOP_UP_ATTEMPT_BUDGET_MULTIPLIER
        top_up_attempts_for_source = 0
        source_domain = _source_domain(source.url)

        def _journal(
            item: FeedItem, decision: str, reasons: tuple[str, ...] = (), *,
            src: Source = source, author: AuthorIdentity | None = None,
        ) -> None:
            """Record one candidate decision — best effort, never load-bearing.

            Two gates, both deliberate: `journal_root=None` (the default) means a
            caller that did not opt in writes nothing, and a dry run never writes
            at all. `setup_check.py` calls `collect_category` directly on every
            health probe, so a leaky gate would fill the log with phantom runs.
            """
            if journal_root is None or dry_run:
                return
            # Defensive around the WHOLE body, not just the write: building the
            # record can raise too (a future caller passing a bad reason code),
            # and no observability bug may ever cost a collected article.
            with suppress(Exception):
                record_decision_impl(
                    journal_root,
                    CandidateDecision(
                        topic=category,
                        source_url=src.url,
                        candidate_url=item.url,
                        decision=decision,
                        reason_codes=reasons,
                        title=item.title,
                        # A resolved identity when the page gave us one — that
                        # profile URL is what makes an author followable later.
                        author_name=author.name if author else item.author,
                        author_url=author.url if author else "",
                        author_id=author.identifier if author else "",
                        role=src.type,
                        run_id=run_id,
                    ),
                )

        try:
            # Consume THIS source's already-fetched body (Phase A); `.result()`
            # re-raises the fetch's captured exception so the except below handles a
            # failed feed identically to the old inline `fetcher(source.url)` call.
            xml_text = fetch_futures[source_index].result()
            items = parse_feed(xml_text)
        except (OSError, ValueError, FeedParseError) as error:
            # A source fetch/parse failure must NOT abort the whole category.
            result.errors += 1
            result.source_errors += 1
            print(f"ERROR: {source.url} — {error}")
            # A dry run must never mutate operational health (it could flip the system
            # to DEGRADED on a probe) — only a real run records source health.
            if not dry_run:
                record_health(registry_path, source=source.url, items=0, status="error")
            _journal(
                FeedItem(url=source.url, title="", author="", date_published="", body="",
                         guid="", categories=[]),
                "fetch_failed",
                ("feed_unreadable",),
            )
            continue

        saved_for_source = 0
        for item in items:
            # Skip items with no link, a non-fetchable scheme (mailto:/javascript:/
            # data:), no host, or an out-of-range port — none are real articles and a
            # bad port must not raise mid-loop and abort the category.
            if not item.url or not _is_valid_article_url(item.url):
                _journal(item, "unsupported", ("bad_url",))
                continue
            # An author-filtered feed (CONVENTIONS §2.4 `publication-filter`) is a
            # whole publication, most of which is somebody else's work. Reject
            # early — before dedup, the per-source budget and any top-up fetch —
            # so another writer's article costs this author nothing. Journalled,
            # so "we read the feed and none of it was theirs" stays
            # distinguishable from a dead feed.
            if (keep := (item_filters or {}).get(source.url)) and not keep(item):
                _journal(item, "off_topic", ("author_mismatch",))
                continue
            # Stop saving from THIS feed once it has used its fair share (the global
            # cap is still respected because the per-source budget derives from it),
            # but keep scanning later sources so each still gets a health event.
            if per_source_cap is not None and saved_for_source >= per_source_cap:
                # Everything after this point in the feed is never examined, so the
                # journal records the boundary itself. Without it a source that hit
                # its cap is indistinguishable from a dead feed in the report.
                _journal(item, "below_topic_cap", ("source_cap_reached",))
                break
            key = normalize(item.url)
            # A guid is only unique WITHIN its own feed (two unrelated feeds routinely
            # reuse generic guids like "1"), so namespace it by the source URL — a
            # bare guid shared across feeds must never collapse two distinct articles.
            guid_key = f"{source.url}\x00{item.guid}" if item.guid else None
            # Cross-run dedup (registry) AND in-run dedup (this fetch / per-feed guid).
            if key in known_urls or key in seen or (guid_key and guid_key in seen):
                # Cross-run vs in-run vs per-feed-guid are operationally different
                # (a registry hit means we already have it; an in-run hit means the
                # feed repeats itself), and `skipped_dup` conflates all three.
                reason = (
                    "registry" if key in known_urls
                    else "in_run_url" if key in seen
                    else "in_run_guid"
                )
                _journal(item, "duplicate_url", (reason,))
                result.skipped_dup += 1
                continue

            body = strip_html(item.body)
            top_up_status = "not-needed"
            # The top-up fetch already downloads the article page for its body.
            # Capturing that same response gives us the page's metadata — real
            # bylines with profile links, several authors, the publisher — for
            # free. Done by wrapping the INJECTED fetcher rather than changing
            # `_top_up_short_body`, whose signature is re-exported and pinned.
            page_html: list[str] = []

            # Both the fetcher and the sink are bound as defaults: the closure is
            # created fresh each iteration, and binding makes that explicit rather
            # than relying on it (ruff B023).
            def _capturing_fetch(
                url: str,
                _inner: Callable[[str], str] = fetcher,
                _sink: list[str] = page_html,
            ) -> str:
                body_text = _inner(url)
                _sink.append(body_text)
                return body_text

            if len(body) < min_body_chars:
                if key in top_up_tried:
                    _journal(item, "too_short", ("top_up_already_tried",))
                    result.skipped_short += 1
                    continue
                if top_up_attempt_cap is not None and top_up_attempts_for_source >= top_up_attempt_cap:
                    # A budget drop, not a content verdict — the page may be fine.
                    _journal(item, "too_short", ("top_up_budget_spent",))
                    result.skipped_short += 1
                    continue
                top_up_tried.add(key)
                top_up_attempts_for_source += 1
                result.top_up_attempted += 1
                item, top_up_status = _top_up_short_body(
                    item, min_body_chars=min_body_chars, fetcher=_capturing_fetch
                )
                if top_up_status == "failed":
                    result.top_up_failed += 1
                elif top_up_status == "still-short":
                    result.top_up_still_short += 1
            body = strip_html(item.body)
            if len(body) < min_body_chars:
                _journal(item, "too_short", (f"top_up_{top_up_status.replace('-', '_')}",))
                result.skipped_short += 1
                continue
            reject_reason = _article_body_reject_reason(body)
            if reject_reason:
                _journal(item, "junk_wall", ("body_rejected",))
                result.skipped_junk += 1
                print(f"JUNK/WALL: {item.url} — {reject_reason}. Article skipped.")
                continue
            if top_up_status == "saved":
                result.top_up_saved += 1

            if dry_run:
                # Keep cross-category dedup honest: a later category sharing this
                # `known_urls` set must still see this url as taken, so the dry-run
                # "would save" count matches what a live run would actually save.
                known_urls.add(key)
                seen.add(key)
                if guid_key:
                    seen.add(guid_key)
                result.saved += 1
                saved_for_source += 1
                continue  # count what we WOULD save, but write nothing

            # Feed-level metadata only: the entry's own `dc:creator`/`<author>`
            # plus the feed this arrived through. Both are already in hand, so
            # enrichment costs no extra request — the collector's cost profile is
            # unchanged. Richer HTML metadata (schema.org multi-author, publisher)
            # needs the article page, which is fetched only on short-body top-up;
            # threading it out of there is a separate change.
            # JSON-LD outranks the feed (only it names several authors and links
            # each to a profile); the feed's `dc:creator` still wins over the
            # page's meta tags, and survives a page that credits nobody.
            page_metadata = from_html(page_html[0], item.url) if page_html else ContentMetadata()
            metadata = merge_feed_author(page_metadata, item.author)
            text = build_article(
                item, source_name=source_domain, category=category,
                tags=_article_tags(category, item.categories, tags_path=tags_path),
                collected=today, tier=source.tier,
                metadata=metadata, source_url=source.url,
            )
            # DEFERRED FOLLOW-UP: an append-only registry (dropping the per-URL rescan
            # on write) is OUT OF SCOPE here — it touches load_known_urls/dedup
            # correctness and is a separate, higher-risk change. Registry writes stay
            # exactly as before: single-threaded, in source order, under the lock.
            # Atomic UNIQUE write THEN an atomic check-then-append: the final name is
            # claimed via os.link so two concurrent writers (collector + `/save`) that
            # slugify to the same stem each get a distinct file (no TOCTOU clobber), a
            # reader never sees a partial file, and the registry insert is gated on the
            # URL still being absent UNDER THE REGISTRY LOCK — so a concurrent collector
            # / `/save` that registered this URL after our `known_urls` snapshot can't
            # lead to a duplicate primary key. Either insert fails (rollback the orphan)
            # or it loses the dedup race (rollback the orphan, count it as a duplicate).
            dest = _atomic_write_unique(category_dir, f"{today}_{slugify(item.title)}", text)
            try:
                inserted = append_registry_row(
                    registry_path, collected=today, category=category,
                    url=key, title=item.title or "Untitled",
                )
            except OSError as error:
                dest.unlink(missing_ok=True)
                result.errors += 1
                print(f"ERROR: registry append failed for {item.url} — {error}; removed orphan")
                continue
            if not inserted:
                # Lost the dedup race: the URL was registered between our snapshot and
                # now. Drop the orphan so a file never exists without owning its row.
                dest.unlink(missing_ok=True)
                _journal(item, "duplicate_url", ("lost_registry_race",))
                known_urls.add(key)
                result.skipped_dup += 1
                continue
            _journal(
                item, "selected",
                ("full_body",) if top_up_status == "not-needed" else ("topped_up",),
                author=metadata.authors[0] if metadata.authors else None,
            )
            known_urls.add(key)
            seen.add(key)
            if guid_key:
                seen.add(guid_key)
            result.saved += 1
            saved_for_source += 1

        if not dry_run:
            record_health(
                registry_path, source=source.url, items=saved_for_source, status="ok"
            )
        # NB: no early break on a full cap — every active source must still be
        # fetched and recorded for feed-liveness, even once the save cap is reached.

    return result
