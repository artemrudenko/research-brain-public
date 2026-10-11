"""report_vault.py — the Vault (lessons/playbooks) tab renderer for the report.

Split out of `digest_report_html.py`: rendering the lessons/playbooks vault
tab is self-contained (only needs the `ReportVaultNote`/`ReportStats` shapes),
so it moves cleanly with no circular-import risk.
"""

from __future__ import annotations

from scripts.delivery.email_html import attr, esc
from scripts.delivery.report_inline import inline
from scripts.delivery.report_models import ReportStats, ReportVaultNote


def _vault_note_cards(notes: list[ReportVaultNote], empty: str) -> str:
    """Render compact cards for one vault note type."""
    if not notes:
        return f'<p class="rb-empty">{esc(empty)}</p>'
    cards: list[str] = []
    for idx, note in enumerate(notes):
        tags = " ".join(f'<span class="rb-chip">{esc(tag)}</span>' for tag in note.tags)
        link = (
            f'<a class="rb-file" href="{attr(note.local_path)}" '
            f'data-md-title="{attr(note.title)}">open note</a>'
            if note.local_path
            else '<span class="rb-muted">No local link.</span>'
        )
        searchable = " ".join(
            [note.title, note.note_type, note.metadata, note.summary, " ".join(note.tags)]
        ).lower()
        cards.append(
            f'<article class="rb-vault-note reveal" data-search="{attr(searchable)}" '
            f'style="animation-delay:{idx * 24}ms">'
            f'<div class="rb-vault-kind">{esc(note.note_type)}</div>'
            f"<h3>{esc(note.title)}</h3>"
            f'<p class="rb-p">{inline(note.summary) if note.summary else "No summary."}</p>'
            f'<div class="rb-tags">{tags}</div>'
            f'<div class="rb-filebar">{link}'
            + (f' <span class="rb-mini">{esc(note.metadata)}</span>' if note.metadata else "")
            + "</div>"
            "</article>"
        )
    return "".join(cards)


def _render_vault(
    lessons: list[ReportVaultNote],
    playbooks: list[ReportVaultNote],
    stats: ReportStats | None,
) -> str:
    """Render the lessons/playbooks vault tab."""
    lessons_base = stats.lessons_base_path if stats else ""
    playbooks_base = stats.playbooks_base_path if stats else ""
    lesson_link = (
        f'<a href="{attr(lessons_base)}">open lessons.base</a>'
        if lessons_base
        else '<span class="rb-muted">lessons.base path unavailable</span>'
    )
    playbook_link = (
        f'<a href="{attr(playbooks_base)}">open playbooks.base</a>'
        if playbooks_base
        else '<span class="rb-muted">playbooks.base path unavailable</span>'
    )
    return (
        '<section class="rb-card reveal">'
        '<h2 class="rb-sec">Vault front doors</h2>'
        '<div class="rb-vault-grid">'
        '<div class="rb-stat">'
        f'<div class="rb-stat-num num">{esc(str(len(lessons)))}</div>'
        f'<div class="rb-stat-lbl">Lessons · {lesson_link}</div>'
        "</div>"
        '<div class="rb-stat">'
        f'<div class="rb-stat-num num">{esc(str(len(playbooks)))}</div>'
        f'<div class="rb-stat-lbl">Playbooks · {playbook_link}</div>'
        "</div>"
        "</div>"
        '<div class="rb-vault-cols">'
        '<section><h3>Lessons</h3>'
        f'{_vault_note_cards(lessons, "No lesson notes yet.")}'
        "</section>"
        '<section><h3>Playbooks</h3>'
        f'{_vault_note_cards(playbooks, "No playbooks yet.")}'
        "</section>"
        "</div>"
        "</section>"
    )
