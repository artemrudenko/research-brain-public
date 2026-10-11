"""
sonar.py — query the Perplexity Sonar chat API (stdlib urllib only, no SDK).

Unlike `perplexity.py` (the RAW `/search` endpoint used for corroboration, which
returns independent primary sources to count distinct domains), this hits the
`/chat/completions` Sonar endpoint and returns a *synthesized answer + the
citations it used*. That synthesis is deliberately NOT fed into research-build's
own synthesis — it is an independent second opinion consumed only as an
adversarial input in Phase 6.5 Critique (CONVENTIONS §15a). Keeping it out of the
synthesis path is what preserves the project's trust model: instruction-stripping,
verbatim-raw, and claim traceability all stay intact.

Any error (network, HTTP, bad JSON, no key) is swallowed and reported as an empty
`{answer:"", citations:[]}` + a printed message — the caller never sees an
exception, mirroring the soft-skip discipline of the other adapters
(CONVENTIONS §3/§10).
"""

import json
import urllib.error
import urllib.request

# Perplexity chat/completions endpoint (JSON POST, Bearer auth).
PERPLEXITY_CHAT_URL = "https://api.perplexity.ai/chat/completions"

# Network timeout (seconds) for the cross-check call. Sonar reasoning models can
# run longer than a raw search, so this is more generous than the search adapters.
_TIMEOUT = 60


def _post_chat(
    api_key: str, question: str, model: str, max_tokens: int
) -> dict[str, object]:
    """POST a chat request to Sonar; return the parsed JSON response dict.

    Isolated so tests can monkeypatch this single function instead of urllib —
    the network call is the only thing that touches the outside world here.
    """
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": question}],
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        PERPLEXITY_CHAT_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    # B310: hardcoded https Perplexity Sonar API endpoint, not a user file:// scheme.
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def _first_choice(data: dict[str, object]) -> dict[str, object]:
    """Return the first `choices` entry, or an empty dict if absent/malformed."""
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0]
    return {}


def _extract_answer(data: dict[str, object]) -> str:
    """Pull the assistant message text out of the chat-completions response.

    Tolerates a missing/empty `choices` array (returns "") so a partial payload
    never raises — the caller treats an empty answer as "no cross-check".
    """
    message = _first_choice(data).get("message")
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return ""


def _extract_citations(data: dict[str, object]) -> list[dict[str, str]]:
    """Return the cited sources as `{title, url}` dicts.

    Prefers `search_results` (newer API — carries titles); falls back to the
    older `citations` array of bare URLs (title left empty). Non-dict entries in
    `search_results` are skipped so one malformed item never breaks the list.
    """
    results = data.get("search_results")
    citations: list[dict[str, str]] = []
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            citations.append(
                {"title": str(item.get("title", "")), "url": str(item.get("url", ""))}
            )
    if citations:
        return citations
    # Fallback: a plain list of URL strings under `citations`.
    raw = data.get("citations")
    if isinstance(raw, list):
        for url in raw:
            citations.append({"title": "", "url": str(url)})
    return citations


def search(
    question: str,
    *,
    api_key: str,
    model: str = "sonar",
    max_tokens: int = 1024,
) -> dict[str, object]:
    """Ask Sonar `question`; return `{answer, citations}` for a Phase 6.5 cross-check.

    Returns `{answer:"", citations:[]}` (and prints a clear, non-fatal message) on
    any problem — empty key, network/HTTP error, or unparseable response — so the
    caller can soft-skip. Never raises.

    Default model is plain `sonar`: the cross-check consumes only answer+citations
    and discards reasoning, so the cheaper non-reasoning tier is the right fit. If a
    caller selects a reasoning model (sonar-reasoning-pro), it spends most of the
    budget on hidden reasoning — too small a `max_tokens` then yields
    finish_reason="length" with an EMPTY answer, surfaced as a hint below.
    """
    empty: dict[str, object] = {"answer": "", "citations": []}
    if not api_key:
        print("sonar: no API key — skipping (set PERPLEXITY_API_KEY in config/.env)")
        return empty
    try:
        data = _post_chat(api_key, question, model, max_tokens)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as error:
        # ValueError also covers json.JSONDecodeError (a subclass) on a bad body.
        print(f"sonar: cross-check failed ({error}) — returning no result")
        return empty
    if not isinstance(data, dict):
        return empty
    answer = _extract_answer(data)
    # A reasoning model that exhausts its budget mid-thought returns an empty answer
    # with finish_reason="length" — tell the user to raise max_tokens rather than
    # leaving them to puzzle over a silent "(no cross-check)".
    if not answer and _first_choice(data).get("finish_reason") == "length":
        print(
            f"sonar: answer truncated to empty (finish_reason=length, max_tokens={max_tokens}) "
            "— raise research.cross_check.sonar.max_tokens for reasoning models"
        )
    return {"answer": answer, "citations": _extract_citations(data)}
