"""report_concepts.py — the Concepts tab renderer for the browser digest report.

Split out of `digest_report_html.py`: concept-card rendering (including the
`obsidian://` deep-link helper and the card-preview excerpt logic) is a large,
self-contained slice with no dependency on the digest-body block renderer.
"""

from __future__ import annotations

from scripts.delivery.email_html import attr, esc
from scripts.delivery.report_audit import _is_http_url
from scripts.delivery.report_inline import inline as _inline
from scripts.delivery.report_models import ReportConcept

# Card-preview budget for the concept note: enough for a full Key-facts list,
# small enough that the card stays a card (the modal owns the full text).
_NOTE_PREVIEW_LINES = 16
_NOTE_PREVIEW_CHARS = 1200
_HEADING_PREFIX = "#"


def _obsidian_uri(local_path: str) -> str:
    """An `obsidian://` deep link to a vault file, from its report-relative path.

    The report is a companion to the Obsidian vault (rooted at `brain/`), not a
    replacement — so a click should open the exact note IN Obsidian. Derives the
    vault-relative path (drop everything up to `brain/`, strip `.md`) and URL-
    encodes it. Returns "" when the path is not under a `brain/` vault (nothing to
    open). No `vault=` param — opens in the user's current vault (personal use).
    """
    from urllib.parse import quote  # noqa: PLC0415 — only this path needs it

    marker = "brain/"
    idx = local_path.find(marker)
    if idx < 0:
        return ""
    rel = local_path[idx + len(marker):]
    if rel.endswith(".md"):
        rel = rel[:-3]
    return "obsidian://open?file=" + quote(rel)


def _concept_note_excerpt(body: str) -> tuple[str, bool]:
    """The card-sized preview of a concept note; the modal shows the full file.

    Prefers the `Key facts` section — the definition line above the note
    already covers "what it is", so the facts are the densest remaining piece.
    Without one, falls back to the head of the body. Returns `(excerpt,
    trimmed)`; `trimmed` says the card is showing less than the whole note.
    """
    lines = body.splitlines()
    start, end = 0, len(lines)
    for i, line in enumerate(lines):
        if line.lstrip().startswith(_HEADING_PREFIX) and "key facts" in line.lower():
            start = i
            end = next(
                (
                    j
                    for j in range(i + 1, len(lines))
                    if lines[j].lstrip().startswith(_HEADING_PREFIX)
                ),
                len(lines),
            )
            break
    section = [line for line in lines[start:end] if line.strip()]
    trimmed = len(section) < len([line for line in lines if line.strip()])
    if len(section) > _NOTE_PREVIEW_LINES:
        section = section[:_NOTE_PREVIEW_LINES]
        trimmed = True
    excerpt = "\n".join(section)
    if len(excerpt) > _NOTE_PREVIEW_CHARS:
        excerpt = excerpt[:_NOTE_PREVIEW_CHARS].rsplit(" ", 1)[0] + "…"
        trimmed = True
    return excerpt, trimmed


def _render_concepts(concepts: list[ReportConcept]) -> str:
    """Render concept navigator cards and their expandable detail panels."""
    if not concepts:
        return (
            '<section class="rb-card reveal">'
            '<p class="rb-empty">No concepts are available in this report snapshot.</p>'
            "</section>"
        )
    # Distinct tags across the shown concepts, for the client-side filter chips.
    all_tags = sorted({tag for concept in concepts for tag in concept.tags})
    tag_chips = "".join(
        f'<button type="button" class="rb-tagfilter" data-tag-filter="{attr(tag)}">'
        f"{esc(tag)}</button>"
        for tag in all_tags
    )
    tag_row = (
        '<div class="rb-tagbar" role="group" aria-label="Filter concepts by tag">'
        '<button type="button" class="rb-tagfilter is-on" data-tag-filter="">All</button>'
        f"{tag_chips}</div>"
        if all_tags
        else ""
    )
    cards: list[str] = [
        # The vault is the home of ALL concepts (with Bases filters + the graph);
        # this report shows the digest slice, so lead with a deep link into it.
        '<p class="rb-p rb-obsidian-cta">📊 '
        '<a href="obsidian://open?file=concepts.base">Browse & filter every concept '
        "in Obsidian</a> — Bases views, tags, and the graph live there.</p>"
        '<div class="rb-toolrow">'
        '<input id="conceptSearch" class="rb-search" type="search" '
        'placeholder="Search concepts, tags, sources" aria-label="Search concepts">'
        f'<span class="rb-count num">{len(concepts)} concepts</span>'
        "</div>"
        f"{tag_row}"
    ]
    for idx, concept in enumerate(concepts):
        tags = " ".join(f'<span class="rb-chip">{esc(tag)}</span>' for tag in concept.tags)
        sources = "".join(
            "<li>"
            + (
                f'<a href="{attr(source.local_path)}">source file</a> · '
                if source.local_path
                else ""
            )
            + (
                f'<a href="{attr(source.url)}">original article</a>'
                if _is_http_url(source.url)
                else "source"
            )
            + (f' <span class="rb-mini">{esc(source.tier)}</span>' if source.tier else "")
            + "</li>"
            for source in concept.sources
        )
        if not sources:
            sources = '<li class="rb-muted">No sources listed.</li>'
        excerpt, note_trimmed = _concept_note_excerpt(concept.body.strip())
        body = esc(excerpt or concept.definition or "No concept body.")
        excerpt_hint = (
            '<p class="rb-mini">Excerpt — the full note opens via '
            "“open concept file”.</p>"
            if note_trimmed and concept.local_path
            else ('<p class="rb-mini">Excerpt.</p>' if note_trimmed else "")
        )
        obs_uri = _obsidian_uri(concept.local_path)
        obsidian_link = (
            f'<a class="rb-obsidian" href="{attr(obs_uri)}">⧉ Open in Obsidian</a> · '
            if obs_uri
            else ""
        )
        local = (
            f"{obsidian_link}"
            f'<a class="rb-file" href="{attr(concept.local_path)}" '
            f'data-md-title="{attr(concept.name)}">open concept file</a>'
            if concept.local_path
            else ""
        )
        searchable = " ".join(
            [concept.name, concept.definition, " ".join(concept.tags)]
            + [source.url for source in concept.sources]
        ).lower()
        cards.append(
            f'<article class="rb-concept reveal" data-search="{attr(searchable)}" '
            f'data-tags="{attr(" ".join(concept.tags))}" '
            f'style="animation-delay:{idx * 24}ms">'
            '<button class="rb-concept-head" type="button" aria-expanded="false">'
            f"<span><strong>{esc(concept.name)}</strong>"
            f'<small>{esc(concept.updated)}</small></span><span class="rb-open">Open</span>'
            "</button>"
            f'<p class="rb-p">{_inline(concept.definition) if concept.definition else "No definition."}</p>'
            f'<div class="rb-tags">{tags}</div>'
            '<div class="rb-concept-body" hidden>'
            f'<div class="rb-filebar">{local}</div>'
            "<h3>Sources</h3>"
            f'<ul class="rb-sources">{sources}</ul>'
            "<h3>Concept note</h3>"
            # The embedded script upgrades this <pre> to rendered markdown on
            # load (same mdRender as the vault-file modal); without JS the raw
            # text stays readable as-is.
            f'<pre class="rb-note-md">{body}</pre>'
            f"{excerpt_hint}"
            "</div>"
            "</article>"
        )
    return "".join(cards)
