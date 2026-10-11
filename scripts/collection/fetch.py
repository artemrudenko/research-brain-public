from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from http.client import HTTPMessage
from typing import IO
from urllib.parse import urlsplit

DEFAULT_FETCH_TIMEOUT = 20.0
_USER_AGENT = "research-brain-collect/1.0 (+https://github.com/; headless RSS collector)"
MAX_FEED_BYTES = 10 * 1024 * 1024  # 10 MiB — orders of magnitude above any real feed

# --------------------------------------------------------------------------- #


def _is_disallowed_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True when an address must not be fetched (private / internal / non-routable)."""
    # An IPv4-mapped IPv6 address (::ffff:127.0.0.1) is loopback/private in v4 space,
    # but the IPv6 is_* predicates miss that — unwrap and judge the mapped v4.
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _assert_public_host(url: str) -> None:
    """Refuse a URL whose host resolves to a non-public address (SSRF guard).

    A feed is UNTRUSTED remote input. Without this guard a malicious/compromised
    feed — or a redirect it serves — could point the fetch at the cloud-metadata
    endpoint (169.254.169.254), localhost (127.0.0.1), or an RFC1918 host, exfiltrating
    internal content into `pipeline/1-incoming/`. We enumerate EVERY address the host
    resolves to — across both IPv4 and IPv6, via getaddrinfo (the same resolver
    urllib's socket uses) — and reject if ANY is private / loopback / link-local /
    reserved / multicast / unspecified. Enumerating both families matters: a
    gethostbyname (IPv4-only) check would pass a host with a public A record while the
    socket connects to a private AAAA (e.g. ::1) — a bypass with no DNS race needed.

    Residual caveat — resolve-then-connect TOCTOU (DNS rebinding): the name is
    resolved here, then urllib resolves it again when it actually connects, so a
    racing DNS flip could return a public IP to us and a private one to the socket.
    Defending that needs pinning the connection to the exact IP we vetted (a custom
    opener/connection), which is out of scope for this stdlib-only, best-effort
    collector and this threat model (a hostile feed, not a hostile resolver).
    """
    host = (urlsplit(url).hostname or "").strip()
    if not host:
        raise ValueError(f"refusing to fetch URL with no host: {url!r}")
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, ValueError) as error:
        # Unresolvable — refuse rather than hand an ambiguous host to the socket layer
        # (fail closed for an untrusted feed).
        raise ValueError(
            f"refusing to fetch {url!r}: host {host!r} did not resolve ({error})"
        ) from error
    # sockaddr[0] is the IP string for both AF_INET (ip, port) and AF_INET6
    # (ip, port, flowinfo, scope_id); strip any %scope suffix before parsing. The
    # stdlib types sockaddr[0] as str|int, so narrow to str explicitly.
    resolved: set[str] = set()
    for info in infos:
        ip = info[4][0]
        if isinstance(ip, str):
            resolved.add(ip.split("%", 1)[0])
    if not resolved:
        raise ValueError(
            f"refusing to fetch {url!r}: host {host!r} did not resolve to any address"
        )
    for raw in sorted(resolved):
        try:
            address = ipaddress.ip_address(raw)
        except ValueError as error:
            raise ValueError(
                f"refusing to fetch {url!r}: host {host!r} resolved to "
                f"unparsable address {raw!r} ({error})"
            ) from error
        if _is_disallowed_address(address):
            raise ValueError(
                f"refusing to fetch {url!r}: host {host!r} resolves to "
                f"non-public address {raw}"
            )


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that re-applies the http(s)-only + public-IP checks per hop.

    `fetch` validates the *initial* URL's scheme and host, but stdlib's default
    handler would happily follow a 30x to `ftp://` (or any scheme it allows) or to
    an internal/private host. A feed is untrusted remote input, so a malicious /
    compromised feed server could redirect the fetch off http(s) OR at cloud
    metadata / localhost / RFC1918; refuse any redirect target that isn't http(s)
    AND whose host doesn't resolve to a public address (SSRF guard, every hop).
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        scheme = urlsplit(newurl).scheme.lower()
        if scheme not in ("http", "https"):
            raise urllib.error.HTTPError(
                newurl, code, f"refusing non-http(s) redirect to {newurl!r}", headers, fp
            )
        # Re-apply the SSRF guard on the redirect target (the attacker-controlled hop).
        try:
            _assert_public_host(newurl)
        except ValueError as error:
            raise urllib.error.HTTPError(newurl, code, str(error), headers, fp) from error
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Public aliases so other OUTBOUND-HTTP callers (e.g. the Rocket.Chat webhook)
# reuse the same hardened SSRF guard + per-hop safe-redirect handler instead of
# re-implementing them — one implementation, one place to fix.
assert_public_host = _assert_public_host
SafeRedirectHandler = _SafeRedirectHandler


_OPENER: urllib.request.OpenerDirector | None = None


def _opener() -> urllib.request.OpenerDirector:
    """A process-wide opener that enforces http(s)-only redirects (built once)."""
    global _OPENER
    if _OPENER is None:
        _OPENER = urllib.request.build_opener(_SafeRedirectHandler())
    return _OPENER


def fetch(url: str, *, timeout: float = DEFAULT_FETCH_TIMEOUT) -> str:
    """HTTP GET `url` with an identifying User-Agent; return the decoded body.

    Tests always monkeypatch this (or inject a `fetch_fn`), so the network is
    never touched under test. Hardened for untrusted feeds: the scheme is validated
    up front AND on every redirect hop (`_SafeRedirectHandler`), the destination
    host is resolved and refused if it is non-public (`_assert_public_host`, an SSRF
    guard applied initially AND per redirect hop), and the response is read with a
    hard `MAX_FEED_BYTES` cap so a hostile feed can't be streamed without bound.
    """
    scheme = urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"refusing to fetch non-http(s) URL: {url!r}")
    # SSRF guard: reject a host resolving to a private/loopback/link-local/reserved
    # address BEFORE connecting (each redirect hop is re-checked by _SafeRedirectHandler).
    _assert_public_host(url)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    # B310 rationale: the scheme is validated to http/https just above and on every
    # redirect by _SafeRedirectHandler, so this can't be steered to a file/ftp handler.
    with _opener().open(request, timeout=timeout) as response:  # nosec B310
        charset = response.headers.get_content_charset() or "utf-8"
        # Read one byte past the cap so an over-limit body is detectable, not silently
        # truncated into a half-valid feed.
        data = response.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise ValueError(f"feed exceeds {MAX_FEED_BYTES} bytes — refused")
    try:
        return data.decode(charset, errors="replace")
    except LookupError:
        # A hostile/misconfigured feed can declare an unregistered codec name
        # (e.g. charset=foobar). bytes.decode raises LookupError for that — which
        # errors="replace" does NOT suppress — so fall back to utf-8 rather than
        # letting one bad feed abort the whole category run.
        return data.decode("utf-8", errors="replace")


