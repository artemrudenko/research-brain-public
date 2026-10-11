"""report_models.py — dataclasses shared by the browser-grade digest report.

Split out of `digest_report_html.py` (ADR 0021 style facade split, same pattern
as `scripts/digest/model.py` for the digest builder): every data shape the
report renderer consumes lives here, independent of any rendering logic, so it
has no risk of circular imports with the render-side modules
(`report_concepts.py`, `report_vault.py`, `report_audit.py`,
`digest_report_html.py` itself).

`digest_report_html.py` re-exports every name here unchanged, so
`from scripts.delivery.digest_report_html import ReportConcept` (tests,
`scripts/digest/report_inputs.py`, `build_digest.py`) keeps working exactly as
before the split.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReportSource:
    """One concept source shown in the browser report."""

    url: str
    local_path: str = ""
    tier: str = ""


@dataclass(frozen=True)
class ReportConcept:
    """A concept snapshot for the browser-grade report."""

    name: str
    local_path: str
    updated: str = ""
    tags: list[str] = field(default_factory=list)
    definition: str = ""
    body: str = ""
    sources: list[ReportSource] = field(default_factory=list)


@dataclass(frozen=True)
class ReportGlossaryTerm:
    """One glossary term shown in the browser report."""

    term: str
    explanation: str


@dataclass(frozen=True)
class ReportVaultNote:
    """One lesson/playbook note shown in the browser report vault tab."""

    title: str
    note_type: str
    local_path: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: str = ""
    summary: str = ""


@dataclass(frozen=True)
class ReportAuditDecision:
    """One source-selection decision shown in the report audit tab."""

    title: str
    url: str = ""
    tier: str = ""
    included: bool = False
    rank: int | None = None
    reason: str = ""
    # Reading estimate in minutes (0 = unknown → the report omits the figure).
    read_minutes: int = 0


@dataclass(frozen=True)
class ReportAuditTopic:
    """Per-topic source-selection audit shown in the browser report."""

    topic: str
    total_sources: int
    included_sources: int
    hidden_sources: int
    decisions: list[ReportAuditDecision] = field(default_factory=list)


@dataclass(frozen=True)
class ReportTopicStat:
    """Per-topic collection volume shown in the browser report."""

    topic: str
    sources: int


@dataclass(frozen=True)
class ReportStats:
    """Operational collection/synthesis stats for the browser report."""

    new_sources: int = 0
    topics: int = 0
    included_sources: int = 0
    hidden_sources: int = 0
    audit_path: str = ""
    updated_concepts: int = 0
    concepts_created: int = 0
    concepts_updated: int = 0
    existing_concepts_reused: int = 0
    attention_items: int = 0
    total_concepts: int = 0
    total_lessons: int = 0
    total_playbooks: int = 0
    lessons_base_path: str = ""
    playbooks_base_path: str = ""
    glossary_terms: int = 0
    topic_stats: list[ReportTopicStat] = field(default_factory=list)
