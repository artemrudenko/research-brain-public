#!/usr/bin/env python3
"""
authors.py — who keeps showing up, and who might be worth following.

Read-only aggregation over the decision journal. Author monitoring now exists
(`config/authors.yaml` + `scripts/authors/`), but it stays on the far side of a
user decision: the strongest output here is still a SUGGESTION, which is why
nothing in this module can start, enable, or configure anything. `identity_key`
below is shared with that roster so the two agree on who is who.

The identity ladder is the substance, and it is deliberately conservative:

    same identifier            → the same person
    same canonical profile URL → the same person
    same name, one publication → the same person
    anything else              → different people

Attributing one person's work to another is not a bug you notice later: it
silently poisons every count built on top, and the person it misrepresents never
gets to correct it. So the ladder refuses to guess — no fuzzy name matching, no
merging one name across publications, no "probably the famous one".

`publication` here is the source the article arrived through. It is a proxy, not
a claim about the publisher, which is exactly why it is only ever used to keep
same-named people APART, never to pull two records together.

Honest limitation worth knowing before reading the numbers: today's collector
records a bare name from the feed, so the top two rungs are unreachable in
practice and no feed-only author can be suggested for monitoring (you cannot
follow someone you have no stable handle for). That is a reason to extract
authors from the article page, not a reason to lower the bar.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.normalize_url import normalize_or_raw  # noqa: E402
from scripts.registry import iter_registry_rows  # noqa: E402
from scripts.source_report.events import read_decisions  # noqa: E402
from scripts.value_metrics import classify_status  # noqa: E402

# Suggestion thresholds. Each answers a different objection to "you should follow
# this person", so they are ANDed rather than blended into a score.
MIN_ARTICLES = 3  # one or two pieces is not a pattern
MIN_RUNS = 2  # everything from a single run could be one backfill
MIN_CURATION_RATE = 0.60  # work that keeps getting rejected is not useful to you


@dataclass(frozen=True)
class AuthorMetrics:
    """What the journal and registry together know about one person."""

    key: str
    display_name: str
    articles: int
    runs: int
    passed_curation: int
    rejected_curation: int
    topics: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    profile_url: str = ""
    identifier: str = ""
    last_seen: str = ""

    @property
    def curation_rate(self) -> float:
        """Share of judged articles that survived curation; 0.0 when none judged."""
        judged = self.passed_curation + self.rejected_curation
        return self.passed_curation / judged if judged else 0.0

    @property
    def followable(self) -> bool:
        """Is there a stable handle we could actually monitor them by?"""
        return bool(self.identifier or self.profile_url)


@dataclass(frozen=True)
class MonitoringSuggestion:
    """A proposal for the USER to accept. Carries no action of its own."""

    display_name: str
    reason: str
    profile_url: str = ""
    identifier: str = ""


@dataclass
class _Tally:
    display_name: str = ""
    urls: list[str] = field(default_factory=list)
    runs: set[str] = field(default_factory=set)
    topics: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    profile_url: str = ""
    identifier: str = ""
    last_seen: str = ""


def _publication_of(source_url: str) -> str:
    """The host an article arrived through — a proxy used only to keep names apart."""
    return (urlsplit(source_url).hostname or source_url).lower()


def identity_key(name: str, url: str, identifier: str, publication: str) -> str:
    """Resolve one credited author to a grouping key. Never guesses.

    Public because the monitoring roster (`scripts/authors/`) must resolve
    identity through this exact ladder: two ladders would let the roster and
    these metrics disagree about who is who, and the report would then be unable
    to tell the user which suggested author they already follow.
    """
    if identifier:
        return f"id:{identifier}"
    if url:
        return f"url:{normalize_or_raw(url)}"
    # Name-only: scoped to the publication, so two same-named people on
    # unrelated sites stay two people. Whitespace and case are normalised —
    # that is spelling, not identity — but nothing more.
    return f"name:{' '.join(name.split()).lower()}|pub:{publication}"


def _registry_status_by_url(registry_path: Path) -> dict[str, str]:
    if not registry_path.exists():
        return {}
    return {
        normalize_or_raw(row.url): classify_status(row.status)
        for row in iter_registry_rows(registry_path)
    }


def author_metrics(root: Path, registry_path: Path) -> list[AuthorMetrics]:
    """One row per resolved author, sorted by name for stable output.

    Only COLLECTED articles count as an author's output: a candidate we dropped
    is not something they published to us, and counting it would inflate exactly
    the people whose work we keep refusing.
    """
    statuses = _registry_status_by_url(registry_path)
    tallies: dict[str, _Tally] = {}

    for entry in read_decisions(root):
        if str(entry.get("decision", "")) != "selected":
            continue
        author = entry.get("author")
        if not isinstance(author, dict):
            continue
        name = str(author.get("name", "")).strip()
        if not name:
            continue  # an uncredited article belongs to nobody, not to "unknown"

        url = str(author.get("url", ""))
        identifier = str(author.get("id", ""))
        source = str(entry.get("source_url", ""))
        key = identity_key(name, url, identifier, _publication_of(source))

        tally = tallies.setdefault(key, _Tally(display_name=name))
        tally.urls.append(normalize_or_raw(str(entry.get("candidate_url", ""))))
        run = str(entry.get("run_id", ""))
        if run:
            tally.runs.add(run)
        for value, bucket in ((str(entry.get("topic", "")), tally.topics), (source, tally.sources)):
            if value and value not in bucket:
                bucket.append(value)
        tally.profile_url = tally.profile_url or url
        tally.identifier = tally.identifier or identifier
        ts = str(entry.get("ts", ""))
        if ts > tally.last_seen:
            tally.last_seen = ts

    rows = [
        AuthorMetrics(
            key=key,
            display_name=tally.display_name,
            articles=len(tally.urls),
            runs=len(tally.runs),
            passed_curation=[statuses.get(u, "") for u in tally.urls].count("processed"),
            rejected_curation=[statuses.get(u, "") for u in tally.urls].count("rejected"),
            topics=tuple(tally.topics),
            sources=tuple(tally.sources),
            profile_url=tally.profile_url,
            identifier=tally.identifier,
            last_seen=tally.last_seen,
        )
        for key, tally in tallies.items()
    ]
    return sorted(rows, key=lambda r: (r.display_name, r.key))


def monitoring_suggestions(
    rows: list[AuthorMetrics], followed: set[str] | None = None
) -> list[MonitoringSuggestion]:
    """Authors worth proposing to follow. Every bar must clear; none is weighted.

    `followable` is not negotiable: without a stable URL or identifier there is
    no way to actually monitor the person, and offering it anyway is an empty
    promise the user only discovers after accepting.

    `followed` is the set of identity keys already in the roster
    (`config/authors.yaml`), resolved through this module's own `identity_key`.
    A suggestion is a proposal to FOLLOW someone, so an author already followed
    is dropped — the report never asks you to follow someone you already do.
    Keying on identity (not name) means following one same-named person does not
    silence a genuine suggestion for another. `None`/empty → nobody followed, the
    default, so every qualifying author is suggested.
    """
    already = followed or set()
    suggestions: list[MonitoringSuggestion] = []
    for row in rows:
        if row.key in already:
            continue
        if not (
            row.followable
            and row.articles >= MIN_ARTICLES
            and row.runs >= MIN_RUNS
            and row.curation_rate >= MIN_CURATION_RATE
        ):
            continue
        judged = row.passed_curation + row.rejected_curation
        topics = ", ".join(row.topics) or "your topics"
        suggestions.append(
            MonitoringSuggestion(
                display_name=row.display_name,
                # Say what the numbers were, not "score 0.82" — the user is being
                # asked to make the judgement, so they get the evidence.
                reason=(
                    f"{row.passed_curation} of {judged} pieces by {row.display_name} "
                    f"passed curation on {topics}, across {row.runs} collection runs."
                ),
                profile_url=row.profile_url,
                identifier=row.identifier,
            )
        )
    return suggestions
