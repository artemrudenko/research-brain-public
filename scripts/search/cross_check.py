#!/usr/bin/env python3
"""
cross_check.py — config-gated Sonar cross-check dispatcher (CONVENTIONS §15a).

Reads `config/research.yaml` and, when enabled with a key present, asks the
Perplexity Sonar chat API the research question to produce an INDEPENDENT second
synthesis + its citations. research-build consumes this only as an adversarial
input in Phase 6.5 Critique — never as a synthesis input — so the collection
pipeline (instruction-stripping, verbatim-raw, dedup, claim traceability) is
unchanged whether the cross-check runs or not.

Gating is "if the key is set we run it, otherwise the pipeline runs exactly as
before": the provider defaults to `sonar`, so merely setting PERPLEXITY_API_KEY
activates the cross-check; a missing key (or `provider: none`) soft-skips to an
empty `{answer:"", citations:[]}` with a printed note — never a raise.

Secrets are NOT stored here — only the NAME of the env var (api_key_env).

CLI:
    python3 scripts/search/cross_check.py "<research question>"
"""

import os
import sys
from pathlib import Path

# Resolve config relative to the project root (scripts/search/ -> root).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESEARCH_CONFIG = _PROJECT_ROOT / "config" / "research.yaml"
# `.env` is resolved against the project root regardless of cwd (CONVENTIONS §8).
DEFAULT_ENV_FILE = _PROJECT_ROOT / "config" / ".env"

# Reuse search.py's .env / yaml helpers — no second dotenv/yaml parser to drift.
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.search import search_trail, sonar  # noqa: E402 — after the direct-run prelude
from scripts.search.search import (  # noqa: E402 — after the direct-run prelude
    _safe_load_yaml,
    load_dotenv,
)

# Empty cross-check result (the soft-skip return value, reused everywhere).
EMPTY_RESULT: dict[str, object] = {"answer": "", "citations": []}


def load_config(path: Path = DEFAULT_RESEARCH_CONFIG) -> dict[str, object]:
    """Load and return the `research` mapping from research.yaml.

    A missing file, missing `research:` block, an unavailable PyYAML, OR a
    malformed YAML file all yield an empty dict so the dispatcher falls back to
    its defaults (provider `sonar`, key-gated) rather than failing — the
    cross-check is always optional. Malformed YAML is caught in `_safe_load_yaml`
    (clear message, no raw traceback).
    """
    section = _safe_load_yaml(path).get("research")
    return section if isinstance(section, dict) else {}


def cross_check(
    question: str, config_path: Path = DEFAULT_RESEARCH_CONFIG
) -> dict[str, object]:
    """Run the configured cross-check provider; return `{answer, citations}`.

    Never raises: returns `EMPTY_RESULT` (with a printed note) when the provider
    is `none`, unknown, or its key is unset — so a caller can soft-skip and run
    the pipeline exactly as before.
    """
    config = load_config(config_path)
    settings = config.get("cross_check")
    settings = settings if isinstance(settings, dict) else {}
    provider = str(settings.get("provider", "sonar"))

    if provider == "sonar":
        return _run_sonar(question, settings)

    # `none` or any unrecognized value: no cross-check.
    print(f"cross-check: provider '{provider}' — no cross-check (soft-skip)")
    return dict(EMPTY_RESULT)


def _run_sonar(question: str, settings: dict[str, object]) -> dict[str, object]:
    """Resolve the Sonar key/model from config + env and call the adapter.

    Soft-skips (empty result) when the key named by `api_key_env` is not set.
    A non-numeric `max_tokens` is a config typo, not a reason to crash: it falls
    back to the default and clamps to ≥1.
    """
    # Pass DEFAULT_ENV_FILE explicitly so the module's configured env path (and a
    # test's monkeypatch of it) is honored, rather than the loader's own default.
    load_dotenv(DEFAULT_ENV_FILE)  # pull config/.env into the environment (CONVENTIONS §8)
    sub = settings.get("sonar")
    sub = sub if isinstance(sub, dict) else {}
    api_key_env = str(sub.get("api_key_env", "PERPLEXITY_API_KEY"))
    model = str(sub.get("model", "sonar"))
    try:
        max_tokens = max(1, int(sub.get("max_tokens", 1024)))
    except (TypeError, ValueError):
        max_tokens = 1024
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        print(
            f"cross-check: provider sonar but {api_key_env} is not set — "
            "soft-skip (set it in config/.env; see config/.env.example)"
        )
        return dict(EMPTY_RESULT)
    result = sonar.search(question, api_key=api_key, model=model, max_tokens=max_tokens)
    _record_trail(question, result)
    return result


def _record_trail(question: str, result: dict[str, object]) -> None:
    """Best-effort: append this cross-check to the trail when a target is configured.

    OFF by default (`resolve_trail_target` returns None unless `RESEARCH_TRAIL_DIR`
    is set). The provider is recorded as `sonar`, the result count is the number of
    citations, and the domains come from those citations' URLs. The append is itself
    soft-skip, so a trail hiccup can't abort the cross-check (CONVENTIONS §15b).
    """
    target = search_trail.resolve_trail_target(search_trail.slug_for_query(question))
    if target is None:
        return
    citations = result.get("citations")
    citations = citations if isinstance(citations, list) else []
    urls = [c.get("url", "") for c in citations if isinstance(c, dict)]
    search_trail.append_search_entry(
        target,
        query=question,
        provider="sonar",
        n_results=len(urls),
        urls=urls,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry: `cross_check.py "<question>"`. Prints the result; always exits 0."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print('usage: cross_check.py "<research question>"', file=sys.stderr)
        return 2
    result = cross_check(args[0])
    answer = result.get("answer", "")
    if not answer:
        print("(no cross-check)")
        return 0
    print(f"answer:\n{answer}\n")
    citations = result.get("citations", [])
    if isinstance(citations, list) and citations:
        print("citations:")
        for item in citations:
            if isinstance(item, dict):
                print(f"- {item.get('title', '')} — {item.get('url', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
