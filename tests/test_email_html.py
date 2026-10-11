"""
test_email_html.py — offline tests for the premium HTML email renderer.

The renderer turns the canonical digest markdown (the same file telegram and the
plain-text email use) into a styled, email-client-safe HTML document. Tests pin
the structural hooks (document shell, TL;DR callout, topic badges, trust sub-lines)
and the safety guarantees (raw HTML escaped), not exact pixel styling.
"""


from scripts.delivery import email_html  # noqa: E402

_SAMPLE = (
    "# 🧠 Weekly digest — 2026-06-19\n"
    "\n"
    "_7 new sources across 2 topics, 5 updated concepts._\n"
    "\n"
    "## ⚡ TL;DR\n"
    "\n"
    "- 📰 Most active: **tech-news** (4 of 7 new sources)\n"
    "- 🔎 Worth a look: [GLM-5.2](https://x.com/glm) ⭐\n"
    "- 💡 5 concepts updated: A, B, C +2 more\n"
    "\n"
    "**🟢 Knowledge base:** 5 concepts · 0 orphans\n"
    "\n"
    "## 📰 New sources (last 7 days)\n"
    "\n"
    "### 🏷 ai-ml (2)\n"
    "- **[GLM-5.2](https://x.com/glm)** ⭐\n"
    "  > a `1M-token` model\n"
    "\n"
    "## 💡 Updated concepts (last 7 days)\n"
    "\n"
    "- **Vector DB**\n"
    "  - 🟡 Single-source — treat with caution · 🔗 [example.com](https://example.com/a)\n"
    "  > a store for vectors\n"
)


def test_renders_full_html_document() -> None:
    html = email_html.render_email_html(_SAMPLE)
    low = html.lower()
    assert "<!doctype html" in low
    assert "<html" in low and "</html>" in low
    assert "<body" in low


def test_public_api_surface_is_exported() -> None:
    # The shared markdown→HTML primitives are a PUBLIC API (consumed by the
    # sibling digest_report_html), so they must be importable and in __all__ —
    # no reaching into `_`-prefixed names across modules.
    for name in ("render_email_html", "main", "Block", "ListItem", "esc", "inline", "parse"):
        assert hasattr(email_html, name)
        assert name in email_html.__all__


def test_title_appears_in_head_and_heading() -> None:
    html = email_html.render_email_html(_SAMPLE)
    # The digest's own H1 supplies the document <title> and the header band.
    assert "<title>" in html.lower()
    assert "Weekly digest — 2026-06-19" in html


def test_explicit_title_override_used_in_title_tag() -> None:
    html = email_html.render_email_html(_SAMPLE, title="Custom Subject")
    assert "<title>Custom Subject</title>" in html


def test_volume_line_renders_as_emphasis_subtitle() -> None:
    html = email_html.render_email_html(_SAMPLE)
    # The `_..._` volume line becomes an <em> subtitle, not literal underscores.
    assert "<em>7 new sources across 2 topics, 5 updated concepts.</em>" in html
    assert "_7 new sources" not in html


def test_tldr_section_becomes_callout() -> None:
    html = email_html.render_email_html(_SAMPLE)
    # The TL;DR block is wrapped in its own visually-distinct callout container.
    assert "rb-tldr" in html
    # Its highlight lines survive inside the callout.
    assert "Most active:" in html


def test_topic_header_renders_as_badge() -> None:
    html = email_html.render_email_html(_SAMPLE)
    assert "rb-badge" in html
    assert "ai-ml (2)" in html


def test_links_render_as_anchors() -> None:
    html = email_html.render_email_html(_SAMPLE)
    assert '<a href="https://x.com/glm"' in html
    assert ">GLM-5.2</a>" in html


def test_bold_and_code_and_inline_render() -> None:
    html = email_html.render_email_html(_SAMPLE)
    assert "<strong>tech-news</strong>" in html
    assert "<code" in html and "1M-token" in html


def test_email_keeps_inline_styles_on_links_and_code() -> None:
    # Email clients ignore <style> blocks, so the email path MUST keep its
    # per-element inline styles. This pins the email contract while the report
    # path opts out of them (see test_digest_report_html token-styled tests).
    html = email_html.render_email_html(_SAMPLE)
    link = email_html.inline("[GLM-5.2](https://x.com/glm)")
    assert 'style="color:#4f46e5' in link
    chip = email_html.inline("a `1M-token` model")
    assert '<code style="' in chip and "background:#f3f4f6" in chip
    assert 'style="color:#4f46e5' in html


def test_nested_trust_lines_render_as_subdued_subitems() -> None:
    html = email_html.render_email_html(_SAMPLE)
    # Indented trust/source lines under a concept get the muted sub-item style.
    assert "rb-sub" in html
    assert "Single-source — treat with caution" in html
    assert '<a href="https://example.com/a"' in html


def test_quote_line_renders_as_blockquote() -> None:
    html = email_html.render_email_html(_SAMPLE)
    # `> body` definition/takeaway lines render as a styled quote (full text,
    # email has no collapse), with a class hook.
    assert "rb-quote" in html
    assert "a store for vectors" in html
    assert "a `1M-token`" not in html  # backticks become <code>, not literal


def test_link_disallowed_scheme_renders_plain_text() -> None:
    # HIGH: a javascript:/data: scheme must not become a clickable href — the
    # label survives as plain escaped text, the unsafe href is dropped.
    html = email_html.render_email_html("# T\n\n- [click me](javascript:alert(1))\n")
    assert "<a " not in html
    assert "javascript:" not in html
    assert "click me" in html


def test_link_with_paren_in_url_survives() -> None:
    # HIGH: a URL with a balanced ')' must not be truncated at the first ')'.
    html = email_html.render_email_html(
        "# T\n\n- [wiki](https://en.wikipedia.org/wiki/Foo_(bar))\n"
    )
    assert 'href="https://en.wikipedia.org/wiki/Foo_(bar)"' in html


def test_link_label_with_parens_unescapes_backslashes() -> None:
    # A title with parens ("Attention (Is All You Need)") is backslash-escaped by
    # _md_link; the renderer must UNESCAPE it so the label reads cleanly, not with
    # literal backslashes.
    from scripts.digest.model import _md_link

    html = email_html.inline(_md_link("Attention (Is All You Need)", "https://x.example/a"))
    assert ">Attention (Is All You Need)</a>" in html
    assert "\\(" not in html and "\\)" not in html


def test_link_label_with_brackets_still_renders_as_link() -> None:
    # A title with square brackets ("Foo [2026] review") is escaped to `\[`/`\]`; the
    # link regex must be escape-aware so it still matches (previously it fell through
    # to raw literal markdown with no hyperlink at all).
    from scripts.digest.model import _md_link

    html = email_html.inline(_md_link("Foo [2026] review", "https://x.example/a"))
    assert '<a href="https://x.example/a"' in html
    assert ">Foo [2026] review</a>" in html


def test_link_allowed_schemes_still_render() -> None:
    html = email_html.render_email_html(
        "# T\n\n- [x](https://x.com) [m](mailto:a@b.com)\n"
    )
    assert 'href="https://x.com"' in html
    assert 'href="mailto:a@b.com"' in html


def test_protocol_relative_url_is_rejected() -> None:
    # A scheme-less `//host/...` URL (protocol-relative) inherits the page scheme and
    # is an open-redirect/SSRF vector — it must not become a clickable absolute href.
    assert email_html._is_safe_href("//evil.com/x") is False
    # Normal relative paths and explicit https links must still pass.
    assert email_html._is_safe_href("/relative/path") is True
    assert email_html._is_safe_href("https://good.example/x") is True
    assert email_html._is_safe_href("#fragment") is True


def test_protocol_relative_link_renders_plain_text() -> None:
    html = email_html.render_email_html("# T\n\n- [click me](//evil.com/x)\n")
    assert "//evil.com" not in html
    assert "<a " not in html
    assert "click me" in html


def test_multi_italic_line_is_not_treated_as_subtitle() -> None:
    # LOW: a paragraph like `_a_ and _b_` is NOT the volume subtitle — only the
    # single volume line directly under the H1 is. It must render as a normal
    # paragraph (two <em> spans), not a single <em>-wrapped subtitle.
    md = "# Weekly digest\n\n_3 new sources._\n\n## Section\n\n_a_ and _b_\n"
    html = email_html.render_email_html(md)
    # The real volume line is still the subtitle.
    assert "<em>3 new sources.</em>" in html
    # `_a_ and _b_` renders as a normal paragraph with two emphasis spans, not as
    # one subtitle that swallows " and " inside a single <em>.
    assert "<em>a</em> and <em>b</em>" in html


def test_raw_html_in_content_is_escaped() -> None:
    html = email_html.render_email_html("# Title\n\n- a <script>alert(1)</script> b\n")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_preheader_text_included_when_given() -> None:
    html = email_html.render_email_html(_SAMPLE, preheader="Your week in research")
    assert "Your week in research" in html


def test_quiet_week_one_liner_still_produces_document() -> None:
    quiet = "# Weekly digest — 2026-06-19\n\nQuiet week — no new sources.\n"
    html = email_html.render_email_html(quiet)
    assert "<!doctype html" in html.lower()
    assert "Quiet week — no new sources." in html


def test_bold_wrapped_link_renders_fully() -> None:
    # Regression: every digest source card is `**[title](url)**` (a link nested
    # inside bold). The placeholder substitution must resolve the inner link, not
    # leave a raw NUL placeholder. Previously this rendered "<strong>\x000\x00…".
    out = email_html.inline("**[Deontic Policies](https://arxiv.org/abs/2606.19464)**")
    assert "\x00" not in out  # no leftover placeholder
    assert "Deontic Policies" in out
    assert 'href="https://arxiv.org/abs/2606.19464"' in out
    assert out.startswith("<strong>") and "<a href" in out


def test_bold_wrapped_link_in_full_digest_has_no_placeholder() -> None:
    # End-to-end through the renderer: a source-card line must not leak NUL bytes.
    md = (
        "# Weekly digest — 2026-06-20\n\n## New sources\n\n"
        "- **[Deontic Policies for Runtime Governance](https://arxiv.org/abs/2606.19464)** ⭐\n"
        "  > A takeaway sentence.\n"
    )
    html = email_html.render_email_html(md)
    assert "\x00" not in html
    assert "Deontic Policies for Runtime Governance" in html
    assert 'href="https://arxiv.org/abs/2606.19464"' in html


# --------------------------------------------------------------------------- #
# CLI — lets the MCP-mode digest-deliver skill render the same premium HTML the
# headless SMTP path uses, so the gmail-mcp email is no longer plain markdown
# (BACKLOG: premium HTML email in the MCP/Gmail agent path).
# --------------------------------------------------------------------------- #


def test_cli_renders_digest_file_to_html_out(tmp_path) -> None:
    md = tmp_path / "digest_2026-06-19.md"
    md.write_text(_SAMPLE, encoding="utf-8")
    out = tmp_path / "digest_2026-06-19.html"
    code = email_html.main([str(md), "--out", str(out)])
    assert code == 0
    html = out.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "Weekly digest — 2026-06-19" in html


def test_cli_title_override_sets_title_tag(tmp_path) -> None:
    md = tmp_path / "d.md"
    md.write_text(_SAMPLE, encoding="utf-8")
    out = tmp_path / "d.html"
    email_html.main([str(md), "--out", str(out), "--title", "Research digest — d"])
    assert "<title>Research digest — d</title>" in out.read_text(encoding="utf-8")


def test_cli_prints_to_stdout_without_out(tmp_path, capsys) -> None:
    md = tmp_path / "d.md"
    md.write_text(_SAMPLE, encoding="utf-8")
    code = email_html.main([str(md)])
    assert code == 0
    assert "<!doctype html>" in capsys.readouterr().out
