"""Read-only URL intake classification."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from scripts import collect
from scripts.content_metadata import (
    MetadataParser,
    metadata_from_signals,
    parse_html,
)
from scripts.intake_flow.models import (
    CLARIFICATION_QUESTION,
    Classification,
    Preview,
)
from scripts.intake_flow.topics import topic_for_recurring
from scripts.intake_flow.urls import is_http_url
from scripts.normalize_url import normalize

FetchFn = Callable[[str], str]


def _recurring_result(
    *,
    input_url: str,
    canonical_url: str,
    source_url: str,
    source_type: str,
    score: int,
    reason: str,
    title: str,
    config_dir: Path,
    preview: Preview | None = None,
) -> Classification:
    topic_mode, proposed_topic = topic_for_recurring(source_url, title, config_dir)
    return Classification(
        input_url=input_url,
        canonical_url=canonical_url,
        kind="recurring_source",
        confidence=score / 100,
        reason=reason,
        proposed_action="monitor_source",
        source_url=source_url,
        source_type=source_type,
        topic_mode=topic_mode,  # type: ignore[arg-type]
        proposed_topic=proposed_topic,
        preview=preview,
    )


def _article_result(
    *, input_url: str, canonical_url: str, score: int, reason: str,
    preview: Preview | None = None,
) -> Classification:
    return Classification(
        input_url=input_url,
        canonical_url=canonical_url,
        kind="one_off_article",
        confidence=score / 100,
        reason=reason,
        proposed_action="save_article",
        preview=preview,
    )


def _ambiguous_result(
    *, input_url: str, canonical_url: str, score: int, reason: str,
    preview: Preview | None = None,
) -> Classification:
    return Classification(
        input_url=input_url,
        canonical_url=canonical_url,
        kind="ambiguous",
        confidence=score / 100,
        reason=reason,
        proposed_action="ask_clarification",
        clarification_question=CLARIFICATION_QUESTION,
        preview=preview,
    )


def _preview_from(parsed: MetadataParser, url: str) -> Preview | None:
    """Describe the document classify_url just parsed — best effort, never fatal.

    Reads the SAME parse the verdict is based on, so enrichment costs no second
    request. Wrapped whole: the preview is additive, and a metadata bug must
    never turn a working classification into an error the user cannot act on.
    """
    try:
        metadata = metadata_from_signals(parsed, url)
    except Exception:  # noqa: BLE001 - enrichment is strictly additive.
        return None
    return Preview(
        title=metadata.title,
        publication=metadata.publication,
        authors=metadata.authors,
        published_at=metadata.published_at,
        feed_url=metadata.feed_url,
        content_type=metadata.content_type,
    )


def classify_url(
    url: str, config_dir: Path, fetch_fn: FetchFn | None = None
) -> Classification:
    """Classify one HTTP(S) URL without mutating source or inbox state."""

    cleaned = url.strip()
    if not is_http_url(cleaned):
        raise ValueError("intake URL must be HTTP(S) and include a host")

    canonical_url = normalize(cleaned)
    fetcher = fetch_fn if fetch_fn is not None else collect.fetch

    try:
        body = fetcher(cleaned)
    except Exception as exc:  # noqa: BLE001 - fetch failure becomes ambiguity.
        return _ambiguous_result(
            input_url=cleaned,
            canonical_url=canonical_url,
            score=0,
            reason=f"Could not fetch enough evidence: {exc}",
        )

    try:
        collect.parse_feed(body)
        return _recurring_result(
            input_url=cleaned,
            canonical_url=canonical_url,
            source_url=cleaned,
            source_type="rss",
            score=100,
            reason="The URL returned a valid RSS or Atom feed.",
            title="",
            config_dir=Path(config_dir),
        )
    except collect.FeedParseError:
        pass

    parsed = parse_html(body, cleaned)
    preview = _preview_from(parsed, cleaned)
    recurring_score = 0
    recurring_type = "rss"
    recurring_url = cleaned
    recurring_reason = ""

    if parsed.feed_url:
        recurring_score = 90
        recurring_type = "rss"
        recurring_url = parsed.feed_url
        recurring_reason = "The page advertises an RSS or Atom feed."
    elif len(parsed.article_links) >= 3:
        recurring_score = 70
        recurring_type = "blog"
        recurring_url = cleaned
        recurring_reason = "The page looks like an index with multiple article links."

    article_score = 0
    article_reason = ""
    if parsed.og_article:
        article_score = 80
        article_reason = "The page exposes article metadata."
    elif parsed.has_article_element and parsed.has_published_time:
        article_score = 70
        article_reason = "The page has article structure and published-time metadata."

    if recurring_score >= 70 and article_score >= 70:
        return _ambiguous_result(
            input_url=cleaned,
            canonical_url=canonical_url,
            score=max(recurring_score, article_score),
            reason="The URL has both recurring-source and article evidence.",
            preview=preview,
        )
    if recurring_score >= 70:
        return _recurring_result(
            input_url=cleaned,
            canonical_url=canonical_url,
            source_url=recurring_url,
            source_type=recurring_type,
            score=recurring_score,
            reason=recurring_reason,
            title=parsed.title,
            config_dir=Path(config_dir),
            preview=preview,
        )
    if article_score >= 70:
        return _article_result(
            input_url=cleaned,
            canonical_url=canonical_url,
            score=article_score,
            reason=article_reason,
            preview=preview,
        )

    return _ambiguous_result(
        input_url=cleaned,
        canonical_url=canonical_url,
        score=0,
        reason="The page did not expose enough feed, index, or article evidence.",
        preview=preview,
    )
