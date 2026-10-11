"""Read and render the author roster, `config/authors.yaml` (CONVENTIONS §2.4).

Parsing and rendering both live here (the same pairing `sources/store.py` has),
but neither touches the filesystem to WRITE. `dump_authors_yaml` returns text;
putting that text on disk is `scripts/manage_authors.py`'s job alone, because a
write here is the moment a person starts being followed — the one act the plan
forbids anything but an explicit user decision from performing. Keeping the
write out of this module means a caller that merely wanted to read the roster is
never one convenience method away from changing who is monitored.

The loader is TOLERANT where `scripts/config_validation/authors_cfg.py` is
strict, matching how `sources/store.py` relates to its validator: unknown keys
are ignored and absent optionals default, so a roster written by a newer release
still loads. The one thing it will not do is invent a handle — an entry with no
usable identity loads as-is and is refused later, visibly, by `plan.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._yaml import optional_yaml, yaml_scalar  # noqa: E402
from scripts.authors.model import MonitoredAuthor  # noqa: E402
from scripts.normalize_url import normalize_or_raw  # noqa: E402
from scripts.source_report.authors import identity_key  # noqa: E402

AUTHORS_YAML = "authors.yaml"


def roster_identity_key(author: MonitoredAuthor) -> str:
    """This roster entry's grouping key.

    The single adapter from a stored `MonitoredAuthor` to the ladder in
    `source_report.authors.identity_key`, so the roster, the collection metrics
    and the "you already follow them" suggestion filter all agree on who is who
    — a second copy of this mapping is exactly how they would drift apart.

    One roster-only rung sits on top of that shared ladder: an `rss` author is
    identified by its FEED. The journal ladder has no feed to key on, but the
    roster does, and two same-named people followed on different feeds are two
    different rows — the name+publication fallback alone would silently merge
    them. So a feed breaks a name-only tie. It never shadows a real `id:`/`url:`
    (those ARE person identity, shared with author nodes and suggestions): the
    override applies only where the shared ladder fell through to `name:`.
    """
    key = identity_key(
        author.name, author.profile_url, author.identifier, author.publication.lower()
    )
    if author.feed and key.startswith("name:"):
        return f"feed:{normalize_or_raw(author.feed)}"
    return key

def roster_identity_keys(root: Path, *, authors_yaml: str = AUTHORS_YAML) -> set[str]:
    """The identity keys of everyone in the roster (`config/authors.yaml`).

    The single public accessor for "who is followed", so the suggestion filter
    (`source_insights._followed_keys`) and the author-node cross-reference
    (`authors.nodes.followed_node_status`) share ONE roster read and ONE ladder
    — a second copy is how they would drift on "who is who". Read-only and
    forgiving: an absent, empty, or malformed roster yields an empty set (nobody
    followed) rather than failing a caller that is otherwise fine.
    """
    try:
        authors = load_authors(root / "config" / authors_yaml)
    except (ValueError, RuntimeError):
        return set()
    return {roster_identity_key(author) for author in authors}


# YAML key → dataclass field, where the two differ (see MonitoredAuthor).
_RENAMED = {"id": "identifier", "url": "profile_url"}
_TEXT_FIELDS = (
    "name", "monitoring", "topic", "feed", "publication", "query", "added", "note",
)


def _require_yaml() -> ModuleType:
    yaml = optional_yaml()
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to read the author roster (config/authors.yaml) "
            "— install it with: pip install pyyaml"
        )
    return yaml


def _text(entry: dict[str, object], key: str) -> str:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) else ""


def _parse_entry(entry: dict[str, object], where: str) -> MonitoredAuthor:
    active = entry.get("active", True)
    if not isinstance(active, bool):
        raise ValueError(f"{where}: `active` must be a boolean (true/false)")
    fields = {field: _text(entry, field) for field in _TEXT_FIELDS}
    fields.update({field: _text(entry, key) for key, field in _RENAMED.items()})
    return MonitoredAuthor(**fields, active=active)


def parse_authors_yaml_text(text: str) -> list[MonitoredAuthor]:
    """Parse authors.yaml text into records; raise ValueError when malformed."""
    yaml = _require_yaml()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"{AUTHORS_YAML}: YAML parse error: {exc}") from exc
    if data is None:
        return []
    if not isinstance(data, dict):
        raise ValueError(f"{AUTHORS_YAML}: top level must be a mapping/object")

    raw = data.get("authors")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{AUTHORS_YAML}: `authors` must be a list")

    authors: list[MonitoredAuthor] = []
    for i, entry in enumerate(raw):
        where = f"{AUTHORS_YAML}: authors[{i}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be a mapping")
        authors.append(_parse_entry(entry, where))
    return authors


def load_authors(path: Path) -> list[MonitoredAuthor]:
    """Load the roster, or [] when the file does not exist.

    Absent is the default and means nobody is followed — so a missing file is
    the quiet, correct answer here, never an error.
    """
    path = Path(path)
    if not path.exists():
        return []
    return parse_authors_yaml_text(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Deterministic emitter (stdlib string building — no PyYAML needed to write)
# --------------------------------------------------------------------------- #

_AUTHORS_YAML_HEADER = (
    "schema_version: 1\n"
    "# config/authors.yaml — the authors you have chosen to follow.\n"
    "# Machine-written by scripts/manage_authors.py: the VALUES are yours to edit;\n"
    "# comments and formatting are regenerated on every change.\n"
    "# Nothing adds a row here on its own — a suggestion becomes an entry only\n"
    "# when you accept it (CONVENTIONS §2.4).\n"
    "# Per-author keys: name (required) / monitoring (rss|publication-filter|\n"
    "#   scholarly; legacy search rows remain readable) / topic (which topic their work belongs to)\n"
    "#   / feed (rss) / publication (publication-filter)\n"
    "#   / id + url (stable handles) / query (legacy search only) / active (true|false,\n"
    "#   default true) / added / note.\n"
)

# Emitted in a fixed order so a roster edit produces a minimal, readable diff.
_EMIT_ORDER = (
    ("name", "name"),
    ("monitoring", "monitoring"),
    ("topic", "topic"),
    ("feed", "feed"),
    ("publication", "publication"),
    ("id", "identifier"),
    ("url", "profile_url"),
    ("query", "query"),
    ("added", "added"),
    ("note", "note"),
)


def dump_authors_yaml(authors: list[MonitoredAuthor]) -> str:
    """Render the roster as canonical authors.yaml text (stable, round-trips)."""
    lines = [_AUTHORS_YAML_HEADER.rstrip("\n")]
    if not authors:
        # An explicit empty roster, never a deleted file: the file records that
        # the user made a decision, and its absence would read as "never asked".
        lines.append("authors: []")
        return "\n".join(lines) + "\n"
    lines.append("authors:")
    for author in authors:
        first = True
        for key, field in _EMIT_ORDER:
            value = getattr(author, field)
            if not value:
                continue  # omit empties — an absent optional is not a value
            prefix = "  - " if first else "    "
            lines.append(f"{prefix}{key}: {yaml_scalar(value)}")
            first = False
        lines.append(f"    active: {'true' if author.active else 'false'}")
    return "\n".join(lines) + "\n"


__all__ = [
    "AUTHORS_YAML",
    "dump_authors_yaml",
    "load_authors",
    "parse_authors_yaml_text",
    "roster_identity_key",
]
