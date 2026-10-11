"""URL helpers for read-only intake classification."""

from __future__ import annotations

from urllib.parse import urlsplit


def is_http_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in {"http", "https"} and bool(parts.netloc)
