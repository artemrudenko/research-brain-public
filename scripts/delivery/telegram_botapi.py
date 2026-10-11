"""
telegram_botapi.py — send a digest via the Telegram Bot API.

Uses the `sendMessage` endpoint with a bot token from the environment. The Bot
API rejects messages longer than 4096 chars, so the body is split into chunks
on paragraph/line boundaries before sending.

Sends as **plain text by default** (no `parse_mode`). Digests are heading-heavy
markdown and frequently contain unbalanced `* _ [ ]` in titles; legacy `Markdown`
(V1) parse mode rejects those with HTTP 400. Plain text is the safe default — a
caller can opt into a specific mode (e.g. `MarkdownV2`) via the `parse_mode`
argument once the body is known to be escaped for it.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# Telegram hard limit on a single sendMessage text payload.
TELEGRAM_MAX_CHARS = 4096

# --- Markdown -> Telegram HTML rendering ----------------------------------- #
# Telegram supports a small HTML subset (<b>, <i>, <a>, <code>); it has no
# headings or lists. We map the canonical digest markdown onto that subset so the
# message renders as formatted text (bold sections, clickable source links)
# instead of raw `**`/`#`/`[]()` characters.
# Link URL: a run of non-paren/non-space chars, allowing balanced `(...)` groups
# inside, so a legitimate URL like `…/Foo_(bar)` is captured whole instead of
# being truncated at the first `)` (BUG H3a).
# The label group is escape-aware (`\\.` before the class) so a title whose brackets
# were backslash-escaped by `digest.model._md_link` (`Foo \[2026\]`) still matches.
_MD_LINK = re.compile(r"\[((?:\\.|[^\]\\])+)\]\(((?:[^()\s]|\([^()]*\))+)\)")
# Undo `_md_link`'s backslash escaping of `\ [ ] ( )` so the label reads cleanly.
_MD_LABEL_ESCAPE = re.compile(r"\\([\\\[\]()])")
# Only these URL schemes are allowed to become a clickable href; anything else
# (javascript:, data:, …) from untrusted article content is rendered as plain
# text with the href dropped (BUG H3b). A scheme-less/relative URL is allowed.
_ALLOWED_LINK_SCHEMES = ("http", "https", "mailto")
_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_MD_CODE = re.compile(r"`([^`]+)`")
_MD_ITALIC = re.compile(r"(?<![\w*])_([^_]+)_(?![\w*])")
# Single-asterisk italics (`*word*`), matched AFTER bold so `**x**` is untouched.
_MD_ITALIC_STAR = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
# A markdown blockquote line (`> body` / `  > body`) — used for concept
# definitions and source takeaways, rendered as a plain Telegram <blockquote>.
_MD_QUOTE = re.compile(r"^\s*>\s?(.*)$")
# A light divider drawn above each top-level (##) section to create visual
# hierarchy — Telegram HTML has no font sizes, so weight + caps + a rule is the
# strongest scannable structure available.
_TG_DIVIDER = "──────────"
_MD_BULLET = re.compile(r"^(\s*)[-*]\s+(.*)$")


def _esc(text: str) -> str:
    """Escape the three HTML-significant characters in text content."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _is_safe_href(href: str) -> bool:
    """True when `href` carries an allowed scheme (or is scheme-less/relative).

    A URL with an explicit scheme must use one of `_ALLOWED_LINK_SCHEMES`;
    anything else (javascript:, data:, …) is unsafe. A URL with no `scheme:`
    prefix (relative / fragment / scheme-less) is treated as safe, EXCEPT a
    protocol-relative `//host/...` URL — it resolves to an absolute link under the
    ambient scheme (an open-redirect/SSRF vector), so it is rejected.
    """
    if href.lstrip().startswith("//"):
        return False
    head = href.split(":", 1)[0].strip().lower() if ":" in href else ""
    # A "scheme" must look like one (letters/digits/+-.) — otherwise the colon is
    # just part of a path/query, so treat it as scheme-less and allow it.
    if not head or not re.fullmatch(r"[a-z][a-z0-9+.\-]*", head):
        return True
    return head in _ALLOWED_LINK_SCHEMES


def _format_inline(escaped: str) -> str:
    """Apply bold/code/italic markup to an already-escaped, link-stashed string."""
    escaped = _MD_BOLD.sub(r"<b>\1</b>", escaped)
    escaped = _MD_CODE.sub(r"<code>\1</code>", escaped)
    escaped = _MD_ITALIC.sub(r"<i>\1</i>", escaped)
    escaped = _MD_ITALIC_STAR.sub(r"<i>\1</i>", escaped)
    return escaped


def _wrap_section_blockquote(
    lines: list[str], marker: str, *, expandable: bool = False
) -> list[str]:
    """Wrap the body of the section whose header contains `marker` in a quote.

    Finds the bold header line containing `marker` (e.g. ``"TL;DR"`` or the
    synthesis ``"🧪"`` emoji — robust to the digest's language), then wraps the
    contiguous content lines that follow it (up to the next blank line or section
    divider) in a single `<blockquote>` — `expandable` adds the collapsible
    variant. The header itself stays outside the quote. A no-op when no matching
    header is present (graceful for quiet weeks / omitted sections).
    """
    open_tag = "<blockquote expandable>" if expandable else "<blockquote>"
    result: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        result.append(line)
        index += 1
        if not (line.startswith("<b>") and marker in line):
            continue
        # Skip blank lines between the header and its content (don't re-emit them,
        # so the quote sits directly under the header).
        while index < len(lines) and not lines[index].strip():
            index += 1
        body: list[str] = []
        while (
            index < len(lines)
            and lines[index].strip()
            and lines[index].strip() != _TG_DIVIDER
        ):
            body.append(lines[index])
            index += 1
        if body:
            result.append(f"{open_tag}{chr(10).join(body)}</blockquote>")
    return result


def markdown_to_telegram_html(md: str) -> str:
    """Render canonical digest markdown as Telegram-flavoured HTML.

    Headings become bold lines (Telegram has no headings), list bullets become
    `• `/`◦ `, and `[text](url)` becomes a real `<a href>` link. Links are stashed
    BEFORE escaping/inline passes so a `_` inside a URL can never be mistaken for
    italics, then restored last with their text and href escaped.
    """
    links: list[tuple[str, str]] = []

    def _stash(match: re.Match) -> str:
        links.append((match.group(1), match.group(2)))
        return f"\x00L{len(links) - 1}\x00"

    staged = _MD_LINK.sub(_stash, md)

    rendered: list[str] = []
    # A run of consecutive `>` lines becomes one plain <blockquote>; any other
    # line ends (flushes) the run.
    quote_buffer: list[str] = []

    def _flush_quote() -> None:
        if quote_buffer:
            # Expandable: a short quote (most takeaways) shows in full, while a
            # long concept definition collapses to a few lines with "show more",
            # so a digest full of concepts stays scannable.
            rendered.append(
                "<blockquote expandable>" + "\n".join(quote_buffer) + "</blockquote>"
            )
            quote_buffer.clear()

    for line in staged.split("\n"):
        quote = _MD_QUOTE.match(line)
        if quote:
            quote_buffer.append(_format_inline(_esc(quote.group(1))))
            continue
        _flush_quote()
        heading = _MD_HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            text_raw = heading.group(2)
            # Banner (#) and section (##) headers are uppercased for weight; the
            # topic subheaders (###) stay title-case. Uppercase the RAW text
            # (no HTML yet) so generated tags are never corrupted.
            if level <= 2:
                text_raw = text_raw.upper()
            if level == 2:
                rendered.append(_TG_DIVIDER)  # rule above each major section
            rendered.append(f"<b>{_format_inline(_esc(text_raw))}</b>")
            continue
        bullet = _MD_BULLET.match(line)
        if bullet:
            mark = "• " if len(bullet.group(1)) == 0 else "   ◦ "
            rendered.append(f"{mark}{_format_inline(_esc(bullet.group(2)))}")
            continue
        rendered.append(_format_inline(_esc(line)))
    _flush_quote()

    # Set two sections apart with native Telegram quotes. The TL;DR is a PLAIN
    # quote — it's the summary, so it must always show in full (never collapsed
    # behind "show more"). The long synthesis prose stays expandable.
    rendered = _wrap_section_blockquote(rendered, "TL;DR", expandable=False)
    rendered = _wrap_section_blockquote(rendered, "🧪", expandable=True)

    text = "\n".join(rendered)

    for index, (label, href) in enumerate(links):
        clean_label = _esc(_MD_LABEL_ESCAPE.sub(r"\1", label))
        if _is_safe_href(href):
            safe_href = _esc(href).replace(chr(34), "%22")
            replacement = f'<a href="{safe_href}">{clean_label}</a>'
        else:
            # Disallowed scheme (javascript:/data:/…): drop the href, keep the
            # label as plain escaped text so nothing clickable/unsafe is emitted.
            replacement = clean_label
        text = text.replace(f"\x00L{index}\x00", replacement)
    return text

# Network timeout (seconds) per sendMessage call.
_TIMEOUT = 30

# Bounded per-chunk retry on a transient failure (one extra attempt). The retry
# lives at the per-chunk level so a transient failure on a later chunk RESUMES
# from that chunk and never resends earlier, already-delivered chunks (BUG C1).
# This is self-contained, so deliver.py must NOT additionally retry the whole
# Telegram message (that would restart from chunk 1 and double-send).
_MAX_CHUNK_ATTEMPTS = 2

# A 429 rate-limit is the dominant mid-sequence chunk failure. Because a failed send
# restarts from chunk 1 on the next run (double-sending earlier chunks), honor the
# Retry-After header before the one retry so the burst clears and the call completes in
# one shot. Capped so a broken/hostile server can't hold the delivery lock unbounded.
# `_SLEEP` is an injection seam for tests; a non-429 failure retries immediately (0s).
_MAX_RETRY_AFTER_SECONDS = 30.0
_SLEEP = time.sleep


def _http_failure_reason(error: urllib.error.HTTPError) -> str:
    """A short, SECRET-FREE diagnosis of a Bot API HTTP failure.

    Includes the status code and Telegram's own `description` (a 401 "invalid
    token", a 403 "bot was blocked", a 400 "can't parse entities" all read
    differently — that difference is exactly what the operator needs). Never
    includes the request URL: it embeds the bot token.
    """
    reason = f"HTTP {getattr(error, 'code', '?')}"
    try:
        payload = json.loads(error.read().decode("utf-8", errors="replace"))
        description = str(payload.get("description", "")).strip()
    except Exception:  # noqa: BLE001 — a diagnosis helper must never raise  # nosec B110
        description = ""
    if description:
        reason += f" — {description[:160]}"
    return reason


def _retry_after_seconds(error: urllib.error.HTTPError) -> float:
    """Seconds to wait before retrying, from a 429's Retry-After header (0 otherwise)."""
    if getattr(error, "code", None) != 429:
        return 0.0
    try:
        raw = (error.headers.get("Retry-After") or "").strip()
    except AttributeError:
        raw = ""
    try:
        seconds = float(int(raw))
    except (TypeError, ValueError):
        seconds = 1.0  # a 429 with no/garbled header still warrants a short backoff
    return max(0.0, min(seconds, _MAX_RETRY_AFTER_SECONDS))


# Matches a line that starts a markdown heading (`# `, `## `, … up to `######`).
# Used to prefer splitting a long message just before a section heading so a
# section's title stays attached to its body in the next chunk. In the rendered
# HTML path headings are `<b>…</b>` (no `#`), so the `──────────` divider line
# drawn above each section is the boundary instead — both are recognised here.
_HEADING_RE = re.compile(r"^#{1,6} ", re.MULTILINE)
_DIVIDER_LINE_RE = re.compile(rf"^{_TG_DIVIDER}$", re.MULTILINE)

# Room reserved at the end of a chunk for the "(i/N)" continuation marker, so
# appending the marker never pushes a chunk back over the limit.
_MARKER_RESERVE = 12

# The two blockquote open variants Telegram accepts, and the close tag. Chunking
# is blockquote-aware: if a split lands inside an open blockquote, the tag is
# closed at the end of the chunk and reopened (same variant) at the start of the
# next, so every emitted chunk has balanced tags (Telegram 400s on unbalanced
# HTML — BUG C2).
_BLOCKQUOTE_OPEN_EXPANDABLE = "<blockquote expandable>"
_BLOCKQUOTE_OPEN_PLAIN = "<blockquote>"
_BLOCKQUOTE_CLOSE = "</blockquote>"
# Worst-case extra characters a rebalance adds to one chunk: a close tag appended
# at its end PLUS the longest open tag reopened at its start. Reserved in the
# per-chunk budget so the rebalanced chunk still fits within `limit`.
_BLOCKQUOTE_RESERVE = len(_BLOCKQUOTE_CLOSE) + len(_BLOCKQUOTE_OPEN_EXPANDABLE)


def _is_header_only(chunk: str) -> bool:
    """True when `chunk` carries no body — only section dividers and headers.

    A split that yields such a chunk would orphan a section header into its own
    near-empty Telegram message (the body block that follows it overflows the
    window, so the only blank-line boundary sits right after the header). The
    caller rejects that split and breaks deeper into the body instead. Recognises
    both the rendered-HTML path (`──────────` divider lines and `<b>…</b>`
    headers) and the raw-markdown path (`#`-prefixed headings).
    """
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines:
        return True
    for line in lines:
        if line == _TG_DIVIDER:
            continue
        if _HEADING_RE.match(line):  # raw-markdown heading (`## …`)
            continue
        if line.startswith("<b>") and line.endswith("</b>"):  # rendered header
            continue
        return False
    return True


def _find_heading_break(window: str) -> int:
    """Index of the last section boundary in `window` (after offset 0), else -1.

    A boundary is a markdown heading (`## `) OR a rendered section divider line,
    so both the raw-markdown and the Telegram-HTML paths split before a section.
    A boundary at offset 0 is ignored — splitting there yields an empty leading
    chunk and makes no progress.
    """
    last = -1
    for pattern in (_HEADING_RE, _DIVIDER_LINE_RE):
        for match in pattern.finditer(window):
            if match.start() > 0:
                last = max(last, match.start())
    return last


def _open_blockquote_at_end(chunk: str) -> str | None:
    """Return the open blockquote tag still unclosed at the end of `chunk`, else None.

    Compares the position of the last open tag (either variant) against the last
    close tag: if an open tag follows the last close (or there is no close), the
    chunk ends inside a blockquote and must be closed/reopened across the split.
    """
    last_close = chunk.rfind(_BLOCKQUOTE_CLOSE)
    last_exp = chunk.rfind(_BLOCKQUOTE_OPEN_EXPANDABLE)
    last_plain = chunk.rfind(_BLOCKQUOTE_OPEN_PLAIN)
    # A plain "<blockquote>" search also matches inside "<blockquote expandable>"
    # (same prefix); prefer the expandable hit so the reopened variant is correct.
    if last_exp >= 0 and last_exp == last_plain:
        last_plain = -1
    last_open = max(last_exp, last_plain)
    if last_open < 0 or last_open < last_close:
        return None
    return _BLOCKQUOTE_OPEN_EXPANDABLE if last_open == last_exp else _BLOCKQUOTE_OPEN_PLAIN


def _retreat_past_open_tag(window: str, split_at: int) -> int:
    """Pull `split_at` back to the `<` if the cut falls inside an HTML tag.

    A hard cut (a long run with no newline) can land in the middle of a
    `<blockquote …>` / `</blockquote>` tag. A truncated tag is something
    :func:`_open_blockquote_at_end` cannot recognise or repair, so the chunk
    ships unbalanced and Telegram 400s. Detect an unterminated `<` in the
    leading chunk and retreat to it so every chunk holds only whole tags.
    """
    head = window[:split_at]
    open_lt = head.rfind("<")
    # Only retreat when the trailing `<` has no closing `>` after it (i.e. the
    # cut is inside a tag) and retreating still makes forward progress.
    if open_lt > 0 and ">" not in head[open_lt:]:
        return open_lt
    return split_at


def _rebalance_blockquotes(chunks: list[str]) -> list[str]:
    """Close/reopen blockquote tags so every chunk has balanced tags.

    When a chunk ends inside an open blockquote, append the close tag here and
    prepend the same open variant to the next chunk. The per-chunk budget in
    `chunk_text` reserves room for both, so this never pushes a chunk over `limit`.
    """
    if len(chunks) <= 1:
        return chunks
    balanced: list[str] = []
    carry_open: str | None = None  # open tag to prepend to the current chunk
    for chunk in chunks:
        if carry_open:
            chunk = carry_open + chunk
            carry_open = None
        open_tag = _open_blockquote_at_end(chunk)
        if open_tag:
            chunk = chunk + _BLOCKQUOTE_CLOSE
            carry_open = open_tag
        balanced.append(chunk)
    return balanced


def chunk_text(text: str, *, limit: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """Split `text` into pieces no longer than `limit` characters.

    Prefers to break just before a top-level `##`/heading boundary, then on
    blank lines, then single newlines, then a hard cut, so Markdown sections
    survive intact where possible. A short message yields one chunk.

    The effective per-piece budget is `limit - _MARKER_RESERVE` so that a later
    "(i/N)" continuation marker can be appended without exceeding `limit`. When the
    body contains blockquotes, `_BLOCKQUOTE_RESERVE` is also subtracted so the
    close/reopen tags added by :func:`_rebalance_blockquotes` still fit `limit`.
    """
    # Only reserve blockquote room when there are blockquotes to rebalance — so a
    # plain-text body keeps the full budget (and existing boundary behaviour).
    # Match EITHER variant: the prefix "<blockquote" covers both the plain
    # "<blockquote>" and the larger "<blockquote expandable>" (the synthesis/quote
    # path uses the expandable one, which is exactly the case that needs the reserve).
    blockquote_reserve = _BLOCKQUOTE_RESERVE if "<blockquote" in text else 0
    budget = max(1, limit - _MARKER_RESERVE - blockquote_reserve)
    if len(text) <= budget:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > budget:
        window = remaining[:budget]
        # Prefer a heading boundary, then a blank line, then a single newline,
        # then a hard cut — so a section's heading travels with its body.
        split_at = _find_heading_break(window)
        if split_at <= 0:
            split_at = window.rfind("\n\n")
        if split_at <= 0:
            split_at = window.rfind("\n")
        if split_at <= 0:
            split_at = budget  # no natural boundary — hard cut
        # Guard against orphaning a section header: if the leading chunk is only
        # a header/divider (its body overflows the window, so the chosen blank
        # line sits right after the header), break deeper into the body instead
        # — the next line boundary, or a hard cut — so the header keeps its body.
        if _is_header_only(remaining[:split_at]):
            deeper = window.rfind("\n", split_at + 1)
            split_at = deeper if deeper > split_at else budget
        # Never cut through an HTML tag — a truncated `<blockquote …>` can't be
        # rebalanced and would ship unbalanced markup (Telegram 400).
        split_at = _retreat_past_open_tag(window, split_at)
        chunks.append(remaining[:split_at].rstrip("\n"))
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    # Keep blockquote tags balanced across the cuts (Telegram rejects unbalanced
    # HTML). Reserved budget above guarantees the added tags still fit `limit`.
    return _rebalance_blockquotes(chunks)


def split_section_messages(text: str, *, limit: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """Split rendered digest HTML into one Telegram message per major section.

    The digest renderer draws a `──────────` divider above every top-level (`##`)
    section. We use those dividers as message boundaries so a section header
    always *starts* a message instead of being orphaned at the foot of the
    previous one (a header alone at the bottom of one bubble, its body in the
    next). Grouping: the banner/volume preamble, the TL;DR block and the first
    content section (New sources) share the opening message; each remaining
    section (Updated concepts, Synthesis, Needs attention) gets its own message.

    A section longer than `limit` is sub-split by :func:`chunk_text`. Text with
    no dividers (plain text / a quiet-week one-liner) falls back to `chunk_text`.
    """
    lines = text.split("\n")
    divider_positions = [i for i, line in enumerate(lines) if line.strip() == _TG_DIVIDER]
    if not divider_positions:
        return chunk_text(text, limit=limit)

    # Preamble = banner + volume (everything before the first divider). Each
    # section spans from its divider to the next (or end of text).
    preamble = "\n".join(lines[: divider_positions[0]]).strip("\n")
    sections: list[str] = []
    for order, start in enumerate(divider_positions):
        end = (
            divider_positions[order + 1]
            if order + 1 < len(divider_positions)
            else len(lines)
        )
        sections.append("\n".join(lines[start:end]).strip("\n"))

    # First message keeps the preamble, the TL;DR block and the first content
    # section together; each later section stands alone. With ≤2 sections the
    # whole digest is one logical group.
    if len(sections) <= 2:
        groups = ["\n\n".join(part for part in [preamble, *sections] if part)]
    else:
        head = "\n\n".join(part for part in [preamble, sections[0], sections[1]] if part)
        groups = [head, *sections[2:]]

    messages: list[str] = []
    for index, group in enumerate(groups):
        # A standalone section message leads with a divider line; the message
        # boundary itself is the separator, so drop that now-redundant rule.
        if index > 0 and group.startswith(_TG_DIVIDER):
            group = group[len(_TG_DIVIDER) :].lstrip("\n")
        if len(group) <= limit - _MARKER_RESERVE:
            messages.append(group)
        else:
            messages.extend(chunk_text(group, limit=limit))
    return messages


def _with_continuation_markers(chunks: list[str]) -> list[str]:
    """Append a "(i/N)" marker to each chunk when there is more than one.

    A single-chunk message is returned unchanged (no marker noise on short
    digests). The marker fits within the budget reserved in `chunk_text`.
    """
    total = len(chunks)
    if total <= 1:
        return chunks
    return [f"{chunk}\n\n({index}/{total})" for index, chunk in enumerate(chunks, 1)]


def _post_send_message(
    token: str, chat_id: str, text: str, *, parse_mode: str | None = None
) -> int:
    """Call the Bot API `sendMessage`; return the HTTP status code.

    Isolated so tests can monkeypatch this without touching urllib internals.
    `parse_mode` is omitted from the payload when None (plain text — the default).
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    fields = {"chat_id": chat_id, "text": text}
    if parse_mode:
        fields["parse_mode"] = parse_mode
    payload = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    # B310: hardcoded https api.telegram.org endpoint, not a user file:// scheme.
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # nosec B310
        return int(response.status)


@dataclass(frozen=True)
class TelegramSendResult:
    """Outcome of a Bot API send: `ok`, plus a secret-free failure `reason`.

    `__bool__` mirrors `ok` so the result drops into truthiness checks; `reason`
    is None on success and a short diagnosis on failure (e.g. "HTTP 401 —
    Unauthorized") so a failed cron send is distinguishable without a rerun.
    """

    ok: bool
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.ok


def send(
    text: str,
    *,
    token: str,
    chat_id: str,
    parse_mode: str | None = None,
    render_markdown: bool = False,
) -> bool:
    """Send `text` to `chat_id` via the Telegram Bot API (bool contract).

    Thin wrapper over `send_detailed` kept for the stable `send(...) -> bool`
    adapter contract (monkeypatch-friendly); see `send_detailed` for the
    failure-reason-carrying form.
    """
    return send_detailed(
        text,
        token=token,
        chat_id=chat_id,
        parse_mode=parse_mode,
        render_markdown=render_markdown,
    ).ok


def send_detailed(
    text: str,
    *,
    token: str,
    chat_id: str,
    parse_mode: str | None = None,
    render_markdown: bool = False,
) -> TelegramSendResult:
    """Send `text` to `chat_id` via the Telegram Bot API, reporting the outcome.

    Long messages are chunked to respect the 4096-char limit. `ok=True` only if
    every chunk was accepted with a 2xx response; on failure `reason` carries a
    short secret-free diagnosis of the failing chunk's final error.

    With `render_markdown=True` the body is converted from the canonical digest
    markdown to Telegram HTML (bold sections, clickable links) and sent with
    `parse_mode="HTML"` — the polished digest path. Otherwise `parse_mode`
    defaults to None (plain text), safe for heading-heavy markup; pass
    `"MarkdownV2"`/`"HTML"` only when the body is already escaped for that mode.
    """
    if not token or not chat_id:
        return TelegramSendResult(False, "missing bot token or chat_id")
    if render_markdown:
        text = markdown_to_telegram_html(text)
        parse_mode = "HTML"
    # Split on section boundaries so each major section starts its own message (no
    # orphaned headers); falls back to plain chunking when there are no dividers.
    # Each chunk is sent independently with its own bounded retry, so a transient
    # failure resumes from the failing chunk — earlier chunks are never resent.
    for chunk in _with_continuation_markers(split_section_messages(text)):
        ok, reason = _send_chunk(token, chat_id, chunk, parse_mode=parse_mode)
        if not ok:
            return TelegramSendResult(False, reason)
    return TelegramSendResult(True, None)


def _send_chunk(
    token: str, chat_id: str, chunk: str, *, parse_mode: str | None
) -> tuple[bool, str | None]:
    """Post one chunk with a bounded retry; (accepted, final failure reason).

    A transient transport error (timeout / 5xx / non-2xx) gets one extra attempt.
    Because the retry is scoped to this single chunk, recovering it never resends
    any chunk that already went out (resume, not restart — BUG C1). The reason
    reflects the LAST attempt's error and never contains the URL (it embeds the
    bot token).
    """
    reason: str | None = None
    for attempt in range(1, _MAX_CHUNK_ATTEMPTS + 1):
        delay = 0.0
        try:
            status = _post_send_message(token, chat_id, chunk, parse_mode=parse_mode)
            if 200 <= status < 300:
                return True, None
            reason = f"HTTP {status}"
        except urllib.error.HTTPError as error:
            delay = _retry_after_seconds(error)  # honor Retry-After on a 429
            reason = _http_failure_reason(error)
        except (urllib.error.URLError, OSError, ValueError) as error:
            # Network-level failure: describe it without any URL.
            detail = getattr(error, "reason", None) or error
            reason = f"{type(error).__name__}: {str(detail)[:160]}"
        if attempt < _MAX_CHUNK_ATTEMPTS and delay > 0.0:
            _SLEEP(delay)
    return False, reason
