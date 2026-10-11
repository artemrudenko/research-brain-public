"""
test_digest_report_html.py — offline tests for the dynamic showcase-style HTML
digest report (the browser-grade viewing page, distinct from the email HTML).

All tests are self-contained: they feed digest markdown to the renderer and assert
on the produced standalone document. No network, no real vault.
"""

import hashlib
import re

from scripts.delivery import digest_report_html as rp  # noqa: E402
from scripts.delivery.digest_report_html import (  # noqa: E402
    ReportAuditDecision,
    ReportAuditTopic,
    ReportConcept,
    ReportGlossaryTerm,
    ReportSource,
    ReportStats,
    ReportTopicStat,
    ReportVaultNote,
)

_SAMPLE = (
    "# 🧠 Weekly digest — 2026-07-01\n\n"
    "_67 new sources across 6 topics, 35 updated concepts._\n\n"
    "## ⚡ TL;DR\n\n"
    "- 📰 Most active: **ai-ml**\n"
    "- 💡 35 concepts updated\n\n"
    "## 🆕 New sources\n\n"
    "### ai-ml\n\n"
    "- [GLM-5.2](https://example.com/glm) — long-horizon tasks\n"
    "  - 🟢 2 sources\n"
)


def test_returns_a_standalone_document() -> None:
    html = rp.render_digest_report(_SAMPLE)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "<style>" in html
    assert html.rstrip().endswith("</html>")


def test_uses_showcase_design_tokens() -> None:
    # The palette / typography from docs/decks/research-brain-showcase.html.
    html = rp.render_digest_report(_SAMPLE)
    assert "--terra" in html
    assert "Fraunces" in html
    assert "Manrope" in html


def test_inline_code_is_token_styled_not_email_inline() -> None:
    # The report is a browser page with a real stylesheet — inline-code chips
    # must be theme-tokened <code> elements, NOT carry the email renderer's
    # hard-coded light-grey inline style (which stays light in dark mode and
    # clashes with the warm palette; supersedes the 2026-07-13 dark-ink pin).
    md = _SAMPLE + "\n- **Lessons:** 0 active notes in `brain/lessons.base`.\n"
    html = rp.render_digest_report(md)
    assert "<code>brain/lessons.base</code>" in html, (
        "inline code must render as a bare element the stylesheet owns"
    )
    assert "background:#f3f4f6" not in html, (
        "email chip style must not leak into the report"
    )


def test_report_stylesheet_owns_inline_code_chips() -> None:
    # Dark-mode safety moved from per-chip inline pins to the stylesheet: the
    # body chip rule must exist and build on theme tokens so both themes adapt.
    html = rp.render_digest_report(_SAMPLE)
    rule = re.search(r"main code\{([^}]*)\}", html)
    assert rule is not None, "report CSS must style body inline-code chips"
    assert "var(--" in rule.group(1), "chip rule must use theme tokens"


def test_markdown_links_are_token_styled_not_email_inline() -> None:
    # Same contract for links: the global `a{color:var(--terra)}` rule owns
    # link color. The email renderer's hard-coded indigo fails WCAG on the
    # dark surface (2.6:1) and splits the document into two link colors.
    html = rp.render_digest_report(_SAMPLE)
    assert 'href="https://example.com/glm"' in html
    assert "color:#4f46e5" not in html, (
        "email link style must not leak into the report"
    )
    link = re.search(r'<a href="https://example\.com/glm"([^>]*)>', html)
    assert link is not None
    assert "style=" not in link.group(1), "report links must carry no inline style"


def test_hero_carries_title_and_subtitle() -> None:
    html = rp.render_digest_report(_SAMPLE)
    assert "Weekly digest — 2026-07-01" in html
    assert "67 new sources across 6 topics, 35 updated concepts" in html


def test_kpi_cards_extracted_from_subtitle() -> None:
    html = rp.render_digest_report(_SAMPLE)
    # Each headline number becomes a KPI card with the number and its label.
    assert "rb-kpi" in html
    for value, label in (("67", "new sources"), ("6", "topics"), ("35", "updated concepts")):
        assert value in html
        assert label in html


def test_sections_and_tldr_callout_rendered() -> None:
    html = rp.render_digest_report(_SAMPLE)
    assert "TL;DR" in html
    assert "rb-callout" in html
    assert "New sources" in html
    assert "ai-ml" in html


def test_report_has_five_tabs_with_merged_pulse() -> None:
    # Trends/Stats/Audit share one mental model — "this week in numbers" — and
    # merged into one Pulse tab (2026-07-14 review); five tabs fit a phone.
    html = rp.render_digest_report(_SAMPLE)
    assert 'role="tablist"' in html
    for label in ("Digest", "Pulse", "Vault", "Glossary", "Concepts"):
        assert f">{label}</button>" in html
    for panel in ("panel-digest", "panel-pulse", "panel-vault", "panel-glossary", "panel-concepts"):
        assert f'id="{panel}"' in html
    for gone in ("panel-trends", "panel-stats", "panel-audit"):
        assert f'id="{gone}"' not in html
    assert ">Trends</button>" not in html
    assert ">Stats</button>" not in html
    assert ">Audit</button>" not in html


def test_trends_section_moves_to_pulse_tab() -> None:
    sample = _SAMPLE + "\n\n## 📈 Trends — 2026-07-01\n\n- Inflow: 67 this week\n"
    html = rp.render_digest_report(sample)
    assert "Inflow: 67 this week" in html
    assert html.index('id="panel-pulse"') < html.index("Inflow: 67 this week")
    assert html.index("Inflow: 67 this week") < html.index('id="panel-vault"')


def test_pulse_orders_stats_then_trends_then_folded_audit() -> None:
    # The short, weekly-glance content leads; the long operator drilldown
    # folds closed at the bottom so it can't bury the numbers.
    sample = _READER
    html = rp.render_digest_report(
        sample,
        stats=ReportStats(topic_stats=[ReportTopicStat("ai-ml", 3)]),
        audit_topics=_READER_AUDIT,
    )
    pulse = html.index('id="panel-pulse"')
    assert pulse < html.index("Collection stats")
    assert html.index("Collection stats") < html.index("Topic volume")
    assert html.index("Topic volume") < html.index('<details class="rb-audit-fold">')
    assert '<details class="rb-audit-fold" open' not in html, "audit folds closed"


def test_pulse_omits_audit_fold_without_audit_data() -> None:
    html = rp.render_digest_report(_SAMPLE)
    assert "rb-audit-fold" not in html.split('id="panel-pulse"')[1].split("</section></section>")[0] or "rb-audit-fold" not in html


def test_stats_tab_renders_collection_stats() -> None:
    html = rp.render_digest_report(
        _SAMPLE,
        stats=ReportStats(
            new_sources=67,
            topics=6,
            updated_concepts=3,
            concepts_created=2,
            concepts_updated=1,
            existing_concepts_reused=4,
            attention_items=0,
            total_concepts=35,
            glossary_terms=47,
            topic_stats=[
                ReportTopicStat("ai-ml", 20),
                ReportTopicStat("sdlc", 11),
            ],
        ),
    )
    assert "Collection stats" in html
    assert "New sources" in html
    assert "Concept cards shown" in html
    assert "Created (last synthesis)" in html
    assert "Updated (last synthesis)" in html
    assert "Reused during synthesis" in html
    assert "Knowledge reused" not in html
    assert "ai-ml" in html
    assert "47" in html


def test_topic_stats_render_proportional_bars() -> None:
    # "Sources by topic" is comparative data — each row carries a CSS bar
    # scaled against the busiest topic so volumes scan without reading every
    # number. The bar is decorative (numbers stay the data): aria-hidden, and
    # the stylesheet owns its look via theme tokens so both themes adapt.
    html = rp.render_digest_report(
        _SAMPLE,
        stats=ReportStats(
            topic_stats=[ReportTopicStat("ai-ml", 30), ReportTopicStat("claude", 4)],
        ),
    )
    assert re.search(
        r'<span class="rb-topic-bar" aria-hidden="true"><i style="width:100%">'
        r"</i></span>",
        html,
    ), "busiest topic must render a full-width bar"
    assert "width:13%" in html, "4/30 sources must scale to a 13% bar"
    rule = re.search(r"\.rb-topic-bar\{([^}]*)\}", html)
    assert rule is not None and "var(--" in rule.group(1)


def test_topic_stats_bars_handle_zero_sources() -> None:
    # An all-zero window (quiet week) must not divide by zero and renders
    # empty tracks rather than misleading full bars.
    html = rp.render_digest_report(
        _SAMPLE,
        stats=ReportStats(topic_stats=[ReportTopicStat("ai-ml", 0)]),
    )
    assert "width:0%" in html


def test_stats_tab_renders_digest_audit_summary() -> None:
    html = rp.render_digest_report(
        _SAMPLE,
        stats=ReportStats(
            new_sources=5,
            topics=1,
            included_sources=3,
            hidden_sources=2,
            audit_path="digest_2026-07-01.audit.json",
        ),
    )
    assert "Digest audit" in html
    assert "3 shown" in html
    assert "2 hidden by topic cap" in html
    assert 'href="digest_2026-07-01.audit.json"' in html


# Digest markdown with a sources section AND an embedded trends block — the
# fixture for the reader-features wave (momentum arrows, why-chips, read-today).
_READER = (
    "# 🧠 Weekly digest — 2026-07-01\n\n"
    "_3 new sources across 2 topics, 1 updated concept._\n\n"
    "## ⚡ TL;DR\n\n"
    "- 🔎 Worth a look: [GLM-5.2](https://example.com/glm) ⭐\n\n"
    "## 📰 New sources (last 7 days)\n\n"
    "### 🏷 ai-ml (2)\n\n"
    "- [GLM-5.2](https://example.com/glm) — long-horizon tasks\n"
    "- [Other](https://example.com/other) — a second source\n\n"
    "### 🏷 sdlc (1)\n\n"
    "- [Third](https://example.com/third) — a third source\n\n"
    "### 🏷 claude (1)\n\n"
    "- [Fourth](https://example.com/fourth) — no trends line for this topic\n\n"
    "## 📈 Trends — 2026-07-01\n\n"
    "### 📊 Topic volume (this week vs last)\n\n"
    "- **ai-ml** — 30 this week (↑ +20 vs last)\n"
    "- **sdlc** — 2 this week (↓ -3 vs last)\n"
)

_READER_AUDIT = [
    ReportAuditTopic(
        topic="ai-ml",
        total_sources=2,
        included_sources=2,
        hidden_sources=0,
        decisions=[
            ReportAuditDecision(
                title="GLM-5.2",
                url="https://example.com/glm",
                tier="high",
                included=True,
                rank=1,
                reason="selected_by_source_credibility",
                read_minutes=4,
            ),
            ReportAuditDecision(
                title="Other",
                url="https://example.com/other",
                tier="medium",
                included=True,
                rank=2,
                reason="selected_by_source_credibility",
                read_minutes=2,
            ),
        ],
    ),
    ReportAuditTopic(
        topic="sdlc",
        total_sources=1,
        included_sources=1,
        hidden_sources=0,
        decisions=[
            ReportAuditDecision(
                title="Third",
                url="https://example.com/third",
                tier="high",
                included=True,
                rank=1,
                reason="selected_by_source_credibility",
                read_minutes=6,
            ),
        ],
    ),
]


def test_topic_badges_carry_momentum_arrows() -> None:
    # The trends block already knows each topic's week-over-week delta; the
    # sources badge surfaces it as an arrow so momentum reads without opening
    # the Trends tab. Topics without a trends line stay arrow-free.
    html = rp.render_digest_report(_READER)
    ai_badge = re.search(r'<div class="rb-badge">[^<]*ai-ml[^<]*(<span[^>]*rb-mom[^>]*>[^<]*</span>)?', html)
    assert ai_badge is not None
    assert re.search(
        r'<div class="rb-badge">🏷 ai-ml \(2\)\s*<span class="rb-mom up" title="\+20 vs last week">↑</span></div>',
        html,
    ), "ai-ml badge must carry an up arrow with the delta as tooltip"
    assert re.search(
        r'<div class="rb-badge">🏷 sdlc \(1\)\s*<span class="rb-mom down" title="-3 vs last week">↓</span></div>',
        html,
    ), "sdlc badge must carry a down arrow"
    claude_badge = re.search(r'<div class="rb-badge">🏷 claude \(1\)[^<]*</div>', html)
    assert claude_badge is not None, "claude badge must render without an arrow"


def test_source_items_carry_why_chips_scoped_to_sources_section() -> None:
    # Every shown source can explain itself: a muted chip carries the tier and
    # the humanized curation reason from the audit data. The chip appears ONLY
    # in the New-sources section — the same URL in TL;DR stays chip-free.
    html = rp.render_digest_report(_READER, audit_topics=_READER_AUDIT)
    assert re.search(
        r'href="https://example\.com/glm"[^№]*?<span class="rb-why">high · selected by source credibility</span>',
        html,
    ), "the glm source row must carry its tier + reason chip"
    callout = re.search(r'<section class="rb-callout">.*?</section>', html, re.S)
    assert callout is not None
    assert "rb-why" not in callout.group(0), "TL;DR must stay chip-free"


def test_read_today_ranks_top_three_across_topics() -> None:
    # The cross-topic "Read today" strip: top-3 shown sources ranked by tier
    # then per-topic rank, each with its topic and an honest reading estimate.
    html = rp.render_digest_report(_READER, audit_topics=_READER_AUDIT)
    block = re.search(r'<section class="rb-card reveal" id="readToday">.*?</section>', html, re.S)
    assert block is not None, "report must render a Read today card"
    body = block.group(0)
    assert "Read today" in body
    links = re.findall(r'href="(https://example\.com/[a-z]+)"', body)
    assert links == [
        "https://example.com/glm",
        "https://example.com/third",
        "https://example.com/other",
    ], "items must rank high-tier first, then per-topic rank"
    assert "≈ 4 min" in body and "≈ 6 min" in body and "≈ 2 min" in body
    assert "ai-ml" in body and "sdlc" in body


def test_read_today_absent_without_audit_data() -> None:
    html = rp.render_digest_report(_READER)
    assert 'id="readToday"' not in html


def test_read_today_omits_zero_minute_estimates() -> None:
    # A decision without a read_minutes estimate renders no "≈ 0 min" noise.
    audit = [
        ReportAuditTopic(
            topic="ai-ml",
            total_sources=1,
            included_sources=1,
            hidden_sources=0,
            decisions=[
                ReportAuditDecision(
                    title="GLM-5.2",
                    url="https://example.com/glm",
                    tier="high",
                    included=True,
                    rank=1,
                    reason="selected_by_source_credibility",
                ),
            ],
        )
    ]
    html = rp.render_digest_report(_READER, audit_topics=audit)
    block = re.search(r'<section class="rb-card reveal" id="readToday">.*?</section>', html, re.S)
    assert block is not None
    assert "0 min" not in block.group(0)


def test_source_rows_carry_star_buttons_and_data_urls() -> None:
    # Every source row is a pick target: the li carries its URL as data and a
    # star toggle the script wires to localStorage. TL;DR rows stay plain —
    # picks are a sources-section affordance.
    html = rp.render_digest_report(_READER)
    assert re.search(
        r'<li class="rb-li" data-url="https://example\.com/glm">.*?'
        r'<button class="rb-star" data-url="https://example\.com/glm" '
        r'aria-pressed="false" aria-label="Save to picks" title="Save to picks">☆</button>',
        html,
    ), "source rows must carry a data-url and a star toggle"
    callout = re.search(r'<section class="rb-callout">.*?</section>', html, re.S)
    assert callout is not None
    assert "rb-star" not in callout.group(0), "TL;DR rows must not be starrable"


def test_read_today_items_are_starrable() -> None:
    html = rp.render_digest_report(_READER, audit_topics=_READER_AUDIT)
    block = re.search(r'<section class="rb-card reveal" id="readToday">.*?</section>', html, re.S)
    assert block is not None
    assert block.group(0).count("rb-star") == 3, "each read-today pick gets a star"


def test_sources_heading_carries_read_progress_slot() -> None:
    # The script fills "N of M read" from localStorage; the renderer only
    # provides the slot, so a JS-less render shows nothing (progressive).
    html = rp.render_digest_report(_READER)
    assert re.search(
        r'<h2 class="rb-sec">📰[^<]*<span class="rb-progress" id="readProgress"></span></h2>',
        html,
    ), "the sources heading must carry the read-progress slot"


def test_body_carries_digest_id_for_local_state() -> None:
    # localStorage keys are scoped per digest (its date), so week N's stars
    # and read-marks never bleed into week N+1's report.
    html = rp.render_digest_report(_READER)
    assert '<body data-digest-id="2026-07-01">' in html


def test_pick_bar_stays_hidden_despite_display_flex() -> None:
    # `.rb-pickbar{display:flex}` beats the UA sheet's `[hidden]{display:none}`
    # (author specificity), so without an explicit override the empty bar
    # showed "0 picks" on every page load — caught on the 2026-07-14 live run.
    html = rp.render_digest_report(_READER)
    assert ".rb-pickbar[hidden]{display:none}" in html


def test_pick_bar_and_script_wire_stars_seen_and_share() -> None:
    # The floating pick bar ships hidden; the script owns visibility. Sharing
    # goes through the t.me share deep-link (works with any chat, no bot
    # username needed) with a clipboard fallback.
    html = rp.render_digest_report(_READER)
    assert 'id="pickBar" class="rb-pickbar" hidden' in html
    assert 'id="pickShare"' in html and 'id="pickCopy"' in html
    assert "rb-seen:" in html and "rb-star:" in html, "script must scope storage keys"
    assert "https://t.me/share/url" in html
    assert "navigator.clipboard" in html


def test_hero_links_previous_report_when_given() -> None:
    # Reports accumulate side by side in 3-synthesis/ but never knew about
    # each other; the hero links back one issue so readers can walk history.
    html = rp.render_digest_report(_READER, prev_report="digest_2026-06-24.report.html")
    assert (
        '<a class="rb-prev" href="digest_2026-06-24.report.html">← previous digest</a>'
        in html
    )


def test_hero_omits_prev_link_without_sibling() -> None:
    html = rp.render_digest_report(_READER)
    assert 'class="rb-prev"' not in html  # the stylesheet may still name it


def test_audit_tab_renders_topic_decisions_and_reasons() -> None:
    html = rp.render_digest_report(
        _SAMPLE,
        audit_topics=[
            ReportAuditTopic(
                topic="ai-ml",
                total_sources=2,
                included_sources=1,
                hidden_sources=1,
                decisions=[
                    ReportAuditDecision(
                        title="Shown source",
                        url="https://example.com/shown",
                        tier="high",
                        included=True,
                        rank=1,
                        reason="selected_by_source_credibility",
                    ),
                    ReportAuditDecision(
                        title="Hidden source",
                        included=False,
                        reason="hidden_topic_cap",
                    ),
                ],
            )
        ],
    )
    assert '<details class="rb-audit-fold">' in html
    assert "Source audit" in html
    assert "ai-ml" in html
    assert "Shown source" in html
    assert 'href="https://example.com/shown"' in html
    assert "Hidden source" in html
    assert "selected by source credibility" in html
    assert "hidden by topic cap" in html
    assert "trimmed" in html


def test_audit_url_with_embedded_quote_cannot_break_out_of_attribute() -> None:
    # A malicious feed serves an item whose link carries a double-quote plus an event
    # handler. If the href is not quote-escaped, the quote closes the attribute and the
    # handler executes when the operator hovers the link in the browser report.
    html = rp.render_digest_report(
        _SAMPLE,
        audit_topics=[
            ReportAuditTopic(
                topic="ai",
                total_sources=1,
                included_sources=1,
                hidden_sources=0,
                decisions=[
                    ReportAuditDecision(
                        title="Evil",
                        url='https://x.com/a" onmouseover="alert(document.cookie)',
                        tier="high",
                        included=True,
                        rank=1,
                        reason="ok",
                    )
                ],
            )
        ],
    )
    assert 'onmouseover="alert' not in html
    assert "&quot;" in html  # the quote survived as an escaped entity, still inside href


def test_concept_source_url_with_embedded_quote_is_escaped() -> None:
    html = rp.render_digest_report(
        _SAMPLE,
        concepts=[
            ReportConcept(
                name="C",
                local_path="brain/concepts/c.md",
                sources=[ReportSource(url='https://x.com/a" onmouseover="alert(1)')],
            )
        ],
    )
    assert 'onmouseover="alert' not in html


def test_concept_search_attribute_with_quote_cannot_break_out() -> None:
    # The data-search attribute is built from concept name/tags/definition; a quote in
    # any of them must be escaped so it cannot close the attribute and inject markup.
    # (The same text also appears as harmless element content, where a bare quote is
    # inert — so this asserts on the attribute specifically, not a blanket substring.)
    html = rp.render_digest_report(
        _SAMPLE,
        concepts=[
            ReportConcept(
                name='Q" onclick="alert(1)',
                local_path="brain/concepts/q.md",
                definition="def",
            )
        ],
    )
    assert 'data-search="q&quot; onclick=&quot;alert(1)' in html
    assert 'data-search="q" onclick="alert' not in html


def test_glossary_section_moves_to_glossary_tab() -> None:
    sample = _SAMPLE + "\n\n## 📖 Glossary\n\n- **RAG** — Retrieval-Augmented Generation\n"
    html = rp.render_digest_report(sample)
    assert "Retrieval-Augmented Generation" in html
    assert html.index('id="panel-glossary"') < html.index("Retrieval-Augmented Generation")


def test_glossary_tab_can_show_full_searchable_glossary() -> None:
    sample = _SAMPLE + "\n\n## 📖 Glossary\n\n- **RAG** — Retrieval-Augmented Generation\n"
    html = rp.render_digest_report(
        sample,
        glossary_terms=[
            ReportGlossaryTerm("API", "Application Programming Interface"),
            ReportGlossaryTerm("RAG", "Retrieval-Augmented Generation"),
            ReportGlossaryTerm("TTL", "Time to live"),
        ],
    )
    assert "glossarySearch" in html
    assert "3 terms" in html
    assert "Application Programming Interface" in html
    assert "Time to live" in html
    assert "document.querySelectorAll('.rb-term')" in html


def test_concepts_tab_renders_snapshot_and_links() -> None:
    html = rp.render_digest_report(
        _SAMPLE,
        concepts=[
            ReportConcept(
                name="Runtime Governance",
                local_path="../../brain/concepts/runtime-governance.md",
                updated="2026-07-01",
                tags=["ai/governance", "sdlc"],
                definition="Policy and enforcement around agent runtime behavior.",
                body="## What it is\n\nPolicy and enforcement.",
                sources=[
                    ReportSource(
                        url="https://example.com/source",
                        local_path="../1-incoming/sdlc/source.md",
                        tier="high",
                    )
                ],
            )
        ],
    )
    assert "Runtime Governance" in html
    assert "ai/governance" in html
    assert 'href="../../brain/concepts/runtime-governance.md"' in html
    assert 'href="../1-incoming/sdlc/source.md"' in html
    assert 'href="https://example.com/source"' in html
    assert "conceptSearch" in html


def test_vault_tab_renders_lessons_playbooks_and_base_links() -> None:
    html = rp.render_digest_report(
        _SAMPLE,
        lessons=[
            ReportVaultNote(
                title="Runtime Lesson",
                note_type="lesson",
                local_path="../../brain/lessons/runtime-lesson.md",
                tags=["ai/agents"],
                metadata="high confidence",
                summary="A reusable observation.",
            )
        ],
        playbooks=[
            ReportVaultNote(
                title="Runtime Playbook",
                note_type="playbook",
                local_path="../../brain/playbooks/runtime-playbook.md",
                tags=["ai/agents"],
                metadata="draft",
                summary="A reusable method.",
            )
        ],
        stats=ReportStats(
            total_lessons=1,
            total_playbooks=1,
            lessons_base_path="../../brain/lessons.base",
            playbooks_base_path="../../brain/playbooks.base",
        ),
    )
    assert "Vault" in html
    assert 'id="panel-vault"' in html
    assert 'href="../../brain/lessons.base"' in html
    assert 'href="../../brain/playbooks.base"' in html
    assert "Runtime Lesson" in html
    assert "Runtime Playbook" in html
    assert 'href="../../brain/lessons/runtime-lesson.md"' in html
    assert 'href="../../brain/playbooks/runtime-playbook.md"' in html


def test_has_dynamic_reveal_and_countup_script() -> None:
    # "Dynamic" = CSS entrance animation + a self-contained (dependency-free) script
    # that counts KPI numbers up and reveals sections on scroll.
    html = rp.render_digest_report(_SAMPLE)
    assert "@keyframes" in html
    assert "<script>" in html
    assert "IntersectionObserver" in html


def test_has_back_to_top_button() -> None:
    html = rp.render_digest_report(_SAMPLE)
    assert 'id="toTop"' in html
    assert 'aria-label="Back to top"' in html
    assert "window.scrollTo" in html


def test_vault_file_links_render_in_a_markdown_modal() -> None:
    """Clicking "open concept file" / "open note" must render the markdown in an
    in-report modal (fetch + embedded mini-renderer) instead of dumping raw text.
    Under file:// (fetch is origin-blocked) the links keep plain navigation."""
    html = rp.render_digest_report(_SAMPLE)
    # The modal shell ships in every report, hidden until a file link is opened.
    assert 'id="rbMdModal"' in html
    assert 'id="rbMdBody"' in html
    assert 'id="rbMdClose"' in html
    # The script intercepts vault file links, fetches and renders the markdown…
    assert "a.rb-file" in html
    assert "fetch(" in html
    assert "mdRender" in html
    # …escapes the file content before any markdown transform (vault notes are
    # sanitized upstream, but the modal must not trust them with live HTML)…
    assert "mdEscape" in html
    # …and falls back to plain navigation for file:// and failed fetches.
    assert "file:" in html
    assert "window.location.href" in html


def test_vault_file_links_carry_a_modal_title() -> None:
    """The modal headline is the concept/note title, not the file path."""
    html = rp.render_digest_report(
        _SAMPLE,
        concepts=[
            ReportConcept(
                name="Runtime Governance",
                local_path="../../brain/concepts/runtime-governance.md",
            )
        ],
        lessons=[
            ReportVaultNote(
                title="Runtime Lesson",
                note_type="lesson",
                local_path="../../brain/lessons/runtime-lesson.md",
            )
        ],
    )
    assert 'data-md-title="Runtime Governance"' in html
    assert 'data-md-title="Runtime Lesson"' in html


_LONG_CONCEPT_BODY = (
    "## What it is\n\nA long explanation paragraph.\n\n"
    "## Key facts\n\n- fact one\n- fact two\n\n"
    "## Details\n\n" + "\n".join(f"Detail line {i}." for i in range(40))
)


def test_concept_note_previews_key_facts_not_the_whole_file() -> None:
    """The card's "Concept note" is a preview — the modal owns the full text.
    When the note has a Key facts section, that is the important piece (the
    definition line above the note already covers "what it is")."""
    html = rp.render_digest_report(
        _SAMPLE,
        concepts=[
            ReportConcept(
                name="Runtime Governance",
                local_path="../../brain/concepts/runtime-governance.md",
                body=_LONG_CONCEPT_BODY,
            )
        ],
    )
    assert "fact one" in html
    assert "Detail line 30." not in html, "card must not dump the whole note"
    assert "Excerpt" in html, "a trimmed preview must say it is an excerpt"


def test_concept_note_without_key_facts_truncates_long_bodies() -> None:
    body = "\n".join(f"Plain line {i}." for i in range(60))
    html = rp.render_digest_report(
        _SAMPLE,
        concepts=[
            ReportConcept(
                name="Bare",
                local_path="../../brain/concepts/bare.md",
                body=body,
            )
        ],
    )
    assert "Plain line 0." in html
    assert "Plain line 59." not in html
    assert "Excerpt" in html


def test_concept_note_excerpt_is_client_rendered_markdown() -> None:
    """The card's Concept note ships as a `rb-note-md` <pre> that the report's
    embedded renderer upgrades to HTML on load (same mdRender as the modal, so
    the two views can't drift); without JS the raw text stays readable."""
    html = rp.render_digest_report(
        _SAMPLE,
        concepts=[
            ReportConcept(
                name="Runtime Governance",
                local_path="../../brain/concepts/runtime-governance.md",
                body=_LONG_CONCEPT_BODY,
            )
        ],
    )
    assert '<pre class="rb-note-md">' in html
    assert "pre.rb-note-md" in html, "the script must upgrade the note previews"


def test_short_concept_note_is_shown_in_full_without_excerpt_hint() -> None:
    html = rp.render_digest_report(
        _SAMPLE,
        concepts=[
            ReportConcept(
                name="Tiny",
                local_path="../../brain/concepts/tiny.md",
                body="## What it is\n\nShort.",
            )
        ],
    )
    assert "Short." in html
    assert "Excerpt" not in html


def test_escapes_untrusted_content() -> None:
    # A script tag in the digest body must be neutralised, never emitted live.
    html = rp.render_digest_report("# T\n\n_x_\n\n## S\n\n- <script>alert(1)</script>\n")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_deterministic_for_same_input() -> None:
    assert rp.render_digest_report(_SAMPLE) == rp.render_digest_report(_SAMPLE)


def test_supports_dark_mode() -> None:
    # A dark palette is applied via a media query that overrides the CSS custom
    # properties — not by forking the whole stylesheet.
    html = rp.render_digest_report(_SAMPLE)
    assert "@media (prefers-color-scheme: dark)" in html
    # The override redefines the core tokens (checked via the :root vars they set).
    assert "--bg:" in html
    assert "--ink:" in html


def test_has_print_styles() -> None:
    # A print block ensures the report exports cleanly to PDF (white bg, no motion).
    html = rp.render_digest_report(_SAMPLE)
    assert "@media print" in html
    assert "break-inside:avoid" in html


def test_has_semantic_landmarks_and_aria() -> None:
    # The hero is a banner landmark and the body content sits in a <main> region,
    # so assistive tech can navigate the report.
    html = rp.render_digest_report(_SAMPLE)
    assert 'role="banner"' in html
    assert "<main" in html
    # The KPI strip is labelled for screen readers.
    assert "aria-label" in html


def test_links_are_rendered_and_safe() -> None:
    html = rp.render_digest_report(_SAMPLE)
    assert 'href="https://example.com/glm"' in html
    # A javascript: URL from content must never become a live href.
    hostile = rp.render_digest_report("# T\n\n_x_\n\n## S\n\n- [x](javascript:alert(1))\n")
    assert "javascript:alert(1)" not in hostile


def test_google_fonts_url_is_valid_css2_syntax() -> None:
    # Every ;-separated variation tuple must carry one value PER axis —
    # `...wght@1,9..144,400;500` is an HTTP 400 from Google, so the report's
    # display fonts silently fell back to system defaults in every browser.
    import re

    html = rp.render_digest_report(_SAMPLE)
    match = re.search(r'href="(https://fonts\.googleapis\.com/css2\?[^"]+)"', html)
    assert match, "report must link the Google Fonts stylesheet"
    url = match.group(1)
    for family in re.findall(r"family=([^&]+)", url):
        if ":" not in family:
            continue
        _, spec = family.split(":", 1)
        axes, _, tuples = spec.partition("@")
        expected = len(axes.split(","))
        for tup in tuples.split(";"):
            assert len(tup.split(",")) == expected, (
                f"malformed css2 variation tuple {tup!r} for axes {axes!r} in {url}"
            )


# --- Golden byte-identity pin (report_theme split) ---------------------------
#
# The renderer is deterministic, so a (sha256, length) pin over representative
# inputs proves any refactor of the module layout keeps the output byte-for-byte
# identical. The pins below reflect the last INTENTIONAL output change (the
# vault-file markdown modal, 2026-07-14); regenerate them via
# `_print_golden_pins()` only when the output is meant to change.

_GLOSSARY_MD = "\n\n## 📖 Glossary\n\n- **RAG** — Retrieval-Augmented Generation\n"
_TRENDS_MD = "\n\n## 📈 Trends — 2026-07-01\n\n- Inflow: 67 this week\n"


def _golden_render_cases() -> list[tuple[str, str]]:
    """Representative (name, rendered HTML) pairs for the byte-identity pin.

    Together the three cases traverse every render path: `bare` hits all the
    empty/fallback branches (no stats, no audit, empty vault, no concepts),
    `glossary_fallback` renders the markdown glossary without config terms, and
    `rich` fills every tab (KPIs, trends, stats + audit link, per-topic audit
    drilldown, vault, searchable glossary, concept navigator).
    """
    rich = rp.render_digest_report(
        _SAMPLE + _TRENDS_MD + _GLOSSARY_MD,
        title="Weekly digest — golden",
        concepts=[
            ReportConcept(
                name="Runtime Governance",
                local_path="../../brain/concepts/runtime-governance.md",
                updated="2026-07-01",
                tags=["ai/governance", "sdlc"],
                definition="Policy and enforcement around agent runtime behavior.",
                body="## What it is\n\nPolicy and enforcement.",
                sources=[
                    ReportSource(
                        url="https://example.com/source",
                        local_path="../1-incoming/sdlc/source.md",
                        tier="high",
                    )
                ],
            ),
            # Minimal concept: no link, no definition, no sources, body fallback.
            ReportConcept(name="Bare Concept", local_path=""),
        ],
        lessons=[
            ReportVaultNote(
                title="Runtime Lesson",
                note_type="lesson",
                local_path="../../brain/lessons/runtime-lesson.md",
                tags=["ai/agents"],
                metadata="high confidence",
                summary="A reusable observation.",
            )
        ],
        # Minimal note: exercises the "No summary." / "No local link." branches.
        playbooks=[ReportVaultNote(title="Bare Playbook", note_type="playbook")],
        glossary_terms=[
            ReportGlossaryTerm("API", "Application Programming Interface"),
            ReportGlossaryTerm("RAG", "Retrieval-Augmented Generation"),
        ],
        stats=ReportStats(
            new_sources=67,
            topics=6,
            included_sources=3,
            hidden_sources=2,
            audit_path="digest_2026-07-01.audit.json",
            updated_concepts=3,
            concepts_created=2,
            concepts_updated=1,
            existing_concepts_reused=4,
            attention_items=1,
            total_concepts=35,
            total_lessons=1,
            total_playbooks=1,
            lessons_base_path="../../brain/lessons.base",
            playbooks_base_path="../../brain/playbooks.base",
            glossary_terms=2,
            topic_stats=[ReportTopicStat("ai-ml", 20), ReportTopicStat("sdlc", 11)],
        ),
        audit_topics=[
            ReportAuditTopic(
                topic="ai-ml",
                total_sources=2,
                included_sources=1,
                hidden_sources=1,
                decisions=[
                    ReportAuditDecision(
                        title="Shown source",
                        url="https://example.com/shown",
                        tier="high",
                        included=True,
                        rank=1,
                        reason="selected_by_source_credibility",
                    ),
                    ReportAuditDecision(
                        title="Hidden source",
                        included=False,
                        reason="hidden_topic_cap",
                    ),
                ],
            ),
            # Silent topic: exercises the health label + empty-decision branches.
            ReportAuditTopic(
                topic="quiet-topic", total_sources=0, included_sources=0, hidden_sources=0
            ),
        ],
    )
    return [
        ("bare", rp.render_digest_report(_SAMPLE)),
        ("glossary_fallback", rp.render_digest_report(_SAMPLE + _GLOSSARY_MD)),
        ("rich", rich),
    ]


def _print_golden_pins() -> None:
    """Print the current (sha256, length) pins — paste into the golden test.

    Only regenerate after an INTENTIONAL output change:
        uv run python -c "from tests.test_digest_report_html import _print_golden_pins; _print_golden_pins()"
    """
    for name, html in _golden_render_cases():
        digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
        print(f'        "{name}": ("{digest}", {len(html)}),')


def test_output_is_byte_identical_to_pre_split_golden() -> None:
    expected = {
        "bare": ("4f82941135d2eb4bb0824c73b49180550eadb655e5a4789471e3b8e3fbc5a106", 34170),
        "glossary_fallback": ("66e1c2d95cdfe594f45140e3cc68ad54a2b8624a347a231d04fbf2283619b5bb", 34238),
        "rich": ("a7279b2d98be4972e8ae4797db2fac8d61bbca7aacbd229e67978afdec89dfe0", 41687),
    }
    actual = {
        name: (hashlib.sha256(html.encode("utf-8")).hexdigest(), len(html))
        for name, html in _golden_render_cases()
    }
    assert actual == expected, (
        "report output drifted from the pre-split golden; if the change is "
        "intentional, regenerate the pins with _print_golden_pins()"
    )


# --------------------------------------------------------------------------- #
# UI feedback pass (2026-07-22): a11y of the pick button, scoped synthesis
# metrics (resolve the "0 updated" vs "N this run" confusion), complete the
# ARIA tab pattern + keyboard nav, a mobile tab-scroll hint, and a source-tier
# badge in Read today so low-tier picks aren't shown as equal to verified ones.
# --------------------------------------------------------------------------- #


def test_star_button_has_accessible_name() -> None:
    # The pick toggle carried only a title (not an accessible name) and was a
    # tiny tap target. A screen reader needs an aria-label.
    html = rp._star_button("https://example.com/x")
    assert "aria-label=" in html
    assert "rb-star" in html


def test_synthesis_counts_are_scoped_not_ambiguous_this_run() -> None:
    # "Updated this run: 7" next to a hero "0 updated concepts" read as a
    # contradiction. The synthesis-log counts must be scoped to the synthesis
    # step, not the ambiguous "this run".
    html = rp.render_digest_report(
        _SAMPLE,
        stats=ReportStats(
            new_sources=10, topics=2, updated_concepts=0,
            concepts_created=4, concepts_updated=7,
        ),
    )
    assert "Created this run" not in html
    assert "Updated this run" not in html
    assert "last synthesis" in html.lower()


def test_tabs_have_ids_and_panels_are_labelledby() -> None:
    # Complete the ARIA tabs pattern: each tab needs an id, each panel an
    # aria-labelledby pointing back at its tab.
    html = rp.render_digest_report(_SAMPLE)
    for key in ("digest", "pulse", "vault", "glossary", "concepts"):
        assert f'id="tab-{key}"' in html, f"tab {key} missing id"
        assert f'aria-labelledby="tab-{key}"' in html, f"panel {key} missing aria-labelledby"


def test_read_today_marks_source_tier_and_flags_low() -> None:
    topics = [
        ReportAuditTopic(
            topic="codex", total_sources=2, included_sources=2, hidden_sources=0,
            decisions=[
                ReportAuditDecision(
                    title="Verified claim", url="https://example.com/high",
                    tier="high", included=True, rank=1,
                ),
                ReportAuditDecision(
                    title="Unconfirmed claim", url="https://example.com/low",
                    tier="low", included=True, rank=2,
                ),
            ],
        )
    ]
    html = rp._render_read_today(topics)
    assert "rb-tier" in html            # every pick carries a visible tier badge
    assert "rb-tier-low" in html        # low-tier is visually distinct
    assert "rb-tier-high" in html


def test_tab_keyboard_nav_and_mobile_scroll_hint_present() -> None:
    html = rp.render_digest_report(_SAMPLE)
    # Roving-tabindex arrow navigation for the tablist.
    assert "ArrowRight" in html and "ArrowLeft" in html
    assert "Home" in html and "End" in html
    # A CSS affordance that the tab row scrolls on narrow viewports.
    assert "rb-tabs-scroll" in html


# --------------------------------------------------------------------------- #
# "For me, strengthen Obsidian linking + the Concepts tab" (2026-07-22).
# The report is a personal companion to the Obsidian vault, not a replacement:
# deep-link INTO Obsidian (Bases front door + the exact note) and let the
# Concepts tab filter by tag. Progressive enhancement — degrades without JS.
# --------------------------------------------------------------------------- #


def test_obsidian_uri_is_vault_relative_without_extension() -> None:
    assert (
        rp._obsidian_uri("../../brain/concepts/runtime-governance.md")
        == "obsidian://open?file=concepts/runtime-governance"
    )
    assert rp._obsidian_uri("") == ""            # no path -> no link
    assert rp._obsidian_uri("notes/x.md") == ""  # not under a brain/ vault


def test_concepts_tab_deep_links_into_obsidian() -> None:
    html = rp.render_digest_report(
        _SAMPLE,
        concepts=[
            ReportConcept(
                name="Runtime Governance",
                local_path="../../brain/concepts/runtime-governance.md",
                updated="2026-07-01",
                tags=["ai/governance", "sdlc"],
                definition="Policy around agent runtime.",
            )
        ],
    )
    # Bases front door CTA (all concepts + graph live in Obsidian).
    assert "obsidian://open?file=concepts.base" in html
    # Per-concept deep link to the exact note.
    assert "obsidian://open?file=concepts/runtime-governance" in html


def test_concepts_tab_offers_tag_filters() -> None:
    html = rp.render_digest_report(
        _SAMPLE,
        concepts=[
            ReportConcept(name="A", local_path="", tags=["ai/agents"]),
            ReportConcept(name="B", local_path="", tags=["sdlc"]),
        ],
    )
    # A filter chip per distinct tag, wired for the client-side filter.
    assert 'data-tag-filter="ai/agents"' in html
    assert 'data-tag-filter="sdlc"' in html
