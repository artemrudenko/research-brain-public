"""Result types of the brain-hygiene pass: the parsed note, one finding, and
the assembled health of the whole vault. Pure data — no filesystem access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class Concept:
    """One parsed concept note: the fields hygiene checks reason about."""

    path: Path
    stem: str  # filename without extension — the wikilink target id
    note_type: str
    tags: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)  # raw [[concepts/x]] strings
    contributors: list[str] = field(default_factory=list)  # raw [[authors/x]] strings
    parent_playbook: list[str] = field(default_factory=list)
    source_concepts: list[str] = field(default_factory=list)
    sources: list[object] = field(default_factory=list)
    last_verified: date | None = None
    ttl_days: int | None = None
    body: str = ""


@dataclass
class Author:
    """One parsed author node (`brain/authors/<slug>.md`, `type: author`).

    A first-class vault entity (Stage 9, model alpha): the authoritative
    author↔concept link lives on the concept (`contributors:`), so an author
    node carries only identity + optional prose and never lists its own works.
    `identity_key` is the shared collision-safe join key (same ladder as the
    followed-authors roster); `identifier`/`profile_url` are "" when unknown.
    """

    path: Path
    stem: str  # filename without extension — the [[authors/stem]] link target
    note_type: str  # always "author"
    title: str = ""
    identity_key: str = ""
    identifier: str = ""  # ORCID/etc, "" when unknown
    profile_url: str = ""  # "" when unknown
    tags: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)  # raw [[.../x]] strings
    created: str = ""
    last_updated: str = ""
    body: str = ""


@dataclass
class Warning:
    """A single advisory finding, tagged by kind for grouping/reporting."""

    # orphan | weakly-linked | broken-link | missing-sources | uncited-fact |
    # tag | missing-from-index | stale
    kind: str
    concept: str  # concept stem (or "" for vocabulary-level tag findings)
    message: str


@dataclass
class BrainHealth:
    """The full result of one hygiene pass, ready to render or serialize."""

    concept_count: int
    warnings: list[Warning] = field(default_factory=list)

    def _count(self, kind: str) -> int:
        return sum(1 for w in self.warnings if w.kind == kind)

    @property
    def orphans(self) -> int:
        return self._count("orphan")

    @property
    def weakly_linked(self) -> int:
        return self._count("weakly-linked")

    @property
    def missing_from_index(self) -> int:
        return self._count("missing-from-index")

    @property
    def broken_links(self) -> int:
        return self._count("broken-link")

    @property
    def missing_sources(self) -> int:
        return self._count("missing-sources")

    @property
    def uncited_facts(self) -> int:
        return self._count("uncited-fact")

    @property
    def stale(self) -> int:
        return self._count("stale")

    @property
    def tag_findings(self) -> int:
        return self._count("tag")

    @property
    def problem_solution_findings(self) -> int:
        return self._count("problem-solution")

    @property
    def headline(self) -> str:
        """The human-readable one-line health string (CONVENTIONS §13)."""
        return (
            f"brain health: {self.concept_count} concepts, "
            f"{self.orphans} orphans, {self.broken_links} broken links, "
            f"{self.missing_sources} missing-sources, "
            f"{self.uncited_facts} uncited-facts, {self.stale} stale"
            + (
                f", {self.problem_solution_findings} problem-solution findings"
                if self.problem_solution_findings
                else ""
            )
        )

    @property
    def health_headline(self) -> str:
        """The machine-matched headline the digest keys on by `Health:` prefix.

        The digest builder (`build_digest.py`) greps for the exact `Health:`
        prefix, so this line's shape is a contract — keep the prefix stable.
        """
        return (
            f"Health: {self.concept_count} concepts · {self.orphans} orphans · "
            f"{self.broken_links} broken links · {self.missing_sources} "
            f"missing-sources · {self.uncited_facts} uncited-facts · {self.stale} stale"
            + (
                f" · {self.problem_solution_findings} problem-solution findings"
                if self.problem_solution_findings
                else ""
            )
        )
