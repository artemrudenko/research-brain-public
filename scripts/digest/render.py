"""Render a gathered :class:`~scripts.digest.model.DigestData` to markdown.

The digest is a CURATED view, not an archive — this module owns the per-topic
credibility curation (`_curate_topic_items`) alongside the renderer itself.
Everything here is pure: no filesystem, no clock.
"""
from __future__ import annotations

import re

from scripts.corroborate import registrable_domain
from scripts.digest import strings
from scripts.digest.model import (
    QUIET_DIGEST_HTML_MARKER,
    DigestData,
    IncomingItem,
    VaultNoteItem,
    _md_link,
    _normalize_tier,
    _plural,
    _tier_marker,
)

# Per-topic curation: a digest is a CURATED view, not an archive (the raw articles
# live in pipeline/1-incoming/). Each topic shows only its top sources by
# credibility, with a "+N more" note for the remainder — so a noisy topic (e.g. 32
# new sources) stays scannable on Telegram/email instead of dumping every link.
DIGEST_LINKS_PER_TOPIC = 3
# Lower rank sorts first: high-credibility sources lead, unknown-tier trails.
# Distinct from `scan._CONCEPT_TIER_RANK` (the best-evidence pick rank, where
# HIGHER wins) — kept under its own name so the two ranks can't be confused.
_TIER_RANK = {"high": 0, "medium": 1, "low": 2}


def _curate_topic_items(
    items: list[IncomingItem], limit: int = DIGEST_LINKS_PER_TOPIC
) -> tuple[list[IncomingItem], int]:
    """Return (top `limit` items by credibility, count hidden).

    Ordering is by tier (high → medium → low → unknown); Python's stable sort
    preserves each tier's original scan order. The second element is how many
    items were dropped, so the caller can render an honest "+N more" note.
    """
    # Items are already de-duplicated by `scan_incoming`, so this only ranks and
    # slices. `_normalize_tier` may return None (absent/unknown); fold it to a
    # non-key string so it sorts last via the default rank.
    ranked = sorted(items, key=lambda it: _TIER_RANK.get(_normalize_tier(it.tier) or "", 3))
    return ranked[:limit], max(0, len(items) - limit)


# Each issue category in the validate_brain headline ("N orphans · M broken links
# · ...") paired with the word that labels its count. Matching the integer right
# before the label exactly — not the `"0 word"` substring — keeps "10 orphans"
# from being read as the "0 orphans" all-clear (BUG H1).
_HEALTH_ISSUE_WORDS = ("orphan", "broken", "missing", "uncited", "stale")


def _brain_health_clean(headline: str) -> bool:
    """True only when every issue category's count is exactly zero.

    Parses the integer immediately preceding each issue word (e.g. `10 orphans`)
    and requires it to be 0. A category absent from the headline is treated as
    clean, so a partial line never forces a false ⚠️.
    """
    for word in _HEALTH_ISSUE_WORDS:
        match = re.search(rf"(\d+)\s+{word}", headline, re.IGNORECASE)
        if match and int(match.group(1)) != 0:
            return False
    return True


# The extractor's Facts-bullet label ("**Fact.** …"); pure noise in a digest line.
_FACT_LABEL_RE = re.compile(r"^Fact[.:]\s+")
# Titles shorter than this may legitimately recur inside an unrelated summary;
# only a long shared prefix proves the title IS the summary's clipped twin.
_TITLE_ECHO_MIN_CHARS = 24


def _front_door_line(
    label: str,
    notes: list[VaultNoteItem],
    *,
    base_path: str,
    singular: str,
    plural: str,
    language: str = "en",
) -> list[str]:
    """Render one Lessons/Playbooks front-door summary block."""
    out = [
        strings.tr(
            language,
            "front_door_line",
            label=label,
            count_phrase=_plural(len(notes), singular, plural),
            base_path=base_path,
        )
    ]
    for note in notes[:3]:
        meta = f" · {note.metadata}" if note.metadata else ""
        summary = note.summary or ""
        # Auto-extracted lessons title themselves with the fact's clipped first
        # sentence, so `title · meta — summary` reads as the same text twice.
        # When the summary already contains the whole title, the summary alone
        # loses nothing — render it once, without the extractor's "Fact." label.
        title_core = note.title.rstrip("…").strip()
        if (
            summary
            and len(title_core) >= _TITLE_ECHO_MIN_CHARS
            and title_core.lower() in summary.lower()
        ):
            out.append(f"  - {_FACT_LABEL_RE.sub('', summary)}{meta}")
        else:
            summary_part = f" — {summary}" if summary else ""
            out.append(f"  - {note.title}{meta}{summary_part}")
    hidden = max(0, len(notes) - 3)
    if hidden:
        out.append(
            "  - _"
            + strings.tr(language, "more_in_base", hidden=hidden, base_path=base_path)
            + "_"
        )
    return out


def _render_vault_front_doors(data: DigestData) -> list[str]:
    """Weekly digest section that makes lessons/playbooks visible."""
    lang = data.language
    out = [strings.tr(lang, "front_doors_header"), ""]
    out.extend(
        _front_door_line(
            strings.tr(lang, "front_door_lessons"),
            data.lessons,
            base_path="brain/lessons.base",
            singular=strings.tr(lang, "front_door_active_note"),
            plural=strings.tr(lang, "front_door_active_notes"),
            language=lang,
        )
    )
    out.extend(
        _front_door_line(
            strings.tr(lang, "front_door_playbooks"),
            data.playbooks,
            base_path="brain/playbooks.base",
            singular=strings.tr(lang, "front_door_reusable_method"),
            plural=strings.tr(lang, "front_door_reusable_methods"),
            language=lang,
        )
    )
    out.append("")
    return out


def render(data: DigestData, *, daily: bool = False) -> str:
    """Render a DigestData to the digest markdown document.

    `daily` (ADR 0016) renders the light "inflow" variant — a `🗞 Daily digest`
    title and ONLY the `New sources` + `Needs attention` sections, omitting the
    weekly-synthesis sections (TL;DR, knowledge-base health, updated concepts,
    synthesis). When False the output is byte-for-byte the original weekly digest.
    """
    if (data.is_quiet_daily if daily else data.is_quiet):
        # The `Quiet week —` / `Quiet day —` line stays for human readers and
        # legacy detection; the HTML-comment marker is the structural,
        # language-independent contract for deliver.is_quiet_digest. The warm
        # follow-up reassures a non-developer reader the system is working fine.
        lang = data.language
        if daily:
            return (
                strings.tr(lang, "quiet_day_title", date=data.built_on.isoformat())
                + "\n\n"
                + strings.tr(
                    lang, "quiet_day_line",
                    days_phrase=strings.counted(lang, data.lookback_days, "day"),
                )
                + f"\n\n{QUIET_DIGEST_HTML_MARKER}\n"
            )
        return (
            strings.tr(lang, "quiet_week_title", date=data.built_on.isoformat())
            + "\n\n"
            + strings.tr(lang, "quiet_week_line", days=data.lookback_days)
            + f"\n\n{data.knowledge_base_changes_line}\n\n"
            f"{chr(10).join(_render_vault_front_doors(data))}"
            f"{QUIET_DIGEST_HTML_MARKER}\n"
        )

    lang = data.language
    if daily:
        out: list[str] = [
            strings.tr(lang, "daily_title", date=data.built_on.isoformat()), ""
        ]
        out.append(f"_{data.daily_header_summary}_")
    else:
        out = [strings.tr(lang, "weekly_title", date=data.built_on.isoformat()), ""]
        # One-line volume headline so a reader sees the shape of the week up front.
        out.append(f"_{data.header_summary}_")
    out.append("")

    if not daily:
        # TL;DR — up to three highlight lines capturing the essence of the week, so a
        # reader gets the gist before any per-topic detail. Omitted when there is
        # nothing to highlight (it never renders on a quiet week, which returns above).
        tldr = data.tldr_entries
        if tldr:
            out.append(strings.tr(lang, "tldr_header"))
            out.append("")
            for headline, subitems in tldr:
                out.append(f"- {headline}")
                out.extend(f"  - {item}" for item in subitems)
            out.append("")

        # One-line knowledge-base health note (omitted when no report exists). A green
        # dot when every issue count is zero, a warning otherwise.
        if data.brain_health:
            out.append(
                f"**{'🟢' if _brain_health_clean(data.brain_health) else '⚠️'} "
                f"{strings.tr(lang, 'knowledge_base_label').rstrip(':')}:** "
                f"{data.brain_health}"
            )
            out.append("")

        out.append(data.knowledge_base_changes_line)
        if data.existing_concepts_reused > 0:
            out.append(
                strings.tr(lang, "reused_line", count=data.existing_concepts_reused)
            )
        out.append("")

        # One-line OPERATIONAL health note — present only when the system is
        # DEGRADED (dead feed / failed delivery / overdue run), so the reader
        # learns about silent degradation from the digest itself.
        if data.ops_health:
            out.append(f"{strings.tr(lang, 'ops_health_label')} {data.ops_health}")
            out.append("")

        out.extend(_render_vault_front_doors(data))

    # New-sources window label: pluralized for the daily 1-day case ("last 1 day"),
    # kept verbatim ("last N days") on the weekly path so its output is unchanged.
    if strings.resolve(lang) == "ru":
        window_label = strings.counted(lang, data.lookback_days, "day")
    else:
        window_label = (
            _plural(data.lookback_days, "day") if daily else f"{data.lookback_days} days"
        )
    out.append(strings.tr(lang, "new_sources_header", window=window_label))
    out.append("")
    if data.incoming_by_topic:
        for topic in sorted(data.incoming_by_topic):
            items = data.incoming_by_topic[topic]
            # 🏷 + count badge makes each topic group stand out and shows the FULL
            # topic volume, even though only the top sources are listed below.
            out.append(f"### 🏷 {topic} ({len(items)})")
            # Agent-authored one-line synthesis lead, when present: a prose "what
            # happened this week" under the badge, for EVERY topic whose sidecar
            # is current (the freshness gate ran at scan time). On the headless
            # path (no sidecar) only the busiest topic falls back to a derived
            # lead — deriving prose for all topics without an LLM would be noise.
            # A lead is a weekly-synthesis artifact, so the daily inflow digest
            # renders none at all, sidecar or derived (ADR 0016).
            lead: str | None = None
            if not daily:
                lead = data.topic_leads.get(topic)
                if not lead and data.busiest_topic and topic == data.busiest_topic[0]:
                    lead = data.busiest_topic_lead
            if lead:
                out.append(f"_{lead}_")
            if topic in data.debut_topics:
                # First-week honesty: the curated-view promise doesn't hold yet.
                out.append("_" + strings.tr(lang, "debut_topic_caveat") + "_")
            # Curated view: the most credible few, not every article (the full set
            # stays in pipeline/1-incoming/). Keeps a noisy topic scannable.
            shown, hidden = _curate_topic_items(items)
            for item in shown:
                marker = _tier_marker(item.tier)
                # Card style (unified with concepts): a bold title (a clickable
                # link when a URL is present) heads the entry; the takeaway sits
                # below in a quote block, set apart but fully visible.
                titled = _md_link(item.title, item.url) if item.url else f'"{item.title}"'
                out.append(f"- **{titled}**{marker}")
                if item.takeaway:
                    out.append(f"  > {item.takeaway}")
            if hidden:
                # Honest pointer to the remainder (curation is by credibility).
                out.append(
                    "- _"
                    + strings.tr(
                        lang, "more_by_credibility", hidden=hidden, shown=len(shown)
                    )
                    + "_"
                )
            out.append("")
    else:
        out.append(strings.tr(lang, "no_new_sources"))
        out.append("")

    # Weekly-synthesis sections — updated concepts and the synthesis narrative —
    # are omitted from the light daily "inflow" digest (ADR 0016).
    if not daily:
        out.append(
            strings.tr(
                lang,
                "concepts_header",
                days=data.lookback_days,
                window=strings.counted(lang, data.lookback_days, "day"),
            )
        )
        out.append("")
        if data.concepts:
            for concept in data.concepts:
                marker = _tier_marker(concept.tier)
                # Card style: a bold name heads the entry, a compact badge line
                # carries the metadata (corroboration trust + source), and the full
                # definition follows in a quote block — set apart but fully visible.
                out.append(f"- **{concept.name}**{marker}")
                # Badge line: the plain-language corroboration trust (CONVENTIONS §16)
                # and a domain-labelled source link, joined on one line. Omitted when
                # the concept cites no sources (no trust, no link).
                badges: list[str] = []
                if concept.trust:
                    badges.append(concept.trust)
                if concept.source_url:
                    domain = registrable_domain(concept.source_url) or "source"
                    badges.append(f"🔗 [{domain}]({concept.source_url})")
                if badges:
                    out.append(f"  - {' · '.join(badges)}")
                if concept.definition:
                    out.append(f"  > {concept.definition}")
            out.append("")
        else:
            out.append(strings.tr(lang, "no_concept_updates"))
            out.append("")

        # Synthesis section is omitted entirely when there is no run log.
        if data.synthesis_summary:
            out.append(strings.tr(lang, "synthesis_header"))
            out.append("")
            out.append(data.synthesis_summary)  # narrative prose, not a filename bullet
            out.append("")

    out.append(strings.tr(lang, "attention_header"))
    out.append("")
    if data.attention:
        for att in data.attention:
            out.append(
                f"- {att.relpath} "
                f"({strings.tr(lang, 'collected_label')} {att.collected.isoformat()})"
            )
        out.append("")
    else:
        out.append(strings.tr(lang, "nothing_pending"))
        out.append("")

    return "\n".join(out).rstrip() + "\n"
