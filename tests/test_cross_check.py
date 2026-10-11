"""
test_cross_check.py — offline tests for the optional Sonar cross-check slot.

The cross-check is a DIFFERENT slot from corroboration / web_search: it asks the
Perplexity Sonar chat API the same research question and returns a synthesized
{answer, citations} pair used as an *adversarial* input in research-build's
Phase 6.5 Critique — never as a synthesis input (trust model stays intact,
CONVENTIONS §15a). All network I/O is monkeypatched; nothing here hits a real API.

Soft-skip discipline (mirrors search.py / deliver.py): a missing key or missing
config returns an empty {answer:"", citations:[]} with a printed note, never a
raise — "if the key is set we run it, otherwise the pipeline runs exactly as
before".
"""

from pathlib import Path

import pytest

# Make `scripts` importable as a package root (tests run from project root).
from scripts.search import cross_check, sonar

# Skip cleanly if PyYAML is unavailable (dispatcher reads YAML).
pytest.importorskip("yaml", reason="PyYAML required for dispatcher config tests")


# --------------------------------------------------------------------------- #
# Sonar adapter (chat/completions -> {answer, citations})
# --------------------------------------------------------------------------- #


def test_sonar_builds_request_and_parses_answer_and_citations(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post(api_key, question, model, max_tokens):
        captured["api_key"] = api_key
        captured["question"] = question
        captured["model"] = model
        captured["max_tokens"] = max_tokens
        return {
            "choices": [{"message": {"content": "Independent synthesis text."}}],
            # Newer API: search_results carry title + url.
            "search_results": [
                {"title": "Alpha", "url": "https://a.example", "date": "2026-01-01"},
                {"title": "Beta", "url": "https://b.example"},
            ],
        }

    monkeypatch.setattr(sonar, "_post_chat", fake_post)
    out = sonar.search("what is X?", api_key="KEY", model="sonar-reasoning", max_tokens=512)

    assert captured == {
        "api_key": "KEY",
        "question": "what is X?",
        "model": "sonar-reasoning",
        "max_tokens": 512,
    }
    assert out == {
        "answer": "Independent synthesis text.",
        "citations": [
            {"title": "Alpha", "url": "https://a.example"},
            {"title": "Beta", "url": "https://b.example"},
        ],
    }


def test_sonar_citations_fall_back_to_url_only_list(monkeypatch):
    # Older API shape: no search_results, only a `citations` list of bare URLs.
    monkeypatch.setattr(
        sonar,
        "_post_chat",
        lambda api_key, question, model, max_tokens: {
            "choices": [{"message": {"content": "Answer."}}],
            "citations": ["https://x.example", "https://y.example"],
        },
    )
    out = sonar.search("q", api_key="KEY")
    assert out["answer"] == "Answer."
    assert out["citations"] == [
        {"title": "", "url": "https://x.example"},
        {"title": "", "url": "https://y.example"},
    ]


def test_sonar_returns_empty_on_error(monkeypatch):
    import urllib.error

    def boom(api_key, question, model, max_tokens):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(sonar, "_post_chat", boom)
    assert sonar.search("q", api_key="KEY") == {"answer": "", "citations": []}


def test_sonar_empty_on_missing_key():
    assert sonar.search("q", api_key="") == {"answer": "", "citations": []}


def test_sonar_empty_content_on_length_truncation_keeps_citations(monkeypatch, capsys):
    # Reasoning models can burn the whole max_tokens budget on internal reasoning,
    # returning finish_reason="length" with empty content. We must NOT crash, must
    # still surface the citations, and must print a budget hint so a user with too
    # low a max_tokens isn't left guessing why the answer is empty.
    monkeypatch.setattr(
        sonar,
        "_post_chat",
        lambda api_key, question, model, max_tokens: {
            "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
            "search_results": [{"title": "Cited", "url": "https://c.example"}],
        },
    )
    out = sonar.search("q", api_key="KEY", max_tokens=8)
    assert out["answer"] == ""
    assert out["citations"] == [{"title": "Cited", "url": "https://c.example"}]
    # The diagnostic must name the cause (token budget) so it is actionable.
    assert "max_tokens" in capsys.readouterr().out


def test_sonar_tolerates_malformed_payload(monkeypatch):
    # No choices, search_results has a non-dict entry that must be skipped.
    monkeypatch.setattr(
        sonar,
        "_post_chat",
        lambda api_key, question, model, max_tokens: {
            "search_results": ["not-a-dict", {"title": "Ok", "url": "https://ok.example"}],
        },
    )
    out = sonar.search("q", api_key="KEY")
    assert out["answer"] == ""
    assert out["citations"] == [{"title": "Ok", "url": "https://ok.example"}]


# --------------------------------------------------------------------------- #
# Dispatcher (cross_check.cross_check)
# --------------------------------------------------------------------------- #


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "research.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_dispatcher_routes_to_sonar(monkeypatch, tmp_path):
    cfg = _write_config(
        tmp_path,
        "research:\n"
        "  cross_check:\n"
        "    provider: sonar\n"
        "    sonar:\n"
        "      api_key_env: PERPLEXITY_API_KEY\n"
        "      model: sonar-pro\n"
        "      max_tokens: 256\n",
    )
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")

    calls: dict[str, object] = {}

    def fake_search(question, *, api_key, model="sonar-reasoning", max_tokens=1024):
        calls["question"] = question
        calls["api_key"] = api_key
        calls["model"] = model
        calls["max_tokens"] = max_tokens
        return {"answer": "A", "citations": [{"title": "C", "url": "https://c.example"}]}

    monkeypatch.setattr(cross_check.sonar, "search", fake_search)
    out = cross_check.cross_check("the question", config_path=cfg)

    assert out == {"answer": "A", "citations": [{"title": "C", "url": "https://c.example"}]}
    assert calls == {
        "question": "the question",
        "api_key": "pplx-key",
        "model": "sonar-pro",
        "max_tokens": 256,
    }


def test_dispatcher_non_numeric_max_tokens_falls_back_to_default(monkeypatch, tmp_path):
    # A config typo (`max_tokens: "x"`) must not crash: _run_sonar clamps it to
    # the default (1024) and still calls the adapter.
    cfg = _write_config(
        tmp_path,
        "research:\n"
        "  cross_check:\n"
        "    provider: sonar\n"
        "    sonar:\n"
        "      api_key_env: PERPLEXITY_API_KEY\n"
        '      max_tokens: "x"\n',
    )
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")

    calls: dict[str, object] = {}

    def fake_search(question, *, api_key, model="sonar-reasoning", max_tokens=1024):
        calls["max_tokens"] = max_tokens
        return {"answer": "A", "citations": []}

    monkeypatch.setattr(cross_check.sonar, "search", fake_search)
    out = cross_check.cross_check("the question", config_path=cfg)

    # No crash; adapter was called with the DEFAULT max_tokens.
    assert out == {"answer": "A", "citations": []}
    assert calls["max_tokens"] == 1024


def test_dispatcher_missing_key_soft_skips(monkeypatch, tmp_path):
    cfg = _write_config(tmp_path, "research:\n  cross_check:\n    provider: sonar\n")
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.setattr(cross_check, "DEFAULT_ENV_FILE", tmp_path / "nope.env")
    assert cross_check.cross_check("q", config_path=cfg) == {"answer": "", "citations": []}


def test_dispatcher_provider_none_soft_skips(tmp_path):
    cfg = _write_config(tmp_path, "research:\n  cross_check:\n    provider: none\n")
    assert cross_check.cross_check("q", config_path=cfg) == {"answer": "", "citations": []}


def test_dispatcher_missing_config_with_key_defaults_to_sonar(monkeypatch, tmp_path):
    # No research.yaml at all: provider defaults to sonar, so merely having the
    # key set activates the cross-check ("if the key is set we run it").
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
    monkeypatch.setattr(
        cross_check.sonar,
        "search",
        lambda question, *, api_key, model="sonar-reasoning", max_tokens=1024: {
            "answer": "default-on",
            "citations": [],
        },
    )
    out = cross_check.cross_check("q", config_path=tmp_path / "absent.yaml")
    assert out["answer"] == "default-on"


def test_dispatcher_missing_config_without_key_soft_skips(monkeypatch, tmp_path):
    # No config AND no key -> the pipeline runs exactly as before (empty result).
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.setattr(cross_check, "DEFAULT_ENV_FILE", tmp_path / "nope.env")
    assert cross_check.cross_check("q", config_path=tmp_path / "absent.yaml") == {
        "answer": "",
        "citations": [],
    }


# --------------------------------------------------------------------------- #
# Malformed YAML must be CAUGHT (clean message), not raise a raw ParserError
# --------------------------------------------------------------------------- #


def test_load_config_soft_skips_on_malformed_yaml(tmp_path, capsys):
    # A syntactically broken research.yaml must degrade to the documented
    # soft-skip (empty dict + a clear printed message), NOT a raw yaml.YAMLError.
    cfg = tmp_path / "research.yaml"
    cfg.write_text("research: {cross_check: sonar\n", encoding="utf-8")

    assert cross_check.load_config(cfg) == {}
    assert "research.yaml" in capsys.readouterr().out


def test_cross_check_soft_skips_on_malformed_yaml(monkeypatch, tmp_path):
    # End-to-end: a malformed config must not crash the dispatcher. With no key
    # it falls back to the empty cross-check result, never a raw traceback.
    cfg = tmp_path / "research.yaml"
    cfg.write_text("research:\n  cross_check: [unterminated\n", encoding="utf-8")
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.setattr(cross_check, "DEFAULT_ENV_FILE", tmp_path / "nope.env")

    assert cross_check.cross_check("q", config_path=cfg) == {"answer": "", "citations": []}


# --------------------------------------------------------------------------- #
# Unknown provider dispatch and typo/missing-key handling
# --------------------------------------------------------------------------- #


def test_dispatcher_unknown_provider_soft_skips(tmp_path):
    # Unknown provider name (e.g. "sonar_pro" typo) must soft-skip, not crash.
    cfg = _write_config(
        tmp_path,
        "research:\n  cross_check:\n    provider: sonar_pro\n",
    )
    out = cross_check.cross_check("q", config_path=cfg)
    assert out == {"answer": "", "citations": []}


def test_dispatcher_misspelled_provider_soft_skips(tmp_path):
    # Another typo variant: "solar" instead of "sonar".
    cfg = _write_config(
        tmp_path,
        "research:\n  cross_check:\n    provider: solar\n",
    )
    out = cross_check.cross_check("q", config_path=cfg)
    assert out == {"answer": "", "citations": []}


def test_sonar_handles_malformed_json_response(monkeypatch):
    # Provider returns HTTP 200 but malformed JSON.
    # The adapter must handle gracefully without crashing.
    import json

    def bad_json_response(api_key, question, model, max_tokens):
        raise json.JSONDecodeError("Expecting value", "", 0)

    monkeypatch.setattr(sonar, "_post_chat", bad_json_response)
    out = sonar.search("q", api_key="KEY")
    assert out == {"answer": "", "citations": []}


def test_sonar_handles_200_with_incomplete_response(monkeypatch):
    # Return a response that's missing both `choices` and `search_results`.
    monkeypatch.setattr(
        sonar,
        "_post_chat",
        lambda api_key, question, model, max_tokens: {"status": "ok"},  # no choices/results
    )
    out = sonar.search("q", api_key="KEY")
    # _extract_answer should return "" and _extract_citations should return [].
    assert out == {"answer": "", "citations": []}


def test_sonar_handles_non_dict_response(monkeypatch):
    # Response is not a dict at all (e.g. a string or list).
    monkeypatch.setattr(
        sonar,
        "_post_chat",
        lambda api_key, question, model, max_tokens: "not a dict",
    )
    out = sonar.search("q", api_key="KEY")
    # The early isinstance(data, dict) check returns empty.
    assert out == {"answer": "", "citations": []}


def test_sonar_handles_null_choices(monkeypatch):
    # Response has choices=null instead of a list.
    monkeypatch.setattr(
        sonar,
        "_post_chat",
        lambda api_key, question, model, max_tokens: {
            "choices": None,
            "search_results": [],
        },
    )
    out = sonar.search("q", api_key="KEY")
    # _first_choice should return {} (since choices is not a list).
    assert out == {"answer": "", "citations": []}


def test_sonar_handles_malformed_search_results(monkeypatch):
    # search_results contains non-dict entries that should be skipped.
    monkeypatch.setattr(
        sonar,
        "_post_chat",
        lambda api_key, question, model, max_tokens: {
            "choices": [{"message": {"content": "Answer"}}],
            "search_results": [
                "a string, not a dict",
                None,
                {"title": "Valid", "url": "https://v.example"},
                123,  # number
            ],
        },
    )
    out = sonar.search("q", api_key="KEY")
    # Only the dict entry should be extracted.
    assert out["answer"] == "Answer"
    assert out["citations"] == [{"title": "Valid", "url": "https://v.example"}]
