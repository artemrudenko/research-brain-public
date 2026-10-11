"""report_audit.py — the per-topic source-selection drilldown for the report.

Split out of `digest_report_html.py`: the audit fold ("why was each source
shown or hidden") is self-contained — it renders straight from
`ReportAuditTopic`/`ReportAuditDecision` with no dependency on the digest-body
block renderer, so it moves cleanly with zero circular-import risk.
"""

from __future__ import annotations

from scripts.delivery.email_html import attr, esc
from scripts.delivery.report_models import ReportAuditTopic


def _reason_label(reason: str) -> str:
    """Make audit reason codes readable without changing their stable JSON values."""
    labels = {
        "selected_by_source_credibility": "selected by source credibility",
        "hidden_topic_cap": "hidden by topic cap",
    }
    return labels.get(reason, reason.replace("_", " ").strip() or "not specified")


def _topic_health_label(topic: ReportAuditTopic) -> str:
    """Plain-language source-health label for a topic's selection shape."""
    if topic.total_sources == 0:
        return "silent"
    if topic.included_sources == 0:
        return "no digest candidates"
    if topic.hidden_sources > topic.included_sources:
        return "noisy topic"
    if topic.hidden_sources:
        return "trimmed"
    return "fully shown"


def _is_http_url(url: str) -> bool:
    """Only http(s) concept sources become live external links."""
    return url.lower().startswith(("https://", "http://"))


def _render_audit(audit_topics: list[ReportAuditTopic]) -> str:
    """Render the per-topic source-selection drilldown (the audit fold's body)."""
    if not audit_topics:
        return ""
    topic_cards: list[str] = []
    for topic_idx, topic in enumerate(audit_topics):
        rows: list[str] = []
        for idx, decision in enumerate(topic.decisions):
            pill = "Shown" if decision.included else "Hidden"
            pill_class = "show" if decision.included else "hide"
            rank = f'<span class="rb-mini">rank {decision.rank}</span>' if decision.rank else ""
            tier = f'<span class="rb-mini">tier: {esc(decision.tier)}</span>' if decision.tier else ""
            title = (
                f'<a href="{attr(decision.url)}">{esc(decision.title)}</a>'
                if _is_http_url(decision.url)
                else esc(decision.title)
            )
            rows.append(
                f'<li class="rb-audit-row reveal" style="animation-delay:{idx * 16}ms">'
                f'<span class="rb-pill {pill_class}">{pill}</span>'
                f'<span class="rb-audit-title">{title}</span>'
                f"{rank}{tier}"
                f'<span class="rb-audit-reason">{esc(_reason_label(decision.reason))}</span>'
                "</li>"
            )
        if not rows:
            rows.append('<li class="rb-muted">No source decisions for this topic.</li>')
        topic_cards.append(
            f'<section class="rb-audit-topic reveal" style="animation-delay:{topic_idx * 40}ms">'
            '<div class="rb-audit-head">'
            f"<h3>{esc(topic.topic)}</h3>"
            f'<span class="rb-mini">{esc(_topic_health_label(topic))}</span>'
            "</div>"
            '<p class="rb-p">'
            f'<strong class="num">{topic.included_sources}</strong> shown · '
            f'<strong class="num">{topic.hidden_sources}</strong> hidden · '
            f'<strong class="num">{topic.total_sources}</strong> total'
            "</p>"
            f'<ul class="rb-audit-list">{"".join(rows)}</ul>'
            "</section>"
        )
    return (
        '<p class="rb-p">Every collected source in this digest window, grouped by topic, '
        "with the reason it was shown or hidden.</p>"
        f'{"".join(topic_cards)}'
    )
