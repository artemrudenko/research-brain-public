from __future__ import annotations

import datetime
import html
import re
from collections.abc import Callable
from dataclasses import replace
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from scripts.collection.feed import FeedItem

# Marker written instead of an LLM "## Key takeaways" section: the headless path
# has no model, so enrichment is explicitly deferred to curate/synthesis.
_NO_SUMMARY_NOTE = (
    "<!-- headless RSS capture: no LLM summary; "
    "enrichment happens in curate/synthesis -->"
)

# First-5-words slug: non-alphanumerics fold to hyphens (mirrors collect-base Step 6).
_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")
# Drop script-like blocks before stripping the remaining tags.
_HTML_DROP_BLOCK = re.compile(
    r"<(script|style|noscript)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)
_HTML_MAIN_BLOCKS = (
    re.compile(r"<article\b[^>]*>.*?</article\s*>", re.IGNORECASE | re.DOTALL),
    re.compile(r"<main\b[^>]*>.*?</main\s*>", re.IGNORECASE | re.DOTALL),
    re.compile(
        r"<([a-z][a-z0-9:-]*)\b[^>]*\brole\s*=\s*(['\"]?)main\2[^>]*>.*?</\1\s*>",
        re.IGNORECASE | re.DOTALL,
    ),
)
# Collapse any run of whitespace (incl. newlines) to a single space.
_WHITESPACE = re.compile(r"\s+")
# Tags whose CONTENT is never prose (chrome or code-for-machines).
_SKIP_CONTENT_TAGS = frozenset({"script", "style", "noscript", "template", "nav", "footer", "aside"})
# Tags that end a text block: their boundaries become paragraph breaks.
_BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "main", "header", "li", "ul", "ol", "dl",
    "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "table",
    "tr", "figure", "figcaption", "form", "fieldset", "br", "hr",
})
# A paragraph "reads like prose" when it is this long and ends sentences —
# breadcrumbs, vote/follow chrome and menu crumbs are short and terminator-free.
_MIN_LEDE_CHARS = 80
_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)
_SENTENCE_END_RE = re.compile(r"[.!?。！？](?:\s|$)")
_NAV_TOKEN_RE = re.compile(
    r"\b(?:menu|nav|navigation|home|login|signup|sign-in|cookie|subscribe)\w*\b",
    re.IGNORECASE,
)
_JUNK_WALL_MARKERS = (
    "subscribe to continue",
    "create a free account",
    "sign in to read",
    "members only",
    "accept cookies",
    "manage cookies",
    "cookie preferences",
    "register to read",
    "enable javascript",
)

# --------------------------------------------------------------------------- #


class _TextExtractor(HTMLParser):
    """Tag-aware text extraction.

    A real parser (not a tag regex) so a ">" inside a quoted attribute — e.g. a
    Tailwind class like `[&>a]:hidden` — never leaks into prose, and so block
    elements become paragraph breaks instead of one whitespace-collapsed line
    (the digest teaser quotes the first line of the body). Entities unescape as
    DATA, so pre-escaped code samples survive as text and are never re-parsed."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []
        self._blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_CONTENT_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_CONTENT_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def _flush(self) -> None:
        text = _WHITESPACE.sub(" ", "".join(self._parts)).strip()
        self._parts.clear()
        if text:
            self._blocks.append(text)

    def text(self) -> str:
        self._flush()
        return "\n\n".join(self._blocks)


def strip_html(html_text: str) -> str:
    """Strip tags to readable text: quoted attributes parse correctly, block
    elements become paragraph breaks, entities unescape, and whitespace
    collapses only WITHIN a paragraph."""
    extractor = _TextExtractor()
    extractor.feed(html_text)
    extractor.close()
    return extractor.text().strip()


def _drop_leading_chrome(text: str) -> str:
    """Drop leading breadcrumb/social paragraphs until the first prose-like one.

    Page chrome that lives INSIDE the main/article container (breadcrumbs,
    "Upvote N", author-follow rows) opens many static captures; the digest
    teaser quotes exactly that opening. Keep everything from the first
    paragraph that reads like prose; if none qualifies, return the text
    unchanged (never worse than before)."""
    blocks = text.split("\n\n")
    for i, block in enumerate(blocks):
        if len(block) >= _MIN_LEDE_CHARS and _SENTENCE_END_RE.search(block):
            return "\n\n".join(blocks[i:])
    return text


def _extract_static_article_text(page_html: str) -> str:
    """Best-effort article text from static HTML, without browser/JS execution."""
    cleaned = _HTML_DROP_BLOCK.sub(" ", page_html)
    for pattern in _HTML_MAIN_BLOCKS:
        match = pattern.search(cleaned)
        if match:
            return _drop_leading_chrome(strip_html(match.group(0)))
    return _drop_leading_chrome(strip_html(cleaned))


def _top_up_short_body(
    item: FeedItem,
    *,
    min_body_chars: int,
    fetcher: Callable[[str], str],
) -> tuple[FeedItem, str]:
    """Fetch the static article page when an RSS entry only carries a summary.

    Returns `(item, status)` where status is `not-needed`, `saved`, `failed`, or
    `still-short`.
    """
    current_body = strip_html(item.body)
    if len(current_body) >= min_body_chars:
        return item, "not-needed"
    try:
        page_text = fetcher(item.url)
    except (OSError, ValueError):
        return item, "failed"
    topped_up = _extract_static_article_text(page_text)
    # `topped_up` is already stripped-to-text, but `item.body` is contracted to hold
    # RAW (still-HTML) content that the caller strips exactly once more (collect.py /
    # build_article). Re-escape it so that single downstream strip_html round-trips the
    # text back verbatim — otherwise restored markup in code samples (`<script>`) and
    # `<`/`>` in prose would be re-parsed as tags and silently deleted.
    escaped = html.escape(topped_up)
    if len(topped_up) < min_body_chars:
        if len(topped_up) > len(current_body):
            return replace(item, body=escaped), "still-short"
        return item, "still-short"
    return replace(item, body=escaped), "saved"


def _article_body_reject_reason(body: str) -> str | None:
    """Reject long-but-low-signal bodies before saving them as articles."""
    normalized = _WHITESPACE.sub(" ", body).strip()
    words = _WORD_RE.findall(normalized)
    sentence_count = len(_SENTENCE_END_RE.findall(normalized))
    lowered = normalized.lower()
    marker_hits = sum(1 for marker in _JUNK_WALL_MARKERS if marker in lowered)
    marker_occurrences = sum(lowered.count(marker) for marker in _JUNK_WALL_MARKERS)
    marker_density = marker_occurrences / max(len(words), 1)
    nav_token_count = len(_NAV_TOKEN_RE.findall(lowered))

    if marker_hits >= 2 and (marker_density >= 0.02 or sentence_count < 6):
        return "looks like paywall/consent/login wall"
    if marker_hits >= 1 and len(words) < 90:
        return "looks like paywall/consent/login wall"
    if len(words) < 80 or (sentence_count < 3 and nav_token_count >= 10):
        return "too little prose after extraction"
    return None


def slugify(title: str) -> str:
    """First 5 words of the title, lowercased, non-alphanumerics → hyphens.

    Repeated separators collapse and leading/trailing hyphens are stripped; an
    empty/blank title yields "untitled" (mirrors collect-base Step 6 + inbox.py).
    """
    words = title.strip().split()[:5]
    slug = _SLUG_NON_ALNUM.sub("-", " ".join(words).lower()).strip("-")
    return slug or "untitled"


def to_iso_date(raw: str, *, fallback: str) -> str:
    """Return `YYYY-MM-DD` from an RFC822 or ISO8601 date string.

    Tries the email/RFC822 form first (`parsedate_to_datetime`), then ISO8601
    (`datetime.fromisoformat`, with a trailing `Z` normalised to `+00:00`). An
    empty or unparseable value returns `fallback` (typically today's date), so a
    feed with a missing/garbled date still yields a strict-valid `date_published`.
    """
    candidate = raw.strip()
    if not candidate:
        return fallback
    # RFC822 (e.g. "Mon, 15 Jun 2026 09:00:00 +0000") — the common RSS form.
    try:
        parsed = parsedate_to_datetime(candidate)
        if parsed is not None:
            return parsed.date().isoformat()
    except (TypeError, ValueError):
        pass
    # ISO8601 (e.g. "2026-06-10T12:30:00Z") — the common Atom form.
    try:
        iso = candidate.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(iso).date().isoformat()
    except ValueError:
        return fallback


