#!/usr/bin/env python3
"""
digest_report_html.py — render the canonical digest markdown as a dynamic,
browser-grade HTML report (the "viewing page", distinct from the email HTML).

Where `email_html.py` targets email clients (inline styles, no JS, table shell),
this targets a *browser*: a self-contained page in the warm design of
`docs/decks/research-brain-showcase.html` — a hero band, KPI cards, section cards, a
plain-language read — with tasteful CSS entrance animations and a tiny,
dependency-free script that counts the headline numbers up and reveals sections
on scroll. It reuses `email_html`'s markdown parser and inline renderer so both
outputs read the exact same digest structure and escaping discipline; only the
presentation layer differs.

The runtime stays stdlib-only and deterministic (no timestamps, no randomness),
so the same markdown always yields byte-identical HTML. Google Fonts are linked
(a browser nicety) with a system-font fallback, so the page renders fine offline.

Layout: this file is the entry point + the digest-body/pulse/glossary rendering
and the top-level document assembly. The data shapes live in `report_models.py`
(`Report*` dataclasses — no rendering logic, so other report modules can import
them without a circular dependency on this file), and the three largest,
self-contained tabs are split into their own modules: `report_audit.py` (the
per-topic source-selection drilldown), `report_concepts.py` (the Concepts tab
+ `obsidian://` deep links), and `report_vault.py` (the lessons/playbooks tab).
`report_inline.py` holds the shared inline-markdown helper (`inline`) so those
modules don't import it back from here. Every name from all of these is
re-exported below, so `from scripts.delivery.digest_report_html import
ReportConcept` (tests, `scripts/digest/report_inputs.py`, `build_digest.py`)
keeps working unchanged. The static presentation payload — the embedded
stylesheet, the count-up/reveal script, and the font links — lives in
`report_theme.py`.

Semantics/ARIA: the hero is a `role="banner"` landmark, the digest body is
a labelled `<main>` region, and the KPI strip is an `aria-label`led group. The
heading hierarchy (single hero `<h1>`, section `<h2>`s) is preserved, and
`prefers-reduced-motion` disables the reveal animation.

Public API: :func:`render_digest_report`.
"""

from __future__ import annotations

import re

# Reuse the trusted digest parser + inline renderer (DRY): one markdown contract,
# one escaping discipline, shared with the email transport.
from scripts.delivery.email_html import Block, attr, esc, parse
from scripts.delivery.report_audit import (  # noqa: F401 — re-exported
    _is_http_url,
    _reason_label,
    _render_audit,
    _topic_health_label,
)
from scripts.delivery.report_concepts import (  # noqa: F401 — re-exported
    _concept_note_excerpt,
    _obsidian_uri,
    _render_concepts,
)
from scripts.delivery.report_inline import inline
from scripts.delivery.report_models import (  # noqa: F401 — re-exported
    ReportAuditDecision,
    ReportAuditTopic,
    ReportConcept,
    ReportGlossaryTerm,
    ReportSource,
    ReportStats,
    ReportTopicStat,
    ReportVaultNote,
)

# The static presentation payload (embedded CSS, the count-up/reveal script,
# the font links) lives beside the render logic in report_theme.
from scripts.delivery.report_theme import REPORT_FONT_LINKS, REPORT_SCRIPT, REPORT_STYLE
from scripts.delivery.report_vault import _render_vault, _vault_note_cards  # noqa: F401

# Headline "<number> <label>" pairs in the volume subtitle become KPI cards. The
# label runs until an "across" filler, a comma/period, or end — tuned to our own
# rendered subtitle ("N new sources across M topics, K updated concepts.").
_KPI_RE = re.compile(r"(\d[\d,]*)\s+([a-z][a-z ]*?)(?:\s+across\b|\s*[,.]|$)", re.I)
_MAX_KPIS = 4


def _first(blocks: list[Block], kind: str) -> str:
    """The text of the first block of `kind`, or '' when absent."""
    for block in blocks:
        if block.kind == kind:
            return block.text
    return ""


def _extract_kpis(subtitle: str) -> list[tuple[str, str]]:
    """Pull up to `_MAX_KPIS` (number, label) pairs from the volume subtitle."""
    pairs = [(m.group(1), m.group(2).strip()) for m in _KPI_RE.finditer(subtitle)]
    return pairs[:_MAX_KPIS]


def _render_kpis(kpis: list[tuple[str, str]]) -> str:
    """Render the KPI cards; the number carries data-target for the count-up."""
    if not kpis:
        return ""
    cards = "".join(
        f'<div class="rb-kpi reveal" style="animation-delay:{i * 70}ms">'
        f'<div class="rb-kpi-num num" data-target="{attr(value.replace(",", ""))}">'
        f"{esc(value)}</div>"
        f'<div class="rb-kpi-lbl">{esc(label)}</div></div>'
        for i, (value, label) in enumerate(kpis)
    )
    # Labelled region so screen readers announce the headline-metric strip.
    return f'<div class="rb-kpis" role="group" aria-label="Key metrics">{cards}</div>'


# One topic-volume line inside the embedded trends section, language-agnostic:
# a bold topic followed by an up/down arrow with its signed delta. Flat weeks
# (→) intentionally don't match — a flat arrow on every badge is noise.
_MOMENTUM_RE = re.compile(r"\*\*(?P<topic>[^*]+)\*\*[^(\n]*\((?P<arrow>[↑↓])\s*(?P<delta>[+\-−]?[\d,]+)")

# A sources-section topic badge: "🏷 <topic> (<count>)".
_TOPIC_BADGE_RE = re.compile(r"^🏷\s*(?P<topic>\S+)\s*\(\d+\)$")


def _extract_momentum(blocks: list[Block]) -> dict[str, tuple[str, str]]:
    """Map topic → (arrow, signed delta) from the digest's trends lines."""
    momentum: dict[str, tuple[str, str]] = {}
    for block in blocks:
        for item in block.items:
            match = _MOMENTUM_RE.search(item.text)
            if match:
                momentum.setdefault(
                    match.group("topic").strip(),
                    (match.group("arrow"), match.group("delta")),
                )
    return momentum


def _render_badge(block: Block, momentum: dict[str, tuple[str, str]]) -> str:
    """Render a topic badge, annotated with its week-over-week momentum arrow."""
    label = inline(block.text)
    match = _TOPIC_BADGE_RE.match(block.text.strip())
    if match and match.group("topic") in momentum:
        arrow, delta = momentum[match.group("topic")]
        direction = "up" if arrow == "↑" else "down"
        return (
            f'<div class="rb-badge">{label} '
            f'<span class="rb-mom {direction}" title="{attr(delta)} vs last week">{arrow}</span></div>'
        )
    return f'<div class="rb-badge">{label}</div>'


def _tier_badge(tier: str) -> str:
    """A small source-credibility chip (high/medium/low) for a surfaced pick.

    Low-tier picks must not read as equal to verified ones, so the tier is shown
    inline with a class the stylesheet colours distinctly (CONVENTIONS §12).
    """
    label = tier if tier in ("high", "medium", "low") else "untiered"
    return f'<span class="rb-tier rb-tier-{label}">{esc(label)}</span>'


def _star_button(url: str) -> str:
    """The pick toggle: the script wires it to per-digest localStorage."""
    return (
        f'<button class="rb-star" data-url="{attr(url)}" aria-pressed="false" '
        'aria-label="Save to picks" title="Save to picks">☆</button>'
    )


def _render_list(
    block: Block, why: dict[str, str] | None = None, starrable: bool = False
) -> str:
    """Render a bullet run: level-0 items as rows, level-1 as muted sub-lines.

    `why` maps a source URL to its humanized curation line; matching rows get a
    muted "why am I seeing this" chip. `starrable` rows with a link also carry
    their URL as data plus a pick toggle. Both are sources-section affordances —
    the caller scopes them; TL;DR and other lists stay plain.
    """
    rows: list[str] = []
    for item in block.items:
        if item.level == 0:
            link = re.search(r"\]\((https?://[^()\s]+)\)", item.text)
            url = link.group(1) if link else ""
            chip = ""
            if why and url and url in why:
                chip = f' <span class="rb-why">{esc(why[url])}</span>'
            if starrable and url:
                rows.append(
                    f'<li class="rb-li" data-url="{attr(url)}">'
                    f"{inline(item.text)}{chip} {_star_button(url)}</li>"
                )
            else:
                rows.append(f'<li class="rb-li">{inline(item.text)}{chip}</li>')
        else:
            rows.append(f'<li class="rb-sub">{inline(item.text)}</li>')
    return f'<ul class="rb-list">{"".join(rows)}</ul>'


def _render_body_block(
    block: Block,
    momentum: dict[str, tuple[str, str]] | None = None,
    why: dict[str, str] | None = None,
    starrable: bool = False,
) -> str:
    """Render one non-hero block to its showcase-styled HTML fragment."""
    if block.kind == "callout":  # the TL;DR block, with its bullets as children
        inner = "".join(_render_body_block(child) for child in block.children)
        return (
            '<section class="rb-callout"><div class="rb-callout-h">⚡ '
            f"{inline(block.text.replace('⚡', '').strip())}</div>{inner}</section>"
        )
    if block.kind == "h2":
        return f'<h2 class="rb-sec">{inline(block.text)}</h2>'
    if block.kind == "badge":
        return _render_badge(block, momentum or {})
    if block.kind == "list":
        return _render_list(block, why, starrable)
    if block.kind == "quote":
        return f'<blockquote class="rb-quote">{inline(block.text)}</blockquote>'
    if block.kind == "para":
        return f'<p class="rb-p">{inline(block.text)}</p>'
    return ""  # h1 / subtitle live in the hero, not the body


def _why_map(audit_topics: list[ReportAuditTopic]) -> dict[str, str]:
    """Map each SHOWN source URL to its humanized 'tier · reason' chip text."""
    why: dict[str, str] = {}
    for topic in audit_topics:
        for decision in topic.decisions:
            if decision.included and decision.url:
                tier = decision.tier or "untiered"
                why.setdefault(decision.url, f"{tier} · {_reason_label(decision.reason)}")
    return why


def _render_read_today(audit_topics: list[ReportAuditTopic]) -> str:
    """The cross-topic 'Read today' strip: top-3 shown sources by tier, then rank.

    Turns the report from an inventory into a morning reading list: the three
    strongest picks across ALL topics, each with an honest reading estimate.
    """
    order = {"high": 0, "medium": 1, "low": 2}
    picks = [
        (decision, topic.topic)
        for topic in audit_topics
        for decision in topic.decisions
        if decision.included and decision.url
    ]
    if not picks:
        return ""
    picks.sort(key=lambda p: (order.get(p[0].tier, 3), p[0].rank or 99, p[0].title))
    rows = "".join(
        f'<li class="rb-today-item" data-url="{attr(decision.url)}">'
        f'<a href="{attr(decision.url)}">{esc(decision.title)}</a>'
        f'<span class="rb-chip">{esc(topic)}</span>'
        f'{_tier_badge(decision.tier)}'
        + (
            f'<span class="rb-mini">≈ {decision.read_minutes} min</span>'
            if decision.read_minutes
            else ""
        )
        + f" {_star_button(decision.url)}</li>"
        for decision, topic in picks[:3]
    )
    # Whether any surfaced pick rests on a low-tier source — drives an honest note.
    has_low = any(d.tier == "low" for d, _ in picks[:3])
    low_note = (
        '<p class="rb-p rb-tier-note"><em>⚠ A low-tier pick is unverified — '
        'confirm against a primary source before relying on it.</em></p>'
        if has_low
        else ""
    )
    return (
        '<section class="rb-card reveal" id="readToday">'
        '<h2 class="rb-sec">🎯 Read today</h2>'
        '<p class="rb-p"><em>Top picks across every topic — ranked by source tier, then rank.</em></p>'
        f"{low_note}"
        f'<ul class="rb-list rb-today">{rows}</ul>'
        "</section>"
    )


def _render_body(
    blocks: list[Block],
    momentum: dict[str, tuple[str, str]] | None = None,
    why: dict[str, str] | None = None,
) -> str:
    """Render the body: every block except the hero's h1/subtitle, with staggered reveal.

    Each section (h2) opens a fresh card; following blocks fold into it until the
    next section, so the page reads as a stack of section cards. The why-chips
    apply only inside the sources section (📰) — TL;DR and other lists stay clean.
    """
    cards: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            cards.append("".join(current))
            current.clear()

    in_sources = False
    for block in blocks:
        if block.kind in ("h1", "subtitle"):
            continue
        if block.kind in ("h2", "callout") and current:
            flush()
        if block.kind == "h2":
            in_sources = block.text.strip().startswith("📰")
            if in_sources:
                # The read-progress slot: the script fills "N of M read" from
                # localStorage; a JS-less render simply shows nothing.
                current.append(
                    f'<h2 class="rb-sec">{inline(block.text)}'
                    '<span class="rb-progress" id="readProgress"></span></h2>'
                )
                continue
        current.append(
            _render_body_block(
                block, momentum, why if in_sources else None, starrable=in_sources
            )
        )
    flush()

    return "".join(
        f'<section class="rb-card reveal" style="animation-delay:{i * 60}ms">{card}</section>'
        for i, card in enumerate(cards)
    )


def _is_glossary_heading(block: Block) -> bool:
    """True for the digest glossary section heading."""
    return block.kind == "h2" and "glossary" in block.text.lower()


def _is_trends_heading(block: Block) -> bool:
    """True for the digest trends section heading."""
    return block.kind == "h2" and "trends" in block.text.lower()


def _split_report_sections(blocks: list[Block]) -> tuple[list[Block], list[Block], list[Block]]:
    """Move markdown glossary and trends sections to their own report tabs."""
    digest: list[Block] = []
    glossary: list[Block] = []
    trends: list[Block] = []
    target = digest
    for block in blocks:
        if _is_glossary_heading(block):
            target = glossary
        elif _is_trends_heading(block):
            target = trends
        target.append(block)
    return digest, glossary, trends


def _render_trends(blocks: list[Block]) -> str:
    """Render the extracted trends section."""
    content = _render_body(blocks)
    if not content.strip():
        content = (
            '<section class="rb-card reveal">'
            '<p class="rb-empty">No trends section was generated for this digest.</p>'
            "</section>"
        )
    return content


def _render_stats(stats: ReportStats | None) -> str:
    """Render collection and synthesis stats."""
    if stats is None:
        return (
            '<section class="rb-card reveal">'
            '<p class="rb-empty">No stats snapshot is available for this report.</p>'
            "</section>"
        )
    metrics = [
        ("New sources", stats.new_sources),
        ("Topics", stats.topics),
        ("Concept cards shown", stats.updated_concepts),
        ("Created (last synthesis)", stats.concepts_created),
        ("Updated (last synthesis)", stats.concepts_updated),
        ("Reused during synthesis", stats.existing_concepts_reused),
        ("Needs attention", stats.attention_items),
        ("Total concepts", stats.total_concepts),
        ("Lessons", stats.total_lessons),
        ("Playbooks", stats.total_playbooks),
        ("Glossary terms", stats.glossary_terms),
    ]
    cards = "".join(
        '<div class="rb-stat">'
        f'<div class="rb-stat-num num">{esc(str(value))}</div>'
        f'<div class="rb-stat-lbl">{esc(label)}</div>'
        "</div>"
        for label, value in metrics
    )
    # Comparative data gets a decorative bar scaled to the busiest topic so
    # volumes scan at a glance; the number stays the accessible data point.
    max_sources = max((item.sources for item in stats.topic_stats), default=0)
    topic_rows = "".join(
        f"<li><span>{esc(item.topic)}</span>"
        '<span class="rb-topic-bar" aria-hidden="true">'
        f'<i style="width:{round(100 * item.sources / max_sources) if max_sources else 0}%">'
        "</i></span>"
        f'<strong class="num">{item.sources}</strong></li>'
        for item in stats.topic_stats
    )
    if not topic_rows:
        topic_rows = '<li><span>No collected sources in this window.</span><strong>0</strong></li>'
    audit_link = (
        f'<a href="{attr(stats.audit_path)}">open audit sidecar</a>'
        if stats.audit_path
        else '<span class="rb-muted">No audit sidecar path available.</span>'
    )
    return (
        '<section class="rb-card reveal">'
        '<h2 class="rb-sec">Collection stats</h2>'
        f'<div class="rb-stat-grid">{cards}</div>'
        '<h2 class="rb-sec rb-subsec">Digest audit</h2>'
        f'<p class="rb-p" aria-label="Digest audit: {stats.included_sources} shown, '
        f'{stats.hidden_sources} hidden by topic cap">'
        f'<strong class="num">{stats.included_sources}</strong> shown · '
        f'<strong class="num">{stats.hidden_sources}</strong> hidden by topic cap · '
        f"{audit_link}"
        "</p>"
        '<h2 class="rb-sec rb-subsec">Sources by topic</h2>'
        f'<ul class="rb-topic-stats">{topic_rows}</ul>'
        "</section>"
    )


def _render_pulse(
    stats: ReportStats | None,
    trends_blocks: list[Block],
    audit_topics: list[ReportAuditTopic],
) -> str:
    """The merged 'this week in numbers' tab: stats → trends → folded audit.

    Trends/Stats/Audit shared one mental model but three tab slots; the short
    weekly-glance content leads, and the long operator drilldown folds closed
    at the bottom so it can't bury the numbers (2026-07-14 review).
    """
    audit = _render_audit(audit_topics)
    fold = (
        '<section class="rb-card reveal"><details class="rb-audit-fold">'
        "<summary>🔍 Source audit — why each source was shown or hidden</summary>"
        f"{audit}</details></section>"
        if audit
        else ""
    )
    return _render_stats(stats) + _render_trends(trends_blocks) + fold


def _render_glossary(
    blocks: list[Block], glossary_terms: list[ReportGlossaryTerm]
) -> str:
    """Render the glossary tab as a searchable full glossary."""
    if glossary_terms:
        rows = [
            '<div class="rb-toolrow">'
            '<input id="glossarySearch" class="rb-search" type="search" '
            'placeholder="Search glossary terms" aria-label="Search glossary terms">'
            f'<span class="rb-count num">{len(glossary_terms)} terms</span>'
            "</div>"
        ]
        for idx, item in enumerate(glossary_terms):
            searchable = f"{item.term} {item.explanation}".lower()
            rows.append(
                f'<article class="rb-term reveal" data-search="{attr(searchable)}" '
                f'style="animation-delay:{idx * 18}ms">'
                f'<h3>{esc(item.term)}</h3>'
                f'<p>{inline(item.explanation)}</p>'
                "</article>"
            )
        return "".join(rows)

    # Fallback for older callers/tests that only pass digest markdown. In normal
    # build_digest --report output this is replaced by the full config glossary.
    content = "".join(_render_body_block(block) for block in blocks if block.kind != "h1")
    if not content.strip():
        content = '<p class="rb-empty">No glossary terms were used in this digest.</p>'
    return f'<section class="rb-card reveal">{content}</section>'


def render_digest_report(
    markdown: str,
    *,
    title: str | None = None,
    concepts: list[ReportConcept] | None = None,
    lessons: list[ReportVaultNote] | None = None,
    playbooks: list[ReportVaultNote] | None = None,
    glossary_terms: list[ReportGlossaryTerm] | None = None,
    stats: ReportStats | None = None,
    audit_topics: list[ReportAuditTopic] | None = None,
    prev_report: str = "",
) -> str:
    """Render digest `markdown` as a standalone, dynamic HTML report document.

    `title` overrides the page/hero title (defaults to the digest's H1). The
    output is a complete `<!DOCTYPE html>` document with embedded styles + a
    dependency-free script; it is deterministic for a given input.
    """
    blocks = parse(markdown)
    doc_title = title or _first(blocks, "h1") or "Research digest"
    subtitle = _first(blocks, "subtitle")
    kpis = _extract_kpis(subtitle)
    digest_blocks, glossary_blocks, trends_blocks = _split_report_sections(blocks)
    momentum = _extract_momentum(trends_blocks)
    why = _why_map(audit_topics or [])
    # Per-digest key for the reader's local state (read-marks, picks): week N's
    # stars must never bleed into week N+1's report.
    date_match = re.search(r"\d{4}-\d{2}-\d{2}", doc_title)
    digest_id = date_match.group(0) if date_match else "digest"

    hero_sub = f'<div class="sub">{inline(subtitle)}</div>' if subtitle else ""
    # One issue back: reports sit side by side in 3-synthesis/, so history is
    # walkable without an index page. "" (no known sibling) renders nothing.
    hero_prev = (
        f'<a class="rb-prev" href="{attr(prev_report)}">← previous digest</a>'
        if prev_report
        else ""
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{esc(doc_title)}</title>{REPORT_FONT_LINKS}"
        f'<style>{REPORT_STYLE}</style></head>'
        f'<body data-digest-id="{attr(digest_id)}"><div class="wrap">'
        # role="banner" marks the hero as the page's masthead landmark; the digest
        # body sits in a labelled <main> so assistive tech can skip straight to it.
        f'<header class="hero reveal" role="banner"><h1>{inline(doc_title)}</h1>{hero_sub}{hero_prev}</header>'
        # A horizontally-scrollable tablist on narrow screens (rb-tabs-scroll adds
        # the right-edge fade hint); each tab has an id its panel points back to via
        # aria-labelledby, and roving tabindex + arrow keys give a full ARIA pattern.
        '<nav class="tabs rb-tabs-scroll" role="tablist" aria-label="Report sections">'
        '<button class="tab" id="tab-digest" role="tab" aria-selected="true" tabindex="0" aria-controls="panel-digest">Digest</button>'
        '<button class="tab" id="tab-pulse" role="tab" aria-selected="false" tabindex="-1" aria-controls="panel-pulse">Pulse</button>'
        '<button class="tab" id="tab-vault" role="tab" aria-selected="false" tabindex="-1" aria-controls="panel-vault">Vault</button>'
        '<button class="tab" id="tab-glossary" role="tab" aria-selected="false" tabindex="-1" aria-controls="panel-glossary">Glossary</button>'
        '<button class="tab" id="tab-concepts" role="tab" aria-selected="false" tabindex="-1" aria-controls="panel-concepts">Concepts</button>'
        "</nav>"
        f'<main aria-label="Digest report">'
        '<section id="panel-digest" class="panel" role="tabpanel" aria-labelledby="tab-digest" tabindex="0">'
        f"{_render_kpis(kpis)}"
        f"{_render_read_today(audit_topics or [])}"
        f"{_render_body(digest_blocks, momentum, why)}"
        "</section>"
        '<section id="panel-pulse" class="panel" role="tabpanel" aria-labelledby="tab-pulse" tabindex="0" hidden>'
        f"{_render_pulse(stats, trends_blocks, audit_topics or [])}"
        "</section>"
        '<section id="panel-vault" class="panel" role="tabpanel" aria-labelledby="tab-vault" tabindex="0" hidden>'
        f"{_render_vault(lessons or [], playbooks or [], stats)}"
        "</section>"
        '<section id="panel-glossary" class="panel" role="tabpanel" aria-labelledby="tab-glossary" tabindex="0" hidden>'
        f"{_render_glossary(glossary_blocks, glossary_terms or [])}"
        "</section>"
        '<section id="panel-concepts" class="panel" role="tabpanel" aria-labelledby="tab-concepts" tabindex="0" hidden>'
        f"{_render_concepts(concepts or [])}"
        "</section>"
        f"</main>"
        # The pick bar ships hidden; the script shows it once any pick exists.
        '<div id="pickBar" class="rb-pickbar" hidden>'
        '<span class="rb-pickbar-count">⭐ <span id="pickCount"></span></span>'
        '<button id="pickShare" type="button">Share via Telegram</button>'
        '<button id="pickCopy" type="button">Copy</button>'
        "</div>"
        '<button id="toTop" class="to-top" type="button" aria-label="Back to top">↑</button>'
        # The vault-file modal shell: hidden until a `.rb-file` link is opened;
        # the embedded script fetches the markdown and renders it in here.
        '<dialog id="rbMdModal" class="rb-md-modal" aria-labelledby="rbMdTitle">'
        '<div class="rb-md-frame">'
        '<div class="rb-md-head"><h2 id="rbMdTitle"></h2>'
        '<div class="rb-md-tools">'
        '<a id="rbMdRaw" href="#" target="_blank" rel="noopener">raw</a>'
        '<button id="rbMdClose" class="rb-md-close" type="button" aria-label="Close">×</button>'
        "</div></div>"
        '<div id="rbMdBody" class="rb-md-body"></div>'
        "</div></dialog>"
        f"</div><script>{REPORT_SCRIPT}</script></body></html>\n"
    )
