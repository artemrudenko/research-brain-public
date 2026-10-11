"""Typed records for the author-monitoring roster (CONVENTIONS §2.4).

`MonitoredAuthor` is one accepted `config/authors.yaml` entry; `CollectionPlan`
is what that entry resolves to once we ask "so what do we actually fetch?".

They are kept apart on purpose. The roster is the user's decision and changes
only when they say so; the plan is derived, disposable, and depends on config
the user edits elsewhere (a `publication-filter` author's feed comes from
`sources.yaml`). Collapsing the two would make a plan look like a promise the
roster never made.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MonitoredAuthor:
    """One accepted entry: a person, and the handle we agreed to follow them by.

    Field names follow the code, not the YAML, where the two would collide with
    builtins or read as noise: YAML `id` → `identifier`, YAML `url` →
    `profile_url`. `scripts/authors/store.py` owns that mapping.
    """

    name: str
    monitoring: str
    topic: str = ""
    feed: str = ""
    identifier: str = ""
    profile_url: str = ""
    publication: str = ""
    query: str = ""
    active: bool = True
    added: str = ""
    note: str = ""


@dataclass(frozen=True)
class CollectionPlan:
    """What to poll for one author, and how to read what comes back.

    `fetch_url` empty means there is nothing a headless run can poll — legacy
    `search` rows have this shape, so cron can skip them *and say
    it skipped it*. A silent skip is indistinguishable from "this author
    published nothing", which is the one report the user cannot debug.
    """

    author_key: str
    display_name: str
    variant: str
    topic: str = ""
    fetch_url: str = ""
    query: str = ""
    match_identity: bool = False
    agent_only: bool = False
