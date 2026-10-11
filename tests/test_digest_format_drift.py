"""Drift tests: the digest FORMAT is owned by the code; the prose must match.

The agentic path (`schedule/weekly-digest.md`, `skills/digest-build/SKILL.md`)
builds digests by following prose, the headless path by running
`scripts/digest/render.py` — when the two describe different markers/headings,
users get two different digest formats depending on who built this week's.
These tests parse the prose and pin it to the code's actual constants, so any
future format change must update both sides in one commit.
"""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

from scripts.corroborate import trust_line
from scripts.digest.model import QUIET_DIGEST_HTML_MARKER, _tier_marker
from scripts.hygiene.model import BrainHealth

_WEEKLY_DIGEST = (_PROJECT_ROOT / "schedule" / "weekly-digest.md").read_text(encoding="utf-8")
_WEEKLY_SYNTHESIS = (
    _PROJECT_ROOT / "schedule" / "weekly-synthesis.md"
).read_text(encoding="utf-8")
_DIGEST_BUILD = (
    _PROJECT_ROOT / "skills" / "digest-build" / "SKILL.md"
).read_text(encoding="utf-8")
_CONVENTIONS = (_PROJECT_ROOT / "docs" / "CONVENTIONS.md").read_text(encoding="utf-8")
_SCHEDULING = (_PROJECT_ROOT / "docs" / "scheduling.md").read_text(encoding="utf-8")
_SETUP_WIZARD = (
    _PROJECT_ROOT / "skills" / "setup-wizard" / "SKILL.md"
).read_text(encoding="utf-8")
_AGENTS = (_PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
_ARCHITECTURE = (_PROJECT_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
_VALIDATE_BRAIN = (_PROJECT_ROOT / "scripts" / "validate_brain.py").read_text(
    encoding="utf-8"
)
_BUILD_DIGEST_SCRIPT = (_PROJECT_ROOT / "scripts" / "build_digest.py").read_text(
    encoding="utf-8"
)
_DIGEST_SCAN = (_PROJECT_ROOT / "scripts" / "digest" / "scan.py").read_text(
    encoding="utf-8"
)

# The section headings render.py actually writes (parameterized parts elided).
_RENDER_HEADINGS = (
    "## ⚡ TL;DR",
    "## 📰 New sources",
    "## 💡 Updated concepts",
    "## 🧪 Synthesis this week",
    "## 📌 Needs attention",
)


def test_prose_template_uses_the_rendered_section_headings() -> None:
    for heading in _RENDER_HEADINGS:
        assert heading in _WEEKLY_DIGEST, (
            f"weekly-digest.md template lost the real heading {heading!r} — "
            "the agent-built digest would diverge from the headless one"
        )


def test_prose_does_not_describe_the_retired_bracket_tier_markers() -> None:
    # The code renders only a trailing ⭐ for tier: high (model._tier_marker);
    # `[high]` / `[medium]` / `[low]` markers never render.
    for prose in (_WEEKLY_DIGEST, _DIGEST_BUILD):
        assert "[high] / [medium] / [low]" not in prose
        assert "`[high]` / `[medium]` / `[low]`" not in prose
    assert _tier_marker("high") == " ⭐"
    assert _tier_marker("medium") == ""
    assert "⭐" in _WEEKLY_DIGEST


def test_prose_trust_lines_match_corroborate_output() -> None:
    # Both text-map paths use the same non-confirmation marker:
    filtered = trust_line({"level": "multi", "collapsed": True, "independent": 3})
    reported = trust_line({"level": "multi", "collapsed": False, "independent": 3})
    single = trust_line({"level": "single"})
    assert filtered == "🔵 3 retained publisher domains — check the claim"
    assert reported == "🔵 3 retained publisher domains — check the claim"
    assert single == "🟡 One retained publisher domain — check the claim"
    # The prose must show the same glyph forms (with N in place of the count).
    for needle in (
        "🔵 N retained publisher domains — check the claim",
        "🟡 One retained publisher domain — check the claim",
    ):
        assert needle in _WEEKLY_DIGEST, f"weekly-digest.md lost {needle!r}"
    # The retired plain-ASCII glyphs must not resurface as the format.
    assert "`✓ Confirmed" not in _WEEKLY_DIGEST
    assert "`⚠ Single-source" not in _WEEKLY_DIGEST


def test_prose_health_line_matches_render_prefix() -> None:
    # render.py writes "**🟢 Knowledge base:** <headline>" (⚠️ when dirty).
    assert "**🟢 Knowledge base:**" in _WEEKLY_DIGEST
    assert "**Knowledge base health:**" not in _WEEKLY_DIGEST


def test_prose_health_headline_is_the_machine_matched_form() -> None:
    # The digest keys on the `Health:` middot headline, not the human comma one.
    weekly_run = (_PROJECT_ROOT / "schedule" / "weekly-run.md").read_text(encoding="utf-8")
    health = BrainHealth(concept_count=12)
    assert health.health_headline.startswith("Health: ")
    assert "·" in health.health_headline
    assert "Health: N concepts · X orphans" in weekly_run
    assert "uncited-facts" in health.health_headline
    for prose in (
        _WEEKLY_DIGEST,
        weekly_run,
        _CONVENTIONS,
        _VALIDATE_BRAIN,
        _BUILD_DIGEST_SCRIPT,
        _DIGEST_SCAN,
    ):
        assert "uncited-facts" in prose
    for prose in (_AGENTS, _ARCHITECTURE, _SCHEDULING, _SETUP_WIZARD):
        assert "uncited" in prose
    assert "any issue counter is non-zero" in _WEEKLY_DIGEST


def test_scheduling_docs_match_headless_collection_contract() -> None:
    assert "static article-page top-up" in _SCHEDULING
    assert "summary-only feeds needing body-completion" not in _SCHEDULING
    assert "feed already carries the full article body" not in _SCHEDULING


def test_quiet_marker_documented_in_both_prose_files() -> None:
    assert QUIET_DIGEST_HTML_MARKER in _DIGEST_BUILD
    assert QUIET_DIGEST_HTML_MARKER in _WEEKLY_DIGEST


def test_value_evidence_prose_matches_rendered_contract() -> None:
    for needle in (
        "concepts created",
        "concepts updated",
        "existing concepts reused",
        "Knowledge base changes",
        "Reused existing knowledge",
    ):
        assert needle in _WEEKLY_SYNTHESIS
        assert needle in _WEEKLY_DIGEST
        assert needle in _DIGEST_BUILD
