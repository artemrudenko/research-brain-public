#!/usr/bin/env python3
"""
build_digest.py — deterministic, headless weekly-digest builder.

The agent-driven `weekly-digest` task can enrich a digest with prose, but the
headless (cron) path needs a *deterministic* equivalent that runs without an
agent. This module is that equivalent: it scans the same inputs the task does
and writes the same `digest_YYYY-MM-DD.md` file, which `deliver.py` then sends.

Layout: this file is the CLI + stable import surface. The implementation lives
in the `scripts/digest/` package — `model` (data types + text primitives),
`scan` (everything that reads the vault), `render` (markdown rendering) — and
every name is re-exported here, so `from scripts.build_digest import …` keeps
working unchanged for callers and tests.

Every build writes the canonical Markdown digest plus a JSON audit sidecar next
to it (`digest_YYYY-MM-DD.audit.json`) explaining the per-topic source-selection
decisions. `--html` writes the email-grade HTML render; `--report` writes the
static browser-grade operator report (`digest_YYYY-MM-DD.report.html`) that links
to the audit sidecar.

What it scans (all relative to the project root, resolved regardless of cwd):
  - `pipeline/1-incoming/**/*.md` — articles whose frontmatter `collected:` date
    falls within the lookback window, grouped by `category` (topic). For each:
    the title plus the first "Key takeaways" bullet (falling back to the first
    non-empty body line).
  - `brain/concepts/*.md` — concept notes whose frontmatter (or body) `last_updated`
    falls within the lookback window. SEED / EXAMPLE notes are excluded
    (CONVENTIONS §5.1). For each: the concept name plus the first line of its
    "What it is" / definition section.
  - `pipeline/3-synthesis/synthesis-run_*.md` — the most recent run log is summarized
    under "Synthesis this week" (best-effort; omitted when none exists).
  - `pipeline/3-synthesis/brain-health_*.md` — the most recent brain-health report
    (written by `scripts/validate_brain.py`) yields a one-line "Knowledge base health"
    note, e.g. "12 concepts · 0 orphans · 0 broken links · 0 missing-sources ·
    0 uncited-facts · 1 stale" (best-effort; omitted when none exists).
  - "Needs attention": incoming files older than 14 days whose registry `status`
    is blank (not `processed` / `rejected`).

Source credibility: an article's frontmatter or a concept's `sources:` entry may
carry an optional `tier:` field (high / medium / low). Only `high` renders a marker —
a trailing ` ⭐` next to the item (see `model._tier_marker`) — so a reader can spot
the most credible items. `medium` / `low` / absent `tier` → no marker (graceful).

Corroboration (CONVENTIONS §16): each updated concept also gets a plain-language
*trust line* derived from its `sources:` by `scripts/corroborate.py` — "🔵 Reported
by N sources" (≥2 distinct registrable domains; "🟢 Confirmed by N independent
sources" only when syndication was actually collapsed) or "🟡 Single-source — treat
with caution" (1). A concept with no sources renders no trust line (graceful).

Lookback comes from `config/schedule.yaml` → `digest.lookback_days` (default 7);
the `--lookback N` CLI flag overrides it.

A "quiet week" (zero new sources AND zero updated concepts) writes a one-line
digest and prints a `QUIET_WEEK_MARKER` line on stdout so the caller can choose
to skip delivery; the process still exits 0.

CLI:
    python3 scripts/build_digest.py [out.md] [--lookback N] [--require-synthesis-log]
                                    [--allow-unsanitized]

`out.md` defaults to `pipeline/3-synthesis/digest_YYYY-MM-DD.md` (date = today).

The anti-injection sanitize gate is ON BY DEFAULT (fail-closed): the build refuses
(non-zero exit, nothing written) unless every incoming article has a current sanitized
companion (reusing `sanitize_incoming.gate_tree` — the same S1–S9 gate the agentic
`weekly-run.md` runs at step 2). The render side matches the gate: `scan_incoming`
reads the CURRENT sanitized companion (not the raw article) whenever one exists, so the
delivered digest carries only S1–S9-stripped text. Run `sanitize_incoming.py sanitize`
first when ingesting untrusted feeds; an empty incoming tree passes
trivially. `--allow-unsanitized` is the explicit opt-out for fully-controlled feeds
(builds from raw articles, though a current companion is still preferred); the legacy
`--require-sanitized` flag is accepted as a no-op reaffirming the default.

`--require-synthesis-log` (default OFF) is an optional barrier for the gated
orchestrator: it refuses to build (non-zero exit, nothing written) unless a recent
synthesis run log `pipeline/3-synthesis/synthesis-run_YYYY-MM-DD.md` exists — dated
today or within `SYNTHESIS_LOG_GRACE_DAYS` (a midnight-rollover grace) — so a
half-written / never-synthesized brain/ can never be digested. Left off, the
headless cron path builds as before (it legitimately runs without the synthesis step).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

# Resolve the project root from this file's location (scripts/ -> root), so the
# builder works no matter the current working directory (CONVENTIONS §1).
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Make the `scripts` package importable when run directly as a script
# (`python3 scripts/build_digest.py`), not only as a module (`-m scripts...`).
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.delivery.digest_report_html import render_digest_report  # noqa: E402
from scripts.delivery.email_html import render_email_html  # noqa: E402
from scripts.digest import strings as digest_strings  # noqa: E402
from scripts.digest.model import (  # noqa: E402
    QUIET_WEEK_MARKER,
    TIER_VALUES,
    AttentionItem,
    ConceptItem,
    DigestData,
    IncomingItem,
    IncomingNotSanitized,
    SynthesisLogMissing,
    VaultNoteItem,
    _md_link,
    _normalize_tier,
    _plural,
    _tier_marker,
)
from scripts.digest.render import (  # noqa: E402
    DIGEST_LINKS_PER_TOPIC,
    _brain_health_clean,
    _curate_topic_items,
    render,
)
from scripts.digest.report_inputs import (  # noqa: E402
    _digest_audit_payload,
    _previous_report_name,
    _report_audit_topics,
    _report_concepts,
    _report_glossary_terms,
    _report_rel_path,
    _report_stats,
    _report_vault_notes,
)
from scripts.digest.scan import (  # noqa: E402
    DEFAULT_DAILY_LOOKBACK_DAYS,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_TECHNICAL_LEVEL,
    HANDLED_STATUSES,
    LEAD_MAX_CHARS,
    STALE_INCOMING_DAYS,
    SYNTHESIS_LOG_GRACE_DAYS,
    SYNTHESIS_LOG_TEMPLATE,
    _check_incoming_sanitized,
    _concept_definition,
    _concept_last_updated,
    _concept_name,
    _concept_source_tier,
    _concept_sources,
    _dedup_by_url,
    _first_takeaway,
    _frontmatter_block,
    _is_seed_or_example,
    _parse_iso_date,
    _parse_registry_statuses,
    _sources_block,
    _split_frontmatter,
    _status_key,
    _within_lookback,
    gather,
    latest_brain_health,
    latest_synthesis_summary,
    latest_value_evidence,
    load_topic_leads,
    read_daily_lookback_days,
    read_lookback_days,
    read_technical_level,
    scan_attention,
    scan_concepts,
    scan_incoming,
    scan_vault_notes,
    synthesis_log_exists,
)
from scripts.glossary import append_glossary, load_glossary, uncovered_acronyms  # noqa: E402
from scripts.registry import atomic_write_text as _atomic_write_text  # noqa: E402
from scripts.trends import build_trends_section  # noqa: E402

# The compatibility surface: everything the pre-split 1,600-line module defined
# at top level and other modules / tests import from here. Keeping the private
# helpers listed keeps `from scripts.build_digest import _split_frontmatter`
# (brain_status.py) and the tests' `bd._…` accesses working across the split.
__all__ = [
    "DEFAULT_DAILY_LOOKBACK_DAYS",
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_TECHNICAL_LEVEL",
    "DIGEST_LINKS_PER_TOPIC",
    "HANDLED_STATUSES",
    "LEAD_MAX_CHARS",
    "PROJECT_ROOT",
    "QUIET_WEEK_MARKER",
    "STALE_INCOMING_DAYS",
    "SYNTHESIS_LOG_GRACE_DAYS",
    "SYNTHESIS_LOG_TEMPLATE",
    "TIER_VALUES",
    "AttentionItem",
    "ConceptItem",
    "DigestData",
    "IncomingItem",
    "IncomingNotSanitized",
    "SynthesisLogMissing",
    "VaultNoteItem",
    "_atomic_write_text",
    "_brain_health_clean",
    "_check_incoming_sanitized",
    "_concept_definition",
    "_concept_last_updated",
    "_concept_name",
    "_concept_source_tier",
    "_concept_sources",
    "_curate_topic_items",
    "_dedup_by_url",
    "_first_takeaway",
    "_frontmatter_block",
    "_is_seed_or_example",
    "_md_link",
    "_normalize_tier",
    "_parse_iso_date",
    "_parse_registry_statuses",
    "_plural",
    "_sources_block",
    "_split_frontmatter",
    "_status_key",
    "_tier_marker",
    "_within_lookback",
    "build_digest",
    "audit_out_path",
    "daily_out_path",
    "default_out_path",
    "gather",
    "html_out_path",
    "latest_brain_health",
    "latest_synthesis_summary",
    "latest_value_evidence",
    "load_topic_leads",
    "main",
    "read_daily_lookback_days",
    "read_lookback_days",
    "read_technical_level",
    "render",
    "report_out_path",
    "scan_attention",
    "scan_concepts",
    "scan_incoming",
    "scan_vault_notes",
    "synthesis_log_exists",
]


def build_digest(
    out_path: Path,
    *,
    root: Path = PROJECT_ROOT,
    lookback_days: int | None = None,
    today: date | None = None,
    require_synthesis_log: bool = False,
    require_sanitized: bool = True,
    write_html: bool = False,
    write_report: bool = False,
    daily: bool = False,
    include_trends: bool = False,
) -> DigestData:
    """Build the digest, write it to `out_path`, and return the gathered data.

    `lookback_days` overrides config when given; `today` overrides the system
    clock (used by tests for determinism).

    `write_html` (default OFF) additionally persists a self-contained, styled
    HTML report next to the markdown (`html_out_path(out_path)`), reusing the
    same `email_html.render_email_html` renderer the email transport uses — so
    the markdown stays the canonical artifact and the HTML is a derived view.

    `require_synthesis_log` is an opt-in barrier (default OFF): when True, the
    build REFUSES (raises :class:`SynthesisLogMissing`, writing nothing) unless
    today's synthesis run log exists — so a missing or partial synthesis can never
    be digested. Left OFF, behavior is exactly as before, which keeps the headless
    cron path (which legitimately builds without the agent synthesis step) working.

    `require_sanitized` is a second, fail-closed barrier (default ON): the build
    REFUSES (raises :class:`IncomingNotSanitized`, writing nothing) unless every
    incoming article has a current sanitized companion — so the headless path can
    never render un-sanitized incoming frontmatter into a delivered digest unless
    the caller explicitly opts out (`require_sanitized=False` / CLI
    `--allow-unsanitized`, for fully-controlled feeds). An empty incoming tree
    passes trivially, so a fresh install / quiet week still builds.
    """
    if today is None:
        # Default "today" off UTC (not local date.today()) so every persisted
        # digest date sits on the same axis health.py reads — near local midnight
        # in a non-UTC zone, a local date would mis-stamp the filename/window and
        # flip health's stale-boundary verdict (the cross-clock seam).
        today = datetime.now(UTC).date()
    # Fail-closed sanitize barrier runs BEFORE any gather/write, so a missing
    # companion never lets un-sanitized incoming text reach the rendered digest.
    if require_sanitized:
        _check_incoming_sanitized(root / "pipeline" / "1-incoming")
    if require_synthesis_log and not synthesis_log_exists(
        root / "pipeline" / "3-synthesis", today=today
    ):
        raise SynthesisLogMissing(
            f"refusing to build digest: no recent synthesis run log "
            f"(e.g. {SYNTHESIS_LOG_TEMPLATE.format(date=today.isoformat())}, within "
            f"{SYNTHESIS_LOG_GRACE_DAYS}-day grace) under pipeline/3-synthesis/ — "
            f"brain/ may be un-synthesized this run"
        )
    if lookback_days is None:
        # Daily and weekly read their own lookback block (ADR 0016).
        reader = read_daily_lookback_days if daily else read_lookback_days
        lookback_days = reader(root / "config" / "schedule.yaml")
    data = gather(root, today=today, lookback_days=lookback_days)
    language = data.language  # chrome language (delivery.language; en fallback)
    # Append a plain-language glossary for any jargon the digest actually uses
    # (config/glossary.yaml; no-op when the file is absent or nothing matches).
    glossary_path = root / "config" / "glossary.yaml"
    rendered = render(data, daily=daily)
    # Embed the weekly TRENDS section (ADR 0017) inline before the glossary, so
    # the digest carries "how it's changing" next to "what happened". Weekly-only:
    # the light daily inflow digest never renders it (it's a same-week snapshot).
    # Quiet weeks are also skipped: render_trends never returns empty, so the
    # one-line quiet digest would otherwise grow a zero-noise Trends section.
    if include_trends and not daily and not data.is_quiet:
        section = build_trends_section(root=root, today=today, language=language)
        if section.strip():
            rendered = f"{rendered.rstrip(chr(10))}\n\n{section.rstrip(chr(10))}\n"
    markdown = append_glossary(
        rendered, glossary_path, heading=digest_strings.tr(language, "glossary_heading")
    )
    # Make the audience knob visible on the deterministic artifact: this builder
    # cannot reword at delivery.technical_level (docs/audience-levels.md), so a
    # non-default level gets an honest one-line footer instead of a silent no-op.
    # Quiet digests stay one-liners; the agent replaces this line when it
    # re-renders at the level (schedule/weekly-digest.md).
    level = read_technical_level(root / "config" / "channels.yaml")
    if level != DEFAULT_TECHNICAL_LEVEL and not (
        data.is_quiet_daily if daily else data.is_quiet
    ):
        markdown = (
            markdown.rstrip("\n")
            + "\n\n"
            + digest_strings.tr(language, "footer_audience", level=level)
            + "\n"
        )
    # Make the feedback loop discoverable on the delivered artifact: one muted
    # line naming the phrases the digest-feedback skill maps onto config changes.
    # Quiet digests stay one-liners.
    if not (data.is_quiet_daily if daily else data.is_quiet):
        markdown = (
            markdown.rstrip("\n")
            + "\n\n"
            + digest_strings.tr(language, "footer_feedback")
            + "\n"
        )
    # A browser report nothing names is invisible: when one is written alongside,
    # point the delivered markdown at the sibling file (same directory, so the
    # relative link opens from Obsidian / a file browser; the Telegram MCP path
    # attaches the file itself — skills/digest-deliver).
    if write_report and not (data.is_quiet_daily if daily else data.is_quiet):
        report_name = report_out_path(out_path).name
        markdown = (
            markdown.rstrip("\n")
            + "\n\n"
            + digest_strings.tr(language, "footer_report", name=report_name)
            + "\n"
        )
    # Non-fatal sufficiency check: warn (never fail) when the digest uses domain
    # acronyms the glossary does not yet define, so under-coverage is visible.
    missing = uncovered_acronyms(rendered, load_glossary(glossary_path))
    if missing:
        print(
            f"warning: {len(missing)} acronym(s) in the digest are not in the "
            f"glossary — consider adding them to config/glossary.yaml: "
            f"{', '.join(missing)}",
            file=sys.stderr,
        )
    # Atomic write so a crash mid-write can never truncate/corrupt the digest.
    _atomic_write_text(out_path, markdown)
    audit_path = audit_out_path(out_path)
    _atomic_write_text(
        audit_path,
        json.dumps(
            _digest_audit_payload(
                data,
                root=root,
                digest_path=out_path,
                digest_markdown=markdown,
                daily=daily,
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    if write_html:
        # Render the SAME canonical markdown to a styled, standalone HTML report.
        _atomic_write_text(html_out_path(out_path), render_email_html(markdown))
    if write_report:
        # Render the SAME canonical markdown to the dynamic, browser-grade
        # viewing report (showcase design) — a page to open, not to email.
        report_path = report_out_path(out_path)
        report_concepts = _report_concepts(root, report_dir=report_path.parent)
        report_lessons = _report_vault_notes(
            root, report_dir=report_path.parent, subdir="lessons", note_type="lesson"
        )
        report_playbooks = _report_vault_notes(
            root,
            report_dir=report_path.parent,
            subdir="playbooks",
            note_type="playbook",
        )
        report_glossary = _report_glossary_terms(glossary_path)
        _atomic_write_text(
            report_path,
            render_digest_report(
                markdown,
                concepts=report_concepts,
                lessons=report_lessons,
                playbooks=report_playbooks,
                glossary_terms=report_glossary,
                stats=_report_stats(
                    data,
                    audit_path=_report_rel_path(audit_path, report_dir=report_path.parent),
                    total_concepts=len(report_concepts),
                    total_lessons=len(report_lessons),
                    total_playbooks=len(report_playbooks),
                    lessons_base_path=_report_rel_path(
                        root / "brain" / "lessons.base", report_dir=report_path.parent
                    ),
                    playbooks_base_path=_report_rel_path(
                        root / "brain" / "playbooks.base", report_dir=report_path.parent
                    ),
                    glossary_terms=len(report_glossary),
                ),
                audit_topics=_report_audit_topics(data),
                prev_report=_previous_report_name(report_path, daily=daily),
            ),
        )
    return data


def default_out_path(root: Path, today: date) -> Path:
    """The conventional output path: pipeline/3-synthesis/digest_YYYY-MM-DD.md."""
    return root / "pipeline" / "3-synthesis" / f"digest_{today.isoformat()}.md"


def html_out_path(out_path: Path) -> Path:
    """The HTML report sibling of a digest markdown path (same stem, `.html`)."""
    return out_path.with_suffix(".html")


def report_out_path(out_path: Path) -> Path:
    """The dynamic viewing-report sibling of a digest path (same stem, `.report.html`).

    A distinct suffix from the email `.html` so the two artifacts (email-grade vs
    browser-grade) never collide on one file.
    """
    return out_path.with_suffix(".report.html")


def audit_out_path(out_path: Path) -> Path:
    """The JSON audit sidecar sibling of a digest path (`.audit.json`)."""
    return out_path.with_suffix(".audit.json")


def daily_out_path(root: Path, today: date) -> Path:
    """The daily digest path: pipeline/3-synthesis/digest_daily_YYYY-MM-DD.md.

    A distinct stem from the weekly `digest_YYYY-MM-DD.md` so a daily and weekly
    build on the same date never collide on one file (ADR 0016).
    """
    return root / "pipeline" / "3-synthesis" / f"digest_daily_{today.isoformat()}.md"


def _live_run_lock_holder(root: Path) -> str | None:
    """A short description of a LIVE weekly-run lock holder, or None.

    "Live" mirrors the lock's own reclaim semantics without stealing anything:
    a lock is dead (→ None, safe to build) when its lease has lapsed, or when
    it belongs to this host and its pid no longer exists. Read-only — the CLI
    check must never mutate lock state (it isn't the lock's owner).
    """
    import socket  # noqa: PLC0415 — only this check needs it
    import time  # noqa: PLC0415

    from scripts.run_lock import (  # noqa: PLC0415 — lazy: CLI-only concern
        DEFAULT_STALE_AFTER,
        is_pid_alive,
        read_lock,
    )

    info = read_lock(root / "pipeline" / ".run.lock")
    if info is None:
        return None
    age = time.time() - info.ts
    if age >= DEFAULT_STALE_AFTER:
        return None  # lease lapsed — the next acquire would reclaim it anyway
    if info.host == socket.gethostname() and not is_pid_alive(info.pid):
        return None  # same-host holder is verifiably dead
    return f"pid {info.pid} on {info.host}, note {info.note!r}, {int(age)}s old"


def main(argv: list[str] | None = None, *, today: date | None = None) -> int:
    """CLI entry point: `build_digest.py [out.md] [--lookback N]`.

    `today` overrides the system clock (tests pass it for deterministic dates).
    """
    parser = argparse.ArgumentParser(
        prog="build_digest.py",
        description="Deterministically build the weekly digest markdown file.",
    )
    parser.add_argument(
        "out",
        nargs="?",
        default=None,
        help="Output path (default: pipeline/3-synthesis/digest_YYYY-MM-DD.md).",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=None,
        metavar="N",
        help="Override digest.lookback_days from config/schedule.yaml.",
    )
    parser.add_argument(
        "--require-synthesis-log",
        action="store_true",
        help=(
            "Refuse to build unless a recent synthesis run log "
            "(pipeline/3-synthesis/synthesis-run_YYYY-MM-DD.md, dated today or "
            "within a 1-day grace) exists, so a "
            "missing/partial synthesis is never digested. Default OFF "
            "(the headless cron path builds without the agent synthesis step)."
        ),
    )
    parser.add_argument(
        "--require-sanitized",
        action="store_true",
        help=(
            "Deprecated no-op kept for compatibility: the sanitize gate is now the "
            "DEFAULT (refuse to build unless every incoming article has a current "
            "S1–S9 sanitized companion; run `sanitize_incoming.py sanitize` "
            "first). Conflicts with --allow-unsanitized."
        ),
    )
    parser.add_argument(
        "--allow-unsanitized",
        action="store_true",
        help=(
            "Explicitly OPT OUT of the fail-closed sanitize gate and build even when "
            "incoming articles lack a current sanitized companion — only for fully-"
            "controlled feeds. Default: the gate is ON."
        ),
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help=(
            "Also write a self-contained, styled HTML report next to the markdown "
            "(digest_YYYY-MM-DD.html), reusing the email renderer. Default OFF "
            "(the markdown stays the canonical artifact)."
        ),
    )
    parser.add_argument(
        "--daily",
        action="store_true",
        help=(
            "Build the light DAILY 'inflow' digest (ADR 0016): only New sources + "
            "Needs attention, a 1-day default window (daily_digest.lookback_days), "
            "written to digest_daily_YYYY-MM-DD.md. Default OFF (weekly digest)."
        ),
    )
    parser.add_argument(
        "--trends",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Embed the weekly TRENDS section (ADR 0017) inline in the weekly digest "
            "— topic volume, rising tags, activity, and knowledge growth vs the "
            "prior week. ON by default so scheduled/cron digests carry it without "
            "an extra flag; --no-trends disables. Quiet weeks and --daily never "
            "embed it."
        ),
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help=(
            "Also write a dynamic, browser-grade HTML report next to the markdown "
            "(digest_YYYY-MM-DD.report.html) in the showcase design — a page to "
            "open and view (distinct from the email --html). Default OFF."
        ),
    )
    parser.add_argument(
        "--ignore-run-lock",
        action="store_true",
        help=(
            "Build even while pipeline/.run.lock is held by a live weekly run. "
            "Default OFF: a digest built mid-run can read a half-synthesized "
            "brain/. Only for operators who know the run is not writing."
        ),
    )
    args = parser.parse_args(argv)

    if args.lookback is not None and args.lookback <= 0:
        print("error: --lookback must be a positive integer", file=sys.stderr)
        return 2

    if args.require_sanitized and args.allow_unsanitized:
        print(
            "error: --require-sanitized and --allow-unsanitized contradict each "
            "other; the sanitize gate is on by default — drop both, or keep only "
            "--allow-unsanitized to opt out",
            file=sys.stderr,
        )
        return 2

    if not args.ignore_run_lock:
        holder = _live_run_lock_holder(PROJECT_ROOT)
        if holder is not None:
            print(
                "error: refusing to build — the weekly-run run lock is held "
                f"({holder}); a digest built now could read a half-synthesized "
                "brain/. Wait for the run to finish (a crashed run frees the lock "
                "when its lease lapses), or pass --ignore-run-lock to override.",
                file=sys.stderr,
            )
            return 5

    if today is None:
        # UTC default for the same cross-clock reason as build_digest (above).
        today = datetime.now(UTC).date()
    # The daily variant defaults to its own distinct filename (ADR 0016).
    default_path = (daily_out_path if args.daily else default_out_path)(PROJECT_ROOT, today)
    out_path = Path(args.out) if args.out else default_path

    try:
        data = build_digest(
            out_path,
            root=PROJECT_ROOT,
            lookback_days=args.lookback,
            today=today,
            require_synthesis_log=args.require_synthesis_log,
            require_sanitized=not args.allow_unsanitized,
            write_html=args.html,
            write_report=args.report,
            daily=args.daily,
            include_trends=args.trends,
        )
    except SynthesisLogMissing as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except IncomingNotSanitized as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4

    print(f"wrote {out_path}")
    print(f"wrote {audit_out_path(out_path)}")
    if args.html:
        print(f"wrote {html_out_path(out_path)}")
    if args.report:
        print(f"wrote {report_out_path(out_path)}")
    # The daily digest's quiet check ignores concepts (it never renders them).
    if data.is_quiet_daily if args.daily else data.is_quiet:
        # Emit the marker so a cron caller can grep stdout and skip delivery.
        print(QUIET_WEEK_MARKER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
