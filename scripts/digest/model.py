"""Data types and shared text primitives for the digest builder.

Everything a scanned digest *is* — the item dataclasses, the aggregate
:class:`DigestData` (with its TL;DR / quiet-week derivations), the gate
exceptions, and the small pure text helpers both the scan and render layers
lean on. Nothing here touches the filesystem.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import strings

# Printed on stdout (and only then) when the week is quiet, so a cron caller can
# grep for it and decide whether to skip the delivery step.
QUIET_WEEK_MARKER = "QUIET_WEEK"

# Written INTO a quiet digest (weekly or daily) as its own line, so
# `deliver.py --skip-quiet` detects quietness structurally instead of matching
# the English "Quiet week —" wording (which breaks on delivery.language: ru or
# an agent-built digest phrased differently). Invisible in every HTML render.
# deliver.py keeps an inline copy (no cross-package import); a drift test pins
# the two constants equal.
QUIET_DIGEST_HTML_MARKER = "<!-- research-brain: quiet-digest -->"

# Source-credibility tiers (CONVENTIONS §12). Anything outside this set — or an
# absent field — renders no marker, so the digest stays clean by default.
TIER_VALUES = frozenset({"high", "medium", "low"})


class SynthesisLogMissing(RuntimeError):
    """Raised when the synthesis barrier is on but today's run log is absent.

    Signals that brain/ may be half-written or never synthesized this run, so the
    digest must NOT be built. The CLI maps this to a non-zero exit; callers that
    invoke `build_digest` directly can catch it.
    """


class IncomingNotSanitized(RuntimeError):
    """Raised when `--require-sanitized` is on but an incoming article lacks a
    current sanitized companion (missing / stale / corrupt).

    The digest ships incoming-article text to a reader, so an un-sanitized article
    could surface unstripped injection text. With the barrier on, the build fails
    closed (writes nothing) instead — and what it does render always comes from the
    current sanitized companion (see `scan_incoming`), never the raw article.
    The CLI maps this to a non-zero exit; direct callers can catch it.
    """


def _normalize_tier(value: str | None) -> str | None:
    """Return a known tier (high/medium/low), else None for an absent/unknown value."""
    if not value:
        return None
    cleaned = value.strip().strip("\"'").lower()
    return cleaned if cleaned in TIER_VALUES else None


def _tier_marker(tier: str | None) -> str:
    """Render a high-credibility source as a trailing ` ⭐`; nothing otherwise.

    A star flags the most trustworthy sources without cluttering every line with a
    `[medium]`/`[low]` tag — the single-source trust line already conveys caution.
    """
    return " ⭐" if tier == "high" else ""


def _md_link(text: str, url: str) -> str:
    """Render a markdown link whose label can't break out of the `[...]` brackets.

    A raw `]` (or `(`/`)`) in a title otherwise closes the label early and lets a
    `](evil)` sequence hijack the link target (BUG L3). Escaping the bracket/paren
    characters in the label keeps the title readable while the only real link
    target stays `url`.
    """
    safe = (
        text.replace("\\", "\\\\")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )
    return f"[{safe}]({url})"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    """Format a count with a noun, pluralizing by adding `s` unless given a form.

    e.g. `_plural(1, "new source") -> "1 new source"`,
    `_plural(3, "new source") -> "3 new sources"`.
    """
    word = singular if count == 1 else (plural or singular + "s")
    return f"{count} {word}"


@dataclass
class IncomingItem:
    """A recently collected article worth surfacing in the digest."""

    title: str
    topic: str
    takeaway: str
    tier: str | None = None
    url: str = ""  # the article's source URL, rendered as a clickable link
    # Stable identity for dedup when `url` is empty: the RAW title, so a sanitized
    # display title can't split two copies of the same source. Falls back to `title`.
    dedup_key: str = ""
    # Length of the DISPLAY body (sanitized companion when current) — the build
    # turns it into the report's reading-time estimate without re-reading files.
    text_chars: int = 0


@dataclass
class ConceptItem:
    """A recently updated concept note worth surfacing in the digest."""

    name: str
    definition: str
    tier: str | None = None
    # Plain-language corroboration line (CONVENTIONS §16); "" when the concept
    # cites no sources, so it renders no trust line (graceful).
    trust: str = ""
    source_url: str = ""  # first cited source URL, rendered as a "source" link


@dataclass
class VaultNoteItem:
    """A lesson or playbook note surfaced in the digest/report vault snapshot."""

    title: str
    note_type: str
    path: str = ""
    metadata: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class AttentionItem:
    """An incoming file that has gone stale without being processed."""

    relpath: str
    collected: date


@dataclass
class DigestData:
    """Everything gathered for one digest, ready to render to markdown."""

    built_on: date
    lookback_days: int
    # Chrome language (delivery.language) — 'en' keeps historical output
    # byte-identical; see scripts.digest.strings.
    language: str = "en"
    incoming_by_topic: dict[str, list[IncomingItem]] = field(default_factory=dict)
    concepts: list[ConceptItem] = field(default_factory=list)
    # Per-topic one-line synthesis lead (agent-authored; empty for topics without
    # a current sidecar). The WEEKLY render shows every present lead under its
    # topic badge; the daily inflow digest renders none (ADR 0016).
    topic_leads: dict[str, str] = field(default_factory=dict)
    synthesis_summary: str | None = None
    brain_health: str | None = None
    concepts_created: int = 0
    concepts_updated: int = 0
    existing_concepts_reused: int = 0
    # Topics whose registry history STARTS inside the lookback window (or is
    # absent entirely) — their first week, before per-topic rules settled.
    debut_topics: set[str] = field(default_factory=set)
    lessons: list[VaultNoteItem] = field(default_factory=list)
    playbooks: list[VaultNoteItem] = field(default_factory=list)
    # One-line operational summary (dead feeds / failed delivery / overdue run)
    # from health.ops_headline — set ONLY when the system is DEGRADED, so a
    # healthy week's digest stays clean.
    ops_health: str | None = None
    attention: list[AttentionItem] = field(default_factory=list)

    @property
    def new_source_count(self) -> int:
        """Count of DISTINCT in-window sources across all topics.

        Dedup runs per topic, so one URL filed under two `category:` values shows
        once under each topic (legitimate display) but is still a single source —
        count keys globally (URL, or title when no URL) so totals never inflate.
        """
        keys = {item.url or item.title for item in self._incoming_in_order()}
        return len(keys)

    @property
    def topic_count(self) -> int:
        """Number of distinct topics that have at least one new source."""
        return len(self.incoming_by_topic)

    @property
    def is_quiet(self) -> bool:
        """A week is 'quiet' only with no new sources, concepts, or attention items.

        A backlog of stale unprocessed sources (the "Needs attention" list) must
        keep the digest non-quiet so it renders and surfaces them — otherwise the
        quiet one-liner would silently hide a growing backlog.
        """
        return (
            self.new_source_count == 0
            and len(self.concepts) == 0
            and self.concepts_created == 0
            and self.concepts_updated == 0
            and self.existing_concepts_reused == 0
            and not self.attention
        )

    @property
    def knowledge_base_changes_line(self) -> str:
        """Stable digest line for per-run concept writes from the synthesis log."""
        return strings.tr(
            self.language,
            "kb_changes_line",
            created=self.concepts_created,
            updated=self.concepts_updated,
        )

    @property
    def header_summary(self) -> str:
        """One-line, pluralized headline of the week's volume.

        e.g. "3 new sources across 2 topics, 1 updated concept." — gives a
        non-technical reader the shape of the week before any detail.
        """
        return strings.tr(
            self.language,
            "header_summary",
            sources_phrase=strings.counted(self.language, self.new_source_count, "new source"),
            topics_phrase=strings.counted(self.language, self.topic_count, "topic"),
            concepts_phrase=strings.counted(self.language, len(self.concepts), "updated concept"),
        )

    @property
    def is_quiet_daily(self) -> bool:
        """A DAILY digest is quiet with no new sources and no attention items.

        Unlike the weekly :pyattr:`is_quiet`, concepts are irrelevant — the daily
        "inflow" render never shows them (ADR 0016), so only inflow (new sources)
        and the attention backlog decide whether there is anything to say.
        """
        return self.new_source_count == 0 and not self.attention

    @property
    def daily_header_summary(self) -> str:
        """One-line volume headline for the daily digest (sources only, no concepts)."""
        return strings.tr(
            self.language,
            "daily_header_summary",
            sources_phrase=strings.counted(self.language, self.new_source_count, "new source"),
            topics_phrase=strings.counted(self.language, self.topic_count, "topic"),
        )

    def _incoming_in_order(self) -> list[IncomingItem]:
        """All in-window incoming items, topics alphabetical, items in scan order.

        A single stable ordering both the TL;DR standout pick and any flat scan
        can share, matching the alphabetical topic order used when rendering.
        """
        items: list[IncomingItem] = []
        for topic in sorted(self.incoming_by_topic):
            items.extend(self.incoming_by_topic[topic])
        return items

    @property
    def busiest_topic(self) -> tuple[str, int] | None:
        """The topic with the most new sources (alphabetical tie-break), or None."""
        if not self.incoming_by_topic:
            return None
        topic, items = max(
            sorted(self.incoming_by_topic.items()),
            key=lambda kv: len(kv[1]),
        )
        return topic, len(items)

    @staticmethod
    def _pick_standout(items: list[IncomingItem]) -> IncomingItem | None:
        """A single noteworthy source from `items`: the first high-tier one, else
        the first. Shared by the global TL;DR standout and the per-topic lead."""
        for item in items:
            if item.tier == "high":
                return item
        return items[0] if items else None

    def _standout_source(self) -> IncomingItem | None:
        """The single most noteworthy source across every topic."""
        return self._pick_standout(self._incoming_in_order())

    @property
    def busiest_topic_lead(self) -> str | None:
        """A deterministic one-line synthesis lead for the busiest topic.

        The agent-authored `digest-lead.md` sidecars are absent on the headless
        path, so its digest carried no per-topic prose at all. This fills that gap
        for the single busiest topic — derived purely from structured data (the
        source count + the topic's own top source), so it needs no LLM. Returned
        only when there is more than one topic (with a single topic the "most
        active" framing is meaningless and the TL;DR already states the count)."""
        busiest = self.busiest_topic
        if busiest is None or self.topic_count <= 1:
            return None
        topic, count = busiest
        sources = _plural(count, "new source")
        top = self._pick_standout(self.incoming_by_topic.get(topic, []))
        if top is None:
            return f"The week's most active topic — {sources}."
        return f'The week\'s most active topic — {sources}, led by "{top.title}".'

    @property
    def tldr_entries(self) -> list[tuple[str, list[str]]]:
        """Up to three "essence of the week" highlights as (headline, sub-items).

        Distinct from `header_summary` (which only counts volume): these surface
        *what* the week was about — where reading concentrated, the single most
        credible source to read, and which concepts moved. The concepts highlight
        carries its names as sub-items (rendered one per line) rather than a
        comma-run, which reads far better in Telegram and email.
        """
        entries: list[tuple[str, list[str]]] = []

        # 1. Where the week's reading concentrated.
        busiest = self.busiest_topic
        if busiest:
            topic, count = busiest
            if self.topic_count > 1:
                share = strings.tr(
                    self.language, "tldr_share", count=count,
                    total_phrase=strings.counted(self.language, self.new_source_count, "new source"),
                )
                entries.append(
                    (strings.tr(self.language, "tldr_most_active", topic=topic, share=share), [])
                )
            else:
                entries.append((
                    strings.tr(
                        self.language, "tldr_only_topic", topic=topic,
                        count_phrase=strings.counted(self.language, count, "new source"),
                    ),
                    [],
                ))

        # 2. The single source most worth a reader's time.
        standout = self._standout_source()
        if standout:
            titled = (
                _md_link(standout.title, standout.url)
                if standout.url
                else standout.title
            )
            entries.append((
                strings.tr(
                    self.language, "tldr_worth_a_look",
                    titled=titled, marker=_tier_marker(standout.tier),
                ),
                [],
            ))

        # 3. The concepts that moved this week — every name as its own sub-item.
        #    The TL;DR is the at-a-glance summary, so it lists all of them rather
        #    than hiding the tail behind a "…and N more" collapse.
        if self.concepts:
            names = [concept.name for concept in self.concepts]
            entries.append((
                strings.tr(
                    self.language, "tldr_concepts_updated",
                    count_phrase=strings.counted(self.language, len(self.concepts), "concept"),
                ),
                names,
            ))

        return entries[:3]

    @property
    def tldr_lines(self) -> list[str]:
        """The TL;DR headlines only (sub-items dropped) — a flat list for reuse."""
        return [headline for headline, _ in self.tldr_entries]
