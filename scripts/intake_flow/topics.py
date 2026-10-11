"""Topic and slug helpers for URL intake classification."""

from __future__ import annotations

import html
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

from scripts.manage_sources import list_state

TOKEN_RE = re.compile(r"[a-z0-9]+")
COMMON_TLDS = {
    "com",
    "org",
    "net",
    "io",
    "dev",
    "ai",
    "co",
    "ru",
    "de",
    "fr",
    "uk",
}


def tokens(text: str) -> set[str]:
    ascii_text = (
        unicodedata.normalize("NFKD", html.unescape(text))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return set(TOKEN_RE.findall(ascii_text.lower()))


def safe_slug(text: str) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", html.unescape(text))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    slug_tokens = TOKEN_RE.findall(ascii_text.lower())
    if not slug_tokens:
        return "source"
    return "-".join(slug_tokens)


def hostname_slug(url: str) -> str:
    host = (urlsplit(url).hostname or "source").lower()
    if host.startswith("www."):
        host = host[4:]
    parts = [part for part in host.split(".") if part]
    if len(parts) > 1 and parts[-1] in COMMON_TLDS:
        parts = parts[:-1]
    return safe_slug("-".join(parts))


def topic_for_recurring(url: str, title: str, config_dir: Path) -> tuple[str, str]:
    existing_topics = [
        topic.name
        for topic in list_state(config_dir).topics
        if topic.name != "example-topic"
    ]
    evidence = tokens(f"{url} {title}")
    scores: list[tuple[str, int]] = []
    for topic in existing_topics:
        overlap = len(evidence & tokens(topic))
        if overlap > 0:
            scores.append((topic, overlap))

    if scores:
        scores.sort(key=lambda item: item[1], reverse=True)
        best_score = scores[0][1]
        winners = [topic for topic, score in scores if score == best_score]
        if len(winners) == 1:
            return "existing", winners[0]

    return "create", hostname_slug(url)
