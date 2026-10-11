"""
test_content_metadata.py — the shared title/author/publication/date/feed extractor.

Before this package there were two half-extractors: `intake_flow/evidence.py`
(HTML signals for URL classification) and the RSS field reads in
`collection/feed.py`. Neither produced authors beyond a display string, and a
second parser would have been a third. `scripts/content_metadata/` is the single
implementation both call.

Everything here is parsed from UNTRUSTED remote documents, so the security
contract is part of the unit contract, not a separate suite: a hostile JSON-LD
block must not crash intake, a `javascript:` author URL must not survive, and an
oversized block must be ignored rather than parsed. The suite is offline by
construction (conftest blocks outbound sockets) — no test may fetch anything,
and nothing in this module ever dereferences an author URL.
"""

from __future__ import annotations

from scripts.content_metadata import (
    AuthorIdentity,
    ContentMetadata,
    from_html,
    parse_html,
)

BASE = "https://example.com/posts/hello"


def _html(head: str = "", body: str = "") -> str:
    return f"<html><head>{head}</head><body>{body}</body></html>"


def _jsonld(payload: str) -> str:
    return f'<script type="application/ld+json">{payload}</script>'


# ── authors: JSON-LD shapes ───────────────────────────────────────────────────
#
# schema.org lets `author` be a bare string, an object, a list of either, and
# lets the whole document hide inside an `@graph`. All four appear in the wild;
# missing any one of them silently drops the author for a whole publisher.


def test_jsonld_author_as_plain_string() -> None:
    meta = from_html(_html(_jsonld('{"@type":"Article","author":"Jane Doe"}')), BASE)
    assert [a.name for a in meta.authors] == ["Jane Doe"]
    assert meta.evidence["authors"] == "jsonld"


def test_jsonld_author_as_object_keeps_url() -> None:
    meta = from_html(
        _html(
            _jsonld(
                '{"@type":"Article","author":'
                '{"@type":"Person","name":"Jane Doe","url":"https://example.com/jane"}}'
            )
        ),
        BASE,
    )
    assert meta.authors == (AuthorIdentity(name="Jane Doe", url="https://example.com/jane"),)


def test_jsonld_multiple_authors_are_all_kept_in_document_order() -> None:
    meta = from_html(
        _html(
            _jsonld(
                '{"@type":"Article","author":['
                '{"name":"Jane Doe"},{"name":"John Roe"},"Ada Lovelace"]}'
            )
        ),
        BASE,
    )
    assert [a.name for a in meta.authors] == ["Jane Doe", "John Roe", "Ada Lovelace"]


def test_jsonld_graph_wrapper_is_unwrapped() -> None:
    meta = from_html(
        _html(
            _jsonld(
                '{"@context":"https://schema.org","@graph":['
                '{"@type":"WebSite","name":"Site"},'
                '{"@type":"NewsArticle","author":{"name":"Jane Doe"},'
                '"headline":"Hello","datePublished":"2026-07-20"}]}'
            )
        ),
        BASE,
    )
    assert [a.name for a in meta.authors] == ["Jane Doe"]
    assert meta.title == "Hello"
    assert meta.published_at == "2026-07-20"


def test_duplicate_authors_collapse_without_fuzzy_matching() -> None:
    # Exact repeats (the same person listed twice) collapse; near-matches never
    # merge — "J. Doe" and "Jane Doe" stay two people. We do not guess identity.
    meta = from_html(
        _html(
            _jsonld(
                '{"@type":"Article","author":['
                '{"name":"Jane Doe"},{"name":"Jane Doe"},{"name":"J. Doe"}]}'
            )
        ),
        BASE,
    )
    assert [a.name for a in meta.authors] == ["Jane Doe", "J. Doe"]


# ── authors: precedence ladder ────────────────────────────────────────────────


def test_jsonld_author_beats_meta_author() -> None:
    meta = from_html(
        _html(
            _jsonld('{"@type":"Article","author":{"name":"Jane Doe"}}')
            + '<meta name="author" content="Newsroom Bot">'
        ),
        BASE,
    )
    assert [a.name for a in meta.authors] == ["Jane Doe"]
    assert meta.evidence["authors"] == "jsonld"


def test_rel_author_beats_article_author_meta() -> None:
    meta = from_html(
        _html(
            '<meta property="article:author" content="Newsroom Bot">',
            '<a rel="author" href="https://example.com/jane">Jane Doe</a>',
        ),
        BASE,
    )
    assert meta.authors == (AuthorIdentity(name="Jane Doe", url="https://example.com/jane"),)
    assert meta.evidence["authors"] == "rel-author"


def test_meta_author_used_when_nothing_richer_exists() -> None:
    meta = from_html(_html('<meta name="author" content="Jane Doe">'), BASE)
    assert [a.name for a in meta.authors] == ["Jane Doe"]
    assert meta.evidence["authors"] == "meta"


def test_byl_meta_is_read_and_by_prefix_stripped() -> None:
    meta = from_html(_html('<meta name="byl" content="By Jane Doe">'), BASE)
    assert [a.name for a in meta.authors] == ["Jane Doe"]


def test_visible_byline_is_last_resort() -> None:
    meta = from_html(_html(body='<span class="byline">By Jane Doe</span>'), BASE)
    assert [a.name for a in meta.authors] == ["Jane Doe"]
    assert meta.evidence["authors"] == "byline"


def test_no_author_anywhere_yields_no_authors() -> None:
    # The frontmatter writer renders the "unknown" display string; the model
    # stays honest and simply has nobody, so a caller can tell absent from named.
    meta = from_html(_html("<title>Hello</title>"), BASE)
    assert meta.authors == ()
    assert "authors" not in meta.evidence


# ── author identity ───────────────────────────────────────────────────────────


def test_orcid_identifier_is_recognised() -> None:
    meta = from_html(
        _html(
            _jsonld(
                '{"@type":"Article","author":{"name":"Jane Doe",'
                '"identifier":"https://orcid.org/0000-0002-1825-0097"}}'
            )
        ),
        BASE,
    )
    assert meta.authors[0].identifier == "orcid:0000-0002-1825-0097"
    assert meta.authors[0].identifier_type == "orcid"


def test_name_alone_produces_no_identifier() -> None:
    meta = from_html(_html(_jsonld('{"@type":"Article","author":"Jane Doe"}')), BASE)
    assert meta.authors[0].identifier == ""
    assert meta.authors[0].identifier_type == ""


def test_author_url_with_hostile_scheme_is_dropped_but_name_survives() -> None:
    meta = from_html(
        _html(
            _jsonld(
                '{"@type":"Article","author":'
                '{"name":"Jane Doe","url":"javascript:alert(1)"}}'
            )
        ),
        BASE,
    )
    assert meta.authors == (AuthorIdentity(name="Jane Doe"),)


def test_author_url_data_scheme_is_dropped() -> None:
    meta = from_html(
        _html(_jsonld('{"@type":"Article","author":{"name":"J","url":"data:text/html,x"}}')),
        BASE,
    )
    assert meta.authors[0].url == ""


def test_relative_author_url_resolves_against_the_document() -> None:
    meta = from_html(
        _html(_jsonld('{"@type":"Article","author":{"name":"Jane","url":"/authors/jane"}}')),
        BASE,
    )
    assert meta.authors[0].url == "https://example.com/authors/jane"


# ── publication ───────────────────────────────────────────────────────────────


def test_publication_prefers_jsonld_publisher() -> None:
    meta = from_html(
        _html(
            _jsonld(
                '{"@type":"Article","publisher":{"@type":"Organization",'
                '"name":"Example Research"}}'
            )
            + '<meta property="og:site_name" content="Example Blog">'
        ),
        BASE,
    )
    assert meta.publication == "Example Research"
    assert meta.evidence["publication"] == "jsonld"


def test_publication_falls_back_to_og_site_name() -> None:
    meta = from_html(_html('<meta property="og:site_name" content="Example Blog">'), BASE)
    assert meta.publication == "Example Blog"
    assert meta.evidence["publication"] == "og"


def test_publication_falls_back_to_hostname() -> None:
    meta = from_html(_html("<title>Hello</title>"), BASE)
    assert meta.publication == "example.com"
    assert meta.evidence["publication"] == "hostname"


# ── title, date, feed, canonical ──────────────────────────────────────────────


def test_title_prefers_og_title_over_title_tag() -> None:
    meta = from_html(
        _html('<title>Site — Hello</title><meta property="og:title" content="Hello">'),
        BASE,
    )
    assert meta.title == "Hello"


def test_title_tag_whitespace_is_collapsed() -> None:
    meta = from_html(_html("<title>\n  Hello   world\n</title>"), BASE)
    assert meta.title == "Hello world"


def test_published_at_read_from_meta() -> None:
    meta = from_html(
        _html('<meta property="article:published_time" content="2026-07-20T10:00:00Z">'),
        BASE,
    )
    assert meta.published_at == "2026-07-20T10:00:00Z"


def test_feed_and_canonical_links_are_absolutised() -> None:
    meta = from_html(
        _html(
            '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
            '<link rel="canonical" href="/posts/hello">'
        ),
        BASE,
    )
    assert meta.feed_url == "https://example.com/feed.xml"
    assert meta.canonical_url == "https://example.com/posts/hello"


def test_non_http_feed_link_is_rejected() -> None:
    meta = from_html(
        _html('<link rel="alternate" type="application/rss+xml" href="javascript:x">'),
        BASE,
    )
    assert meta.feed_url == ""


# ── hostile / malformed input ─────────────────────────────────────────────────


def test_malformed_jsonld_does_not_raise_and_leaves_other_signals_intact() -> None:
    meta = from_html(
        _html(_jsonld("{not json at all,,,") + '<meta name="author" content="Jane Doe">'),
        BASE,
    )
    assert [a.name for a in meta.authors] == ["Jane Doe"]


def test_oversized_jsonld_block_is_ignored() -> None:
    from scripts.content_metadata.jsonld import MAX_BLOCK_BYTES

    padding = "x" * (MAX_BLOCK_BYTES + 1)
    meta = from_html(
        _html(_jsonld(f'{{"@type":"Article","author":"Jane Doe","pad":"{padding}"}}')),
        BASE,
    )
    assert meta.authors == ()


def test_author_name_with_newline_and_yaml_punctuation_is_flattened() -> None:
    # The name reaches a YAML writer downstream; the extractor must not hand it a
    # multi-line value. Structure-bearing characters survive as literal text —
    # neutralising them is the emitter's job — but line breaks never do.
    meta = from_html(
        _html(_jsonld('{"@type":"Article","author":"Jane\\nDoe: - name: evil"}')),
        BASE,
    )
    assert meta.authors[0].name == "Jane Doe: - name: evil"


def test_zero_width_characters_are_stripped_from_names() -> None:
    meta = from_html(
        _html(_jsonld('{"@type":"Article","author":"Ja\\u200bne Doe"}')),
        BASE,
    )
    assert meta.authors[0].name == "Jane Doe"


def test_absurdly_long_author_name_is_truncated() -> None:
    from scripts.content_metadata.normalize import MAX_NAME_CHARS

    meta = from_html(
        _html(_jsonld(f'{{"@type":"Article","author":"{"A" * (MAX_NAME_CHARS + 50)}"}}')),
        BASE,
    )
    assert len(meta.authors[0].name) == MAX_NAME_CHARS


def test_empty_document_yields_empty_metadata_not_an_error() -> None:
    meta = from_html("", BASE)
    assert isinstance(meta, ContentMetadata)
    assert meta.authors == ()


def test_extraction_is_deterministic_for_identical_input() -> None:
    doc = _html(
        _jsonld('{"@type":"Article","author":[{"name":"B"},{"name":"A"}]}')
        + '<meta property="og:site_name" content="Example">'
    )
    assert from_html(doc, BASE) == from_html(doc, BASE)


# ── absorbed intake signals ───────────────────────────────────────────────────
#
# `intake_flow/evidence.py` used to own these; classification still needs them,
# so the merged parser keeps producing them rather than intake keeping a second
# parser alive.


def test_parse_html_still_reports_article_classification_signals() -> None:
    signals = parse_html(
        _html(
            '<meta property="og:type" content="article">'
            '<meta property="article:published_time" content="2026-07-20">',
            "<article>body</article>",
        ),
        BASE,
    )
    assert signals.og_article is True
    assert signals.has_published_time is True
    assert signals.has_article_element is True


def test_parse_html_collects_article_links_for_index_detection() -> None:
    signals = parse_html(
        _html(body='<a href="/2026/07/post-one">one</a><a href="/about">about</a>'),
        BASE,
    )
    assert signals.article_links == {"https://example.com/2026/07/post-one"}


def test_jsonld_article_type_still_marks_og_article() -> None:
    signals = parse_html(_html(_jsonld('{"@type":"BlogPosting","headline":"x"}')), BASE)
    assert signals.og_article is True
