"""
perplexity.py — query the Perplexity Search API (stdlib urllib only, no SDK).

This is the RAW-RESULTS Search API (`/search`), not the Sonar chat/answer API:
for corroboration (CONVENTIONS §16) we want independent primary sources to count
distinct registrable domains, NOT another model's synthesized answer. A single
JSON POST returns a list of result objects; we normalize each to
`{title, url, snippet}` so the dispatcher stays provider-agnostic.

Any error (network, HTTP, bad JSON, no key) is swallowed and reported as an empty
list + a printed message — the caller never sees an exception, mirroring the
soft-skip discipline of the Tavily adapter and the delivery adapters
(CONVENTIONS §3/§10).
"""

import json
import urllib.error
import urllib.request

# Perplexity Search API endpoint (JSON POST, Bearer auth).
PERPLEXITY_API_URL = "https://api.perplexity.ai/search"

# Network timeout (seconds) for the search call.
_TIMEOUT = 30


def _post_search(api_key: str, query: str, max_results: int) -> dict[str, object]:
    """POST a search request to Perplexity; return the parsed JSON response dict.

    Isolated so tests can monkeypatch this single function instead of urllib —
    the network call is the only thing that touches the outside world here.
    """
    payload = json.dumps({"query": query, "max_results": max_results}).encode("utf-8")
    request = urllib.request.Request(
        PERPLEXITY_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    # B310: hardcoded https Perplexity API endpoint, not a user file:// scheme.
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def _normalize(results: object) -> list[dict[str, str]]:
    """Map Perplexity's `results` array to a list of `{title, url, snippet}` dicts.

    Tolerates the snippet field arriving under any of `snippet` / `content` /
    `text` (the API has used different keys across versions) and skips any
    non-dict entry so a malformed item never breaks the whole response.
    """
    normalized: list[dict[str, str]] = []
    if not isinstance(results, list):
        return normalized
    for item in results:
        if not isinstance(item, dict):
            continue
        snippet = item.get("snippet") or item.get("content") or item.get("text") or ""
        normalized.append(
            {
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "snippet": str(snippet),
            }
        )
    return normalized


def search(query: str, *, api_key: str, max_results: int = 5) -> list[dict[str, str]]:
    """Search Perplexity for `query`; return normalized `{title, url, snippet}`.

    Returns `[]` (and prints a clear, non-fatal message) on any problem — empty
    key, network/HTTP error, or unparseable response — so the dispatcher can soft
    -skip. Never raises.
    """
    if not api_key:
        print("perplexity: no API key — skipping (set PERPLEXITY_API_KEY in config/.env)")
        return []
    try:
        data = _post_search(api_key, query, max_results)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as error:
        # ValueError also covers json.JSONDecodeError (a subclass) on a bad body.
        print(f"perplexity: search failed ({error}) — returning no results")
        return []
    return _normalize(data.get("results") if isinstance(data, dict) else None)
