#!/usr/bin/env python3
"""
corroborate.py — deterministic publisher-diversity signal (CONVENTIONS §16).

Count publisher domains in concept source records, with optional lexical
near-duplicate collapse. Neither different domains nor dissimilar texts prove
independent reporting or verify a claim against its sources.

The historical function/key names `independent_sources` and `independent` are
retained for API compatibility; their values are publisher-count proxies only.
The count is derived from `sources:` and never stored as an auxiliary counter.

API:
  - registrable_domain(url) -> approximate publisher domain
  - independent_sources(sources, *, texts=None) -> retained publisher count
  - corroboration(sources) -> {"independent": N, "level": "multi"|"single"|"none", ...}
  - trust_line(corr) -> publisher-diversity line (empty when 0)

Stdlib only. No network, no embeddings.
"""
from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlsplit

# Direct-run bootstrap: when invoked as `python scripts/corroborate.py` the
# package root isn't on sys.path, so the `scripts.*` imports below would fail.
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.dedup import find_duplicates

# A pragmatic, deliberately small multi-part public-suffix list (NOT the full
# PSL — KISS, CONVENTIONS §16). These are the common second-level suffixes where
# the registrable domain is the *third* label from the right (e.g. `co.uk`).
# Extend only when a real suffix shows up in the corpus.
_MULTI_PART_SUFFIXES = frozenset(
    {
        "co.uk", "org.uk", "gov.uk", "ac.uk", "me.uk", "ltd.uk", "plc.uk", "net.uk",
        "com.au", "net.au", "org.au", "gov.au", "edu.au",
        "co.nz", "org.nz", "govt.nz",
        "co.jp", "or.jp", "ne.jp", "go.jp", "ac.jp",
        "co.in", "net.in", "org.in", "gov.in",
        "co.za", "org.za", "gov.za",
        "com.br", "gov.br", "org.br",
        "com.cn", "gov.cn", "org.cn", "net.cn",
        "com.sg", "edu.sg", "gov.sg",
        "co.kr", "or.kr", "go.kr",
        "com.mx", "gob.mx", "org.mx",
        "co.il", "org.il", "ac.il",
        "com.tr", "gov.tr", "com.tw", "com.ua", "com.ar", "co.id", "co.th",
    }
)

# Shared-hosting platforms where each subdomain is a *distinct* publisher, so the
# registrable unit is the subdomain (e.g. two different `*.substack.com` authors
# are two publisher identities, not one). This grouping does not assess their
# editorial or evidentiary independence.
_PLATFORM_SUFFIXES = frozenset(
    {
        "substack.com", "medium.com", "wordpress.com", "blogspot.com",
        "tumblr.com", "github.io", "gitlab.io", "gitbook.io", "notion.site",
    }
)


def _is_ipv4(host: str) -> bool:
    """True when `host` is a dotted-quad IPv4 literal (each octet 0–255)."""
    parts = host.split(".")
    if len(parts) != 4:
        return False
    return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)

# A plausible hostname: dot-separated labels of letters/digits/hyphens, with at
# least one dot. Rejects junk like "not a url" so it yields "" rather than a
# bogus domain.
_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


class Corroboration(TypedDict):
    """Result of :func:`corroboration`."""

    independent: int
    level: str  # "multi" (>=2 retained publisher groups) | "single" (1) | "none" (0)
    collapsed: bool  # Historical flag: a text map was supplied, not verified provenance


def registrable_domain(url: str) -> str:
    """Extract the registrable domain (eTLD+1) from ``url``.

    Lowercases the host, drops any port, and folds a leading ``www.`` away
    implicitly by taking the registrable boundary. Multi-part public suffixes
    (``co.uk`` etc., see :data:`_MULTI_PART_SUFFIXES`) keep three labels; all
    other hosts keep the last two. A bare host without a scheme is tolerated.
    Returns ``""`` when no host can be determined.
    """
    # urlsplit needs a scheme to populate netloc; add one for bare hosts.
    candidate = url.strip()
    if "//" not in candidate:
        candidate = "//" + candidate
    host = urlsplit(candidate).hostname or ""
    host = host.lower().strip(".")
    if not host or not _HOST_RE.match(host):
        return ""

    # An IPv4 literal is its own registrable identity — never truncate it to the
    # last two octets (which would collapse unrelated hosts to e.g. "0.1").
    if _is_ipv4(host):
        return host

    labels = host.split(".")
    if len(labels) <= 2:
        return host  # already eTLD+1 (e.g. "nytimes.com")

    # Shared-hosting platform: keep one label ABOVE the platform suffix so each
    # subdomain stays a distinct publisher (e.g. "a.substack.com" -> itself).
    for suffix in _PLATFORM_SUFFIXES:
        if host == suffix:
            return host
        if host.endswith("." + suffix):
            keep = suffix.count(".") + 2  # suffix labels + the publisher label
            return ".".join(labels[-keep:])

    last_two = ".".join(labels[-2:])
    if last_two in _MULTI_PART_SUFFIXES:
        # e.g. "www.bbc.co.uk" -> registrable boundary is the last THREE labels.
        return ".".join(labels[-3:])
    # Default: registrable domain is the last two labels ("www.nytimes.com" ->
    # "nytimes.com"), which collapses any subdomain (www, blog, ...).
    return last_two


def _source_url(entry: object) -> str:
    """Pull a URL string out of one `sources:` entry (a dict) or a bare string."""
    if isinstance(entry, dict):
        value = entry.get("url", "")
        return value if isinstance(value, str) else ""
    if isinstance(entry, str):
        return entry
    return ""


def independent_sources(
    sources: list[dict], *, texts: dict[str, str] | None = None
) -> int:
    """Count publisher groups in source URLs, optionally collapsing similar texts.

    Without `texts`, this is a distinct-domain count. With `texts`, lexical
    near-duplicates are grouped first; missing bodies retain their domain identity.
    Neither path determines whether sources share an upstream claim or whether
    a passage supports it. The function name is historical, not an independence
    guarantee. Empty/unparseable URLs are ignored.
    """
    # Map each source to (url, registrable_domain), skipping ones without a host.
    domains: list[str] = []
    urls: list[str] = []
    for entry in sources:
        url = _source_url(entry)
        domain = registrable_domain(url)
        if domain:
            domains.append(domain)
            urls.append(url)

    if not domains:
        return 0

    if texts is None:
        # No text bodies: count distinct publisher domains only.
        return len(set(domains))

    # With texts: collapse near-duplicate stories first. A cluster of near-dupes
    # spanning several domains contributes one retained publisher group.
    # Sources missing a text body are treated as their own (non-dup) text so
    # they always retain their own domain identity.
    bodies = [texts.get(url, url) for url in urls]
    clusters = find_duplicates(bodies)

    clustered_indices: set[int] = set()
    independent_domains: set[str] = set()
    for cluster in clusters:
        clustered_indices.update(cluster)
        # One representative domain per near-duplicate cluster.
        independent_domains.add(domains[cluster[0]])
    # Every source NOT folded into a cluster keeps its own domain.
    for index, domain in enumerate(domains):
        if index not in clustered_indices:
            independent_domains.add(domain)
    return len(independent_domains)


def corroboration(
    sources: list[dict], *, texts: dict[str, str] | None = None
) -> Corroboration:
    """Derive the corroboration level from a concept's `sources:` (CONVENTIONS §16).

    ``multi`` = >=2 publisher groups, ``single`` = 1, ``none`` = 0.
    The legacy `independent` key is not a verified-independence count.
    """
    count = independent_sources(sources, texts=texts)
    if count >= 2:
        level = "multi"
    elif count == 1:
        level = "single"
    else:
        level = "none"
    # Historical flag: a text map was supplied. It is not a coverage,
    # provenance-independence or factual-verification verdict.
    return {"independent": count, "level": level, "collapsed": texts is not None}


def trust_line(corr: Corroboration, *, language: str = "en") -> str:
    """Render publisher diversity without implying claim verification.

    Both multi-source paths get the same bounded wording: text deduplication
    does not justify a green confirmation badge. Language localizes digest
    chrome; unsupported languages fall back to English.
    """
    from scripts.digest import strings as _strings

    ru = _strings.resolve(language) == "ru"
    level = corr.get("level")
    if level == "multi":
        n = corr["independent"]
        if ru:
            noun = _strings.plural_ru(int(n), "домен", "домена", "доменов")
            return f"🔵 Учтено {n} {noun} издателей — проверьте утверждение"
        return f"🔵 {n} retained publisher domains — check the claim"
    if level == "single":
        return _strings.tr(language, "trust_single")
    return ""


def corroborate_with_search(
    query: str,
    sources: list[dict],
    *,
    search_fn: Callable[[str], list[dict]] | None = None,
    max_new: int = 5,
) -> tuple[Corroboration, list[dict]]:
    """Find additional publisher-domain candidates; do not verify their claims.

    This is the live wiring between the §15 search subsystem and §16
    corroboration. The base corroboration is computed from `sources`; when a real
    search provider is configured (`config/search.yaml`), `search_fn(query)`
    results whose registrable domain is NOT already present in `sources` are added
    as new publisher candidates and the corroboration is recomputed over the
    union. The result is never collapsed (no body texts), so it tops out at
    a publisher-diversity line. Search results are not supporting evidence until reviewed.

    Soft-skip by design (mirrors `scripts/delivery/deliver.py`): a sentinel
    `claude-websearch` note, an empty result, or a search error leaves the base
    corroboration unchanged and returns no discoveries — this function never
    raises. Returns `(corroboration, discovered)` where `discovered` is the list
    of new `{"url", "title"}` sources, ready to fold into a concept's `sources:`
    after review.
    """
    base = corroboration(sources)
    if search_fn is None:
        # Lazy import so corroborate.py stays usable without the search package.
        from scripts.search.search import web_search

        search_fn = web_search

    try:
        results = search_fn(query)
    except Exception as error:  # noqa: BLE001 — a search failure must not break corroboration
        # Any provider/transport failure → soft-skip with the base verdict, but leave
        # a stderr breadcrumb (mirrors the soft-skip logging in deliver.py/health.py)
        # so a silently-degraded enrichment is diagnosable. Best-effort: never raises.
        print(f"corroborate: search enrichment skipped — {error}", file=sys.stderr)
        return base, []

    existing = {
        registrable_domain(_source_url(s)) for s in sources
    } - {""}
    discovered: list[dict] = []
    seen_new: set[str] = set()
    for hit in results or []:
        # Skip the claude-websearch sentinel note (kind == "note") and any hit
        # without a usable URL.
        if hit.get("kind") == "note":
            continue
        url = str(hit.get("url", "")).strip()
        domain = registrable_domain(url)
        if not domain or domain in existing or domain in seen_new:
            continue
        seen_new.add(domain)
        discovered.append({"url": url, "title": str(hit.get("title", "")).strip()})
        if len(discovered) >= max_new:
            break

    if not discovered:
        return base, []

    enriched = corroboration(sources + discovered)
    return enriched, discovered


def _main(argv: list[str] | None = None) -> int:
    """CLI: search for corroborating sources of a claim and print the trust line.

    Usage: python3 scripts/corroborate.py enrich "<claim>" [--source URL ...]
    Uses the configured provider (`config/search.yaml`); soft-skips when search is
    disabled or unconfigured (the base, sources-only verdict is printed).
    """
    import argparse

    parser = argparse.ArgumentParser(description="Search-enriched corroboration (§15/§16).")
    parser.add_argument("command", choices=["enrich"], help="the only action")
    parser.add_argument("query", help="the claim/title to corroborate")
    parser.add_argument(
        "--source", action="append", default=[], metavar="URL",
        help="an existing source URL (repeatable)",
    )
    args = parser.parse_args(argv)

    sources = [{"url": url} for url in args.source]
    corr, discovered = corroborate_with_search(args.query, sources)
    print(trust_line(corr) or "(no sources)")
    if discovered:
        print(f"discovered {len(discovered)} new publisher-domain candidate(s):")
        for d in discovered:
            print(f"  - {d['url']}  {d['title']}".rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
