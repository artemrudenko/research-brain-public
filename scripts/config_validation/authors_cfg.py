"""Validation for the OPTIONAL author-monitoring roster (CONVENTIONS §2.4).

`config/authors.yaml` records the people the user has explicitly chosen to
follow. Two properties of this file are load-bearing, and both are the schema's
share of the plan's hard rule — *nothing may start monitoring an author on its
own*:

  - **absent is valid, and is the default.** No file means nobody is followed.
    The configured-off state costs nothing, so it is the one you get by default;
    only a deliberate write turns monitoring on.
  - **every entry must carry a handle its variant can actually act on.** Each of
    the active and legacy variants reach a person through different handles, so
    the required companion field differs per variant (the table below). An entry
    that names a person but gives no way to find them is not a weak
    configuration — it is one that would be *resolved by guessing*, and guessing
    attributes one person's work to another. That is the same refusal the
    identity ladder in `scripts/source_report/authors.py` makes when it declines
    to merge two same-named authors.

    | monitoring           | requires                                    |
    |----------------------|---------------------------------------------|
    | `rss`                | `feed` — an author-specific feed URL        |
    | `publication-filter` | `publication` + a stable `id` or `url`      |
    | `scholarly`          | `id` — ORCID/OpenAlex/S2 are queried by it  |
    | `search`             | `query` — the standing search string        |

This module validates SHAPE only. It never resolves an identifier, never probes
a feed, and never decides that somebody is worth following — `source_report`
suggests, the user accepts, `author-manage` writes.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

from scripts.config_schema import AUTHOR_MONITORING_VARIANTS, LEGACY_AUTHOR_MONITORING_VARIANTS
from scripts.config_validation.yaml_helpers import load_yaml_mapping, url_error

# Per-variant required companion field(s). Keyed by variant so the enum SSOT and
# this table are checked against each other by test rather than by eye.
_REQUIRED_URL_FIELD = {"rss": "feed"}
_REQUIRED_TEXT_FIELD = {"publication-filter": "publication", "search": "query"}

# Variants that cannot be resolved from a display name and so demand a stable
# handle. `scholarly` insists on `id` specifically: a profile URL is not what
# OpenAlex/ORCID are queried by, so accepting one would leave the lookup to fall
# back on the name — the exact collision this schema exists to prevent.
_NEEDS_STABLE_IDENTITY = ("publication-filter",)
_NEEDS_IDENTIFIER = ("scholarly",)

# Variants that COLLECT. Their articles land in `pipeline/1-incoming/<topic>/`
# and are judged by that topic's curate rules, so an author with no topic has
# nowhere to go — and where a person's work belongs is knowledge only the user
# has. Legacy `search` is exempt only to keep old rows readable for removal.
_NEEDS_TOPIC = ("rss", "publication-filter", "scholarly")


def _text_value(entry: dict[str, object], key: str) -> str:
    """The stripped string at `key`, or "" when absent or not a string."""
    value = entry.get(key)
    return value.strip() if isinstance(value, str) else ""


def entry_errors(entry: dict[str, object], where: str = "authors entry") -> list[str]:
    """Return every schema error for one roster entry (never just the first).

    Public so `scripts/manage_authors.py` can apply the SAME rules at the write
    boundary. One rule set means a roster the mutator accepts can never be one
    `validate_config.py` later rejects — the user would have no way to tell
    which of the two was wrong.
    """
    errors: list[str] = []

    if not _text_value(entry, "name"):
        errors.append(f"{where}: `name` must be a non-empty display name")

    variant = _text_value(entry, "monitoring")
    if not variant:
        errors.append(
            f"{where}: `monitoring` is required — one of "
            f"{', '.join(AUTHOR_MONITORING_VARIANTS)}"
        )
    elif variant not in (*AUTHOR_MONITORING_VARIANTS, *LEGACY_AUTHOR_MONITORING_VARIANTS):
        errors.append(
            f"{where}: `monitoring` must be one of "
            f"{', '.join(AUTHOR_MONITORING_VARIANTS)}, got {variant!r}"
        )
    else:
        errors += _variant_errors(where, entry, variant)

    # `url` is optional, but a present one must be a real URL — a half-typed
    # profile link silently disables the identity it was meant to establish.
    if "url" in entry and (error := url_error(where, "url", entry["url"])):
        errors.append(error)

    if "active" in entry and not isinstance(entry["active"], bool):
        errors.append(
            f"{where}: `active` must be a boolean true/false, got {entry['active']!r}"
        )
    return errors


def _variant_errors(where: str, entry: dict[str, object], variant: str) -> list[str]:
    """Return the handle requirements this variant leaves unmet."""
    errors: list[str] = []

    if url_key := _REQUIRED_URL_FIELD.get(variant):
        if error := url_error(where, url_key, entry.get(url_key)):
            errors.append(f"{error} (required by `monitoring: {variant}`)")

    if text_key := _REQUIRED_TEXT_FIELD.get(variant):
        if not _text_value(entry, text_key):
            errors.append(
                f"{where}: `{text_key}` is required by `monitoring: {variant}`"
            )

    if variant in _NEEDS_TOPIC and not _text_value(entry, "topic"):
        errors.append(
            f"{where}: `topic` is required by `monitoring: {variant}` — collected "
            f"articles land in that topic's folder and are judged by its curate "
            f"rules, and only you know where this person's work belongs"
        )

    if variant in _NEEDS_IDENTIFIER and not _text_value(entry, "id"):
        errors.append(
            f"{where}: `id` is required by `monitoring: {variant}` — a scholarly "
            f"source is queried by identifier (e.g. `orcid:0000-0002-1825-0097`), "
            f"and resolving a display name would credit the wrong person"
        )

    if variant in _NEEDS_STABLE_IDENTITY and not (
        _text_value(entry, "id") or _text_value(entry, "url")
    ):
        errors.append(
            f"{where}: `monitoring: {variant}` needs a stable `id` or `url` — "
            f"filtering a shared feed by display name alone cannot tell two "
            f"same-named authors apart"
        )
    return errors


def validate_authors_yaml(path: Path, yaml: ModuleType) -> list[str]:
    """Return schema errors for the optional authors.yaml (CONVENTIONS §2.4)."""
    if not path.exists():
        return []  # nobody is followed — the default, and a valid one
    errors, data = load_yaml_mapping(path, yaml)
    if errors or data is None:
        return errors

    authors = data.get("authors")
    if authors is None:
        return []  # an empty roster, spelled the other way
    if not isinstance(authors, list):
        return [f"{path.name}: `authors` must be a list"]

    for i, entry in enumerate(authors):
        where = f"{path.name}: authors[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{where} must be a mapping")
            continue
        errors += entry_errors(entry, where)
    return errors


__all__ = ["entry_errors", "validate_authors_yaml"]
