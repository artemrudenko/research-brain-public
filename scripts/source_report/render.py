#!/usr/bin/env python3
"""
render.py — the standalone Source Insights page.

A SIBLING of the digest report, not a sixth tab inside it. That report holds at
five tabs on purpose (five fit a phone — the 2026-07-14 Trends/Stats/Audit merge
into Pulse exists for exactly that reason), and source intelligence is a
different audience on a different cadence anyway: the digest is for the reader,
this is for whoever tends the source list.

It reuses the digest report's theme and escaping wholesale rather than growing a
second visual language: `REPORT_STYLE` / `REPORT_SCRIPT` for the look and the tab
behaviour, `esc` / `attr` for output encoding, and the same http(s) allowlist
before anything becomes an href. Everything rendered here — source URLs, author
names, topic labels — came out of a remote document, so that reuse is a security
property, not just consistency.

Deterministic by contract, like its sibling: no timestamps and no randomness in
the render path, and ordering is the CALLER's job (`metrics.source_metrics`
already sorts), so the same data always yields byte-identical HTML.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.delivery.email_html import attr, esc  # noqa: E402
from scripts.delivery.report_theme import (  # noqa: E402
    REPORT_FONT_LINKS,
    REPORT_SCRIPT,
    REPORT_STYLE,
)
from scripts.source_report.authors import (  # noqa: E402
    AuthorMetrics,
    MonitoringSuggestion,
)
from scripts.source_report.metrics import SourceMetrics  # noqa: E402

# How each confidence band is described to a reader. The wording matters as much
# as the number: "established" invites acting on the row, "insufficient" says the
# numbers are about our history, not about the source.
_CONFIDENCE_NOTE = {
    "established": "established — enough history to read into",
    "low": "low confidence — a few runs only",
    "insufficient": "insufficient data — too new to judge",
}


def _is_http_url(url: str) -> bool:
    """Only http(s) values become live links — same gate the digest report uses."""
    return url.lower().startswith(("https://", "http://"))


def _link(url: str) -> str:
    """A source URL as a link when safe, as plain text otherwise.

    The value is always SHOWN: dropping a hostile URL silently would hide which
    source produced the row, which is the one thing this page exists to say.
    """
    # `attr` (quote=True) for the visible text too, not just the href. A bare
    # quote is inert in a text node, so `esc` would be *sufficient* — but then
    # the same hostile URL renders escaped in one place and raw in another, and
    # the invariant "this URL never appears unescaped anywhere" stops holding.
    # A URL is a machine token, not prose: escaping its quotes costs nothing.
    if _is_http_url(url):
        return f'<a href="{attr(url)}">{attr(url)}</a>'
    return attr(url)


def _handle(suggestion: MonitoringSuggestion) -> str:
    """The stable handle that tells two same-named authors apart.

    The identifier (`orcid:…`) is preferred — it is what `/author add` needs and
    what the identity ladder keys on; the profile URL is the fallback, rendered as
    a link. Empty when the suggestion carries neither (which `followable` should
    already have excluded), so the name simply stands alone.
    """
    if suggestion.identifier:
        return f" <span class='rb-muted'>({esc(suggestion.identifier)})</span>"
    if suggestion.profile_url:
        return f" <span class='rb-muted'>({_link(suggestion.profile_url)})</span>"
    return ""


def _chips(pairs: list[tuple[str, int]]) -> str:
    """Decision counts as labelled chips — never collapsed into one figure."""
    return "".join(
        f'<span class="rb-chip">{esc(name)} {count}</span>' for name, count in pairs
    )


def _source_card(row: SourceMetrics) -> str:
    note = _CONFIDENCE_NOTE.get(row.confidence, row.confidence)
    topics = ", ".join(esc(t) for t in row.topics)
    known = row.passed_curation + row.rejected_curation + row.pending_curation
    curation = (
        f"{row.passed_curation} kept · {row.rejected_curation} rejected · "
        f"{row.pending_curation} awaiting curation"
        if known
        else "nothing from this source has reached curation yet"
    )
    return (
        '<section class="rb-card reveal">'
        f"<h3>{_link(row.source_url)}</h3>"
        f'<p class="rb-muted">{esc(note)}</p>'
        f"<p>{row.considered} considered · {row.selected} collected</p>"
        f"<p>{esc(curation)}</p>"
        f'<p class="rb-chips">{_chips(sorted(row.by_decision.items()))}</p>'
        + (f'<p class="rb-muted">Topics: {topics}</p>' if topics else "")
        + "</section>"
    )


def _authors_panel(
    authors: list[AuthorMetrics], suggestions: list[MonitoringSuggestion]
) -> str:
    """Who keeps showing up — and, separately, who might be worth following.

    Suggestions lead because they are the only actionable thing here, but they
    are phrased as evidence for the user to judge, never as a score. Nothing on
    this page starts monitoring: the capability does not exist yet, and an
    author with no stable profile URL is never suggested at all, because there
    would be no way to follow them.
    """
    if not authors:
        return (
            '<section class="rb-card"><p>No authors recorded yet. Authors appear '
            "as collected articles credit them.</p></section>"
        )

    proposed = ""
    if suggestions:
        items = "".join(
            f"<li><strong>{esc(s.display_name)}</strong>{_handle(s)} — "
            f"{esc(s.reason)}</li>"
            for s in suggestions
        )
        proposed = (
            '<section class="rb-card reveal"><h3>Worth following?</h3>'
            f"<ul>{items}</ul>"
            "<p class='rb-muted'>Suggestions only — Source Insights never follows "
            "anyone; nothing here has been enabled. Use <code>/author add</code> "
            "to start monitoring one.</p></section>"
        )

    cards = []
    for row in authors:
        where = "".join(f"<li>{_link(url)}</li>" for url in row.sources)
        judged = row.passed_curation + row.rejected_curation
        rate = (
            f"{row.passed_curation} of {judged} passed curation"
            if judged
            else "none judged at curation yet"
        )
        handle = (
            f"<p>{_link(row.profile_url)}</p>"
            if row.profile_url
            else "<p class='rb-muted'>No profile link — cannot be followed.</p>"
        )
        cards.append(
            '<section class="rb-card reveal">'
            f"<h3>{esc(row.display_name)}</h3>"
            f"<p>{row.articles} article(s) across {row.runs} run(s) · {esc(rate)}</p>"
            f"{handle}<ul>{where}</ul></section>"
        )
    return proposed + "".join(cards)


def _decisions_panel(rows: list[SourceMetrics]) -> str:
    """Why candidates were dropped, aggregated across sources."""
    totals: dict[str, int] = {}
    for row in rows:
        for name, count in row.by_decision.items():
            totals[name] = totals.get(name, 0) + count
    if not totals:
        return '<section class="rb-card"><p>No decisions recorded yet.</p></section>'
    return (
        '<section class="rb-card reveal">'
        "<h3>Every decision, across all sources</h3>"
        "<p class='rb-muted'>Counts, not verdicts — a rejection for being a "
        "duplicate means something very different from one for being off-topic.</p>"
        f'<p class="rb-chips">{_chips(sorted(totals.items()))}</p>'
        "</section>"
    )


def render_source_report(
    rows: list[SourceMetrics],
    *,
    generated_for: str,
    authors: list[AuthorMetrics] | None = None,
    suggestions: list[MonitoringSuggestion] | None = None,
) -> str:
    """Render the full standalone page. `generated_for` is the ISO date in the title.

    The date is passed IN rather than read from the clock so the render stays
    deterministic and testable — the same contract the digest report holds.
    """
    title = f"Source insights — {generated_for}"
    if rows:
        subtitle = (
            f"{len(rows)} source(s) · "
            f"{sum(r.considered for r in rows)} candidates considered"
        )
        sources_panel = "".join(_source_card(row) for row in rows)
    else:
        subtitle = "Nothing recorded yet"
        sources_panel = (
            '<section class="rb-card"><p>No collection decisions have been '
            "recorded yet. This page fills in as collection runs; a dry run "
            "deliberately records nothing.</p></section>"
        )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{esc(title)}</title>{REPORT_FONT_LINKS}"
        f"<style>{REPORT_STYLE}</style></head>"
        '<body><div class="wrap">'
        f'<header class="hero reveal" role="banner"><h1>{esc(title)}</h1>'
        f'<p class="hero-sub">{esc(subtitle)}</p></header>'
        '<nav class="tabs" role="tablist" aria-label="Report sections">'
        '<button class="tab" role="tab" aria-selected="true" '
        'aria-controls="panel-sources">Sources</button>'
        '<button class="tab" role="tab" aria-selected="false" '
        'aria-controls="panel-authors">Authors</button>'
        '<button class="tab" role="tab" aria-selected="false" '
        'aria-controls="panel-decisions">Decisions</button>'
        "</nav>"
        '<main aria-label="Source insights">'
        f'<section id="panel-sources" class="panel" role="tabpanel">{sources_panel}</section>'
        f'<section id="panel-authors" class="panel" role="tabpanel" hidden>'
        f"{_authors_panel(authors or [], suggestions or [])}</section>"
        f'<section id="panel-decisions" class="panel" role="tabpanel" hidden>'
        f"{_decisions_panel(rows)}</section>"
        "</main></div>"
        f"<script>{REPORT_SCRIPT}</script></body></html>\n"
    )
