#!/usr/bin/env python3
"""
search.py — config-gated web-search dispatcher (CONVENTIONS §15).

Reads `config/search.yaml` and routes `web_search(query)` to the configured
provider:

    claude-websearch  -> in-agent default. A headless caller cannot invoke the
                         agent's WebSearch tool, so this returns a single
                         sentinel result noting "use the in-agent WebSearch tool".
    tavily            -> calls scripts.search.tavily with the key named by
                         tavily.api_key_env (resolved from the environment /
                         config/.env). Missing key -> soft-skip (empty + message).
    none / unknown    -> soft-skip (empty + message).

Soft-skip discipline (mirrors scripts/delivery/deliver.py, CONVENTIONS §8/§10):
nothing here ever raises on a missing key or missing config — it returns an empty
list and prints a clear, non-fatal message. Secrets come only from env (*_env).

CLI:
    python3 scripts/search/search.py "<query>"
"""

import os
import sys
from pathlib import Path
from typing import Any

# Sentinel kind for a claude-websearch result so a headless caller can detect
# "this is a note, not a real hit" without string-matching the message.
CLAUDE_WEBSEARCH_KIND = "note"

# Message returned for the in-agent default when called headlessly.
CLAUDE_WEBSEARCH_NOTE = "use the in-agent WebSearch tool (headless can't call Claude WebSearch)"

# Resolve config relative to the project root (scripts/search/ -> root).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEARCH_CONFIG = _PROJECT_ROOT / "config" / "search.yaml"
# `.env` is resolved against the project root regardless of cwd (CONVENTIONS §8).
DEFAULT_ENV_FILE = _PROJECT_ROOT / "config" / ".env"

if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(_PROJECT_ROOT))

# Reuse deliver.py's stdlib .env loader so headless search and headless delivery
# resolve secrets identically (no second dotenv parser to drift, CONVENTIONS §8).
# A divergent local fallback once lived here and did NOT strip surrounding quotes,
# so a quoted key in .env (`KEY="pplx..."`) reached the API verbatim -> 401. Always
# the CANONICAL quote-stripping loader (the prelude above covers direct runs).
from scripts.delivery.deliver import load_dotenv  # noqa: E402 — after the direct-run prelude
from scripts.search import (  # noqa: E402 — after the direct-run prelude
    perplexity,
    search_trail,
    tavily,
)


def _optional_yaml() -> Any | None:  # Any: optional-dependency boundary (PyYAML)
    """Import PyYAML lazily; return None when it is absent (no raise).

    Search is always optional and the headless `python3` runtime has no PyYAML,
    so a missing dependency must soft-skip — not crash the documented headless
    dispatcher (`python3 scripts/search/search.py "<query>"`, BUG 4).
    """
    try:
        import yaml  # noqa: PLC0415 — lazy import is intentional (optional dep)
    except ImportError:
        return None
    return yaml


def _safe_load_yaml(path: Path) -> dict[str, object]:
    """Parse a config YAML file, soft-skipping on absence/missing-dep/malformed.

    Returns the parsed top-level mapping, or `{}` for any of: the file is absent,
    PyYAML is unavailable, the file is not a mapping, OR the YAML is malformed.
    A malformed file is CAUGHT here (clear printed message naming the file) rather
    than surfacing a raw yaml.YAMLError traceback — config (search/research) is
    always optional, so a typo'd config degrades to the documented soft-skip
    instead of crashing the dispatcher. Mirrors validate_config._check_yaml_mapping.
    """
    if not path.exists():
        return {}
    yaml = _optional_yaml()
    if yaml is None:
        # Headless without PyYAML: degrade to the documented soft-skip.
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        # Malformed config: caught, not raised — print an actionable note and
        # soft-skip so the dispatcher falls back to its defaults.
        print(f"config: {path.name} has a YAML parse error: {exc} — soft-skip")
        return {}
    return raw if isinstance(raw, dict) else {}


def load_config(path: Path = DEFAULT_SEARCH_CONFIG) -> dict[str, object]:
    """Load and return the `search` mapping from search.yaml.

    A missing file, missing `search:` block, OR an unavailable PyYAML all yield
    an empty dict so the dispatcher can soft-skip rather than fail — search is
    always optional (the in-agent WebSearch tool is the default path). An empty
    config makes the dispatcher fall back to the `claude-websearch` provider.
    """
    section = _safe_load_yaml(path).get("search")
    return section if isinstance(section, dict) else {}


def web_search(
    query: str, config_path: Path = DEFAULT_SEARCH_CONFIG
) -> list[dict[str, str]]:
    """Dispatch `query` to the configured provider; return `{title,url,snippet}` list.

    Never raises on a missing key/config: returns `[]` (with a printed note) so a
    caller can soft-skip. `claude-websearch` returns one sentinel note result
    (kind="note") telling a headless caller to use the in-agent WebSearch tool.
    """
    config = load_config(config_path)
    provider = str(config.get("provider", "claude-websearch"))

    if provider == "claude-websearch":
        # In-agent default: a headless process can't call Claude's WebSearch.
        return [{"kind": CLAUDE_WEBSEARCH_KIND, "note": CLAUDE_WEBSEARCH_NOTE}]

    if provider == "tavily":
        return _keyed_search(config, query, "tavily", tavily, "TAVILY_API_KEY")

    if provider == "perplexity":
        return _keyed_search(config, query, "perplexity", perplexity, "PERPLEXITY_API_KEY")

    # `none` or any unrecognized value: no web search.
    print(f"search: provider '{provider}' — no web search (soft-skip)")
    return []


def _keyed_search(
    config: dict[str, object],
    query: str,
    provider: str,
    adapter: Any,  # Any: optional search-provider module boundary (tavily/perplexity)
    default_env: str,
) -> list[dict[str, str]]:
    """Run a key-authenticated provider (tavily / perplexity); soft-skip on no key.

    Both keyed providers share the same shape: a `{api_key_env, max_results}`
    sub-block, a Bearer/key secret resolved from `config/.env`, and an adapter
    `search(query, *, api_key, max_results)`. Factored out so the two branches
    can't drift (DRY).
    """
    # Pass DEFAULT_ENV_FILE explicitly so the module's configured env path (and a
    # test's monkeypatch of it) is honored, rather than the loader's own default.
    load_dotenv(DEFAULT_ENV_FILE)  # pull config/.env into the environment (CONVENTIONS §8)
    sub = config.get(provider)
    sub = sub if isinstance(sub, dict) else {}
    api_key_env = str(sub.get("api_key_env", default_env))
    # A non-numeric / non-positive max_results is a config typo, not a reason
    # to crash: fall back to the default and clamp to ≥1.
    try:
        max_results = max(1, int(sub.get("max_results", 5)))
    except (TypeError, ValueError):
        max_results = 5
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        print(
            f"search: provider {provider} but {api_key_env} is not set — "
            "soft-skip (set it in config/.env; see config/.env.example)"
        )
        return []
    results = adapter.search(query, api_key=api_key, max_results=max_results)
    _record_trail(query, provider, results)
    return results


def _record_trail(query: str, provider: str, results: list[dict[str, str]]) -> None:
    """Best-effort: append this search to the trail when a target is configured.

    OFF by default — `resolve_trail_target` returns None unless `RESEARCH_TRAIL_DIR`
    is set, so unit tests and the headless cron path write nothing. The append is
    itself soft-skip (never raises), so a trail hiccup can't abort the search
    (CONVENTIONS §15b). The default `claude-websearch` provider never reaches here:
    its sentinel is returned earlier and its real results belong to the agent's own
    WebSearch tool (recorded via the research skills, not this script).
    """
    target = search_trail.resolve_trail_target(search_trail.slug_for_query(query))
    if target is None:
        return
    search_trail.append_search_entry(
        target,
        query=query,
        provider=provider,
        n_results=len(results),
        urls=[r.get("url", "") for r in results],
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry: `search.py "<query>"`. Prints results; always exits 0 (soft)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print('usage: search.py "<query>"', file=sys.stderr)
        return 2
    query = args[0]
    results = web_search(query)
    if not results:
        print("(no results)")
        return 0
    for item in results:
        if item.get("kind") == CLAUDE_WEBSEARCH_KIND:
            print(f"note: {item.get('note', '')}")
        else:
            print(f"- {item.get('title', '')} — {item.get('url', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
