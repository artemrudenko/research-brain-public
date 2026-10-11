"""Tests for the shared read-only URL intake classifier."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from scripts import collect, intake  # noqa: E402
from scripts import manage_sources as ms  # noqa: E402

EXAMPLE_CONFIG = Path(__file__).resolve().parent / "fixtures" / "example_config"

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>AI Agents Feed</title>
<item><title>One</title><link>https://example.com/one</link></item>
</channel></rss>
"""

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom Feed</title>
<entry><title>One</title><link rel="alternate" href="https://example.com/one" /></entry>
</feed>
"""

HTML_WITH_FEED = """<!doctype html>
<html><head>
<title>Example Blog</title>
<link rel="alternate" type="application/rss+xml" href="/feed.xml">
</head><body>Blog home</body></html>
"""

ARTICLE_HTML = """<!doctype html>
<html><head>
<title>One Article</title>
<meta property="og:type" content="article">
<meta property="article:published_time" content="2026-07-01T10:00:00Z">
<script type="application/ld+json">{"@type": "NewsArticle", "headline": "One"}</script>
</head><body><article>Article body</article></body></html>
"""

INDEX_HTML = """<!doctype html>
<html><head><title>AI Agents Blog</title></head><body>
<a href="/2026/first-post">First</a>
<a href="/2026/second-post">Second</a>
<a href="/2026/third-post">Third</a>
</body></html>
"""


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    # The ACTIVE config is the YAML twins (YAML-only since 0.8.0, CONVENTIONS
    # §2.3) plus the tag registry — the same trio a fresh install ships.
    d = tmp_path / "config"
    d.mkdir()
    for name in ("sources.yaml", "topics.yaml", "tags.yaml"):
        (d / name).write_text((EXAMPLE_CONFIG / name).read_text(encoding="utf-8"))
    return d


def _snapshot(path: Path) -> dict[str, bytes]:
    if not path.exists():
        return {}
    return {
        str(child.relative_to(path)): child.read_bytes()
        for child in sorted(p for p in path.rglob("*") if p.is_file())
    }


def _classify(
    config_dir: Path, url: str, body: str | BaseException, seen: list[str] | None = None
) -> intake.Classification:
    def fetch(url_to_fetch: str) -> str:
        if seen is not None:
            seen.append(url_to_fetch)
        if isinstance(body, BaseException):
            raise body
        return body

    return intake.classify_url(url, config_dir, fetch_fn=fetch)


def test_direct_rss_is_recurring(config_dir: Path) -> None:
    result = _classify(config_dir, "https://feeds.example.com/rss.xml", RSS)

    assert result.kind == "recurring_source"
    assert result.source_type == "rss"
    assert result.source_url == "https://feeds.example.com/rss.xml"
    assert result.confidence == 1.0
    assert result.proposed_action
    assert result.clarification_question is None
    assert result.to_dict()["kind"] in {"recurring_source", "one_off_article", "ambiguous"}


def test_direct_atom_is_recurring(config_dir: Path) -> None:
    result = _classify(config_dir, "https://feeds.example.com/atom.xml", ATOM)

    assert result.kind == "recurring_source"
    assert result.source_type == "rss"
    assert result.confidence == 1.0


def test_html_feed_discovery_is_recurring(config_dir: Path) -> None:
    result = _classify(config_dir, "https://example.com/blog", HTML_WITH_FEED)

    assert result.kind == "recurring_source"
    assert result.source_type == "rss"
    assert result.source_url == "https://example.com/feed.xml"
    assert result.confidence == 0.9
    assert result.clarification_question is None


def test_article_metadata_is_one_off(config_dir: Path) -> None:
    result = _classify(config_dir, "https://example.com/articles/one", ARTICLE_HTML)

    assert result.kind == "one_off_article"
    assert result.source_url is None
    assert result.source_type is None
    assert result.proposed_action == "save_article"
    assert result.confidence == 0.8
    assert result.clarification_question is None


def test_blog_index_is_recurring(config_dir: Path) -> None:
    result = _classify(config_dir, "https://example.com/blog", INDEX_HTML)

    assert result.kind == "recurring_source"
    assert result.source_type == "blog"
    assert result.source_url == "https://example.com/blog"
    assert result.confidence == 0.7


def test_conflicting_signals_are_ambiguous(config_dir: Path) -> None:
    result = _classify(
        config_dir,
        "https://example.com/post",
        HTML_WITH_FEED.replace("</head>", '<meta property="og:type" content="article"></head>'),
    )

    assert result.kind == "ambiguous"
    assert result.proposed_action == "ask_clarification"
    assert result.clarification_question == (
        "Should I save this one article, or monitor this site for future updates?"
    )


def test_ambiguous_result_has_one_exact_question(config_dir: Path) -> None:
    failed = _classify(config_dir, "https://example.com/unknown", OSError("offline"))
    weak = _classify(config_dir, "https://example.com/unknown", "<html><body>Unknown</body></html>")

    for result in (failed, weak):
        assert result.kind == "ambiguous"
        assert result.clarification_question == (
            "Should I save this one article, or monitor this site for future updates?"
        )
        assert result.proposed_action == "ask_clarification"
        assert result.reason


def test_unique_existing_topic_is_proposed(config_dir: Path) -> None:
    ms.add_topic(config_dir, "ai-agents")
    ms.add_topic(config_dir, "pkm-notes")

    result = _classify(config_dir, "https://example.com/ai-agents/feed.xml", RSS)

    assert result.kind == "recurring_source"
    assert result.topic_mode == "existing"
    assert result.proposed_topic == "ai-agents"


def test_topic_tie_or_no_match_requests_create_without_writing(config_dir: Path) -> None:
    ms.add_topic(config_dir, "ai-agents")
    ms.add_topic(config_dir, "ai-research")
    before = _snapshot(config_dir)

    tied = _classify(config_dir, "https://example.com/ai/feed.xml", RSS)
    nomatch = _classify(config_dir, "https://robotics.example.com/feed.xml", RSS)

    assert tied.topic_mode == "create"
    assert tied.proposed_topic == "example"
    assert nomatch.topic_mode == "create"
    assert nomatch.proposed_topic == "robotics-example"
    assert _snapshot(config_dir) == before


def test_classification_writes_nothing(config_dir: Path, tmp_path: Path) -> None:
    pipeline = tmp_path / "pipeline"
    (pipeline / "1-incoming" / "_inbox").mkdir(parents=True)
    (pipeline / "registry.md").write_text("| Collected | Category | URL | Title | Status |\n")
    before_config = _snapshot(config_dir)
    before_pipeline = _snapshot(pipeline)

    result = _classify(config_dir, "https://example.com/feed.xml", RSS)

    assert result.kind == "recurring_source"
    assert _snapshot(config_dir) == before_config
    assert _snapshot(pipeline) == before_pipeline


def test_default_fetch_is_resolved_at_call_time(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def patched_fetch(url: str) -> str:
        seen.append(url)
        return RSS

    monkeypatch.setattr(collect, "fetch", patched_fetch)
    result = intake.classify_url("https://feeds.example.com/rss.xml", config_dir)

    assert result.kind == "recurring_source"
    assert seen == ["https://feeds.example.com/rss.xml"]


def test_classifier_never_calls_raw_urllib(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def blocked(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("raw urllib.request.urlopen must not be called")

    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    result = _classify(config_dir, "https://feeds.example.com/rss.xml", RSS)

    assert result.kind == "recurring_source"


def test_injected_fetch_is_used(config_dir: Path) -> None:
    seen: list[str] = []
    result = _classify(config_dir, "https://feeds.example.com/rss.xml", RSS, seen)

    assert result.kind == "recurring_source"
    assert seen == ["https://feeds.example.com/rss.xml"]


def test_non_http_url_is_rejected(config_dir: Path) -> None:
    with pytest.raises(ValueError):
        intake.classify_url("file:///etc/passwd", config_dir, fetch_fn=lambda _url: RSS)


def test_cli_outputs_json(config_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(collect, "fetch", lambda _url: RSS)

    rc = intake.main(["https://feeds.example.com/rss.xml", "--config-dir", str(config_dir), "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "recurring_source"
    assert payload["input_url"] == "https://feeds.example.com/rss.xml"


def test_cli_help_lists_supported_flags(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        intake.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "url" in out
    assert "--config-dir" in out
    assert "--json" in out
