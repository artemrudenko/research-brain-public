"""Is this feed item by the author we are following? (CONVENTIONS §2.4)

The whole of `publication-filter`, and the awkward part of author monitoring.
The roster entry carries a stable handle — the validator insists on an `id` or
`url` precisely so this decision is not left to a name — but a publication feed
usually credits a bare `dc:creator` NAME and nothing else. Those two never
compare equal as identity keys, so matching cannot simply diff them.

The resolution is to ask the identity ladder its other question. `identity_key`
answers "given this observation, whose is it?"; here we need "given this person,
which observations resolve to them?" — which is the same three rungs read
outward:

    their identifier
    their canonical profile URL
    their name, scoped to this one publication

An item matches when its own key is one of those. Everything else is a
non-match, and that asymmetry is deliberate: missing one of Jane's articles
costs her a mention in a digest, while a false match credits her with a
stranger's work — permanently, in a knowledge base she cannot correct. So there
is no fuzzy name matching, no initials, no "Doe, Jane". If the feed spells her
differently than she registered, we lose the article. That is the cheap failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.authors.model import MonitoredAuthor  # noqa: E402
from scripts.source_report.authors import identity_key  # noqa: E402


def _host(value: str) -> str:
    """Lowercased host with `www.` dropped — spelling, not identity."""
    text = value.strip().lower()
    if "//" in text:
        from urllib.parse import urlsplit  # noqa: PLC0415 — only needed on this path

        text = urlsplit(text).hostname or text
    else:
        text = text.split("/", 1)[0]
    return text.removeprefix("www.")


def match_keys(author: MonitoredAuthor) -> frozenset[str]:
    """Every identity key that resolves TO this author.

    One per rung of the ladder they actually have. The name rung is always
    scoped to their publication: unscoped, "Jane Doe" would match every Jane Doe
    on every site the user collects, which is the collision the scope exists to
    prevent.
    """
    publication = _host(author.publication)
    keys = set()
    if author.identifier:
        keys.add(identity_key("", "", author.identifier, publication))
    if author.profile_url:
        keys.add(identity_key("", author.profile_url, "", publication))
    if author.name:
        keys.add(identity_key(author.name, "", "", publication))
    return frozenset(keys)


def item_matches(
    author: MonitoredAuthor,
    name: str,
    url: str = "",
    identifier: str = "",
    publication: str = "",
) -> bool:
    """True when this feed item's credited author IS the monitored author.

    `publication` defaults to the author's own — the caller passes it only when
    the item arrived through a different feed, where a name-only match must not
    carry across.

    An item crediting nobody never matches: attributing it would hand the whole
    publication's uncredited output to one person. And a contradicting
    identifier loses to nothing — if the item names an identifier that is not
    theirs, the names agreeing is not evidence, it is the collision itself.
    """
    if not (name.strip() or url.strip() or identifier.strip()):
        return False

    scope = _host(publication) if publication else _host(author.publication)
    item_key = identity_key(name, url, identifier, scope)
    return item_key in match_keys(author)


__all__ = ["item_matches", "match_keys"]
