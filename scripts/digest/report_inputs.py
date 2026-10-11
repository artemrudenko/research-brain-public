"""report_inputs.py — build the audit sidecar + browser-report input models.

Split out of `build_digest.py` (was ~1,600 lines pre-split, still 955 after the
earlier `scripts/digest/` split) so the "gather report-facing data" concern has
its own home next to `scan`/`render`/`model`. Two families of helpers live here:

- the JSON **audit sidecar** builder (`_digest_audit_payload`) — the per-topic
  source-selection decisions behind every delivered digest;
- the **browser-report snapshot** builders (`_report_*`) — concepts, lessons,
  playbooks, glossary terms, and stats, all re-derived read-only from `brain/`
  and `DigestData` for `digest_report_html.render_digest_report`.

`build_digest.py` re-exports every name here unchanged, so
`from scripts.build_digest import _report_audit_topics` (tests) and internal
calls inside `build_digest()` keep working exactly as before the split.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from scripts.delivery.digest_report_html import (
    ReportAuditDecision,
    ReportAuditTopic,
    ReportConcept,
    ReportGlossaryTerm,
    ReportSource,
    ReportStats,
    ReportTopicStat,
    ReportVaultNote,
)
from scripts.digest.model import DigestData, _normalize_tier
from scripts.digest.render import _curate_topic_items
from scripts.digest.scan import (
    _concept_definition,
    _concept_last_updated,
    _concept_name,
    _frontmatter_block,
    _is_seed_or_example,
    _sources_block,
    _split_frontmatter,
    scan_vault_notes,
)
from scripts.glossary import load_glossary

_SOURCE_FIELD_RE = re.compile(r"^\s*(?:-\s*)?(url|archive|tier)\s*:\s*(.+?)\s*$", re.I)


def _digest_audit_payload(
    data: DigestData, *, root: Path, digest_path: Path, digest_markdown: str, daily: bool
) -> dict[str, object]:
    """Build the deterministic JSON audit sidecar for one rendered digest.

    The audit explains the digest's source-selection surface without becoming a
    second source of truth: every count is derived from the already-gathered
    `DigestData` and the same per-topic curation rule the Markdown renderer uses.
    """
    topics: list[dict[str, object]] = []
    included_total = 0
    hidden_total = 0
    for topic in sorted(data.incoming_by_topic):
        items = data.incoming_by_topic[topic]
        shown, hidden_count = _curate_topic_items(items)
        shown_keys = {item.url or item.dedup_key or item.title for item in shown}
        decisions: list[dict[str, object]] = []
        rank = 0
        for item in shown + [i for i in items if (i.url or i.dedup_key or i.title) not in shown_keys]:
            key = item.url or item.dedup_key or item.title
            included = key in shown_keys
            if included:
                rank += 1
            decisions.append(
                {
                    "title": item.title,
                    "url": item.url,
                    "tier": _normalize_tier(item.tier),
                    "included": included,
                    "rank": rank if included else None,
                    "reason": (
                        "selected_by_source_credibility"
                        if included
                        else "hidden_topic_cap"
                    ),
                }
            )
        included_total += len(shown)
        hidden_total += hidden_count
        topics.append(
            {
                "topic": topic,
                "total_sources": len(items),
                "included_sources": len(shown),
                "hidden_sources": hidden_count,
                "decisions": decisions,
            }
        )
    return {
        "schema_version": "digest_audit.v1",
        "built_on": data.built_on.isoformat(),
        "lookback_days": data.lookback_days,
        "digest_path": _report_rel_path(digest_path, report_dir=root),
        "digest_sha256": hashlib.sha256(digest_markdown.encode("utf-8")).hexdigest(),
        "daily": daily,
        "quiet": data.is_quiet_daily if daily else data.is_quiet,
        "totals": {
            "new_sources": data.new_source_count,
            "topics": data.topic_count,
            "included_sources": included_total,
            "hidden_sources": hidden_total,
            "updated_concepts": len(data.concepts),
            "concepts_created": data.concepts_created,
            "concepts_updated": data.concepts_updated,
            "existing_concepts_reused": data.existing_concepts_reused,
            "lessons": len(data.lessons),
            "playbooks": len(data.playbooks),
            "attention_items": len(data.attention),
        },
        "topics": topics,
    }


def _previous_report_name(report_path: Path, *, daily: bool) -> str:
    """Newest same-kind sibling report older than this one ("" when none).

    Weekly issues walk to weekly issues only — daily inflow reports are a
    separate series (ADR 0016) and never appear as "previous digest".
    """
    prefix = "digest_daily_" if daily else "digest_"
    candidates = sorted(
        p.name
        for p in report_path.parent.glob(f"{prefix}*.report.html")
        if p.name != report_path.name
        and (daily or "daily" not in p.name)
        and p.name < report_path.name  # ISO dates sort lexicographically
    )
    return candidates[-1] if candidates else ""


def _report_audit_topics(data: DigestData) -> list[ReportAuditTopic]:
    """Build source-selection drilldown data for the browser-grade report."""
    topics: list[ReportAuditTopic] = []
    for topic in sorted(data.incoming_by_topic):
        items = data.incoming_by_topic[topic]
        shown, hidden_count = _curate_topic_items(items)
        shown_keys = {item.url or item.dedup_key or item.title for item in shown}
        decisions: list[ReportAuditDecision] = []
        rank = 0
        for item in shown + [
            i for i in items if (i.url or i.dedup_key or i.title) not in shown_keys
        ]:
            key = item.url or item.dedup_key or item.title
            included = key in shown_keys
            if included:
                rank += 1
            decisions.append(
                ReportAuditDecision(
                    title=item.title,
                    url=item.url,
                    tier=_normalize_tier(item.tier) or "",
                    included=included,
                    rank=rank if included else None,
                    reason=(
                        "selected_by_source_credibility"
                        if included
                        else "hidden_topic_cap"
                    ),
                    # ~900 display chars ≈ a minute of reading; nonzero bodies
                    # never round down to zero, unknown lengths stay 0 (omitted).
                    read_minutes=(
                        max(1, round(item.text_chars / 900)) if item.text_chars else 0
                    ),
                )
            )
        topics.append(
            ReportAuditTopic(
                topic=topic,
                total_sources=len(items),
                included_sources=len(shown),
                hidden_sources=hidden_count,
                decisions=decisions,
            )
        )
    return topics


def _report_rel_path(target: Path, *, report_dir: Path) -> str:
    """Return a stable POSIX relative link from the report to `target`."""
    return os.path.relpath(target, report_dir).replace(os.sep, "/")


def _report_glossary_terms(glossary_path: Path) -> list[ReportGlossaryTerm]:
    """Snapshot every configured glossary term for the browser-grade report."""
    return [
        ReportGlossaryTerm(term=term, explanation=explanation)
        for term, explanation in load_glossary(glossary_path).items()
    ]


def _report_stats(
    data: DigestData,
    *,
    audit_path: str = "",
    total_concepts: int,
    total_lessons: int = 0,
    total_playbooks: int = 0,
    lessons_base_path: str = "",
    playbooks_base_path: str = "",
    glossary_terms: int,
) -> ReportStats:
    """Build collection/synthesis stats for the browser-grade report."""
    topic_stats = [
        ReportTopicStat(topic=topic, sources=len(items))
        for topic, items in sorted(
            data.incoming_by_topic.items(), key=lambda kv: (-len(kv[1]), kv[0])
        )
    ]
    included_sources = 0
    hidden_sources = 0
    for items in data.incoming_by_topic.values():
        shown, hidden = _curate_topic_items(items)
        included_sources += len(shown)
        hidden_sources += hidden
    return ReportStats(
        new_sources=data.new_source_count,
        topics=data.topic_count,
        included_sources=included_sources,
        hidden_sources=hidden_sources,
        audit_path=audit_path,
        updated_concepts=len(data.concepts),
        concepts_created=data.concepts_created,
        concepts_updated=data.concepts_updated,
        existing_concepts_reused=data.existing_concepts_reused,
        attention_items=len(data.attention),
        total_concepts=total_concepts,
        total_lessons=total_lessons,
        total_playbooks=total_playbooks,
        lessons_base_path=lessons_base_path,
        playbooks_base_path=playbooks_base_path,
        glossary_terms=glossary_terms,
        topic_stats=topic_stats,
    )


def _parse_tag_list(value: str) -> list[str]:
    """Parse the simple concept `tags: [a, b]` shape used in frontmatter."""
    cleaned = value.strip().strip("[]")
    return [part.strip().strip("\"'") for part in cleaned.split(",") if part.strip()]


def _report_sources(fm_text: str, *, root: Path, report_dir: Path) -> list[ReportSource]:
    """Extract URL/archive/tier triples from a concept's `sources:` block."""
    sources: list[ReportSource] = []
    current: dict[str, str] = {}
    for line in _sources_block(fm_text).splitlines():
        match = _SOURCE_FIELD_RE.match(line)
        if not match:
            continue
        key, value = match.group(1).lower(), match.group(2).strip().strip("\"'")
        if key == "url" and current:
            sources.append(_report_source(current, root=root, report_dir=report_dir))
            current = {}
        current[key] = value
    if current:
        sources.append(_report_source(current, root=root, report_dir=report_dir))
    return sources


def _report_source(data: dict[str, str], *, root: Path, report_dir: Path) -> ReportSource:
    """Convert one parsed source mapping into report-link fields."""
    archive = data.get("archive", "")
    local_path = ""
    if archive:
        target = root / archive
        if target.exists():
            local_path = _report_rel_path(target, report_dir=report_dir)
    return ReportSource(
        url=data.get("url", ""),
        local_path=local_path,
        tier=data.get("tier", ""),
    )


def _report_concepts(root: Path, *, report_dir: Path) -> list[ReportConcept]:
    """Snapshot all live concept notes for the browser-grade report."""
    concepts_dir = root / "brain" / "concepts"
    if not concepts_dir.exists():
        return []
    concepts: list[ReportConcept] = []
    for path in sorted(concepts_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        fields, body = _split_frontmatter(text)
        if _is_seed_or_example(fields, body):
            continue
        fm_text = _frontmatter_block(text)
        updated = _concept_last_updated(fields, body)
        concepts.append(
            ReportConcept(
                name=_concept_name(fields, body, path),
                local_path=_report_rel_path(path, report_dir=report_dir),
                updated=updated.isoformat() if updated else "",
                tags=_parse_tag_list(fields.get("tags", "")),
                definition=_concept_definition(body),
                body=body.strip(),
                sources=_report_sources(fm_text, root=root, report_dir=report_dir),
            )
        )
    return concepts


def _report_vault_notes(
    root: Path, *, report_dir: Path, subdir: str, note_type: str
) -> list[ReportVaultNote]:
    """Snapshot lesson/playbook notes for the browser-grade report."""
    notes: list[ReportVaultNote] = []
    for note in scan_vault_notes(root / "brain" / subdir, note_type):
        path = Path(note.path)
        local_path = _report_rel_path(path, report_dir=report_dir) if path.exists() else ""
        notes.append(
            ReportVaultNote(
                title=note.title,
                note_type=note.note_type,
                local_path=local_path,
                tags=note.tags,
                metadata=note.metadata,
                summary=note.summary,
            )
        )
    return notes
