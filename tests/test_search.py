"""
test_search.py — offline tests for the optional web-search provider.

All network I/O is monkeypatched; nothing here touches a real API. Covers the
Tavily adapter (request building + result parsing, error -> []), and the
search.py dispatcher (routes by provider, missing key -> soft-skip empty,
claude-websearch -> sentinel note). No conftest edits needed.
"""

from pathlib import Path

import pytest

# Make `scripts` importable as a package root (tests run from project root).
from scripts.search import perplexity, search, tavily

# Skip cleanly if PyYAML is unavailable in this interpreter (dispatcher reads YAML).
pytest.importorskip("yaml", reason="PyYAML required for dispatcher config tests")


# --------------------------------------------------------------------------- #
# Tavily adapter
# --------------------------------------------------------------------------- #


def test_tavily_builds_request_and_parses_results(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post(api_key, query, max_results):
        captured["api_key"] = api_key
        captured["query"] = query
        captured["max_results"] = max_results
        return {
            "results": [
                {"title": "First", "url": "https://a.example", "content": "snippet a"},
                {"title": "Second", "url": "https://b.example", "content": "snippet b"},
            ]
        }

    monkeypatch.setattr(tavily, "_post_search", fake_post)
    out = tavily.search("agents", api_key="KEY", max_results=2)

    # Request was built from the args.
    assert captured == {"api_key": "KEY", "query": "agents", "max_results": 2}
    # Results normalized to {title, url, snippet}.
    assert out == [
        {"title": "First", "url": "https://a.example", "snippet": "snippet a"},
        {"title": "Second", "url": "https://b.example", "snippet": "snippet b"},
    ]


def test_tavily_returns_empty_on_error(monkeypatch):
    import urllib.error

    def boom(api_key, query, max_results):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(tavily, "_post_search", boom)
    assert tavily.search("q", api_key="KEY") == []


def test_tavily_empty_on_missing_key():
    # No key -> no network call, just an empty list (no raise).
    assert tavily.search("q", api_key="") == []


def test_tavily_sends_key_in_bearer_header_not_body(monkeypatch):
    # The API key must travel in an `Authorization: Bearer <key>` header (mirroring
    # perplexity.py/sonar.py), never in the JSON body — a body key is more easily
    # logged/cached/leaked than a header.
    import json as _json

    captured: dict[str, object] = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"results": []}'

    def fake_urlopen(request, timeout=None):
        captured["headers"] = dict(request.header_items())
        captured["body"] = request.data
        return _FakeResponse()

    monkeypatch.setattr(tavily.urllib.request, "urlopen", fake_urlopen)
    tavily.search("agents", api_key="KEY", max_results=2)

    # Authorization header carries the bearer token (header names are title-cased).
    headers = {k.lower(): v for k, v in captured["headers"].items()}
    assert headers["authorization"] == "Bearer KEY"
    # The body no longer contains the key under any casing.
    body = _json.loads(captured["body"].decode("utf-8"))
    assert "api_key" not in body
    assert "KEY" not in captured["body"].decode("utf-8")
    assert body == {"query": "agents", "max_results": 2}


def test_tavily_tolerates_malformed_results(monkeypatch):
    monkeypatch.setattr(
        tavily,
        "_post_search",
        lambda api_key, query, max_results: {"results": ["not-a-dict", {"title": "Ok"}]},
    )
    out = tavily.search("q", api_key="KEY")
    # The bad entry is skipped; the dict entry is normalized with empty defaults.
    assert out == [{"title": "Ok", "url": "", "snippet": ""}]


# --------------------------------------------------------------------------- #
# Perplexity adapter (raw Search API)
# --------------------------------------------------------------------------- #


def test_perplexity_builds_request_and_parses_results(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post(api_key, query, max_results):
        captured["api_key"] = api_key
        captured["query"] = query
        captured["max_results"] = max_results
        return {
            "results": [
                {"title": "First", "url": "https://a.example", "snippet": "snip a"},
                # second uses `content` to prove the field-tolerant normalizer:
                {"title": "Second", "url": "https://b.example", "content": "snip b"},
            ]
        }

    monkeypatch.setattr(perplexity, "_post_search", fake_post)
    out = perplexity.search("agents", api_key="KEY", max_results=2)

    assert captured == {"api_key": "KEY", "query": "agents", "max_results": 2}
    assert out == [
        {"title": "First", "url": "https://a.example", "snippet": "snip a"},
        {"title": "Second", "url": "https://b.example", "snippet": "snip b"},
    ]


def test_perplexity_returns_empty_on_error(monkeypatch):
    import urllib.error

    def boom(api_key, query, max_results):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(perplexity, "_post_search", boom)
    assert perplexity.search("q", api_key="KEY") == []


def test_perplexity_empty_on_missing_key():
    assert perplexity.search("q", api_key="") == []


# --------------------------------------------------------------------------- #
# Dispatcher (search.web_search)
# --------------------------------------------------------------------------- #


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "search.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_dispatcher_routes_to_tavily(monkeypatch, tmp_path):
    cfg = _write_config(
        tmp_path,
        "search:\n"
        "  provider: tavily\n"
        "  tavily:\n"
        "    api_key_env: TAVILY_API_KEY\n"
        "    max_results: 3\n",
    )
    monkeypatch.setenv("TAVILY_API_KEY", "secret-key")

    calls: dict[str, object] = {}

    def fake_search(query, *, api_key, max_results=5):
        calls["query"] = query
        calls["api_key"] = api_key
        calls["max_results"] = max_results
        return [{"title": "T", "url": "https://t.example", "snippet": "s"}]

    monkeypatch.setattr(search.tavily, "search", fake_search)
    out = search.web_search("rag", config_path=cfg)

    assert out == [{"title": "T", "url": "https://t.example", "snippet": "s"}]
    assert calls == {"query": "rag", "api_key": "secret-key", "max_results": 3}


def test_dispatcher_non_numeric_max_results_falls_back_to_default(monkeypatch, tmp_path):
    # A config typo (`max_results: "notanumber"`) is not a reason to crash:
    # _keyed_search clamps it to the default (5) and still calls the provider.
    cfg = _write_config(
        tmp_path,
        "search:\n"
        "  provider: tavily\n"
        "  tavily:\n"
        "    api_key_env: TAVILY_API_KEY\n"
        '    max_results: "notanumber"\n',
    )
    monkeypatch.setenv("TAVILY_API_KEY", "secret-key")

    calls: dict[str, object] = {}

    def fake_search(query, *, api_key, max_results=5):
        calls["max_results"] = max_results
        return [{"title": "T", "url": "https://t.example", "snippet": "s"}]

    monkeypatch.setattr(search.tavily, "search", fake_search)
    out = search.web_search("rag", config_path=cfg)

    # No crash; provider was called with the DEFAULT max_results.
    assert out == [{"title": "T", "url": "https://t.example", "snippet": "s"}]
    assert calls["max_results"] == 5


def test_dispatcher_tavily_missing_key_soft_skips(monkeypatch, tmp_path):
    cfg = _write_config(
        tmp_path,
        "search:\n  provider: tavily\n  tavily:\n    api_key_env: TAVILY_API_KEY\n",
    )
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    # Point the .env loader at a nonexistent file so no real .env supplies the key.
    monkeypatch.setattr(search, "DEFAULT_ENV_FILE", tmp_path / "nope.env")

    # Must not raise; returns empty.
    assert search.web_search("q", config_path=cfg) == []


def test_dispatcher_routes_to_perplexity(monkeypatch, tmp_path):
    cfg = _write_config(
        tmp_path,
        "search:\n"
        "  provider: perplexity\n"
        "  perplexity:\n"
        "    api_key_env: PERPLEXITY_API_KEY\n"
        "    max_results: 4\n",
    )
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")

    calls: dict[str, object] = {}

    def fake_search(query, *, api_key, max_results=5):
        calls["query"] = query
        calls["api_key"] = api_key
        calls["max_results"] = max_results
        return [{"title": "P", "url": "https://p.example", "snippet": "s"}]

    monkeypatch.setattr(search.perplexity, "search", fake_search)
    out = search.web_search("rag", config_path=cfg)

    assert out == [{"title": "P", "url": "https://p.example", "snippet": "s"}]
    assert calls == {"query": "rag", "api_key": "pplx-key", "max_results": 4}


def test_dispatcher_perplexity_missing_key_soft_skips(monkeypatch, tmp_path):
    cfg = _write_config(
        tmp_path,
        "search:\n  provider: perplexity\n  perplexity:\n    api_key_env: PERPLEXITY_API_KEY\n",
    )
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.setattr(search, "DEFAULT_ENV_FILE", tmp_path / "nope.env")
    assert search.web_search("q", config_path=cfg) == []


def test_dispatcher_claude_websearch_returns_sentinel(tmp_path):
    cfg = _write_config(tmp_path, "search:\n  provider: claude-websearch\n")
    out = search.web_search("q", config_path=cfg)
    assert len(out) == 1
    assert out[0]["kind"] == search.CLAUDE_WEBSEARCH_KIND
    assert out[0]["note"] == search.CLAUDE_WEBSEARCH_NOTE


def test_dispatcher_none_provider_soft_skips(tmp_path):
    cfg = _write_config(tmp_path, "search:\n  provider: none\n")
    assert search.web_search("q", config_path=cfg) == []


def test_dispatcher_missing_config_defaults_to_claude_websearch(tmp_path):
    # No file at all -> empty config -> provider defaults to claude-websearch.
    out = search.web_search("q", config_path=tmp_path / "absent.yaml")
    assert len(out) == 1 and out[0]["kind"] == search.CLAUDE_WEBSEARCH_KIND


# --------------------------------------------------------------------------- #
# Missing PyYAML must SOFT-SKIP, not crash — BUG 4
# --------------------------------------------------------------------------- #


def test_load_config_soft_skips_without_pyyaml(monkeypatch, tmp_path):
    # config/search.yaml EXISTS but the headless `python3` runtime has no PyYAML.
    # load_config must degrade to an empty dict (the documented soft-skip),
    # NOT raise — search is always optional (BUG 4).
    cfg = tmp_path / "search.yaml"
    cfg.write_text("search:\n  provider: tavily\n", encoding="utf-8")

    import builtins

    real_import = builtins.__import__

    def no_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("simulated: no PyYAML in headless runtime")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_yaml)

    assert search.load_config(cfg) == {}


def test_web_search_soft_skips_without_pyyaml(monkeypatch, tmp_path):
    # End-to-end: with PyYAML absent and an EXISTING config, the dispatcher must
    # return the soft-skip (claude-websearch sentinel from the default provider),
    # never an uncaught RuntimeError (the documented headless dispatcher contract).
    cfg = tmp_path / "search.yaml"
    cfg.write_text("search:\n  provider: tavily\n", encoding="utf-8")

    import builtins

    real_import = builtins.__import__

    def no_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("simulated headless")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_yaml)

    # Empty config -> provider defaults to claude-websearch -> sentinel note.
    out = search.web_search("q", config_path=cfg)
    assert len(out) == 1 and out[0]["kind"] == search.CLAUDE_WEBSEARCH_KIND


# --------------------------------------------------------------------------- #
# Malformed YAML must be CAUGHT (clean message), not raise a raw ParserError
# --------------------------------------------------------------------------- #


def test_load_config_soft_skips_on_malformed_yaml(tmp_path, capsys):
    # A syntactically broken search.yaml must degrade to the documented soft-skip
    # (empty dict + a clear printed message), NOT surface a raw yaml.YAMLError.
    cfg = tmp_path / "search.yaml"
    # Unclosed flow mapping -> yaml.safe_load raises a ParserError/ScannerError.
    cfg.write_text("search: {provider: tavily\n", encoding="utf-8")

    assert search.load_config(cfg) == {}
    # The message must name the file so it is actionable.
    assert "search.yaml" in capsys.readouterr().out


def test_web_search_soft_skips_on_malformed_yaml(tmp_path):
    # End-to-end: a malformed config must not crash the dispatcher; it falls back
    # to the default provider (claude-websearch sentinel), never a raw traceback.
    cfg = tmp_path / "search.yaml"
    cfg.write_text("search:\n  provider: [unterminated\n", encoding="utf-8")

    out = search.web_search("q", config_path=cfg)
    assert len(out) == 1 and out[0]["kind"] == search.CLAUDE_WEBSEARCH_KIND


# --------------------------------------------------------------------------- #
# Unknown provider dispatch and malformed responses
# --------------------------------------------------------------------------- #


def test_dispatcher_unknown_provider_soft_skips(tmp_path):
    # Misspelled or unknown provider name (e.g. "sonar_pro" vs "sonar") must
    # soft-skip with a clear message, not crash. Returns empty list.
    cfg = _write_config(
        tmp_path,
        "search:\n  provider: sonar_pro\n",
    )
    out = search.web_search("q", config_path=cfg)
    assert out == []


def test_dispatcher_misspelled_provider_soft_skips(tmp_path):
    # Similar to unknown provider: typo in provider name (e.g. "tavvily")
    # must soft-skip, not crash.
    cfg = _write_config(
        tmp_path,
        "search:\n  provider: tavvily\n",
    )
    out = search.web_search("q", config_path=cfg)
    assert out == []


def test_tavily_handles_malformed_json_response(monkeypatch):
    # Provider returns HTTP 200 but with invalid/incomplete JSON.
    # The adapter must handle gracefully without crashing.
    import json

    def bad_json_response(api_key, query, max_results):
        # Simulate a response that raises json.JSONDecodeError.
        raise json.JSONDecodeError("Expecting value", "", 0)

    monkeypatch.setattr(tavily, "_post_search", bad_json_response)
    # Must return empty list, not crash.
    out = tavily.search("q", api_key="KEY")
    assert out == []


def test_tavily_handles_200_with_incomplete_json(monkeypatch):
    # Return incomplete JSON structure: missing 'results' key.
    monkeypatch.setattr(
        tavily,
        "_post_search",
        lambda api_key, query, max_results: {"status": "ok"},  # no 'results'
    )
    out = tavily.search("q", api_key="KEY")
    # _normalize should handle gracefully; results defaults to None
    # which _normalize treats as non-list and returns [].
    assert out == []


def test_tavily_handles_null_results(monkeypatch):
    # API returns 200 with `results: null` instead of a list.
    monkeypatch.setattr(
        tavily,
        "_post_search",
        lambda api_key, query, max_results: {"results": None},
    )
    out = tavily.search("q", api_key="KEY")
    # None is not a list, so _normalize returns [].
    assert out == []


def test_tavily_handles_string_results(monkeypatch):
    # Malformed response where results is a string, not a list.
    monkeypatch.setattr(
        tavily,
        "_post_search",
        lambda api_key, query, max_results: {"results": "not a list"},
    )
    out = tavily.search("q", api_key="KEY")
    # String is not a list, so _normalize returns [].
    assert out == []
