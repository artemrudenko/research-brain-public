"""
email_html.py — render the canonical digest markdown as a premium HTML email.

The plain-text digest (and Telegram HTML) read fine, but an email client can do
much more: a centred card, a branded header band, a highlighted TL;DR callout,
topic "badges", accent-coloured links, and subdued trust/source sub-lines. This
module turns the SAME `digest_YYYY-MM-DD.md` markdown into that styled document so
email recipients get a polished read while every other channel is unaffected.

Design constraints (email is not a browser):
  - **Inline styles everywhere.** Gmail/Outlook strip or ignore much of a `<head>`
    `<style>` block, so each structural element carries its own `style="…"`. A small
    `<style>` block is still emitted for a responsive tweak and dark-mode hint, but
    nothing depends on it rendering.
  - **Table-based shell.** The outer layout is a centred table (max 640px) — the
    most portable way to centre a card across clients.
  - **Stable class hooks.** Elements also carry `rb-*` classes (`rb-tldr`,
    `rb-badge`, `rb-sub`) so the output is testable and themeable without parsing CSS.
  - **Safety.** All content text is HTML-escaped; only links/bold/italic/code from
    the trusted digest markdown are turned into markup (same discipline as the
    Telegram renderer).

Public API: :func:`render_email_html`.
"""
from __future__ import annotations

import argparse
import html as _html
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Public API: the renderer/CLI plus the shared markdown→HTML primitives (block
# model + parser + text helpers) that the sibling `digest_report_html` reuses.
__all__ = ["render_email_html", "main", "Block", "ListItem", "esc", "attr", "inline", "parse"]

# --------------------------------------------------------------------------- #
# Palette — one place to retheme the email.
# --------------------------------------------------------------------------- #
_INK = "#1a1a2e"          # primary text
_MUTED = "#6b7280"        # secondary text (subtitles, trust lines)
_ACCENT = "#4f46e5"       # links + header band
_ACCENT_SOFT = "#eef2ff"  # tinted callout / badge background
_BORDER = "#e5e7eb"       # hairline rules
_PAGE_BG = "#f5f6f8"      # area around the card
_CARD_BG = "#ffffff"

# --------------------------------------------------------------------------- #
# Inline markdown → HTML (links, bold, code, italics) with escaping.
# --------------------------------------------------------------------------- #
# Link URL: balanced-paren aware so a legitimate `…/Foo_(bar)` URL is captured
# whole instead of truncated at the first `)` (matches the Telegram renderer). The
# label group is escape-aware (`\\.` before the char class) so a title whose brackets
# were backslash-escaped by `_md_link` (e.g. `Foo \[2026\]`) still matches as a link.
_LINK = re.compile(r"\[((?:\\.|[^\]\\])+)\]\(((?:[^()\s]|\([^()]*\))+)\)")
# Undo the backslash escaping `digest.model._md_link` applies to a link label so the
# rendered text reads cleanly (no literal backslashes before ()[] chars).
_MD_LABEL_ESCAPE = re.compile(r"\\([\\\[\]()])")


def _unescape_md_label(label: str) -> str:
    """Reverse `_md_link`'s backslash escaping of `\\ [ ] ( )` in a link label."""
    return _MD_LABEL_ESCAPE.sub(r"\1", label)
# Only these schemes may become a clickable href; others (javascript:/data:/…)
# from untrusted content are rendered as plain text with the href dropped.
_ALLOWED_LINK_SCHEMES = ("http", "https", "mailto")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_ITALIC_US = re.compile(r"(?<![\w*])_([^_]+)_(?![\w*])")
# Single-asterisk italics, matched only after bold has been consumed.
_ITALIC_STAR = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")

_LINK_STYLE = f"color:{_ACCENT};text-decoration:none;font-weight:600"
_CODE_STYLE = (
    # color is pinned, not inherited: the browser report reuses this renderer,
    # and its dark mode sets a LIGHT page ink that would land on this light
    # chip (light-on-light). Dark-on-light also survives dark-mode email
    # clients that keep author backgrounds.
    "background:#f3f4f6;color:#1F2937;border-radius:4px;padding:1px 5px;"
    "font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px"
)


def esc(text: str) -> str:
    """Escape HTML-significant characters in plain content."""
    return _html.escape(text, quote=False)


def attr(text: str) -> str:
    """Escape a value for use inside a double-quoted HTML attribute.

    Unlike `esc`, this also escapes quotes so an attacker-controlled value (a feed
    URL, a concept name in a data-search attribute) cannot close the attribute and
    inject an event handler.
    """
    return _html.escape(text, quote=True)


def _is_safe_href(href: str) -> bool:
    """True when `href` uses an allowed scheme (or is scheme-less/relative).

    An explicit scheme must be in `_ALLOWED_LINK_SCHEMES`; anything else
    (javascript:, data:, …) is unsafe. A scheme-less URL is treated as safe,
    EXCEPT a protocol-relative `//host/...` URL — it resolves to an absolute link
    under the ambient scheme (an open-redirect/SSRF vector), so it is rejected.
    """
    if href.lstrip().startswith("//"):
        return False
    head = href.split(":", 1)[0].strip().lower() if ":" in href else ""
    if not head or not re.fullmatch(r"[a-z][a-z0-9+.\-]*", head):
        return True  # the colon is part of a path/query, not a scheme
    return head in _ALLOWED_LINK_SCHEMES


def inline(text: str, *, inline_styles: bool = True) -> str:
    """Render inline markdown to safe HTML.

    Links/bold/code are extracted to placeholders BEFORE escaping so their URLs
    and labels can't be mangled and content angle-brackets are always escaped;
    italics then run on the escaped remainder; finally the placeholders restore.

    ``inline_styles`` keeps the per-element style attributes email clients need
    (they ignore ``<style>`` blocks). Pass ``False`` for stylesheet-owned
    contexts like the HTML report, where inline styles would fight the page's
    theme tokens (hard-coded indigo/grey can't follow dark mode).
    """
    spans: list[str] = []

    def _stash(rendered: str) -> str:
        spans.append(rendered)
        return f"\x00{len(spans) - 1}\x00"

    def _link(match: re.Match[str]) -> str:
        label = esc(_unescape_md_label(match.group(1)))
        if not _is_safe_href(match.group(2)):
            # Disallowed scheme: drop the href, keep the label as plain text.
            return _stash(label)
        href = _html.escape(match.group(2), quote=True)
        if not inline_styles:
            return _stash(f'<a href="{href}">{label}</a>')
        return _stash(f'<a href="{href}" style="{_LINK_STYLE}">{label}</a>')

    def _bold(match: re.Match[str]) -> str:
        return _stash(f"<strong>{esc(match.group(1))}</strong>")

    def _code(match: re.Match[str]) -> str:
        if not inline_styles:
            return _stash(f"<code>{esc(match.group(1))}</code>")
        return _stash(f'<code style="{_CODE_STYLE}">{esc(match.group(1))}</code>')

    text = _LINK.sub(_link, text)
    text = _BOLD.sub(_bold, text)  # before single-`*` italics
    text = _CODE.sub(_code, text)
    text = esc(text)
    text = _ITALIC_US.sub(r"<em>\1</em>", text)
    text = _ITALIC_STAR.sub(r"<em>\1</em>", text)
    # Restore placeholders iteratively: a stashed span can itself contain a
    # placeholder (e.g. `**[label](url)**` stashes the <a>, then the <strong>
    # wraps that placeholder), so a single pass would leave the inner one raw.
    # Each span only references earlier (lower-index) spans, so this terminates.
    while "\x00" in text:
        substituted = re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)
        if substituted == text:
            break  # no resolvable placeholder left (defensive — stray NUL)
        text = substituted
    return text


# --------------------------------------------------------------------------- #
# Parse the digest markdown into a small block model.
# --------------------------------------------------------------------------- #
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
# A blockquote line (`> body` / `  > body`) — concept definitions and source
# takeaways. Rendered as a styled, fully-visible quote (email has no collapse).
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
# The header subtitle is the digest's single `_volume line_` directly under the
# H1: ONE italic span wrapping the whole line with no inner `_` pairs. A line like
# `_a_ and _b_` (multiple spans) is a normal paragraph, not the subtitle (BUG L6).
_SUBTITLE_LINE = re.compile(r"^_([^_]+)_$")


@dataclass
class ListItem:
    """One bullet: level 0 is a top item, level 1+ a muted sub-line (trust/source)."""

    level: int
    text: str


@dataclass
class Block:
    """A rendered-ready chunk of the digest: kind + its payload."""

    kind: str  # h1 | subtitle | callout | h2 | badge | list | para
    text: str = ""
    items: list[ListItem] = field(default_factory=list)
    children: list[Block] = field(default_factory=list)


def _gather_bullets(lines: list[str], start: int) -> tuple[list[ListItem], int]:
    """Collect a run of consecutive bullet lines starting at `start`."""
    items: list[ListItem] = []
    index = start
    while index < len(lines):
        bullet = _BULLET.match(lines[index])
        if not bullet:
            break
        indent = len(bullet.group(1))
        items.append(ListItem(level=0 if indent == 0 else 1, text=bullet.group(2)))
        index += 1
    return items, index


def parse(markdown: str) -> list[Block]:
    """Turn digest markdown into an ordered list of blocks."""
    blocks: list[Block] = []
    lines = markdown.split("\n")
    index = 0
    # The subtitle only lives in the preamble (before the first section). Once a
    # section starts, a whole-line italic is ordinary emphasis, not the subtitle.
    seen_section = False
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue

        heading = _HEADING.match(stripped)
        if heading:
            level, text = len(heading.group(1)), heading.group(2)
            if level >= 2:
                seen_section = True  # past the preamble — no more subtitle
            if level == 1:
                blocks.append(Block("h1", text))
            elif level == 2 and "TL;DR" in text.upper():
                # Capture the whole TL;DR block (its bullets) until the next
                # top-level section, and render it as a single callout.
                inner_start = index + 1
                scan = inner_start
                while scan < len(lines):
                    nxt = _HEADING.match(lines[scan].strip())
                    if nxt and len(nxt.group(1)) <= 2:
                        break
                    scan += 1
                blocks.append(
                    Block("callout", text, children=parse("\n".join(lines[inner_start:scan])))
                )
                index = scan
                continue
            elif level == 2:
                blocks.append(Block("h2", text))
            else:  # level >= 3 -> topic group header, rendered as a badge
                blocks.append(Block("badge", text))
            index += 1
            continue

        # The `_volume line_` in the preamble becomes the header subtitle — but
        # only a SINGLE italic span covering the whole line, and only before any
        # section (so `_a_ and _b_` mid-document stays a normal paragraph).
        subtitle = _SUBTITLE_LINE.match(stripped)
        if subtitle and not seen_section:
            blocks.append(Block("subtitle", subtitle.group(1)))
            index += 1
            continue

        if _QUOTE.match(line):
            quote_lines: list[str] = []
            while index < len(lines):
                quote = _QUOTE.match(lines[index])
                if not quote:
                    break
                quote_lines.append(quote.group(1))
                index += 1
            blocks.append(Block("quote", "\n".join(quote_lines)))
            continue

        if _BULLET.match(line):
            items, index = _gather_bullets(lines, index)
            blocks.append(Block("list", items=items))
            continue

        blocks.append(Block("para", stripped))
        index += 1
    return blocks


# --------------------------------------------------------------------------- #
# Render blocks → styled HTML fragments.
# --------------------------------------------------------------------------- #


def _render_list(items: list[ListItem]) -> str:
    """Render a bullet run: top items as list rows, sub-items as muted lines."""
    rows: list[str] = []
    for item in items:
        if item.level == 0:
            rows.append(
                f'<tr><td style="padding:5px 0;color:{_ACCENT};'
                'font-size:15px;line-height:1.5;vertical-align:top;width:18px">•</td>'
                f'<td style="padding:5px 0;color:{_INK};font-size:15px;line-height:1.5">'
                f"{inline(item.text)}</td></tr>"
            )
        else:
            rows.append(
                '<tr><td></td>'
                f'<td class="rb-sub" style="padding:1px 0 1px 4px;color:{_MUTED};'
                f'font-size:13px;line-height:1.45">{inline(item.text)}</td></tr>'
            )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'width="100%" style="margin:2px 0 10px">' + "".join(rows) + "</table>"
    )


def _render_block(block: Block) -> str:
    """Render one block to its styled HTML."""
    if block.kind == "subtitle":
        return (
            f'<p style="margin:6px 0 0;color:{_MUTED};font-size:15px">'
            f"<em>{inline(block.text)}</em></p>"
        )
    if block.kind == "callout":
        inner = "".join(_render_block(child) for child in block.children)
        return (
            f'<table role="presentation" class="rb-tldr" cellpadding="0" cellspacing="0" '
            f'border="0" width="100%" style="background:{_ACCENT_SOFT};border-radius:10px;'
            f'border-left:4px solid {_ACCENT};margin:18px 0"><tr><td style="padding:14px 18px">'
            f'<p style="margin:0 0 6px;font-size:13px;font-weight:700;letter-spacing:.04em;'
            f'text-transform:uppercase;color:{_ACCENT}">{inline(block.text)}</p>'
            f"{inner}</td></tr></table>"
        )
    if block.kind == "quote":
        # A concept definition / source takeaway: a left-bordered quote block,
        # fully visible (email has no collapse), normal-weight readable text.
        inner = "<br>".join(inline(part) for part in block.text.split("\n"))
        return (
            f'<table role="presentation" class="rb-quote" cellpadding="0" cellspacing="0" '
            f'border="0" width="100%" style="margin:4px 0 14px"><tr>'
            f'<td style="border-left:3px solid {_BORDER};padding:2px 0 2px 12px;'
            f'color:{_INK};font-size:14px;line-height:1.55">{inner}</td></tr></table>'
        )
    if block.kind == "h2":
        return (
            f'<h2 style="margin:26px 0 4px;padding-bottom:8px;border-bottom:1px solid {_BORDER};'
            f'color:{_INK};font-size:17px;font-weight:700">{inline(block.text)}</h2>'
        )
    if block.kind == "badge":
        return (
            '<p style="margin:16px 0 4px">'
            f'<span class="rb-badge" style="display:inline-block;background:{_ACCENT_SOFT};'
            f'color:{_ACCENT};font-size:13px;font-weight:700;padding:3px 10px;border-radius:999px">'
            f"{inline(block.text)}</span></p>"
        )
    if block.kind == "list":
        return _render_list(block.items)
    # paragraph (includes the "Knowledge base" bold line and the quiet-week note)
    return (
        f'<p style="margin:10px 0;color:{_INK};font-size:15px;line-height:1.55">'
        f"{inline(block.text)}</p>"
    )


# --------------------------------------------------------------------------- #
# Document shell.
# --------------------------------------------------------------------------- #


def _extract_title(blocks: list[Block]) -> str:
    """The digest's own H1 (sans leading emoji) makes a clean subject/title."""
    for block in blocks:
        if block.kind == "h1":
            return re.sub(r"^[^\w]+", "", block.text).strip() or "Weekly digest"
    return "Weekly digest"


def _header_band(blocks: list[Block]) -> str:
    """The accent header band carrying the digest's H1 title."""
    title = next((b.text for b in blocks if b.kind == "h1"), "Weekly digest")
    return (
        f'<tr><td style="background:{_ACCENT};padding:22px 28px;border-radius:14px 14px 0 0">'
        f'<h1 style="margin:0;color:#ffffff;font-size:21px;font-weight:800;line-height:1.3">'
        f"{inline(title)}</h1></td></tr>"
    )


def render_email_html(
    markdown: str, *, title: str | None = None, preheader: str = ""
) -> str:
    """Render canonical digest markdown as a full, styled HTML email document.

    `title` overrides the `<title>` (e.g. the email subject); when omitted the
    digest's own H1 is used. `preheader` is the hidden inbox-preview snippet.
    """
    blocks = parse(markdown)
    doc_title = title or _extract_title(blocks)
    # Everything except the H1 (which becomes the header band) renders in the body.
    body = "".join(_render_block(b) for b in blocks if b.kind != "h1")

    preheader_html = (
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">'
        f"{esc(preheader)}</div>"
        if preheader
        else ""
    )

    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        f"<title>{esc(doc_title)}</title>"
        "<style>"
        "@media (max-width:620px){.rb-card{width:100%!important}"
        ".rb-pad{padding:20px!important}}"
        "</style></head>"
        f'<body style="margin:0;padding:0;background:{_PAGE_BG};'
        '-webkit-font-smoothing:antialiased">'
        f"{preheader_html}"
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
        f'style="background:{_PAGE_BG};font-family:-apple-system,BlinkMacSystemFont,'
        "'Segoe UI',Roboto,Helvetica,Arial,sans-serif\">"
        '<tr><td align="center" style="padding:24px 12px">'
        '<table role="presentation" class="rb-card" cellpadding="0" cellspacing="0" border="0" '
        f'width="640" style="width:640px;max-width:640px;background:{_CARD_BG};'
        'border-radius:14px;overflow:hidden">'
        f"{_header_band(blocks)}"
        f'<tr><td class="rb-pad" style="padding:8px 28px 24px">{body}</td></tr>'
        f'<tr><td style="padding:16px 28px;border-top:1px solid {_BORDER};color:{_MUTED};'
        'font-size:12px;line-height:1.5">Generated by research-brain · '
        "your weekly knowledge digest</td></tr>"
        "</table></td></tr></table></body></html>"
    )


def main(argv: list[str] | None = None) -> int:
    """Render a digest markdown file as premium HTML email.

    Lets the MCP-mode `digest-deliver` skill produce the exact HTML the headless
    SMTP path sends (`render_email_html`), so a `gmail-mcp` email is polished HTML
    rather than plain markdown. Writes to `--out` or prints to stdout."""
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("digest", help="path to the digest markdown file")
    ap.add_argument("--out", help="write the HTML here (default: stdout)")
    ap.add_argument(
        "--title", default=None,
        help="override the <title> / header band (e.g. the email subject)",
    )
    ap.add_argument("--preheader", default="", help="hidden inbox-preview snippet")
    args = ap.parse_args(argv)

    markdown = Path(args.digest).read_text(encoding="utf-8")
    html = render_email_html(markdown, title=args.title, preheader=args.preheader)
    if args.out:
        Path(args.out).write_text(html, encoding="utf-8")
    else:
        print(html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
