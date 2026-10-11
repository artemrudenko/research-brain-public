#!/usr/bin/env python3
"""
normalize_url.py — canonical URL key for registry dedup (CONVENTIONS §9, R8).

Two links that point at the same article should collapse to one dedup key, so
that http/https, www/m, trailing-slash and tracking-query variants are all
recognised as the same source and not collected twice.

Canonicalisation rules (all applied):
  - scheme  → forced to `https` for comparison (http and https dedup together)
  - host    → lowercased; leading `www.` / `m.` stripped; `user:pass@` userinfo
              dropped; default port (80/443) dropped but any non-default port
              kept; an IPv6 literal stays bracketed (`[2001:db8::1]`)
  - path    → trailing slash dropped (but the root path `/` is preserved)
  - query   → known tracking params (utm_*, fbclid, ...) dropped; the remaining
              meaningful params are kept and re-serialized in sorted order, so a
              key stays canonical while distinct articles (e.g. YouTube `?v=AAA`
              vs `?v=BBB`, WordPress `?p=123`) keep distinct keys
  - fragment→ dropped (`#section`)

Usage (CLI):
    python3 scripts/normalize_url.py <url>          # prints the dedup key
    from scripts.normalize_url import normalize     # programmatic use
"""
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit, urlunsplit

# Host prefixes that point at the same site and should be folded away.
_STRIP_HOST_PREFIXES = ("www.", "m.")

# The scheme-default port for the normalized (https-forced) URL. Any explicit
# port equal to this is the default and is dropped; any other port is kept.
# `http`'s default 80 also collapses here because http is forced to https first.
_DEFAULT_PORTS = frozenset({80, 443})

# Query params that only track the visitor, never identify the content. Dropping
# them lets the same article reached via different campaigns dedup together, while
# any other param (e.g. `v`, `p`, `id`, `page`) is content-bearing and kept.
_TRACKING_PARAMS = frozenset(
    {"utm", "fbclid", "gclid", "mc_eid", "igshid", "ref", "mc_cid", "msclkid"}
)


def _canonical_query(query: str) -> str:
    """Drop tracking params, then re-serialize the rest in sorted order.

    Sorting makes param order insignificant (`?a=1&b=2` and `?b=2&a=1` collapse),
    and the tracking filter (utm_* prefix + the known set) folds campaign variants
    of one article together without losing the params that identify the content.
    """
    kept = [
        (key, value)
        for key, value in parse_qsl(query, keep_blank_values=True)
        if not (key.lower().startswith("utm_") or key.lower() in _TRACKING_PARAMS)
    ]
    return urlencode(sorted(kept))


def _canonical_netloc(parts: SplitResult) -> str:
    """Build the canonical netloc: lowercased host (prefixes stripped), an IPv6
    literal re-bracketed, plus an explicit non-default port.

    ``parts.hostname`` is used because it already drops any ``user:pass@``
    userinfo and the ``[...]`` brackets around an IPv6 literal — we re-add the
    brackets ourselves so the result round-trips, and we read ``parts.port``
    separately to keep a non-default port that ``hostname`` would otherwise lose.
    """
    host = (parts.hostname or "").lower()

    # An IPv6 literal contains colons; the www./m. prefix strip applies only to
    # ordinary dotted hostnames and must never touch the address itself.
    is_ipv6 = ":" in host
    if not is_ipv6:
        for prefix in _STRIP_HOST_PREFIXES:
            if host.startswith(prefix):
                host = host[len(prefix):]
                break

    # Re-bracket the IPv6 literal that `hostname` unwrapped.
    netloc = f"[{host}]" if is_ipv6 else host

    # Keep only a non-default port (`parts.port` raises on malformed input, but
    # urlsplit has already accepted the netloc by this point).
    if parts.port is not None and parts.port not in _DEFAULT_PORTS:
        netloc = f"{netloc}:{parts.port}"

    return netloc


def normalize(url: str) -> str:
    """Return a canonical dedup key for ``url``.

    The key is a normalised URL string; two URLs that address the same article
    (differing only in scheme, www/m prefix, trailing slash, fragment or query)
    produce the same key. See module docstring for the exact rules.
    """
    raw = url.strip()
    parts = urlsplit(raw)

    # A non-http(s) scheme (mailto:, ftp:, tel:, ...) isn't a collectable article;
    # leave it untouched rather than mangling it into `https://mailto:...`.
    if parts.scheme and parts.scheme not in ("http", "https"):
        return raw

    # If the URL had no scheme, urlsplit puts the host in `path`. Re-parse with a
    # scheme so host/path are separated correctly.
    if not parts.netloc and parts.path:
        parts = urlsplit("https://" + raw)

    # Netloc: lowercased host with www./m. stripped and userinfo dropped; an IPv6
    # literal stays bracketed; a non-default port is kept (default 80/443 dropped).
    netloc = _canonical_netloc(parts)

    # Path: drop a trailing slash, but keep the bare root path as "".
    path = parts.path.rstrip("/")

    # Scheme forced to https; tracking query params dropped (the rest kept,
    # sorted); fragment dropped.
    return urlunsplit(("https", netloc, path, _canonical_query(parts.query), ""))


def normalize_or_raw(url: str) -> str:
    """`normalize(url)` that never raises — the comparison key for status/identity
    lookups fed a stored or frontmatter URL.

    Two URLs that address the same article produce the same key (see `normalize`).
    An empty/whitespace URL yields ""; a malformed URL `normalize` can't parse (e.g.
    an out-of-range port or bad IPv6 literal) degrades to the stripped raw string,
    so a caller gets one stable key without repeating a try/except at every site.
    """
    cleaned = (url or "").strip()
    if not cleaned:
        return ""
    try:
        return normalize(cleaned)
    except ValueError:
        return cleaned


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("usage: normalize_url.py <url>", file=sys.stderr)
        raise SystemExit(2)
    print(normalize(sys.argv[1]))
