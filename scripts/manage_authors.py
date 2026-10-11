#!/usr/bin/env python3
"""
manage_authors.py — the ONLY write path into config/authors.yaml.

Adding a row here is the moment a person starts being followed, which is the one
act the plan reserves for an explicit user decision. So the capability lives in
exactly one module, and the suggesting side (`scripts/source_report/authors.py`)
does not import it — a comment promising "we only suggest" is not a constraint,
an absent import is. `tests/test_manage_authors.py` walks that import graph.

Every mutator validates through `config_validation.authors_cfg.entry_errors`,
the same rules `validate_config.py` applies. One rule set means this module can
never write a roster the validator later rejects, which would leave the user
holding two tools that disagree and no way to tell which one is wrong.

Identity is resolved by the shared ladder (`source_report.authors.identity_key`),
so "already following them" means the same thing here as in the report — and
two same-named people on different sites stay two entries, as they should.

Usage:
    python3 scripts/manage_authors.py add NAME --monitoring VARIANT [options]
    python3 scripts/manage_authors.py list
    python3 scripts/manage_authors.py pause NAME
    python3 scripts/manage_authors.py resume NAME
    python3 scripts/manage_authors.py remove NAME
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.authors.collect import not_collected_caveat  # noqa: E402
from scripts.authors.model import MonitoredAuthor  # noqa: E402
from scripts.authors.nodes import followed_node_status  # noqa: E402
from scripts.authors.store import (  # noqa: E402
    AUTHORS_YAML,
    dump_authors_yaml,
    load_authors,
    roster_identity_key,
)
from scripts.config_schema import AUTHOR_MONITORING_VARIANTS  # noqa: E402
from scripts.config_validation.authors_cfg import entry_errors  # noqa: E402
from scripts.registry import atomic_write_text  # noqa: E402

DEFAULT_CONFIG_DIR = "config"


def _path(config_dir: Path) -> Path:
    return Path(config_dir) / AUTHORS_YAML


def _key(author: MonitoredAuthor) -> str:
    """This author's identity, via the ladder the whole system shares."""
    return roster_identity_key(author)


def _write(config_dir: Path, authors: list[MonitoredAuthor]) -> None:
    path = _path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, dump_authors_yaml(authors))


def _as_entry(author: MonitoredAuthor) -> dict[str, object]:
    """The YAML-shaped mapping for `author`, for validation before writing.

    Empty optionals are OMITTED, exactly as `dump_authors_yaml` omits them.
    Validating a shape we would never write is worse than not validating: it
    rejects entries that would have been fine on disk (an absent `url` is not a
    malformed one), and it would hide the reverse mistake just as easily.
    """
    entry: dict[str, object] = {"active": author.active}
    for key, value in (
        ("name", author.name),
        ("monitoring", author.monitoring),
        ("topic", author.topic),
        ("feed", author.feed),
        ("publication", author.publication),
        ("id", author.identifier),
        ("url", author.profile_url),
        ("query", author.query),
    ):
        if value:
            entry[key] = value
    return entry


def _find(authors: list[MonitoredAuthor], name: str) -> int:
    """Index of the entry matching `name` (case/space-insensitive), or -1.

    Matching is by display name because that is what the user types. It stays
    unambiguous in practice: two same-named people can only both be in the
    roster with distinct handles, and the caller is told when that happens.
    """
    wanted = " ".join(name.split()).lower()
    matches = [
        i for i, a in enumerate(authors) if " ".join(a.name.split()).lower() == wanted
    ]
    if len(matches) > 1:
        raise LookupError(
            f"{name!r} matches {len(matches)} entries — they are different people "
            f"sharing a name; edit {AUTHORS_YAML} directly to change one"
        )
    return matches[0] if matches else -1


def add_author(
    config_dir: Path,
    name: str,
    monitoring: str,
    topic: str = "",
    feed: str = "",
    identifier: str = "",
    profile_url: str = "",
    publication: str = "",
    query: str = "",
    added: str = "",
    note: str = "",
    active: bool = True,
) -> bool:
    """Add one accepted author to the roster.

    Idempotent on IDENTITY, not on name: re-accepting the same suggestion is a
    no-op returning False, while two same-named people with distinct handles
    both get their row. Raises ValueError when the entry would not validate.
    """
    author = MonitoredAuthor(
        name=" ".join((name or "").split()),
        monitoring=(monitoring or "").strip(),
        topic=topic.strip(),
        feed=feed.strip(),
        identifier=identifier.strip(),
        profile_url=profile_url.strip(),
        publication=publication.strip(),
        query=query.strip(),
        added=added.strip(),
        note=note.strip(),
        active=active,
    )
    if author.monitoring not in AUTHOR_MONITORING_VARIANTS:
        raise ValueError(
            f"{author.monitoring!r} is not available for new author monitoring; "
            f"choose one of: {', '.join(AUTHOR_MONITORING_VARIANTS)}"
        )
    if errors := entry_errors(_as_entry(author), f"{AUTHORS_YAML}: {author.name!r}"):
        raise ValueError("; ".join(errors))

    authors = load_authors(_path(config_dir))
    if any(_key(existing) == _key(author) for existing in authors):
        return False
    authors.append(author)
    _write(config_dir, authors)
    return True


def set_author_active(config_dir: Path, name: str, active: bool) -> bool:
    """Pause or resume monitoring for one author.

    Returns True when the state changed, False when it already matched.
    Raises LookupError when nobody by that name is in the roster.
    """
    authors = load_authors(_path(config_dir))
    index = _find(authors, name)
    if index < 0:
        raise LookupError(f"no author named {name!r} in {AUTHORS_YAML}")
    if authors[index].active == active:
        return False
    authors[index] = replace(authors[index], active=active)
    _write(config_dir, authors)
    return True


def remove_author(config_dir: Path, name: str) -> bool:
    """Drop one author from the roster; removing an absent one is a clean no-op.

    The file survives an emptied roster — it records that the user made these
    decisions, and deleting it would read as "never configured" (which is also
    what would silently re-enable every suggestion prompt).
    """
    authors = load_authors(_path(config_dir))
    index = _find(authors, name)
    if index < 0:
        return False
    del authors[index]
    _write(config_dir, authors)
    return True


def list_authors(config_dir: Path) -> list[MonitoredAuthor]:
    """The roster as stored, in file order."""
    return load_authors(_path(config_dir))


def human_summary(config_dir: Path) -> str:
    """A short readable roster for the skill/CLI to print."""
    authors = list_authors(config_dir)
    if not authors:
        return "No authors are being monitored (config/authors.yaml is empty or absent)."
    lines = [f"Monitored authors ({len(authors)}):"]
    for author in authors:
        handle = author.identifier or author.profile_url or author.feed or author.query
        state = "" if author.active else "  [paused]"
        if author.monitoring == "search":
            state += "  [retired: no collection; use /discover for source proposals]"
        lines.append(f"- {author.name} — {author.monitoring} — {handle}{state}")
    return "\n".join(lines)


def nodes_summary(root: Path) -> str:
    """The author NODES (`brain/authors/`) each marked followed: yes/no.

    The read side of the node↔roster cross-reference (Stage 9, Q4): a node is
    "followed" when its `identity_key` is in the roster. Read-only — listing a
    node never adds it to the roster, and vice versa. Distinct from `list`,
    which shows the roster ("who I follow"), not what the vault knows of them.
    """
    status = followed_node_status(root)
    if not status:
        return "No author nodes yet (brain/authors/ is empty or absent)."
    lines = [f"Author nodes ({len(status)}):"]
    for stem in sorted(status):
        lines.append(f"- {stem} — followed: {'yes' if status[stem] else 'no'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config-dir", default=DEFAULT_CONFIG_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="follow an author you have decided to follow")
    p_add.add_argument("name")
    p_add.add_argument("--monitoring", required=True, choices=AUTHOR_MONITORING_VARIANTS)
    for option in ("topic", "feed", "id", "url", "publication", "query", "added", "note"):
        p_add.add_argument(f"--{option}", default="")

    sub.add_parser("list", help="show the roster")
    sub.add_parser(
        "nodes", help="list author nodes (brain/authors/) with followed: yes/no"
    )
    for command, help_text in (("pause", "stop following"), ("resume", "resume following")):
        p = sub.add_parser(command, help=help_text)
        p.add_argument("name")
    p_rm = sub.add_parser("remove", help="drop an author from the roster")
    p_rm.add_argument("name")

    args = parser.parse_args(argv)
    config_dir = Path(args.config_dir)
    if not config_dir.is_absolute():
        config_dir = PROJECT_ROOT / config_dir

    try:
        if args.command == "add":
            added = add_author(
                config_dir,
                name=args.name,
                monitoring=args.monitoring,
                topic=args.topic,
                feed=args.feed,
                identifier=args.id,
                profile_url=args.url,
                publication=args.publication,
                query=args.query,
                added=args.added,
                note=args.note,
            )
            print(
                f"Now following {args.name}." if added
                else f"{args.name} is already in the roster — nothing changed."
            )
            # Structural honesty: a scholarly author is staged but not collected
            # yet, and the CLI must say so itself — not rely on the skill. This is
            # a property of the monitoring VARIANT, so it prints whether the row
            # was just inserted OR already present (a repeat add must not hide it).
            caveat = not_collected_caveat(args.monitoring)
            if caveat:
                print(caveat)
        elif args.command == "list":
            print(human_summary(config_dir))
        elif args.command == "nodes":
            # Nodes + roster live under the vault root (config_dir's parent).
            print(nodes_summary(config_dir.parent))
        elif args.command in ("pause", "resume"):
            changed = set_author_active(config_dir, args.name, args.command == "resume")
            print(
                f"{args.name}: {args.command}d." if changed
                else f"{args.name} was already {args.command}d — nothing changed."
            )
        elif args.command == "remove":
            print(
                f"Removed {args.name}." if remove_author(config_dir, args.name)
                else f"{args.name} is not in the roster — nothing changed."
            )
    except (ValueError, LookupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


__all__ = [
    "add_author",
    "human_summary",
    "list_authors",
    "nodes_summary",
    "remove_author",
    "set_author_active",
]


if __name__ == "__main__":
    raise SystemExit(main())
