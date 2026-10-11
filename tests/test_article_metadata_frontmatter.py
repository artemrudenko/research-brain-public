"""
test_article_metadata_frontmatter.py — the enriched, still-injection-safe article header.

Collected articles gain optional `authors:` / `publication:` / `source_url:` /
`content_type:` / `metadata_source:` fields. Two properties make this more than
an additive schema change, and both are pinned here:

1. **It is genuinely additive.** An article collected without metadata must come
   out byte-identical to what the previous writer produced, and every existing
   article (which has none of these keys) must keep validating. The required-key
   contract in CONVENTIONS §5 does not move.

2. **`authors:` is the first NESTED structure in this frontmatter.** Until now
   every value was a flat scalar emitted through PyYAML, which is what made a
   hostile `author` like `a: b` harmless. A list of mappings is a new emitter
   path carrying attacker-authored names, so the injection cases live here
   rather than in a general writer test: a name must never be able to introduce
   a key, close the frontmatter, or smuggle a second author.

The security bar is the S1–S9 gate's: the value survives as literal text, the
STRUCTURE is ours alone.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts import collect
from scripts.collection.feed import FeedItem
from scripts.content_metadata import AuthorIdentity, ContentMetadata

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_TODAY = "2026-07-21"


def _item(author: str = "Jane Doe") -> FeedItem:
    return FeedItem(
        url="https://example.com/posts/hello",
        title="Hello world",
        author=author,
        date_published="2026-07-20",
        body="<p>Body text that is long enough to be a real article body.</p>",
        guid="g1",
        categories=[],
    )


def _build(metadata: ContentMetadata | None = None, source_url: str = "", **kw: object) -> str:
    return collect.build_article(
        _item(),
        source_name="example.com",
        category="ai",
        tags=["ai"],
        collected=_TODAY,
        tier="high",
        metadata=metadata,
        source_url=source_url,
        **kw,
    )


def _frontmatter(text: str) -> dict[str, object]:
    """Parse the emitted frontmatter block back into data.

    Round-tripping through a real YAML parser is the point: it is how we assert
    that a hostile name stayed a VALUE and did not become structure.
    """
    assert text.startswith("---\n")
    block = text.split("---\n", 2)[1]
    loaded = yaml.safe_load(block)
    assert isinstance(loaded, dict)
    return loaded


# ── additive: nothing changes when there is no metadata ───────────────────────


def test_article_without_metadata_is_unchanged() -> None:
    """The no-metadata path must produce exactly the previous bytes."""
    legacy = collect.build_article(
        _item(), source_name="example.com", category="ai",
        tags=["ai"], collected=_TODAY, tier="high",
    )
    assert _build() == legacy


def test_no_new_keys_appear_without_metadata() -> None:
    front = _frontmatter(_build())
    for key in ("authors", "publication", "source_url", "content_type", "metadata_source"):
        assert key not in front


def test_required_keys_are_still_all_present_with_metadata() -> None:
    front = _frontmatter(
        _build(ContentMetadata(authors=(AuthorIdentity(name="Jane Doe"),), publication="Example"))
    )
    for key in (
        "source", "url", "title", "author", "date_published",
        "collected", "category", "tags",
    ):
        assert key in front, f"required key {key} went missing"


# ── the enriched fields ───────────────────────────────────────────────────────


def test_single_author_is_emitted_with_url_and_id() -> None:
    front = _frontmatter(
        _build(
            ContentMetadata(
                authors=(
                    AuthorIdentity(
                        name="Jane Doe",
                        url="https://example.com/jane",
                        identifier="orcid:0000-0002-1825-0097",
                        identifier_type="orcid",
                    ),
                ),
                evidence={"authors": "jsonld"},
            )
        )
    )
    assert front["authors"] == [
        {
            "name": "Jane Doe",
            "url": "https://example.com/jane",
            "id": "orcid:0000-0002-1825-0097",
        }
    ]
    assert front["metadata_source"] == "jsonld"


def test_multiple_authors_are_all_emitted_in_order() -> None:
    front = _frontmatter(
        _build(
            ContentMetadata(
                authors=(AuthorIdentity(name="Jane Doe"), AuthorIdentity(name="John Roe"))
            )
        )
    )
    assert front["authors"] == [{"name": "Jane Doe"}, {"name": "John Roe"}]


def test_empty_author_fields_are_omitted_not_emitted_blank() -> None:
    front = _frontmatter(_build(ContentMetadata(authors=(AuthorIdentity(name="Jane Doe"),))))
    assert front["authors"] == [{"name": "Jane Doe"}]


def test_publication_source_url_and_content_type_are_emitted() -> None:
    front = _frontmatter(
        _build(
            ContentMetadata(publication="Example Research", content_type="article"),
            source_url="https://example.com/feed.xml",
        )
    )
    assert front["publication"] == "Example Research"
    assert front["source_url"] == "https://example.com/feed.xml"
    assert front["content_type"] == "article"


def test_display_author_prefers_extracted_author_over_feed_string() -> None:
    text = _build(ContentMetadata(authors=(AuthorIdentity(name="Extracted Name"),)))
    front = _frontmatter(text)
    assert front["author"] == "Extracted Name"
    # The rendered byline is pinned by the digest reader — same shape, new value.
    assert "*By Extracted Name · 2026-07-20*" in text


def test_url_field_still_carries_the_normalized_article_url() -> None:
    # `source_url` is the feed; `url` stays the article and the dedup key.
    front = _frontmatter(_build(source_url="https://example.com/feed.xml"))
    assert front["url"] == "https://example.com/posts/hello"


# ── injection: a hostile author must not become structure ─────────────────────


@pytest.mark.parametrize(
    "hostile",
    [
        "Jane\nDoe",
        "- name: injected",
        "Jane\n- name: injected",
        "a: b",
        "---\ninjected: true",
        "Jane\n---\n\n# Injected body",
        '"quoted" evil',
        "Jane #comment",
        "*anchor",
        "&anchor ref",
        "!!python/object:os.system",
        "\n\n---\n\nnot frontmatter",
    ],
)
def test_hostile_author_name_stays_a_single_scalar_value(hostile: str) -> None:
    front = _frontmatter(
        _build(ContentMetadata(authors=(AuthorIdentity(name=hostile),)))
    )
    authors = front["authors"]
    assert isinstance(authors, list)
    # Exactly one author, and its name is a string — never a smuggled mapping,
    # never a second entry, never a parsed Python object.
    assert len(authors) == 1
    assert isinstance(authors[0], dict)
    assert isinstance(authors[0]["name"], str)
    assert "injected" not in front


def test_hostile_author_url_scheme_is_dropped_at_emit_time() -> None:
    # The extractor already refuses these; the emitter refuses them again, so a
    # caller that hand-builds an AuthorIdentity cannot write a javascript: link.
    front = _frontmatter(
        _build(
            ContentMetadata(
                authors=(AuthorIdentity(name="Jane Doe", url="javascript:alert(1)"),)
            )
        )
    )
    assert front["authors"] == [{"name": "Jane Doe"}]


def test_newlines_in_publication_cannot_close_the_frontmatter() -> None:
    text = _build(ContentMetadata(publication="Example\n---\ninjected: true"))
    front = _frontmatter(text)
    assert "injected" not in front
    assert isinstance(front["publication"], str)


def test_zero_width_characters_are_stripped_from_emitted_names() -> None:
    front = _frontmatter(
        _build(ContentMetadata(authors=(AuthorIdentity(name="Ja​ne Doe"),)))
    )
    assert front["authors"][0]["name"] == "Jane Doe"


def test_absurdly_long_name_is_bounded_at_emit_time() -> None:
    from scripts.content_metadata.normalize import MAX_NAME_CHARS

    front = _frontmatter(
        _build(ContentMetadata(authors=(AuthorIdentity(name="A" * 5000),)))
    )
    assert len(front["authors"][0]["name"]) <= MAX_NAME_CHARS


# ── the real gates ────────────────────────────────────────────────────────────


def test_enriched_article_passes_the_strict_pipeline_validator(tmp_path: Path) -> None:
    text = _build(
        ContentMetadata(
            authors=(AuthorIdentity(name="Jane Doe", url="https://example.com/jane"),),
            publication="Example Research",
            content_type="article",
            evidence={"authors": "jsonld"},
        ),
        source_url="https://example.com/feed.xml",
    )
    incoming = tmp_path / "1-incoming" / "ai"
    incoming.mkdir(parents=True)
    (incoming / "2026-07-21_hello.md").write_text(text, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate-pipeline-frontmatter.py",
            str(tmp_path / "1-incoming"),
            "--strict",
        ],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_sanitizer_preserves_the_new_fields_and_keeps_yaml_parseable(tmp_path: Path) -> None:
    """The S1–S9 gate rewrites values in place; it must not flatten the structure.

    Sanitizing runs on every collected article before synthesis reads it, so a
    nested block it mangled would take the authors down with it — and synthesis
    reads the COMPANION, never the raw file, so this is the copy that matters.
    """
    from scripts.sanitize_incoming import sanitize_file

    text = _build(
        ContentMetadata(
            authors=(
                AuthorIdentity(name="Jane Doe", url="https://example.com/jane"),
                AuthorIdentity(name="John Roe"),
            ),
            publication="Example Research",
            evidence={"authors": "jsonld"},
        ),
        source_url="https://example.com/feed.xml",
    )
    src = tmp_path / "1-incoming" / "ai" / "2026-07-21_hello.md"
    src.parent.mkdir(parents=True)
    src.write_text(text, encoding="utf-8")

    outcome = sanitize_file(src)
    front = _frontmatter(outcome.companion.read_text(encoding="utf-8"))
    assert front["authors"] == [
        {"name": "Jane Doe", "url": "https://example.com/jane"},
        {"name": "John Roe"},
    ]
    assert front["publication"] == "Example Research"
    assert front["source_url"] == "https://example.com/feed.xml"


# ── the collector actually populates this ─────────────────────────────────────


def test_collect_writes_source_url_and_feed_author_provenance(tmp_path: Path) -> None:
    """A real collect run fills the new fields — they are not write-only plumbing.

    Only feed-level facts are expected here: the entry's own author and the feed
    it came through. Both are already in memory, so enrichment adds no request.
    """
    from tests.test_collect import _TODAY as COLLECT_TODAY
    from tests.test_collect import RSS_SAMPLE, _rss_source

    def fetch(url: str, **_: object) -> str:
        assert url.endswith("/rss.xml"), f"unexpected extra fetch: {url}"
        return RSS_SAMPLE

    result = collect.collect_category(
        category="ai",
        sources=[_rss_source()],
        incoming_dir=tmp_path / "1-incoming",
        registry_path=tmp_path / "registry.md",
        today=COLLECT_TODAY,
        known_urls=set(),
        fetch_fn=fetch,
    )
    assert result.saved >= 1

    article = sorted((tmp_path / "1-incoming" / "ai").glob("*.md"))[0]
    front = _frontmatter(article.read_text(encoding="utf-8"))
    assert front["source_url"] == "https://feed.example.com/rss.xml"
    assert front["metadata_source"] == "rss"
    assert isinstance(front["authors"], list)
    # The list mirrors the required display string rather than contradicting it.
    assert front["authors"][0]["name"] == front["author"]


# ── HTML-level authors, when the page was fetched anyway ──────────────────────


_JSONLD_ARTICLE = (
    "<!doctype html><html><head>"
    '<meta property="og:site_name" content="Example Research">'
    '<script type="application/ld+json">'
    '{"@type":"NewsArticle","headline":"Deep dive","author":'
    '[{"name":"Jane Doe","url":"https://example.com/jane"},{"name":"John Roe"}]}'
    "</script></head><body><article><p>"
    + "Real article prose with enough substance. " * 40
    + "</p></article></body></html>"
)


def _collect_short_feed(tmp_path: Path, **kw: object):
    """Collect a feed whose body is too short, so the article page IS fetched."""
    from scripts import collect
    from tests.test_collect import _TODAY as COLLECT_TODAY
    from tests.test_collect import RSS_SHORT, _rss_source

    def fetch(url: str, **_: object) -> str:
        return RSS_SHORT if url.endswith("/rss.xml") else _JSONLD_ARTICLE

    params: dict[str, object] = {
        "category": "ai",
        "sources": [_rss_source()],
        "incoming_dir": tmp_path / "1-incoming",
        "registry_path": tmp_path / "registry.md",
        "today": COLLECT_TODAY,
        "known_urls": set(),
        "fetch_fn": fetch,
    }
    params.update(kw)
    return collect.collect_category(**params)  # type: ignore[arg-type]


def test_top_up_page_yields_multiple_authors_with_profile_links(tmp_path: Path) -> None:
    """The page was fetched for its body; its metadata now comes back too.

    This is the half deferred when the frontmatter fields landed. It costs no
    extra request — the top-up fetch already happened — and it is what turns a
    bare feed name into an author we could actually follow.
    """
    result = _collect_short_feed(tmp_path)
    assert result.saved == 1

    article = next((tmp_path / "1-incoming" / "ai").glob("*.md"))
    front = _frontmatter(article.read_text(encoding="utf-8"))
    assert front["authors"] == [
        {"name": "Jane Doe", "url": "https://example.com/jane"},
        {"name": "John Roe"},
    ]
    assert front["metadata_source"] == "jsonld"
    assert front["publication"] == "Example Research"


def test_feed_author_still_wins_when_the_page_says_nothing(tmp_path: Path) -> None:
    # Precedence unchanged: JSON-LD outranks the feed, but a page with no author
    # must not erase the `dc:creator` the feed did provide.
    from scripts import collect
    from tests.test_collect import _TODAY as COLLECT_TODAY
    from tests.test_collect import RSS_SHORT, _rss_source

    plain = "<html><body><article><p>" + "Prose. " * 200 + "</p></article></body></html>"

    def fetch(url: str, **_: object) -> str:
        if url.endswith("/rss.xml"):
            return RSS_SHORT.replace(
                "<description>tiny</description>",
                "<description>tiny</description><dc:creator>Feed Person</dc:creator>",
            ).replace("<rss version=\"2.0\">",
                      '<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">')
        return plain

    collect.collect_category(
        category="ai", sources=[_rss_source()], incoming_dir=tmp_path / "1-incoming",
        registry_path=tmp_path / "registry.md", today=COLLECT_TODAY,
        known_urls=set(), fetch_fn=fetch,
    )
    article = next((tmp_path / "1-incoming" / "ai").glob("*.md"))
    front = _frontmatter(article.read_text(encoding="utf-8"))
    assert front["authors"] == [{"name": "Feed Person"}]
    assert front["metadata_source"] == "rss"


def test_journal_records_the_author_profile_so_they_become_followable(
    tmp_path: Path,
) -> None:
    """The suggestion engine needs a stable handle; this is where one first exists."""
    from scripts.source_report.authors import author_metrics

    _collect_short_feed(tmp_path, journal_root=tmp_path, run_id="run-1")

    people = author_metrics(tmp_path, tmp_path / "registry.md")
    jane = next(p for p in people if p.display_name == "Jane Doe")
    assert jane.profile_url == "https://example.com/jane"
    assert jane.followable is True
