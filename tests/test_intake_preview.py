"""
test_intake_preview.py — what the user SEES when they paste a link.

Intake could always tell a feed from an article; it just never said what it had
found. The answer was "recurring_source, confidence 0.90" — accurate and
useless, because the person pasting the link cannot check it. The preview
reports the facts behind that verdict: what the page is called, who wrote it,
who published it, and which feed was discovered.

The whole thing is free. `classify_url` already fetches and parses the document
to decide what it is; the preview reads the SAME parse. That is the constraint
this file pins hardest — enriching the answer must not cost a second request, and
it must not be able to change the verdict.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.intake_flow.classification import classify_url
from scripts.intake_flow.rendering import render_human, render_json
from tests.test_intake import ARTICLE_HTML, HTML_WITH_FEED, config_dir  # noqa: F401

AUTHORED_HTML = """<!doctype html>
<html><head>
<title>Site — Deep dive</title>
<meta property="og:type" content="article">
<meta property="og:site_name" content="Example Research">
<meta property="article:published_time" content="2026-07-20T09:00:00Z">
<script type="application/ld+json">
{"@type": "NewsArticle", "headline": "Deep dive",
 "author": [{"name": "Jane Doe", "url": "https://example.com/jane"},
            {"name": "John Roe"}]}
</script>
</head><body><article>Body</article></body></html>
"""


def _classify(html: str, config_dir: Path, url: str = "https://example.com/posts/x"):  # noqa: F811
    calls: list[str] = []

    def fetch(target: str) -> str:
        calls.append(target)
        return html

    result = classify_url(url, config_dir=config_dir, fetch_fn=fetch)
    return result, calls


# ── the preview carries what the verdict was based on ─────────────────────────


def test_article_preview_reports_title_publication_and_date(config_dir: Path) -> None:  # noqa: F811
    result, _ = _classify(AUTHORED_HTML, config_dir)
    assert result.preview is not None
    assert result.preview.title == "Deep dive"
    assert result.preview.publication == "Example Research"
    assert result.preview.published_at == "2026-07-20T09:00:00Z"
    assert result.preview.content_type == "article"


def test_preview_lists_every_credited_author(config_dir: Path) -> None:  # noqa: F811
    result, _ = _classify(AUTHORED_HTML, config_dir)
    assert result.preview is not None
    assert [a.name for a in result.preview.authors] == ["Jane Doe", "John Roe"]
    assert result.preview.authors[0].url == "https://example.com/jane"


def test_preview_reports_the_discovered_feed(config_dir: Path) -> None:  # noqa: F811
    result, _ = _classify(HTML_WITH_FEED, config_dir, url="https://example.com/")
    assert result.preview is not None
    assert result.preview.feed_url == "https://example.com/feed.xml"


def test_preview_is_present_but_sparse_when_the_page_says_little(
    config_dir: Path,  # noqa: F811
) -> None:
    result, _ = _classify("<html><body>hi</body></html>", config_dir)
    assert result.preview is not None
    assert result.preview.authors == ()
    assert result.preview.title == ""


# ── enrichment costs nothing and changes nothing ──────────────────────────────


def test_preview_costs_no_extra_request(config_dir: Path) -> None:  # noqa: F811
    """One fetch, same as before — the preview reads the parse we already did."""
    _, calls = _classify(ARTICLE_HTML, config_dir)
    assert len(calls) == 1


def test_classification_verdict_is_unchanged_by_enrichment(config_dir: Path) -> None:  # noqa: F811
    """The pinned confidence values must survive the preview being added."""
    article, _ = _classify(ARTICLE_HTML, config_dir)
    assert article.kind == "one_off_article"
    assert article.confidence == 0.8

    feed, _ = _classify(HTML_WITH_FEED, config_dir, url="https://example.com/")
    assert feed.kind == "recurring_source"
    assert feed.confidence == 0.9
    assert feed.source_url == "https://example.com/feed.xml"


def test_a_failing_preview_never_degrades_the_verdict(
    config_dir: Path, monkeypatch  # noqa: F811
) -> None:
    """Enrichment is strictly additive: if it breaks, classification still works."""

    def boom(*_a: object, **_kw: object) -> object:
        raise RuntimeError("metadata exploded")

    monkeypatch.setattr("scripts.intake_flow.classification.metadata_from_signals", boom)
    result, _ = _classify(ARTICLE_HTML, config_dir)
    assert result.kind == "one_off_article"
    assert result.confidence == 0.8
    assert result.preview is None


# ── output ────────────────────────────────────────────────────────────────────


def test_human_output_shows_the_facts_a_person_can_check(config_dir: Path) -> None:  # noqa: F811
    result, _ = _classify(AUTHORED_HTML, config_dir)
    text = render_human(result)
    assert "Deep dive" in text
    assert "Example Research" in text
    assert "Jane Doe" in text


def test_human_output_does_not_offer_author_monitoring_yet(config_dir: Path) -> None:  # noqa: F811
    """Authors are REPORTED, not actionable — there is no author monitoring yet.

    Offering an action the system cannot perform is worse than staying quiet: the
    user picks it, nothing happens, and they stop trusting the other options.
    """
    result, _ = _classify(AUTHORED_HTML, config_dir)
    text = render_human(result).lower()
    assert "monitor author" not in text
    assert "track author" not in text


def test_json_output_includes_the_preview(config_dir: Path) -> None:  # noqa: F811
    result, _ = _classify(AUTHORED_HTML, config_dir)
    payload = json.loads(render_json(result))
    assert payload["preview"]["title"] == "Deep dive"
    assert payload["preview"]["authors"][0]["name"] == "Jane Doe"
    # An author with no profile link carries no empty scaffolding.
    assert "url" not in payload["preview"]["authors"][1]


def test_json_omits_preview_entirely_when_there_is_none(config_dir: Path) -> None:  # noqa: F811
    result, _ = _classify(ARTICLE_HTML, config_dir)
    payload = json.loads(render_json(result))
    # Sanity: this fixture DOES produce a preview, so the key is present…
    assert "preview" in payload
    # …but a result built without one must not carry a null placeholder.
    from dataclasses import replace

    assert "preview" not in json.loads(render_json(replace(result, preview=None)))
