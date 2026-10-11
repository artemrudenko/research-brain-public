"""
tavily.py — query the Tavily search API (stdlib urllib only, no SDK).

Tavily is an LLM-oriented search API: a single JSON POST to /search returns a
list of result objects. We normalize each to `{title, url, snippet}` so the
dispatcher can stay provider-agnostic. Any error (network, HTTP, bad JSON, no
key) is swallowed and reported as an empty list + a printed message — the caller
never sees an exception, mirroring the soft-skip discipline of the delivery
adapters (CONVENTIONS §3/§10).
"""

import json
import urllib.error
import urllib.request

# Tavily search endpoint (JSON POST).
TAVILY_API_URL = "https://api.tavily.com/search"

# Network timeout (seconds) for the search call.
_TIMEOUT = 30


def _post_search(api_key: str, query: str, max_results: int) -> dict[str, object]:
    """POST a search request to Tavily; return the parsed JSON response dict.

    Isolated so tests can monkeypatch this single function instead of urllib —
    the network call is the only thing that touches the outside world here.
    """
    payload = json.dumps(
        {"query": query, "max_results": max_results}
    ).encode("utf-8")
    request = urllib.request.Request(
        TAVILY_API_URL,
        data=payload,
        headers={
            # Carry the key in the Authorization header (mirrors perplexity.py /
            # sonar.py) — keeping it out of the JSON body, which is more easily
            # logged/cached/leaked than a header.
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    # B310: hardcoded https Tavily API endpoint, not a user file:// scheme.
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def _normalize(results: object) -> list[dict[str, str]]:
    """Map Tavily's `results` array to a list of `{title, url, snippet}` dicts.

    Tolerates missing fields (Tavily uses `content` for the snippet) and skips
    any non-dict entry so a malformed item never breaks the whole response.
    """
    normalized: list[dict[str, str]] = []
    if not isinstance(results, list):
        return normalized
    for item in results:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "snippet": str(item.get("content", "")),
            }
        )
    return normalized


def search(query: str, *, api_key: str, max_results: int = 5) -> list[dict[str, str]]:
    """Search Tavily for `query`; return normalized `{title, url, snippet}` results.

    Returns `[]` (and prints a clear, non-fatal message) on any problem — empty
    key, network/HTTP error, or unparseable response — so the dispatcher can soft
    -skip. Never raises.
    """
    if not api_key:
        print("tavily: no API key — skipping (set TAVILY_API_KEY in config/.env)")
        return []
    try:
        data = _post_search(api_key, query, max_results)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as error:
        # ValueError also covers json.JSONDecodeError (a subclass) on a bad body.
        print(f"tavily: search failed ({error}) — returning no results")
        return []
    return _normalize(data.get("results") if isinstance(data, dict) else None)
