"""
test_search_trail.py — tests for the durable search-trail observability log.

The search-trail is a machine-readable JSONL record of which queries ran against
which provider and what came back, written BESIDE a manual research session's
other sidecars (`planning/research/{date}_{slug}.search-trail.jsonl`, the same
`{date}_{slug}` prefix as the brief / verification-log / critique-log). It serves
the project's auditable-grounding value: a reviewer can see the provenance of a
session's web research after the fact.

Two paths feed it: (a) the API-provider path auto-wired into search.py /
cross_check.py, and (b) the agent's own claude-websearch (recorded via a skill
instruction calling the helper). Both append through `append_search_entry`.

Soft-skip discipline (mirrors search.py / deliver.py): a trail-logging failure
must NEVER raise — it is swallowed with a printed note, because a logging hiccup
must not abort a search. Off by default: nothing is written unless a trail target
(`RESEARCH_TRAIL_DIR` / an explicit session path) is configured.
"""

import json

# Make `scripts` importable as a package root (tests run from project root).
from scripts.search import search_trail

# `yaml` is only needed by the auto-wiring dispatcher tests at the bottom; the
# helper tests are pure stdlib.


# --------------------------------------------------------------------------- #
# Helper — append / read round-trip
# --------------------------------------------------------------------------- #


def test_append_creates_jsonl_and_reads_back(tmp_path):
    trail = tmp_path / "2026-06-22_topic.search-trail.jsonl"
    search_trail.append_search_entry(
        trail,
        query="what is RAG",
        provider="tavily",
        n_results=2,
        urls=["https://www.bbc.co.uk/news/x", "https://nytimes.com/y"],
    )

    # File now exists with exactly one JSON line.
    assert trail.exists()
    lines = trail.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    entries = search_trail.read_trail(trail)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.query == "what is RAG"
    assert entry.provider == "tavily"
    assert entry.n_results == 2
    # Domains are registrable-domain-extracted (eTLD+1), not raw URLs.
    assert entry.domains == ("bbc.co.uk", "nytimes.com")
    assert entry.ts  # an ISO-ish timestamp was stamped


def test_append_grows_jsonl_without_clobbering(tmp_path):
    trail = tmp_path / "trail.jsonl"
    search_trail.append_search_entry(
        trail, query="q1", provider="tavily", n_results=1, urls=["https://a.example"]
    )
    search_trail.append_search_entry(
        trail, query="q2", provider="perplexity", n_results=0, urls=[]
    )

    entries = search_trail.read_trail(trail)
    assert [e.query for e in entries] == ["q1", "q2"]
    assert [e.provider for e in entries] == ["tavily", "perplexity"]


def test_domains_are_deduplicated_and_blank_dropped(tmp_path):
    trail = tmp_path / "trail.jsonl"
    search_trail.append_search_entry(
        trail,
        query="q",
        provider="tavily",
        n_results=3,
        # Two URLs share the registrable domain; one is junk (-> "" dropped).
        urls=["https://www.bbc.co.uk/a", "https://bbc.co.uk/b", "not a url"],
    )
    entry = search_trail.read_trail(trail)[0]
    assert entry.domains == ("bbc.co.uk",)


# --------------------------------------------------------------------------- #
# Soft-skip — a write failure must NEVER raise
# --------------------------------------------------------------------------- #


def test_write_failure_soft_skips_without_raising(tmp_path, capsys):
    # Point the trail at a path whose parent is a FILE, so opening it raises
    # NotADirectoryError inside the helper. The helper must swallow it.
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    trail = blocker / "nested" / "trail.jsonl"

    # Must not raise.
    search_trail.append_search_entry(
        trail, query="q", provider="tavily", n_results=1, urls=["https://a.example"]
    )
    # A clear, non-fatal note was printed.
    assert "search-trail" in capsys.readouterr().out


def test_read_missing_trail_returns_empty(tmp_path):
    # Reading a trail that was never written is not an error — it's an empty list.
    assert search_trail.read_trail(tmp_path / "absent.jsonl") == []


def test_read_tolerates_a_corrupt_line(tmp_path):
    # A half-written / corrupt line must be skipped, not crash the reader — the
    # trail is observability, never load-bearing.
    trail = tmp_path / "trail.jsonl"
    good = json.dumps(
        {"ts": "2026-06-22T00:00:00", "query": "q", "provider": "tavily",
         "n_results": 1, "domains": ["a.example"]}
    )
    trail.write_text(good + "\n" + "{not valid json\n", encoding="utf-8")
    entries = search_trail.read_trail(trail)
    assert len(entries) == 1
    assert entries[0].query == "q"


# --------------------------------------------------------------------------- #
# Session-path resolution + off-by-default target resolution
# --------------------------------------------------------------------------- #


def test_trail_path_for_session_uses_sibling_prefix(tmp_path):
    # The trail must live BESIDE the brief, sharing its {date}_{slug} prefix.
    brief = tmp_path / "planning" / "research" / "2026-06-22_my-topic.md"
    path = search_trail.trail_path_for_brief(brief)
    assert path == brief.with_name("2026-06-22_my-topic.search-trail.jsonl")


def test_resolve_target_off_by_default_without_env(monkeypatch):
    # No RESEARCH_TRAIL_DIR and no explicit session -> None (write nothing).
    monkeypatch.delenv(search_trail.TRAIL_DIR_ENV, raising=False)
    assert search_trail.resolve_trail_target("a-slug") is None


def test_resolve_target_uses_env_dir_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv(search_trail.TRAIL_DIR_ENV, str(tmp_path))
    target = search_trail.resolve_trail_target("my-slug")
    assert target == tmp_path / "my-slug.search-trail.jsonl"


# --------------------------------------------------------------------------- #
# Concurrent appends stay line-atomic (append-safe, never a torn line)
# --------------------------------------------------------------------------- #


def test_concurrent_appends_do_not_corrupt_lines(tmp_path):
    import threading

    trail = tmp_path / "trail.jsonl"
    n = 40

    def worker(i):
        search_trail.append_search_entry(
            trail, query=f"q{i}", provider="tavily", n_results=i,
            urls=[f"https://s{i}.example"],
        )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every line must be independently valid JSON (no interleaving/tearing) and
    # all N entries must be present.
    lines = trail.read_text(encoding="utf-8").splitlines()
    assert len(lines) == n
    parsed = [json.loads(line) for line in lines]  # raises if any line is torn
    assert sorted(p["query"] for p in parsed) == sorted(f"q{i}" for i in range(n))


# --------------------------------------------------------------------------- #
# Auto-wiring: search.py records WITH a target, records nothing WITHOUT one
# --------------------------------------------------------------------------- #


def _import_search_modules():
    import pytest

    pytest.importorskip("yaml", reason="PyYAML required for dispatcher config tests")
    from scripts.search import cross_check, search

    return search, cross_check


def _write_search_config(tmp_path, body):
    path = tmp_path / "search.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_web_search_records_trail_when_target_set(monkeypatch, tmp_path):
    search, _ = _import_search_modules()
    cfg = _write_search_config(
        tmp_path,
        "search:\n  provider: tavily\n  tavily:\n    api_key_env: TAVILY_API_KEY\n",
    )
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.setattr(
        search.tavily,
        "search",
        lambda query, *, api_key, max_results=5: [
            {"title": "T", "url": "https://nytimes.com/x", "snippet": "s"}
        ],
    )
    # Turn the trail ON via the env target dir.
    monkeypatch.setenv(search_trail.TRAIL_DIR_ENV, str(tmp_path))

    out = search.web_search("rag agents", config_path=cfg)
    assert out and out[0]["url"] == "https://nytimes.com/x"

    # A trail entry was recorded for the slugged query.
    trail = search_trail.resolve_trail_target(search_trail.slug_for_query("rag agents"))
    assert trail is not None and trail.exists()
    entry = search_trail.read_trail(trail)[0]
    assert entry.provider == "tavily"
    assert entry.n_results == 1
    assert entry.domains == ("nytimes.com",)


def test_web_search_records_nothing_without_target(monkeypatch, tmp_path):
    search, _ = _import_search_modules()
    cfg = _write_search_config(
        tmp_path,
        "search:\n  provider: tavily\n  tavily:\n    api_key_env: TAVILY_API_KEY\n",
    )
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.setattr(
        search.tavily,
        "search",
        lambda query, *, api_key, max_results=5: [
            {"title": "T", "url": "https://nytimes.com/x", "snippet": "s"}
        ],
    )
    # Trail OFF (no env). Nothing must be written anywhere under tmp_path.
    monkeypatch.delenv(search_trail.TRAIL_DIR_ENV, raising=False)

    search.web_search("rag agents", config_path=cfg)
    assert list(tmp_path.glob("*.search-trail.jsonl")) == []


def test_web_search_claude_sentinel_records_nothing(monkeypatch, tmp_path):
    # The default in-agent provider returns a sentinel (no real results to log
    # here — that's the agent's job per the skill wiring). Even with the trail ON,
    # the dispatcher must not write a sentinel "search" as a provider entry.
    search, _ = _import_search_modules()
    cfg = _write_search_config(tmp_path, "search:\n  provider: claude-websearch\n")
    monkeypatch.setenv(search_trail.TRAIL_DIR_ENV, str(tmp_path))

    search.web_search("q", config_path=cfg)
    assert list(tmp_path.glob("*.search-trail.jsonl")) == []


def test_cross_check_records_trail_when_target_set(monkeypatch, tmp_path):
    _, cross_check = _import_search_modules()
    cfg = tmp_path / "research.yaml"
    cfg.write_text("research:\n  cross_check:\n    provider: sonar\n", encoding="utf-8")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
    monkeypatch.setattr(
        cross_check.sonar,
        "search",
        lambda question, *, api_key, model="sonar", max_tokens=1024: {
            "answer": "A",
            "citations": [{"title": "C", "url": "https://bbc.co.uk/x"}],
        },
    )
    monkeypatch.setenv(search_trail.TRAIL_DIR_ENV, str(tmp_path))

    cross_check.cross_check("the question", config_path=cfg)

    trail = search_trail.resolve_trail_target(
        search_trail.slug_for_query("the question")
    )
    assert trail is not None and trail.exists()
    entry = search_trail.read_trail(trail)[0]
    assert entry.provider == "sonar"
    assert entry.domains == ("bbc.co.uk",)
