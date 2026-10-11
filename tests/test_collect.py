"""Tests for scripts/collect.py — the deterministic, stdlib-only RSS collector.

The agent skill `schedule/collect-base.md` does full collection (ranking, LLM
"Key takeaways", browser scraping). A headless cron / Codex run cannot invoke an
LLM, so this module covers the deterministic RSS path — feed bodies plus static
article-page top-up — so `pipeline/1-incoming/` can be populated without an agent.

These tests are hermetic: `collect.fetch` is always monkeypatched (or a fake
`fetch_fn` is injected), so NOTHING here ever touches the network.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

# Make `scripts` importable as a package root (tests run from project root).
_PROJECT_ROOT = Path(__file__).resolve().parents[1]

from scripts import collect
from scripts.manage_sources import Source
from scripts.registry import iter_registry_rows

_TODAY = "2026-06-22"


# --------------------------------------------------------------------------- #
# Sample feeds
# --------------------------------------------------------------------------- #


RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Example Feed</title>
    <link>https://blog.example.com/</link>
    <item>
      <title>First Post About Agents</title>
      <link>https://blog.example.com/first-post</link>
      <dc:creator>Jane Doe</dc:creator>
      <pubDate>Mon, 15 Jun 2026 09:00:00 +0000</pubDate>
      <guid isPermaLink="false">tag:example.com,2026:first</guid>
      <category>AI</category>
      <category>Agents</category>
      <description>A short summary that is too brief.</description>
      <content:encoded><![CDATA[<p>This is the full article body about
        autonomous agents. It contains a great deal of substantive prose so that
        the stripped body comfortably exceeds the minimum-body threshold used by
        the collector. We add several sentences here to be sure the character
        count is well above five hundred characters. Agents are software systems
        that perceive, decide and act. They plan, they call tools, and they
        iterate toward a goal. This paragraph repeats enough real words to make a
        believable article body for the purposes of the deterministic collector
        test suite, which checks that full-body RSS items are saved verbatim.</p>]]></content:encoded>
    </item>
  </channel>
</rss>
"""


ATOM_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Example</title>
  <entry>
    <title>An Atom Entry On Tooling</title>
    <link rel="alternate" href="https://atom.example.org/entry-1"/>
    <id>urn:uuid:atom-entry-1</id>
    <author><name>Sam Rivers</name></author>
    <updated>2026-06-10T12:30:00Z</updated>
    <category term="tools"/>
    <summary>brief summary</summary>
    <content type="html">&lt;p&gt;Full Atom content body. This entry contains
      enough real prose to clear the minimum-body threshold used by the
      deterministic collector. We deliberately write several sentences so the
      cleaned plain-text body is comfortably more than five hundred characters
      long. Tooling around language models is evolving quickly: editors, agents,
      evaluation harnesses, and deployment pipelines all matter. This paragraph
      pads the body with believable content so the Atom path is exercised exactly
      like the RSS path in the collector's save logic and dedup checks.&lt;/p&gt;</content>
  </entry>
</feed>
"""


# A short-body RSS item (under the min threshold) used to test the skip path.
RSS_SHORT = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Too Short</title>
      <link>https://blog.example.com/short</link>
      <description>tiny</description>
    </item>
  </channel>
</rss>
"""


def _article_html(text: str) -> str:
    return (
        "<!doctype html><html><head><title>Ignored</title>"
        "<script>ignoreMe()</script><style>.x{display:none}</style></head>"
        f"<body><article><h1>Article</h1><p>{text}</p></article></body></html>"
    )


def _rss_two_items() -> str:
    """An RSS feed with two distinct full-body items (for count assertions)."""
    body = "Body prose. " * 60  # well over 500 chars once stripped
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Alpha Article One</title>
      <link>https://feed.example.com/alpha</link>
      <description>{body}</description>
    </item>
    <item>
      <title>Beta Article Two</title>
      <link>https://feed.example.com/beta</link>
      <description>{body}</description>
    </item>
  </channel>
</rss>
"""


def _rss_source(url: str = "https://feed.example.com/rss.xml") -> Source:
    return Source(
        url=url, type="rss", tier="high", priority="medium",
        filter_note="all", active=True,
    )


# --------------------------------------------------------------------------- #
# parse_feed
# --------------------------------------------------------------------------- #


def test_parse_feed_rss_extracts_fields() -> None:
    items = collect.parse_feed(RSS_SAMPLE)
    assert len(items) == 1
    item = items[0]
    assert item.url == "https://blog.example.com/first-post"
    assert item.title == "First Post About Agents"
    assert item.author == "Jane Doe"
    assert item.date_published == "Mon, 15 Jun 2026 09:00:00 +0000"
    assert item.guid == "tag:example.com,2026:first"
    assert item.categories == ["AI", "Agents"]
    # Full body comes from content:encoded, NOT the short <description>.
    assert "autonomous agents" in item.body
    assert "too brief" not in item.body


def test_parse_feed_atom_extracts_fields() -> None:
    items = collect.parse_feed(ATOM_SAMPLE)
    assert len(items) == 1
    item = items[0]
    assert item.url == "https://atom.example.org/entry-1"
    assert item.title == "An Atom Entry On Tooling"
    assert item.author == "Sam Rivers"
    assert item.date_published == "2026-06-10T12:30:00Z"
    assert item.guid == "urn:uuid:atom-entry-1"
    assert item.categories == ["tools"]
    # Full body comes from <content>, not <summary>.
    assert "Full Atom content body" in item.body
    assert "brief summary" not in item.body


def test_parse_feed_atom_xhtml_content_uses_full_body_not_summary() -> None:
    # For type="xhtml" the real body lives in child elements, not the <content>.text;
    # the parser must serialize the children so the full body (not the short summary)
    # is what reaches strip_html downstream.
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        "  <entry>\n"
        "    <title>XHTML Entry</title>\n"
        '    <link rel="alternate" href="https://atom.example.org/xhtml-1"/>\n'
        "    <id>urn:uuid:xhtml-1</id>\n"
        "    <summary>tiny</summary>\n"
        '    <content type="xhtml">\n'
        '      <div xmlns="http://www.w3.org/1999/xhtml">\n'
        "        <p>This is the full xhtml body with real prose about tooling.</p>\n"
        "      </div>\n"
        "    </content>\n"
        "  </entry>\n"
        "</feed>\n"
    )
    item = collect.parse_feed(xml)[0]
    from scripts.collection.text import strip_html

    text = strip_html(item.body)
    assert "full xhtml body with real prose" in text
    assert text.strip() != "tiny"


def test_parse_feed_tolerates_missing_fields() -> None:
    xml = (
        '<rss version="2.0"><channel><item>'
        "<link>https://x/y</link>"
        "</item></channel></rss>"
    )
    items = collect.parse_feed(xml)
    assert len(items) == 1
    assert items[0].url == "https://x/y"
    assert items[0].title == ""
    assert items[0].author == ""


def test_parse_feed_malformed_raises() -> None:
    with pytest.raises(collect.FeedParseError):
        collect.parse_feed("<rss><channel><item>unterminated")


def test_parse_feed_rejects_dtd_entity_bomb() -> None:
    # Feeds are untrusted: a DTD (the billion-laughs / entity-expansion vector) is
    # refused outright rather than expanded.
    billion_laughs = (
        '<?xml version="1.0"?>'
        "<!DOCTYPE lolz ["
        '<!ENTITY lol "lol">'
        '<!ENTITY lol2 "&lol;&lol;&lol;">'
        "]>"
        "<rss><channel><item><title>&lol2;</title></item></channel></rss>"
    )
    with pytest.raises(collect.FeedParseError):
        collect.parse_feed(billion_laughs)


# --------------------------------------------------------------------------- #
# strip_html / slugify / to_iso_date
# --------------------------------------------------------------------------- #


def test_strip_html_removes_tags_and_unescapes() -> None:
    html = "<p>Hello&amp;&nbsp;<b>world</b></p>\n\n<p>line   two</p>"
    out = collect.strip_html(html)
    assert "<" not in out and ">" not in out
    assert "&amp;" not in out
    assert "Hello&" in out
    assert "world" in out
    # Whitespace collapsed to readable text.
    assert "line two" in out


def test_strip_html_survives_gt_inside_quoted_attributes() -> None:
    # Tailwind-style arbitrary variants put ">" INSIDE a quoted class value. The
    # old tag regex stopped at the first ">", leaking `a]:hidden">` into prose —
    # the exact artifact the 2026-07-13 live digest shipped to the reader.
    html_text = '<div class="[&>a]:hidden">Back to Articles</div><p>Real prose here.</p>'
    out = collect.strip_html(html_text)
    assert "a]:hidden" not in out
    assert '">' not in out
    assert "Real prose here." in out


def test_strip_html_preserves_paragraph_boundaries() -> None:
    # Collapsing ALL whitespace produced one-giant-line bodies, so the digest
    # teaser could only ever quote the page dump's first chars. Block elements
    # must become line breaks; the first PARAGRAPH is then the lede.
    out = collect.strip_html("<p>One one.</p><p>Two two.</p>")
    assert out.splitlines()[0] == "One one."
    assert "Two two." in out


def test_collect_category_top_up_skips_leading_chrome_paragraphs(tmp_path: Path) -> None:
    # Breadcrumbs and social chrome INSIDE <article> (hf.co-style) must not
    # open the saved body — the digest teaser reads exactly that first line.
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    prose = "Today we announce a deep-link integration between two platforms. " * 20
    article_html = (
        "<html><body><article>"
        '<div class="[&>a]:hidden">Back to Articles</div>'
        "<h1>From Hugging Face to Amazon in one click</h1>"
        "<div>Published July 7, 2026 Upvote 5 Hazim Qudah Follow amazon</div>"
        f"<p>{prose}</p>"
        "</article></body></html>"
    )

    def fetch(url: str, **_: object) -> str:
        return RSS_SHORT if url.endswith("/rss.xml") else article_html

    result = collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(), fetch_fn=fetch,
    )
    assert result.saved == 1
    text = next((incoming / "ai").glob("*.md")).read_text(encoding="utf-8")
    assert "Today we announce a deep-link integration" in text
    assert "Back to Articles" not in text
    assert "Upvote 5" not in text


def test_slugify_first_five_words_lowercased() -> None:
    assert collect.slugify("The Quick Brown Fox Jumps Over The Dog") == "the-quick-brown-fox-jumps"
    assert collect.slugify("Hello, World!") == "hello-world"
    assert collect.slugify("   ") == "untitled"
    assert collect.slugify("") == "untitled"


def test_to_iso_date_parses_rfc822_iso_and_falls_back() -> None:
    assert collect.to_iso_date("Mon, 15 Jun 2026 09:00:00 +0000", fallback=_TODAY) == "2026-06-15"
    assert collect.to_iso_date("2026-06-10T12:30:00Z", fallback=_TODAY) == "2026-06-10"
    assert collect.to_iso_date("not a date", fallback=_TODAY) == _TODAY
    assert collect.to_iso_date("", fallback=_TODAY) == _TODAY


# --------------------------------------------------------------------------- #
# build_article
# --------------------------------------------------------------------------- #


def test_build_article_starts_with_frontmatter_and_omits_empty_tier() -> None:
    item = collect.parse_feed(RSS_SAMPLE)[0]
    text = collect.build_article(
        item, source_name="blog.example.com", category="ai",
        tags=["ai"], collected=_TODAY, tier="",
    )
    assert text.startswith("---\n")
    assert "tier:" not in text  # omitted when empty
    assert "# First Post About Agents" in text
    assert "*By Jane Doe ·" in text
    assert "*Source: https://blog.example.com/first-post*" in text
    # No fabricated LLM summary; an explanatory comment stands in instead.
    assert "## Key takeaways" not in text
    assert "headless RSS capture" in text


def test_build_article_includes_tier_when_set() -> None:
    item = collect.parse_feed(RSS_SAMPLE)[0]
    text = collect.build_article(
        item, source_name="blog.example.com", category="ai",
        tags=["ai"], collected=_TODAY, tier="high",
    )
    assert "tier: high" in text


def test_build_article_normalizes_url_in_frontmatter() -> None:
    item = collect.parse_feed(RSS_SAMPLE)[0]
    text = collect.build_article(
        item, source_name="blog.example.com", category="ai",
        tags=["ai"], collected=_TODAY, tier="",
    )
    # url: line carries the NORMALIZED url (https, no trailing slash, no tracking).
    from scripts.normalize_url import normalize
    expected = normalize(item.url)
    assert f"url: {expected}" in text


def test_build_article_passes_strict_validator(tmp_path: Path) -> None:
    # The written file must satisfy the REAL strict pipeline-frontmatter validator
    # (the same gate CI enforces).
    item = collect.parse_feed(RSS_SAMPLE)[0]
    text = collect.build_article(
        item, source_name="blog.example.com", category="ai",
        tags=["ai"], collected=_TODAY, tier="high",
    )
    incoming = tmp_path / "1-incoming" / "ai"
    incoming.mkdir(parents=True)
    (incoming / "2026-06-22_first.md").write_text(text, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "scripts/validate-pipeline-frontmatter.py", str(tmp_path / "1-incoming"), "--strict"],
        cwd=str(_PROJECT_ROOT), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# --------------------------------------------------------------------------- #
# load_known_urls
# --------------------------------------------------------------------------- #


def test_load_known_urls_missing_file_is_empty(tmp_path: Path) -> None:
    assert collect.load_known_urls(tmp_path / "registry.md") == set()


def test_load_known_urls_reads_normalized_keys(tmp_path: Path) -> None:
    from scripts.normalize_url import normalize
    from scripts.registry import append_registry_row

    registry = tmp_path / "registry.md"
    append_registry_row(
        registry, collected=_TODAY, category="ai",
        url="https://www.example.com/a/", title="A",
    )
    known = collect.load_known_urls(registry)
    assert normalize("https://example.com/a") in known


def test_load_known_urls_tolerates_malformed_stored_url(tmp_path: Path) -> None:
    # A stored row with an out-of-range port (normalize() would raise) must not
    # abort the scan — the well-formed row is still loaded.
    from scripts.normalize_url import normalize
    from scripts.registry import append_registry_row

    registry = tmp_path / "registry.md"
    append_registry_row(
        registry, collected=_TODAY, category="ai",
        url="https://h:99999/p", title="broken",
    )
    append_registry_row(
        registry, collected=_TODAY, category="ai",
        url="https://example.com/a", title="A",
    )
    known = collect.load_known_urls(registry)  # must not raise
    assert normalize("https://example.com/a") in known


# --------------------------------------------------------------------------- #
# collect_category
# --------------------------------------------------------------------------- #


def test_collect_category_writes_files_and_registry_rows(tmp_path: Path) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    feed = _rss_two_items()
    result = collect.collect_category(
        category="ai",
        sources=[_rss_source()],
        incoming_dir=incoming,
        registry_path=registry,
        today=_TODAY,
        known_urls=set(),
        fetch_fn=lambda url, **_: feed,
    )
    assert result.saved == 2
    saved = sorted((incoming / "ai").glob("*.md"))
    assert len(saved) == 2
    assert all(p.name.startswith("2026-06-22_") for p in saved)
    urls = {r.url for r in iter_registry_rows(registry)}
    from scripts.normalize_url import normalize
    assert normalize("https://feed.example.com/alpha") in urls
    assert normalize("https://feed.example.com/beta") in urls


def test_collect_category_dedups_on_rerun(tmp_path: Path) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    feed = _rss_two_items()
    fetch = lambda url, **_: feed  # noqa: E731

    first = collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(), fetch_fn=fetch,
    )
    assert first.saved == 2

    # Re-run with the registry-derived known set: nothing new collected.
    known = collect.load_known_urls(registry)
    second = collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=known, fetch_fn=fetch,
    )
    assert second.saved == 0
    assert second.skipped_dup == 2
    assert len(list((incoming / "ai").glob("*.md"))) == 2  # no new files


def test_collect_category_skips_short_body(tmp_path: Path) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    result = collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(),
        fetch_fn=lambda url, **_: RSS_SHORT,
    )
    assert result.saved == 0
    assert result.skipped_short == 1
    assert not (incoming / "ai").exists() or list((incoming / "ai").glob("*.md")) == []


def test_collect_category_tops_up_short_rss_body_from_article_page(tmp_path: Path) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    article_body = "Static article prose with enough substance. " * 40
    calls: list[str] = []

    def fetch(url: str, **_: object) -> str:
        calls.append(url)
        if url.endswith("/rss.xml"):
            return RSS_SHORT
        if url.endswith("/short"):
            return _article_html(article_body)
        raise AssertionError(f"unexpected fetch: {url}")

    result = collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(), fetch_fn=fetch,
    )
    assert result.saved == 1
    assert result.top_up_attempted == 1
    assert result.top_up_saved == 1
    assert result.top_up_failed == 0
    assert result.top_up_still_short == 0
    assert result.skipped_short == 0
    assert calls == ["https://feed.example.com/rss.xml", "https://blog.example.com/short"]
    article = next((incoming / "ai").glob("*.md"))
    text = article.read_text(encoding="utf-8")
    assert "Static article prose with enough substance" in text
    assert "ignoreMe" not in text
    assert "display:none" not in text


def test_collect_category_top_up_prefers_article_element(tmp_path: Path) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    article_body = "Focused article body with useful information. " * 40
    nav_text = "Navigation boilerplate should not be saved. " * 40

    def fetch(url: str, **_: object) -> str:
        if url.endswith("/rss.xml"):
            return RSS_SHORT
        return (
            "<html><body>"
            f"<nav>{nav_text}</nav>"
            f"<article>{article_body}</article>"
            f"<footer>{nav_text}</footer>"
            "</body></html>"
        )

    result = collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(), fetch_fn=fetch,
    )
    assert result.saved == 1
    article = next((incoming / "ai").glob("*.md"))
    text = article.read_text(encoding="utf-8")
    assert "Focused article body with useful information" in text
    assert "Navigation boilerplate" not in text


def test_collect_default_date_uses_utc_axis_not_local(monkeypatch: pytest.MonkeyPatch) -> None:
    # collect must stamp `collected:` on the UTC axis the digest window uses. Simulate
    # an eastern-timezone machine near local midnight (UTC clock still on the prior
    # day): the default must be the UTC date, and it must ask for an explicit tz clock
    # (not the local date.today()).
    import datetime as dtmod

    fixed_utc = dtmod.datetime(2026, 7, 5, 22, 0, tzinfo=dtmod.UTC)  # = 2026-07-06 01:00 in UTC+3

    class _FixedDateTime(dtmod.datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            assert tz is not None, "collect default must use an explicit UTC clock, not local"
            return fixed_utc

    monkeypatch.setattr(collect.datetime, "datetime", _FixedDateTime)
    assert collect._default_collect_date() == "2026-07-05"


def test_collect_category_top_up_preserves_escaped_code_and_comparisons(
    tmp_path: Path,
) -> None:
    # A summary-only feed is topped up from the article page. That page (a typical
    # web-dev/AI-tooling article) escapes its code samples and uses `<`/`>` in prose.
    # The topped-up body is already stripped-to-text; a second strip_html pass in
    # build_article would re-interpret the restored `<script>`/`< y >` as markup and
    # delete it. The saved article must keep the code sample and comparison intact.
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    prose = "Real prose about web development tooling and pipelines. " * 30
    article_html = (
        "<html><body><article>"
        f"<p>{prose}</p>"
        "<p>Paste this snippet into your page: "
        "<pre><code>&lt;script src=\"https://cdn.example.com/w.js\"&gt;"
        "&lt;/script&gt;</code></pre></p>"
        "<p>Comparison: when x &lt; y and y &gt; z, the loop terminates early.</p>"
        "</article></body></html>"
    )

    def fetch(url: str, **_: object) -> str:
        return RSS_SHORT if url.endswith("/rss.xml") else article_html

    result = collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(), fetch_fn=fetch,
    )
    assert result.saved == 1
    text = next((incoming / "ai").glob("*.md")).read_text(encoding="utf-8")
    assert '<script src="https://cdn.example.com/w.js"></script>' in text
    assert "when x < y and y > z" in text


def test_collect_category_short_body_stays_short_when_static_top_up_fails(
    tmp_path: Path,
) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"

    def fetch(url: str, **_: object) -> str:
        if url.endswith("/rss.xml"):
            return RSS_SHORT
        raise OSError("article page unavailable")

    result = collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(), fetch_fn=fetch,
    )
    assert result.saved == 0
    assert result.skipped_short == 1
    assert result.top_up_attempted == 1
    assert result.top_up_failed == 1
    assert not (incoming / "ai").exists()


def test_collect_category_top_up_attempts_use_bounded_network_budget(tmp_path: Path) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    body = "tiny"
    items = "".join(
        f"<item><title>Short {i}</title>"
        f"<link>https://feed.example.com/short-{i}</link>"
        f"<description>{body}</description></item>"
        for i in range(7)
    )
    feed = f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'
    article_fetches: list[str] = []

    def fetch(url: str, **_: object) -> str:
        if url.endswith("/rss.xml"):
            return feed
        article_fetches.append(url)
        raise OSError("article page unavailable")

    result = collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(), fetch_fn=fetch,
        max_articles=2,
    )
    assert result.saved == 0
    assert result.skipped_short == 7
    assert result.top_up_attempted == 6
    assert result.top_up_failed == 6
    assert len(article_fetches) == 6


def test_collect_category_dry_run_top_up_uses_bounded_network_budget(tmp_path: Path) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    items = "".join(
        f"<item><title>Short Dry {i}</title>"
        f"<link>https://feed.example.com/dry-{i}</link>"
        "<description>tiny</description></item>"
        for i in range(7)
    )
    feed = f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'
    article_fetches: list[str] = []

    def fetch(url: str, **_: object) -> str:
        if url.endswith("/rss.xml"):
            return feed
        article_fetches.append(url)
        raise OSError("article page unavailable")

    result = collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(), fetch_fn=fetch,
        max_articles=2, dry_run=True,
    )
    assert result.saved == 0
    assert result.skipped_short == 7
    assert result.top_up_attempted == 6
    assert result.top_up_failed == 6
    assert len(article_fetches) == 6
    assert not incoming.exists()
    assert not registry.exists()


def test_collect_category_duplicate_short_url_fetches_top_up_once(tmp_path: Path) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<item><title>Short A</title><link>https://feed.example.com/same</link>"
        "<description>tiny</description></item>"
        "<item><title>Short B</title><link>https://feed.example.com/same</link>"
        "<description>tiny</description></item>"
        "</channel></rss>"
    )
    article_fetches: list[str] = []

    def fetch(url: str, **_: object) -> str:
        if url.endswith("/rss.xml"):
            return feed
        article_fetches.append(url)
        return "<html><body>still tiny</body></html>"

    result = collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(), fetch_fn=fetch,
    )
    assert result.saved == 0
    assert result.skipped_short == 2
    assert result.skipped_dup == 0
    assert result.top_up_attempted == 1
    assert result.top_up_still_short == 1
    assert article_fetches == ["https://feed.example.com/same"]


def test_collect_category_later_full_duplicate_can_save_after_top_up_failure(
    tmp_path: Path,
) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    body = "Full duplicate body with enough usable prose. " * 40
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<item><title>Short First</title><link>https://feed.example.com/same</link>"
        "<description>tiny</description></item>"
        "<item><title>Full Later</title><link>https://feed.example.com/same</link>"
        f"<description>{body}</description></item>"
        "</channel></rss>"
    )

    def fetch(url: str, **_: object) -> str:
        if url.endswith("/rss.xml"):
            return feed
        raise OSError("article page unavailable")

    result = collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(), fetch_fn=fetch,
    )
    assert result.saved == 1
    assert result.skipped_short == 1
    assert result.skipped_dup == 0
    assert result.top_up_attempted == 1
    assert result.top_up_failed == 1
    article = next((incoming / "ai").glob("*.md"))
    text = article.read_text(encoding="utf-8")
    assert "Full duplicate body with enough usable prose" in text


def test_collect_category_rejects_static_top_up_junk_wall(tmp_path: Path) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    junk_wall = (
        "Subscribe to continue. Sign in to read. Accept cookies. Manage cookies. "
        "Create a free account. "
    ) * 30

    def fetch(url: str, **_: object) -> str:
        if url.endswith("/rss.xml"):
            return RSS_SHORT
        return _article_html(junk_wall)

    result = collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(), fetch_fn=fetch,
    )
    assert result.saved == 0
    assert result.skipped_junk == 1
    assert result.skipped_short == 0
    assert result.top_up_attempted == 1
    assert result.top_up_saved == 0
    assert not (incoming / "ai").exists()
    assert not registry.exists()


def test_collect_category_rejects_full_feed_body_with_too_little_prose(
    tmp_path: Path,
) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    token_wall = " ".join(f"menu{i}" for i in range(140))
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<item><title>Navigation Wall</title>"
        "<link>https://feed.example.com/wall</link>"
        f"<description>{token_wall}</description></item>"
        "</channel></rss>"
    )

    result = collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(),
        fetch_fn=lambda _url, **_: feed,
    )
    assert result.saved == 0
    assert result.skipped_junk == 1
    assert result.skipped_short == 0
    assert not (incoming / "ai").exists()
    assert not registry.exists()


def test_collect_category_continues_past_source_error(tmp_path: Path) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    good = _rss_source("https://feed.example.com/good.xml")
    bad = _rss_source("https://feed.example.com/bad.xml")
    feed = _rss_two_items()

    def fetch(url: str, **_: object) -> str:
        if "bad" in url:
            raise OSError("feed unreachable")
        return feed

    result = collect.collect_category(
        category="ai", sources=[bad, good], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(), fetch_fn=fetch,
    )
    assert result.errors == 1
    assert result.saved == 2  # the good source still produced its articles


def test_collect_category_dry_run_writes_nothing(tmp_path: Path) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    result = collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(), dry_run=True,
        fetch_fn=lambda url, **_: _rss_two_items(),
    )
    assert result.saved == 2  # counts what it WOULD save
    assert not incoming.exists()
    assert not registry.exists()


def test_collect_category_normalizes_rss_seed_tags(tmp_path: Path) -> None:
    # RSS <category> values should become seed tags only when they normalize
    # through config/tags.yaml; unknown categories are dropped.
    tags = tmp_path / "tags.yaml"
    tags.write_text(
        "domains:\n"
        "  custom:\n"
        "    - ml\n"
        "synonyms:\n"
        "  machine-learning: custom/ml\n"
        "pending: []\n",
        encoding="utf-8",
    )
    body = "Body prose sentence. " * 50
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<item><title>Tagged Article</title>"
        "<link>https://feed.example.com/tagged</link>"
        "<category>machine-learning</category>"
        "<category>unknown-feed-label</category>"
        f"<description>{body}</description></item>"
        "</channel></rss>"
    )
    result = collect.collect_category(
        category="ai",
        sources=[_rss_source()],
        fetch_fn=lambda _u: feed,
        tags_path=tags,
        **_common(tmp_path),
    )
    assert result.saved == 1
    article = next((tmp_path / "1-incoming" / "ai").glob("*.md"))
    text = article.read_text(encoding="utf-8")
    assert "custom/ml" in text
    assert "unknown-feed-label" not in text


def test_collect_category_normalizes_seed_tag_synonym_keys(tmp_path: Path) -> None:
    # User-maintained aliases may use display spelling; normalize synonym keys
    # the same way feed categories are normalized before lookup.
    tags = tmp_path / "tags.yaml"
    tags.write_text(
        "domains:\n"
        "  custom:\n"
        "    - ml\n"
        "synonyms:\n"
        "  Machine Learning: custom/ml\n"
        "pending: []\n",
        encoding="utf-8",
    )
    body = "Body prose sentence. " * 50
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<item><title>Tagged Article</title>"
        "<link>https://feed.example.com/tagged-key</link>"
        "<category>machine_learning</category>"
        f"<description>{body}</description></item>"
        "</channel></rss>"
    )
    result = collect.collect_category(
        category="ai",
        sources=[_rss_source()],
        fetch_fn=lambda _u: feed,
        tags_path=tags,
        **_common(tmp_path),
    )
    assert result.saved == 1
    article = next((tmp_path / "1-incoming" / "ai").glob("*.md"))
    assert "custom/ml" in article.read_text(encoding="utf-8")


def test_collect_category_accepts_canonical_rss_seed_tag(tmp_path: Path) -> None:
    # A feed may already emit the canonical domain/topic tag; it should not need
    # a synonym entry to survive the controlled-vocabulary filter.
    tags = tmp_path / "tags.yaml"
    tags.write_text(
        "domains:\n"
        "  custom:\n"
        "    - ml\n"
        "synonyms: {}\n"
        "pending: []\n",
        encoding="utf-8",
    )
    body = "Body prose sentence. " * 50
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<item><title>Canonical Tagged Article</title>"
        "<link>https://feed.example.com/canonical-tagged</link>"
        "<category>custom/ml</category>"
        f"<description>{body}</description></item>"
        "</channel></rss>"
    )
    result = collect.collect_category(
        category="ai",
        sources=[_rss_source()],
        fetch_fn=lambda _u: feed,
        tags_path=tags,
        **_common(tmp_path),
    )
    assert result.saved == 1
    article = next((tmp_path / "1-incoming" / "ai").glob("*.md"))
    assert "custom/ml" in article.read_text(encoding="utf-8")


def test_collect_category_without_tags_yaml_keeps_topic_tag_only(tmp_path: Path) -> None:
    # Missing config/tags.yaml must not break collection. Feed categories are
    # dropped because there is no live vocabulary, but the topic tag remains.
    body = "Body prose sentence. " * 50
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<item><title>No Registry Article</title>"
        "<link>https://feed.example.com/no-registry</link>"
        "<category>custom/ml</category>"
        f"<description>{body}</description></item>"
        "</channel></rss>"
    )
    result = collect.collect_category(
        category="ai",
        sources=[_rss_source()],
        fetch_fn=lambda _u: feed,
        tags_path=tmp_path / "missing-tags.yaml",
        **_common(tmp_path),
    )
    assert result.saved == 1
    article = next((tmp_path / "1-incoming" / "ai").glob("*.md"))
    text = article.read_text(encoding="utf-8")
    assert "tags: [ai]" in text
    assert "custom/ml" not in text


def test_collect_category_inactive_source_skipped(tmp_path: Path) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    inactive = Source(
        url="https://feed.example.com/rss.xml", type="rss", tier="high",
        priority="medium", filter_note="all", active=False,
    )
    calls: list[str] = []

    def fetch(url: str, **_: object) -> str:
        calls.append(url)
        return _rss_two_items()

    result = collect.collect_category(
        category="ai", sources=[inactive], incoming_dir=incoming,
        registry_path=registry, today=_TODAY, known_urls=set(), fetch_fn=fetch,
    )
    assert result.saved == 0
    assert calls == []  # an inactive source is never fetched


# --------------------------------------------------------------------------- #
# main (CLI)
# --------------------------------------------------------------------------- #


def _write_sources(tmp_path: Path) -> Path:
    """A minimal sources.yaml (schema 2) with two categories, each one RSS source."""
    sources = tmp_path / "sources.yaml"
    sources.write_text(
        "schema_version: 2\n"
        "categories:\n"
        "  - name: ai\n"
        "    sources:\n"
        "      - url: \"https://feed.example.com/ai.xml\"\n"
        "        type: rss\n"
        "        tier: high\n"
        "        priority: medium\n"
        "        filter: all\n"
        "        active: true\n"
        "  - name: ml\n"
        "    sources:\n"
        "      - url: \"https://feed.example.com/ml.xml\"\n"
        "        type: rss\n"
        "        tier: medium\n"
        "        priority: medium\n"
        "        filter: all\n"
        "        active: true\n",
        encoding="utf-8",
    )
    return sources


def test_main_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sources = _write_sources(tmp_path)
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    monkeypatch.setattr(collect, "fetch", lambda url, **_: _rss_two_items())
    rc = collect.main([
        "--sources", str(sources), "--incoming", str(incoming),
        "--registry", str(registry), "--today", _TODAY, "--dry-run",
    ])
    assert rc == 0
    assert not incoming.exists()
    out = capsys.readouterr().out
    assert "OK:" in out
    assert "dry-run" in out


def test_main_reports_active_non_rss_sources_as_rss_lite_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sources = tmp_path / "sources.yaml"
    sources.write_text(
        "schema_version: 2\n"
        "categories:\n"
        "  - name: ai\n"
        "    sources:\n"
        "      - url: \"https://feed.example.com/ai.xml\"\n"
        "        type: rss\n"
        "        tier: high\n"
        "        priority: medium\n"
        "        filter: all\n"
        "        active: true\n"
        "      - url: \"https://blog.example.com/\"\n"
        "        type: blog\n"
        "        tier: medium\n"
        "        priority: medium\n"
        "        filter: all\n"
        "        active: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(collect, "fetch", lambda url, **_: _rss_two_items())
    rc = collect.main([
        "--sources", str(sources),
        "--incoming", str(tmp_path / "1-incoming"),
        "--registry", str(tmp_path / "registry.md"),
        "--today", _TODAY,
        "--dry-run",
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "RSS-lite" in err
    assert "1 active non-RSS source" in err


def test_main_dry_run_reports_static_top_up_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sources = _write_sources(tmp_path)
    body = "Static article prose with enough substance. " * 40

    def fetch(url: str, **_: object) -> str:
        if url.endswith(".xml"):
            return RSS_SHORT
        return _article_html(body)

    monkeypatch.setattr(collect, "fetch", fetch)
    rc = collect.main([
        "--sources", str(sources),
        "--incoming", str(tmp_path / "1-incoming"),
        "--registry", str(tmp_path / "registry.md"),
        "--today", _TODAY,
        "--category", "ai",
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "static top-up 1 attempted, 1 usable, 0 failed, 0 still short" in out


def test_main_seed_tags_use_tags_next_to_selected_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    sources = config / "sources.yaml"
    sources.write_text(
        "schema_version: 2\n"
        "categories:\n"
        "  - name: ai\n"
        "    sources:\n"
        "      - url: \"https://feed.example.com/ai.xml\"\n"
        "        type: rss\n"
        "        tier: high\n"
        "        priority: medium\n"
        "        filter: all\n"
        "        active: true\n",
        encoding="utf-8",
    )
    (config / "tags.yaml").write_text(
        "domains:\n"
        "  local:\n"
        "    - signal\n"
        "synonyms:\n"
        "  machine-learning: local/signal\n"
        "pending: []\n",
        encoding="utf-8",
    )
    body = "Body prose sentence. " * 50
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<item><title>Tagged Article</title>"
        "<link>https://feed.example.com/tagged</link>"
        "<category>machine-learning</category>"
        f"<description>{body}</description></item>"
        "</channel></rss>"
    )
    monkeypatch.setattr(collect, "fetch", lambda url, **_: feed)
    rc = collect.main([
        "--sources", str(sources),
        "--incoming", str(tmp_path / "1-incoming"),
        "--registry", str(tmp_path / "registry.md"),
        "--today", _TODAY,
    ])
    assert rc == 0
    article = next((tmp_path / "1-incoming" / "ai").glob("*.md"))
    assert "local/signal" in article.read_text(encoding="utf-8")


def test_main_category_filter_limits_to_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sources = _write_sources(tmp_path)
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    monkeypatch.setattr(collect, "fetch", lambda url, **_: _rss_two_items())
    rc = collect.main([
        "--sources", str(sources), "--incoming", str(incoming),
        "--registry", str(registry), "--today", _TODAY, "--category", "ai",
    ])
    assert rc == 0
    assert (incoming / "ai").exists()
    assert not (incoming / "ml").exists()  # only the requested category ran
    out = capsys.readouterr().out
    assert "for ai" in out


def test_main_unknown_category_is_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A typo'd --category must fail loudly, not silently collect nothing and exit 0.
    sources = _write_sources(tmp_path)
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    monkeypatch.setattr(collect, "fetch", lambda url, **_: _rss_two_items())
    rc = collect.main([
        "--sources", str(sources), "--incoming", str(incoming),
        "--registry", str(registry), "--today", _TODAY, "--category", "nope",
    ])
    assert rc != 0
    assert not incoming.exists()  # nothing matched, nothing written


def _author_feed() -> str:
    """A followed author's own RSS feed, one full-body item on a distinct URL."""
    body = "Body prose. " * 60
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<item><title>Jane On Agents</title>"
        "<link>https://example.com/jane/post-1</link>"
        f"<description>{body}</description></item>"
        "</channel></rss>"
    )


def test_main_authors_only_collects_roster_feeds_not_ordinary_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # --authors-only is the weekly-run roster pass: it collects ONLY the followed
    # authors' feeds (rss taken whole here), never the topic's ordinary sources,
    # which the agentic collect-topic pass already handled. A topic with no
    # followed author is not fetched at all.
    sources = _write_sources(tmp_path)  # categories: ai, ml (each one ordinary rss)
    (tmp_path / "authors.yaml").write_text(
        "authors:\n  - name: Jane Doe\n    monitoring: rss\n    topic: ai\n"
        "    feed: https://example.com/jane/feed.xml\n",
        encoding="utf-8",
    )
    incoming = tmp_path / "1-incoming"

    def fetch(url: str, **_: object) -> str:
        return _author_feed() if "jane" in url else _rss_two_items()

    monkeypatch.setattr(collect, "fetch", fetch)
    rc = collect.main([
        "--sources", str(sources), "--incoming", str(incoming),
        "--registry", str(tmp_path / "registry.md"), "--today", _TODAY,
        "--authors-only",
    ])
    assert rc == 0
    saved = list((incoming / "ai").glob("*.md")) if (incoming / "ai").exists() else []
    bodies = [f.read_text(encoding="utf-8") for f in saved]
    assert any("Jane On Agents" in b for b in bodies)  # the author's feed collected
    assert not any("Alpha Article One" in b for b in bodies)  # ordinary ai source skipped
    assert not (incoming / "ml").exists()  # ml has no followed author — not fetched


def test_main_authors_only_warns_about_withheld_scholarly_author(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Review 2026-07-22 (P1): a `scholarly` author has no headless collection path,
    # so a run must WARN by name — never drop them silently, which is
    # indistinguishable from an author who published nothing.
    sources = _write_sources(tmp_path)  # categories: ai, ml
    (tmp_path / "authors.yaml").write_text(
        "authors:\n  - name: Dr Cited\n    monitoring: scholarly\n    topic: ai\n"
        "    id: orcid:0000-0002-1825-0097\n",
        encoding="utf-8",
    )
    incoming = tmp_path / "1-incoming"
    monkeypatch.setattr(collect, "fetch", lambda url, **_: _rss_two_items())
    rc = collect.main([
        "--sources", str(sources), "--incoming", str(incoming),
        "--registry", str(tmp_path / "registry.md"), "--today", _TODAY,
        "--authors-only",
    ])
    assert rc == 0  # collecting nothing for them is not a failure
    err = capsys.readouterr().err
    assert "author monitoring" in err  # the WARN channel
    assert "Dr Cited" in err and "scholarly" in err  # named, with the variant


def test_main_authors_only_empty_roster_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With nobody followed (absent authors.yaml), the roster pass is a clean no-op:
    # it must NOT fall through to collecting the ordinary sources.
    sources = _write_sources(tmp_path)
    incoming = tmp_path / "1-incoming"
    monkeypatch.setattr(collect, "fetch", lambda url, **_: _rss_two_items())
    rc = collect.main([
        "--sources", str(sources), "--incoming", str(incoming),
        "--registry", str(tmp_path / "registry.md"), "--today", _TODAY,
        "--authors-only",
    ])
    assert rc == 0
    assert not incoming.exists()  # no author → nothing collected at all


def test_main_authors_only_empty_roster_warning_names_authors_not_rss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # An empty roster under --authors-only leaves nothing selected, so
    # total_attempted is 0 — but the generic "no active RSS sources" warning
    # misattributes the cause (there ARE active RSS sources; they were
    # deliberately excluded). The warning must name the roster instead.
    sources = _write_sources(tmp_path)
    monkeypatch.setattr(collect, "fetch", lambda url, **_: _rss_two_items())
    rc = collect.main([
        "--sources", str(sources), "--incoming", str(tmp_path / "1-incoming"),
        "--registry", str(tmp_path / "registry.md"), "--today", _TODAY,
        "--authors-only",
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "no active RSS sources" not in err, "misattributes cause in authors-only mode"
    assert "author" in err.lower()


def test_main_missing_sources_file_is_error(tmp_path: Path) -> None:
    rc = collect.main([
        "--sources", str(tmp_path / "does-not-exist.md"),
        "--incoming", str(tmp_path / "1-incoming"),
        "--registry", str(tmp_path / "registry.md"),
        "--today", _TODAY,
    ])
    assert rc != 0  # a missing config is a usage error


def test_main_source_name_is_feed_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The frontmatter `source:` field is the feed URL's domain.
    sources = _write_sources(tmp_path)
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    monkeypatch.setattr(collect, "fetch", lambda url, **_: _rss_two_items())
    collect.main([
        "--sources", str(sources), "--incoming", str(incoming),
        "--registry", str(registry), "--today", _TODAY, "--category", "ai",
    ])
    article = next((incoming / "ai").glob("*.md"))
    assert "source: feed.example.com" in article.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Review-cycle hardening: RSS 1.0, Atom self-link, dry-run dedup, fetch safety,
# category path containment.
# --------------------------------------------------------------------------- #


# RSS 1.0 / RDF uses a namespaced <item> that root.iter("item") silently misses,
# so a real RSS-1.0 feed would parse to zero items and look like an empty feed.
# We reject it LOUDLY instead of silently collecting nothing.
RSS1_RDF_SAMPLE = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/">
  <channel rdf:about="https://rdf.example.com/"><title>RDF Feed</title></channel>
  <item rdf:about="https://rdf.example.com/article-1">
    <title>An RSS 1.0 Article</title>
    <link>https://rdf.example.com/article-1</link>
  </item>
</rdf:RDF>
"""


def test_parse_feed_rss1_rdf_is_rejected_loudly() -> None:
    # An RSS 1.0 / RDF feed must raise (a clear health error), not parse to 0 items.
    with pytest.raises(collect.FeedParseError):
        collect.parse_feed(RSS1_RDF_SAMPLE)


ATOM_SELF_ONLY = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Self-only Entry</title>
    <link rel="self" href="https://atom.example.org/feed.xml"/>
    <content type="html">body</content>
  </entry>
</feed>
"""


def test_atom_self_link_is_not_used_as_article_url() -> None:
    # An entry whose only <link> is rel="self" (the FEED url) must not have that
    # url adopted as the article url — else every such entry collides on one key.
    items = collect.parse_feed(ATOM_SELF_ONLY)
    assert len(items) == 1
    assert items[0].url == ""  # no alternate link → no url (skipped downstream)


def test_dry_run_updates_known_urls_for_cross_category_dedup(tmp_path: Path) -> None:
    # In dry-run, an item counted in one category must be deduped in the next
    # category that shares the same shared known_urls set (honest count).
    feed = _rss_two_items()
    known: set[str] = set()
    src = _rss_source()
    common = dict(
        incoming_dir=tmp_path / "1-incoming", registry_path=tmp_path / "registry.md",
        today=_TODAY, dry_run=True, fetch_fn=lambda _url: feed,
    )
    first = collect.collect_category(category="a", sources=[src], known_urls=known, **common)
    second = collect.collect_category(category="b", sources=[src], known_urls=known, **common)
    assert first.saved == 2
    assert second.saved == 0 and second.skipped_dup == 2  # cross-category dedup honored


def test_fetch_redirect_handler_rejects_non_http_scheme() -> None:
    import email.message
    import urllib.error

    handler = collect._SafeRedirectHandler()
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(
            urllib.request.Request("https://ok.example/feed"),
            None, 302, "Found", email.message.Message(),
            "ftp://evil.example/x",
        )


def test_fetch_rejects_oversized_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    import email.message

    class _FakeResp:
        headers = email.message.Message()

        def read(self, amt: int = -1) -> bytes:
            # One byte past the cap so the size guard trips.
            return b"x" * (collect.MAX_FEED_BYTES + 1)

        def __enter__(self) -> _FakeResp:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    class _FakeOpener:
        def open(self, _req: object, timeout: float = 0.0) -> _FakeResp:
            return _FakeResp()

    # Bypass the SSRF host-resolution guard (a public IP) so this test exercises the
    # size cap specifically, not DNS resolution of the placeholder host.
    monkeypatch.setattr(
        collect.socket, "getaddrinfo", lambda *a, **k: _gai("93.184.216.34")
    )
    monkeypatch.setattr(collect, "_opener", lambda: _FakeOpener())
    with pytest.raises(ValueError, match="exceeds"):
        collect.fetch("https://ok.example/feed")


def test_fetch_tolerates_unknown_charset(monkeypatch: pytest.MonkeyPatch) -> None:
    # A hostile/misconfigured feed can declare any charset in its Content-Type.
    # An unregistered codec name makes bytes.decode raise LookupError — which
    # errors="replace" does NOT catch — so fetch must fall back to utf-8 rather
    # than letting one bad feed abort the whole category run.
    import email.message

    class _FakeResp:
        headers = email.message.Message()

        def __init__(self) -> None:
            self.headers["Content-Type"] = "text/xml; charset=charset-from-evil-feed"

        def read(self, amt: int = -1) -> bytes:
            return "<rss>café</rss>".encode()

        def __enter__(self) -> _FakeResp:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    class _FakeOpener:
        def open(self, _req: object, timeout: float = 0.0) -> _FakeResp:
            return _FakeResp()

    monkeypatch.setattr(
        collect.socket, "getaddrinfo", lambda *a, **k: _gai("93.184.216.34")
    )
    monkeypatch.setattr(collect, "_opener", lambda: _FakeOpener())
    # Must not raise LookupError; the utf-8 fallback decodes the body intact.
    assert collect.fetch("https://ok.example/feed") == "<rss>café</rss>"


def test_collect_category_rejects_traversal_category(tmp_path: Path) -> None:
    # A hand-corrupted sources.md category that escapes the incoming dir is refused.
    with pytest.raises(ValueError, match="escapes"):
        collect.collect_category(
            category="../evil",
            sources=[_rss_source()],
            incoming_dir=tmp_path / "1-incoming",
            registry_path=tmp_path / "registry.md",
            today=_TODAY,
            known_urls=set(),
            fetch_fn=lambda _url: _rss_two_items(),
        )


# --------------------------------------------------------------------------- #
# Review findings: run-lock, atomic write, dry-run health, input validation, cap
# --------------------------------------------------------------------------- #


def _rss_n_items(n: int) -> str:
    body = "Body prose sentence. " * 50  # > 500 chars stripped
    items = "".join(
        f"<item><title>Article {i}</title>"
        f"<link>https://feed.example.com/a{i}</link>"
        f"<description>{body}</description></item>"
        for i in range(n)
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


def _common(tmp_path: Path, **over: object) -> dict[str, object]:
    base: dict[str, object] = dict(
        incoming_dir=tmp_path / "1-incoming",
        registry_path=tmp_path / "registry.md",
        today=_TODAY,
        known_urls=set(),
    )
    base.update(over)
    return base


def test_main_skips_cleanly_when_run_lock_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # collect.py must serialise against weekly-run: if the run lock is held, it
    # writes nothing and exits 0 (a held lock is "someone else owns the pipeline").
    from scripts import run_lock

    sources = _write_sources(tmp_path)
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    lock_path = registry.parent / ".run.lock"
    held = run_lock.acquire(lock_path, note="test-holder")
    assert held.acquired
    monkeypatch.setattr(collect, "fetch", lambda url, **_: _rss_two_items())
    try:
        rc = collect.main([
            "--sources", str(sources), "--incoming", str(incoming),
            "--registry", str(registry), "--today", _TODAY, "--category", "ai",
        ])
    finally:
        run_lock.release(lock_path, token=held.token)
    assert rc == 0
    assert not incoming.exists()  # nothing collected while another run held the lock


def test_main_lock_held_skips_acquire_collects_and_leaves_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # --lock-held is the weekly-run roster pass: the orchestrator already owns the
    # single run lock, so collect.py must NOT re-acquire (which would self-skip and
    # collect nothing) and must NOT release it (the orchestrator releases at its end).
    from scripts import run_lock

    sources = _write_sources(tmp_path)
    (tmp_path / "authors.yaml").write_text(
        "authors:\n  - name: Jane Doe\n    monitoring: rss\n    topic: ai\n"
        "    feed: https://example.com/jane/feed.xml\n",
        encoding="utf-8",
    )
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    lock_path = registry.parent / ".run.lock"
    held = run_lock.acquire(lock_path, note="weekly-run")  # the orchestrator's lock
    assert held.acquired

    def fetch(url: str, **_: object) -> str:
        return _author_feed() if "jane" in url else _rss_two_items()

    monkeypatch.setattr(collect, "fetch", fetch)
    try:
        rc = collect.main([
            "--sources", str(sources), "--incoming", str(incoming),
            "--registry", str(registry), "--today", _TODAY,
            "--authors-only", "--lock-held",
        ])
        assert rc == 0
        bodies = [f.read_text(encoding="utf-8") for f in (incoming / "ai").glob("*.md")]
        assert any("Jane On Agents" in b for b in bodies)  # collected despite held lock
        # The orchestrator's lock survives: a fresh acquire still refuses.
        assert not run_lock.acquire(lock_path, note="probe").acquired
    finally:
        run_lock.release(lock_path, token=held.token)


def test_dry_run_does_not_record_health_on_fetch_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A trial run must never mutate operational health (it could flip DEGRADED).
    calls: list[str] = []
    monkeypatch.setattr(collect, "_record_health", lambda *a, **k: calls.append(k.get("status", "")))

    def _boom(_url: str) -> str:
        raise OSError("unreachable feed")

    result = collect.collect_category(
        category="ai", sources=[_rss_source()], dry_run=True, fetch_fn=_boom,
        **_common(tmp_path),
    )
    assert result.errors == 1
    assert calls == []  # no health event recorded in dry-run


def test_registry_failure_rolls_back_orphan_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the registry append fails after the file write, the orphan article must be
    # removed — no file may exist without its registry row.
    def _boom(*_a: object, **_k: object) -> None:
        raise OSError("registry write failed")

    monkeypatch.setattr(collect, "append_registry_row_if_absent", _boom)
    result = collect.collect_category(
        category="ai", sources=[_rss_source()], fetch_fn=lambda _u: _rss_two_items(),
        **_common(tmp_path),
    )
    assert result.saved == 0
    assert result.errors >= 1
    assert list((tmp_path / "1-incoming" / "ai").glob("*.md")) == []  # no orphan


def test_max_articles_caps_saved(tmp_path: Path) -> None:
    # The per-category save cap (collect.max_articles_per_topic) is honoured.
    result = collect.collect_category(
        category="ai", sources=[_rss_source()], max_articles=2,
        fetch_fn=lambda _u: _rss_n_items(5), **_common(tmp_path),
    )
    assert result.saved == 2
    assert len(list((tmp_path / "1-incoming" / "ai").glob("*.md"))) == 2


def test_non_http_item_url_is_skipped(tmp_path: Path) -> None:
    # A feed item whose link is mailto:/javascript: must not become an article.
    body = "Body prose sentence. " * 50
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        f"<item><title>Mail Me</title><link>mailto:spam@example.com</link>"
        f"<description>{body}</description></item>"
        "</channel></rss>"
    )
    result = collect.collect_category(
        category="ai", sources=[_rss_source()], fetch_fn=lambda _u: feed,
        **_common(tmp_path),
    )
    assert result.saved == 0


def test_main_rejects_invalid_today(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    rc = collect.main([
        "--sources", str(sources), "--incoming", str(tmp_path / "1-incoming"),
        "--registry", str(tmp_path / "registry.md"), "--today", "not-a-date",
    ])
    assert rc != 0


# --------------------------------------------------------------------------- #
# Review findings (round 3): non-feed XML, item-url hardening, per-feed guid,
# cap traversal/health, all-fail exit code, CLI bounds, atomic dedup race.
# --------------------------------------------------------------------------- #


def test_parse_feed_rejects_non_feed_html(tmp_path: Path) -> None:
    # A page that is valid XML but not a feed (e.g. an HTML error page) must raise,
    # not parse to an empty list that later masquerades as a healthy, empty feed.
    with pytest.raises(collect.FeedParseError):
        collect.parse_feed("<html><body><h1>404 Not Found</h1></body></html>")


def test_parse_feed_allows_empty_but_valid_feed() -> None:
    # A genuinely empty RSS feed (live, just no items right now) is NOT an error.
    items = collect.parse_feed('<?xml version="1.0"?><rss version="2.0"><channel/></rss>')
    assert items == []


def test_non_feed_source_records_health_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A source returning a non-feed document records a health *error*, not ok/empty,
    # so a broken endpoint can't stay green forever.
    events: list[tuple[str, int]] = []
    monkeypatch.setattr(
        collect, "_record_health",
        lambda *a, **k: events.append((k.get("status", ""), k.get("items", -1))),
    )
    result = collect.collect_category(
        category="ai", sources=[_rss_source()],
        fetch_fn=lambda _u: "<html><body>not a feed</body></html>",
        **_common(tmp_path),
    )
    assert result.errors == 1
    assert events == [("error", 0)]


def test_item_url_without_host_is_skipped(tmp_path: Path) -> None:
    # `https:///path` has a scheme but no host — it is not a fetchable article.
    body = "Body prose sentence. " * 50
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        f"<item><title>No Host</title><link>https:///orphan-path</link>"
        f"<description>{body}</description></item>"
        "</channel></rss>"
    )
    result = collect.collect_category(
        category="ai", sources=[_rss_source()], fetch_fn=lambda _u: feed,
        **_common(tmp_path),
    )
    assert result.saved == 0


def test_item_url_with_invalid_port_does_not_abort_category(tmp_path: Path) -> None:
    # An out-of-range port (99999) once raised an unhandled ValueError that aborted
    # the whole category; now the bad item is skipped and the good one still saves.
    body = "Body prose sentence. " * 50
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        f"<item><title>Bad Port</title><link>https://host:99999/x</link>"
        f"<description>{body}</description></item>"
        f"<item><title>Good One</title><link>https://host/good</link>"
        f"<description>{body}</description></item>"
        "</channel></rss>"
    )
    result = collect.collect_category(
        category="ai", sources=[_rss_source()], fetch_fn=lambda _u: feed,
        **_common(tmp_path),
    )
    assert result.errors == 0  # no crash
    assert result.saved == 1  # the good item still landed


def test_same_guid_across_two_feeds_does_not_collapse(tmp_path: Path) -> None:
    # Two independent feeds that both use a generic guid "1" but DIFFERENT urls must
    # both be collected — guid dedup is per-feed, never shared across the category.
    body = "Body prose sentence. " * 50

    def _feed(url: str) -> str:
        slug = "alpha" if "a." in url else "beta"
        return (
            '<?xml version="1.0"?><rss version="2.0"><channel>'
            f"<item><guid>1</guid><title>{slug}</title>"
            f"<link>https://{slug}.example.com/post</link>"
            f"<description>{body}</description></item>"
            "</channel></rss>"
        )

    sources = [_rss_source("https://a.example.com/rss"), _rss_source("https://b.example.com/rss")]
    result = collect.collect_category(
        category="ai", sources=sources, fetch_fn=_feed, **_common(tmp_path),
    )
    assert result.saved == 2  # both articles, despite the shared guid


def test_cap_does_not_starve_later_sources_of_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # When the first feed fills the per-category cap, later feeds must still be
    # fetched and get a health event — they can't be silently skipped.
    fetched: list[str] = []
    events: list[str] = []
    monkeypatch.setattr(
        collect, "_record_health", lambda *a, **k: events.append(k.get("source", "")),
    )

    def _feed(url: str) -> str:
        fetched.append(url)
        return _rss_n_items(5)

    sources = [_rss_source("https://first.example.com/rss"),
               _rss_source("https://second.example.com/rss")]
    result = collect.collect_category(
        category="ai", sources=sources, max_articles=3, fetch_fn=_feed,
        **_common(tmp_path),
    )
    assert result.saved == 3  # cap still honoured
    assert "https://second.example.com/rss" in fetched  # later feed WAS read
    assert "https://second.example.com/rss" in events  # ...and got a health event


def _distinct_feed(url: str) -> str:
    # A feed whose item URLs are namespaced by the source, so two feeds don't
    # dedup against each other (lets us prove fair per-feed save distribution).
    host = "alpha" if "first" in url else "beta"
    body = "Body prose sentence. " * 50
    items = "".join(
        f"<item><title>{host} {i}</title>"
        f"<link>https://{host}.example.com/p{i}</link>"
        f"<description>{body}</description></item>"
        for i in range(5)
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


def test_cap_is_shared_fairly_across_feeds(tmp_path: Path) -> None:
    # With a category cap of 3 and two full feeds, the first must NOT eat the whole
    # budget — the later feed contributes too (fair split, leftover carried forward).
    registry = tmp_path / "registry.md"
    sources = [_rss_source("https://first.example.com/rss"),
               _rss_source("https://second.example.com/rss")]
    result = collect.collect_category(
        category="ai", sources=sources, max_articles=3, fetch_fn=_distinct_feed,
        incoming_dir=tmp_path / "1-incoming", registry_path=registry,
        today=_TODAY, known_urls=set(),
    )
    assert result.saved == 3  # global cap honoured
    urls = [r.url for r in iter_registry_rows(registry)]
    assert any("beta." in u for u in urls)  # the SECOND feed saved at least one
    assert any("alpha." in u for u in urls)  # ...and the first did too


def test_cap_carries_leftover_when_early_feed_is_short(tmp_path: Path) -> None:
    # Fair split must carry leftover forward: a short first feed (1 item) under a cap
    # of 4 leaves budget for the second feed to fill the rest — total should reach 4.
    registry = tmp_path / "registry.md"
    body = "Body prose sentence. " * 50

    def _feed(url: str) -> str:
        n = 1 if "first" in url else 5
        host = "alpha" if "first" in url else "beta"
        items = "".join(
            f"<item><title>{host} {i}</title>"
            f"<link>https://{host}.example.com/p{i}</link>"
            f"<description>{body}</description></item>"
            for i in range(n)
        )
        return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'

    sources = [_rss_source("https://first.example.com/rss"),
               _rss_source("https://second.example.com/rss")]
    result = collect.collect_category(
        category="ai", sources=sources, max_articles=4, fetch_fn=_feed,
        incoming_dir=tmp_path / "1-incoming", registry_path=registry,
        today=_TODAY, known_urls=set(),
    )
    assert result.saved == 4  # short first feed (1) + leftover absorbed by second (3)
    urls = [r.url for r in iter_registry_rows(registry)]
    assert sum("beta." in u for u in urls) == 3  # second feed picked up the leftover


def test_main_nonzero_when_all_sources_fail_across_categories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Multi-category aggregation: when EVERY source in EVERY category errors, the
    # run must exit non-zero (the cross-category total-failure path).
    sources = _write_sources(tmp_path)  # two categories, one source each

    def _boom(_url: str, **_k: object) -> str:
        raise OSError("all feeds down")

    monkeypatch.setattr(collect, "fetch", _boom)
    rc = collect.main([
        "--sources", str(sources), "--incoming", str(tmp_path / "1-incoming"),
        "--registry", str(tmp_path / "registry.md"), "--today", _TODAY,
    ])
    assert rc != 0


def test_dup_only_feed_plus_failing_feed_is_not_total_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A feed that responds but yields only DUPLICATES is a success, so a sibling
    # feed erroring is a PARTIAL failure (exit 0), not "every source failed".
    from scripts.registry import append_registry_row

    sources = _write_sources(tmp_path)
    registry = tmp_path / "registry.md"
    # Pre-register the ai feed's two items so the ai feed produces only dups.
    for slug in ("alpha", "beta"):
        append_registry_row(
            registry, collected="2026-06-01", category="ai",
            url=f"https://feed.example.com/{slug}", title=slug,
        )

    def _fetch(url: str, **_k: object) -> str:
        if "ai.xml" in url:
            return _rss_two_items()  # both items already registered -> all dups
        raise OSError("ml feed down")

    monkeypatch.setattr(collect, "fetch", _fetch)
    rc = collect.main([
        "--sources", str(sources), "--incoming", str(tmp_path / "1-incoming"),
        "--registry", str(registry), "--today", _TODAY,
    ])
    assert rc == 0  # one source responded (even if only dups) -> not a total failure


def test_main_returns_nonzero_when_all_sources_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Total collection failure (every feed down) must NOT exit 0 — cron would then
    # happily build a digest on stale data.
    sources = _write_sources(tmp_path)

    def _boom(_url: str, **_k: object) -> str:
        raise OSError("feed unreachable")

    monkeypatch.setattr(collect, "fetch", _boom)
    rc = collect.main([
        "--sources", str(sources), "--incoming", str(tmp_path / "1-incoming"),
        "--registry", str(tmp_path / "registry.md"), "--today", _TODAY, "--category", "ai",
    ])
    assert rc != 0


def test_main_rejects_non_positive_max_articles(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    rc = collect.main([
        "--sources", str(sources), "--incoming", str(tmp_path / "1-incoming"),
        "--registry", str(tmp_path / "registry.md"), "--today", _TODAY,
        "--max-articles", "0",
    ])
    assert rc != 0


def test_main_rejects_negative_min_body_chars(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    rc = collect.main([
        "--sources", str(sources), "--incoming", str(tmp_path / "1-incoming"),
        "--registry", str(tmp_path / "registry.md"), "--today", _TODAY,
        "--min-body-chars", "-1",
    ])
    assert rc != 0


# --------------------------------------------------------------------------- #
# Hardening round 4: SSRF private-IP guard, zero-RSS warning, run-lock durable
# co-location, _unique_path TOCTOU.
# --------------------------------------------------------------------------- #


def _gai(*ips: str) -> object:
    """Build a getaddrinfo-shaped return value for the given IP strings.

    Each entry is a (family, type, proto, canonname, sockaddr) tuple; the guard only
    reads sockaddr[0], so family/type are illustrative. IPv6 addresses get the 4-tuple
    sockaddr form real getaddrinfo returns.
    """
    import socket as _s

    out = []
    for ip in ips:
        if ":" in ip:
            out.append((_s.AF_INET6, _s.SOCK_STREAM, 6, "", (ip, 0, 0, 0)))
        else:
            out.append((_s.AF_INET, _s.SOCK_STREAM, 6, "", (ip, 0)))
    return out


def test_fetch_refuses_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    # FIX 1: a host that resolves to a private/loopback/link-local/reserved address
    # must be refused before any connection — an SSRF guard against a feed (or a
    # redirect) pointed at cloud metadata (169.254.169.254), localhost, or RFC1918.
    monkeypatch.setattr(collect.socket, "getaddrinfo", lambda *a, **k: _gai("127.0.0.1"))
    with pytest.raises(ValueError, match="non-public|private|refus"):
        collect.fetch("https://evil.example/feed")


def test_fetch_refuses_link_local_metadata_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    # The classic cloud-metadata SSRF target (169.254.169.254) is link-local — refused.
    monkeypatch.setattr(
        collect.socket, "getaddrinfo", lambda *a, **k: _gai("169.254.169.254")
    )
    with pytest.raises(ValueError):
        collect.fetch("https://metadata.example/latest")


def test_fetch_refuses_dual_stack_host_with_private_ipv6(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SSRF bypass: gethostbyname (IPv4-only) sees a public A record and passes, but
    # urllib connects via getaddrinfo, which also returns a loopback AAAA (::1) — so
    # the socket would reach an internal service. The guard must enumerate EVERY
    # resolved address (both families) and refuse if any is non-public.
    import email.message

    # Public A record — the old IPv4-only check would happily pass on this alone.
    monkeypatch.setattr(collect.socket, "gethostbyname", lambda _host: "93.184.216.34")
    monkeypatch.setattr(
        collect.socket, "getaddrinfo", lambda *a, **k: _gai("93.184.216.34", "::1")
    )

    class _Resp:
        headers = email.message.Message()

        def read(self, _amt: int = -1) -> bytes:
            return b"<rss/>"

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    class _Opener:
        def open(self, _req: object, timeout: float = 0.0) -> _Resp:
            return _Resp()

    # If the guard fails to refuse, fetch would "succeed" via this fake opener rather
    # than touch the network — so the assertion below is about the guard, not the net.
    monkeypatch.setattr(collect, "_opener", lambda: _Opener())
    with pytest.raises(ValueError, match="non-public"):
        collect.fetch("https://dualstack.example/feed")


def test_fetch_refuses_ipv4_mapped_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    # ::ffff:127.0.0.1 is loopback in IPv4 space, but IPv6 is_loopback misses it; the
    # guard must unwrap the mapped v4 and refuse.
    monkeypatch.setattr(
        collect.socket, "getaddrinfo", lambda *a, **k: _gai("::ffff:127.0.0.1")
    )
    with pytest.raises(ValueError, match="non-public"):
        collect.fetch("https://mapped.example/feed")


def test_fetch_allows_public_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    # A public address passes the guard (we still don't touch the network: the opener
    # is faked to return a tiny valid body).
    import email.message

    monkeypatch.setattr(
        collect.socket, "getaddrinfo", lambda *a, **k: _gai("93.184.216.34")
    )

    class _Resp:
        headers = email.message.Message()

        def read(self, _amt: int = -1) -> bytes:
            return b"<rss/>"

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    class _Opener:
        def open(self, _req: object, timeout: float = 0.0) -> _Resp:
            return _Resp()

    monkeypatch.setattr(collect, "_opener", lambda: _Opener())
    assert collect.fetch("https://public.example/feed") == "<rss/>"


def test_safe_redirect_handler_refuses_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    # FIX 1: the SSRF guard must apply on EVERY redirect hop, not only the initial URL.
    import email.message
    import urllib.error

    monkeypatch.setattr(collect.socket, "getaddrinfo", lambda *a, **k: _gai("10.0.0.5"))
    handler = collect._SafeRedirectHandler()
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(
            urllib.request.Request("https://ok.example/feed"),
            None, 302, "Found", email.message.Message(),
            "https://internal.example/secret",
        )


def test_main_warns_when_no_active_rss_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # FIX 2: a category with zero ACTIVE rss sources must emit a stderr WARNING, not
    # silently exit 0 having printed nothing (a silent "quiet week").
    sources = tmp_path / "sources.yaml"
    sources.write_text(
        "schema_version: 2\n"
        "categories:\n"
        "  - name: ai\n"
        "    sources:\n"
        "      - url: \"https://feed.example.com/ai.xml\"\n"
        "        type: rss\n"
        "        tier: high\n"
        "        priority: medium\n"
        "        filter: all\n"
        "        active: false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(collect, "fetch", lambda url, **_: _rss_two_items())
    rc = collect.main([
        "--sources", str(sources), "--incoming", str(tmp_path / "1-incoming"),
        "--registry", str(tmp_path / "registry.md"), "--today", _TODAY, "--category", "ai",
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "no active RSS sources" in err


def test_main_lock_path_relocates_under_state_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FIX 3: with RESEARCH_BRAIN_STATE_DIR set, collect's run lock must be acquired
    # under the relocated state root (co-located with the runtime state on the same
    # persistent volume), not at the hardcoded in-repo `registry.parent/.run.lock`.
    sources = _write_sources(tmp_path)
    state_dir = tmp_path / "vol"
    monkeypatch.setenv("RESEARCH_BRAIN_STATE_DIR", str(state_dir))
    monkeypatch.setattr(collect, "fetch", lambda url, **_: _rss_two_items())

    seen: list[Path] = []
    real_acquire = collect._lock_acquire

    def _spy_acquire(path: Path, **kw: object) -> object:  # noqa: ANN401
        seen.append(Path(path))
        return real_acquire(path, **kw)

    monkeypatch.setattr(collect, "_lock_acquire", _spy_acquire)
    rc = collect.main([
        "--sources", str(sources), "--incoming", str(tmp_path / "1-incoming"),
        "--registry", str(tmp_path / "registry.md"), "--today", _TODAY, "--category", "ai",
    ])
    assert rc == 0
    assert seen, "acquire was never called"
    # The lock relocated onto the persistent volume (the registry here is a tmp path
    # outside the repo, so state_root relocates it by its leaf name — still co-located
    # with the rest of the runtime state on the volume, per state.py's documented edge).
    assert seen[0] == state_dir / ".run.lock"
    assert seen[0].is_relative_to(state_dir)


def test_main_lock_default_registry_preserves_pipeline_substructure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # FIX 3 (real deployment shape): for the DEFAULT in-repo registry, the relocated
    # lock preserves its `pipeline/` substructure under the state dir — exactly where
    # deliver.py's receipts/.delivery.lock relocate, so they share one volume.
    from scripts import state

    state_dir = state.PROJECT_ROOT / "_unused_vol_probe"
    monkeypatch.setenv("RESEARCH_BRAIN_STATE_DIR", str(state_dir))
    relocated = collect._state_root(collect.DEFAULT_REGISTRY.parent / ".run.lock")
    assert relocated == state_dir / "pipeline" / ".run.lock"


def test_unique_write_no_clobber_under_contention(tmp_path: Path) -> None:
    # FIX 4: two writers picking the SAME stem must each get their own file — the old
    # `_unique_path` (exists()-check then write) was a TOCTOU that let one clobber the
    # other. The O_EXCL/os.link claim must hand out distinct paths.
    directory = tmp_path / "out"
    p1 = collect._atomic_write_unique(directory, "same-stem", "first")
    p2 = collect._atomic_write_unique(directory, "same-stem", "second")
    assert p1 != p2
    assert p1.read_text(encoding="utf-8") == "first"
    assert p2.read_text(encoding="utf-8") == "second"
    assert len(list(directory.glob("same-stem*.md"))) == 2


def test_url_already_registered_is_not_double_saved(tmp_path: Path) -> None:
    # A URL already in the registry but ABSENT from the in-memory known_urls snapshot
    # (the dedup-race window) must be caught atomically at append time: no second
    # file, no duplicate registry row, counted as a duplicate.
    from scripts.registry import append_registry_row

    registry = tmp_path / "registry.md"
    append_registry_row(
        registry, collected="2026-06-01", category="ai",
        url="https://feed.example.com/alpha", title="Alpha",
    )
    result = collect.collect_category(
        category="ai", sources=[_rss_source()],
        incoming_dir=tmp_path / "1-incoming", registry_path=registry,
        today=_TODAY, known_urls=set(),  # empty snapshot — pretend we missed the row
        fetch_fn=lambda _u: _rss_two_items(),
    )
    assert result.saved == 1  # only beta is new; alpha is a dedup-race dup
    assert result.skipped_dup == 1
    # alpha must not have produced an orphan file or a duplicate registry row.
    rows = [r for r in iter_registry_rows(registry) if "alpha" in r.url]
    assert len(rows) == 1
    assert len(list((tmp_path / "1-incoming" / "ai").glob("*.md"))) == 1


# --------------------------------------------------------------------------- #
# Bounded-concurrency feed fetching: the network fetch of feeds is parallelised
# (ThreadPoolExecutor, bounded by DEFAULT_FETCH_WORKERS), but parse/dedup/WRITE
# stay single-threaded and in ORIGINAL source order — so outputs and registry-row
# order are byte-identical to the sequential version; only wall-clock changes.
# --------------------------------------------------------------------------- #


def _single_item_feed(host: str) -> str:
    """A one-item full-body RSS feed whose article URL encodes `host` (e.g. s0)."""
    body = "Body prose sentence. " * 50  # > 500 chars stripped
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        f"<item><title>{host} Article</title>"
        f"<link>https://{host}.example.com/post</link>"
        f"<description>{body}</description></item>"
        "</channel></rss>"
    )


def test_collect_category_write_order_matches_sequential(tmp_path: Path) -> None:
    # Determinism: a SCRAMBLED-completion parallel fetch (later sources resolve first)
    # must produce byte-identical registry rows — in original source order — to a
    # forced-sequential run (one worker, no delays). This is the core guarantee.
    from scripts.normalize_url import normalize

    n = 6
    sources = [_rss_source(f"https://s{i}.example.com/rss") for i in range(n)]
    feeds = {s.url: _single_item_feed(f"s{i}") for i, s in enumerate(sources)}

    # Sequential baseline: a single worker fetches in submission (source) order.
    seq_registry = tmp_path / "seq" / "registry.md"
    collect.collect_category(
        category="ai", sources=sources,
        incoming_dir=tmp_path / "seq" / "1-incoming", registry_path=seq_registry,
        today=_TODAY, known_urls=set(),
        fetch_fn=lambda url: feeds[url], fetch_workers=1,
    )
    seq_rows = list(iter_registry_rows(seq_registry))

    # Parallel with reverse-order delays: source 0 finishes LAST, source n-1 first.
    index_of = {s.url: i for i, s in enumerate(sources)}

    def scrambled_fetch(url: str) -> str:
        time.sleep((n - index_of[url]) * 0.02)  # source 0 sleeps longest → resolves last
        return feeds[url]

    par_registry = tmp_path / "par" / "registry.md"
    collect.collect_category(
        category="ai", sources=sources,
        incoming_dir=tmp_path / "par" / "1-incoming", registry_path=par_registry,
        today=_TODAY, known_urls=set(), fetch_fn=scrambled_fetch,  # default workers
    )
    par_rows = list(iter_registry_rows(par_registry))

    # The parallel result is byte-identical to the sequential-expected one, and in
    # strict source order despite the scrambled fetch completion order.
    assert par_rows == seq_rows
    assert [r.url for r in par_rows] == [
        normalize(f"https://s{i}.example.com/post") for i in range(n)
    ]


def test_collect_category_bounded_concurrency(tmp_path: Path) -> None:
    # No more than DEFAULT_FETCH_WORKERS feed fetches may run at once. A counting
    # fetch records the peak in-flight count; the executor's bound is a hard ceiling.
    n = collect.DEFAULT_FETCH_WORKERS + 4  # more sources than the bound
    sources = [_rss_source(f"https://s{i}.example.com/rss") for i in range(n)]
    feeds = {s.url: _single_item_feed(f"s{i}") for i, s in enumerate(sources)}
    lock = threading.Lock()
    state = {"current": 0, "peak": 0}

    def counting_fetch(url: str) -> str:
        with lock:
            state["current"] += 1
            state["peak"] = max(state["peak"], state["current"])
        time.sleep(0.05)  # hold the slot so overlapping fetches accumulate
        with lock:
            state["current"] -= 1
        return feeds[url]

    collect.collect_category(
        category="ai", sources=sources,
        incoming_dir=tmp_path / "1-incoming", registry_path=tmp_path / "registry.md",
        today=_TODAY, known_urls=set(), fetch_fn=counting_fetch,
    )
    # Hard bound: never exceeded (the executor caps at DEFAULT_FETCH_WORKERS).
    assert state["peak"] <= collect.DEFAULT_FETCH_WORKERS
    # ...and the fetches actually overlapped (this really is a concurrent phase).
    assert state["peak"] >= 2


def test_collect_category_concurrent_failure_is_isolated(tmp_path: Path) -> None:
    # One source whose fetch raises must not prevent the others' items from being
    # collected — matches the sequential per-source tolerance, on the concurrent path.
    from scripts.normalize_url import normalize

    sources = [
        _rss_source("https://s0.example.com/rss"),
        _rss_source("https://bad.example.com/rss"),
        _rss_source("https://s2.example.com/rss"),
    ]
    feeds = {
        "https://s0.example.com/rss": _single_item_feed("s0"),
        "https://s2.example.com/rss": _single_item_feed("s2"),
    }

    def fetch(url: str) -> str:
        if "bad" in url:
            raise OSError("feed unreachable")
        return feeds[url]

    registry = tmp_path / "registry.md"
    result = collect.collect_category(
        category="ai", sources=sources,
        incoming_dir=tmp_path / "1-incoming", registry_path=registry,
        today=_TODAY, known_urls=set(), fetch_fn=fetch,
    )
    assert result.source_errors == 1
    assert result.saved == 2  # both good feeds survived the sibling's failure
    urls = {r.url for r in iter_registry_rows(registry)}
    assert normalize("https://s0.example.com/post") in urls
    assert normalize("https://s2.example.com/post") in urls


def test_concurrent_fetch_refuses_non_http_scheme(tmp_path: Path) -> None:
    # With NO fetch_fn injected, the concurrent phase calls the REAL guarded
    # collect.fetch(), which refuses a non-http(s) scheme — the SSRF/scheme guard is
    # intact under concurrency (counted as a source error, nothing saved).
    result = collect.collect_category(
        category="ai", sources=[_rss_source("ftp://evil.example/feed")],
        **_common(tmp_path),
    )
    assert result.saved == 0
    assert result.source_errors == 1


def test_concurrent_fetch_applies_ssrf_private_ip_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The concurrent phase routes through the guarded fetch(): a host resolving to a
    # private/loopback address is refused BEFORE any connection (SSRF), source error.
    monkeypatch.setattr(collect.socket, "getaddrinfo", lambda *a, **k: _gai("127.0.0.1"))
    result = collect.collect_category(
        category="ai", sources=[_rss_source("https://evil.example/feed")],
        **_common(tmp_path),
    )
    assert result.saved == 0
    assert result.source_errors == 1


def test_concurrent_phase_invokes_module_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With no fetch_fn injected, the concurrent phase must invoke the module-level
    # guarded fetch() entry point (never a bypass of it).
    seen: list[str] = []

    def spy(url: str, **_: object) -> str:
        seen.append(url)
        return _rss_two_items()

    monkeypatch.setattr(collect, "fetch", spy)
    collect.collect_category(
        category="ai", sources=[_rss_source()], **_common(tmp_path),
    )
    assert seen == ["https://feed.example.com/rss.xml"]


# --------------------------------------------------------------------------- #
# YAML-only config (CONVENTIONS §2.3, 0.8.0) — a legacy .md spelling resolves to
# the sources.yaml twin, and an unmigrated legacy dir fails LOUDLY.
# --------------------------------------------------------------------------- #


def _write_sources_yaml(tmp_path: Path, *, category: str = "ai") -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(
        "schema_version: 2\n"
        "categories:\n"
        f"  - name: {category}\n"
        "    sources:\n"
        "      - url: \"https://feed.example.com/ai.xml\"\n"
        "        type: rss\n"
        "        tier: high\n"
        "        priority: medium\n"
        "        filter: all\n"
        "        active: true\n",
        encoding="utf-8",
    )
    return path


def test_main_prefers_yaml_twin_over_legacy_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Both formats exist and disagree: the YAML twin is the active config, so
    # articles land under ITS category even though --sources points at the .md.
    _write_sources(tmp_path)  # legacy md with categories ai + ml
    _write_sources_yaml(tmp_path, category="yaml-topic")
    incoming = tmp_path / "1-incoming"
    monkeypatch.setattr(collect, "fetch", lambda url, **_: _rss_two_items())
    rc = collect.main([
        "--sources", str(tmp_path / "sources.md"),
        "--incoming", str(incoming),
        "--registry", str(tmp_path / "registry.md"),
        "--today", _TODAY,
    ])
    assert rc == 0
    assert (incoming / "yaml-topic").is_dir()
    assert not (incoming / "ai").exists()  # the stale md category was ignored
    assert "yaml-topic" in capsys.readouterr().out


def test_main_accepts_explicit_yaml_sources_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yaml_path = _write_sources_yaml(tmp_path)
    incoming = tmp_path / "1-incoming"
    monkeypatch.setattr(collect, "fetch", lambda url, **_: _rss_two_items())
    rc = collect.main([
        "--sources", str(yaml_path),
        "--incoming", str(incoming),
        "--registry", str(tmp_path / "registry.md"),
        "--today", _TODAY,
    ])
    assert rc == 0
    assert list((incoming / "ai").glob("*.md"))


def test_main_reports_malformed_yaml_sources_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "sources.yaml").write_text("categories: 3\n", encoding="utf-8")
    rc = collect.main([
        "--sources", str(tmp_path / "sources.md"),  # twin-resolved to the bad yaml
        "--incoming", str(tmp_path / "1-incoming"),
        "--registry", str(tmp_path / "registry.md"),
        "--today", _TODAY,
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "ERROR" in err and "categories" in err


def test_main_unmigrated_legacy_md_dir_errors_with_migrate_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 0.8.0 retired the .md tables: a dir whose REAL config still lives in
    # sources.md (no YAML twin) must fail LOUDLY with the one-command
    # migrate-config pointer — never silently read the legacy tables, never
    # silently collect nothing.
    (tmp_path / "sources.md").write_text(
        "## Category: ai\n\n"
        "### Active sources\n\n"
        "| URL | Type | Tier | Priority | Filter | Active |\n"
        "|-----|------|------|----------|--------|--------|\n"
        "| https://feed.example.com/ai.xml | rss | high | medium | all | yes |\n",
        encoding="utf-8",
    )
    fetched: list[str] = []
    monkeypatch.setattr(collect, "fetch", lambda url, **_: fetched.append(url) or _rss_two_items())
    rc = collect.main([
        "--sources", str(tmp_path / "sources.md"),
        "--incoming", str(tmp_path / "1-incoming"),
        "--registry", str(tmp_path / "registry.md"),
        "--today", _TODAY,
    ])
    assert rc == 1
    assert fetched == []  # refused before any network activity
    assert not (tmp_path / "1-incoming").exists()
    err = capsys.readouterr().err
    assert "migrate-config" in err
    assert "sources.yaml" in err  # names the file the runtime actually reads
