"""Everything the digest builder READS from the vault.

Frontmatter / date parsing, the `config/schedule.yaml` lookback readers, the
incoming / concept / attention scanners, synthesis-log and brain-health
lookups, the fail-closed sanitize gate, and :func:`gather`, which composes the
scans into one :class:`~scripts.digest.model.DigestData`. No markdown is
rendered here — that is :mod:`scripts.digest.render`'s job.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from scripts.corroborate import corroboration, trust_line
from scripts.digest import parsing, schedule_config, summaries, synthesis
from scripts.digest.model import (
    AttentionItem,
    ConceptItem,
    DigestData,
    IncomingItem,
    IncomingNotSanitized,
    VaultNoteItem,
    _normalize_tier,
)
from scripts.fm import split_frontmatter
from scripts.inbox import INBOX_TOPIC
from scripts.normalize_url import normalize_or_raw
from scripts.registry import iter_registry_rows
from scripts.sanitize_incoming import (
    COMPANION_DIRNAME,
    gate_tree,
    sanitized_path,
    source_digest,
)

DEFAULT_LOOKBACK_DAYS = schedule_config.DEFAULT_LOOKBACK_DAYS
DEFAULT_TECHNICAL_LEVEL = schedule_config.DEFAULT_TECHNICAL_LEVEL

DEFAULT_DAILY_LOOKBACK_DAYS = schedule_config.DEFAULT_DAILY_LOOKBACK_DAYS

# Files in 1-incoming sitting longer than this (days) with a blank registry
# status are surfaced under "Needs attention".
STALE_INCOMING_DAYS = 14

# Registry statuses that mean the article has been dealt with — anything else
# (including blank) counts as "not yet processed" for the attention check.
HANDLED_STATUSES = frozenset({"processed", "rejected"})

# The per-run synthesis completion marker the agentic `weekly-synthesis` step
# writes last (see schedule/weekly-synthesis.md Step 5). Its presence for today's
# date is the proof that brain/ was synthesized THIS run, which the optional
# `--require-synthesis-log` barrier checks for.
SYNTHESIS_LOG_TEMPLATE = synthesis.SYNTHESIS_LOG_TEMPLATE

# Grace (in days) the `--require-synthesis-log` barrier allows between the newest
# synthesis run log's date and the digest-build date. `weekly-synthesis` stamps the
# log with ITS run date; if synthesis finishes at 23:5x on day N and the digest
# builds just after 00:00 on day N+1 (long synthesis / big vault), a strict
# "today only" check would false-trip on the midnight rollover. A 1-day grace
# absorbs exactly that rollover while a genuinely stale log (>1 day old → synthesis
# did NOT run for this run) still fails — preserving the barrier's purpose.
SYNTHESIS_LOG_GRACE_DAYS = synthesis.SYNTHESIS_LOG_GRACE_DAYS

# Marks a concept note as a shipped example rather than real knowledge.
_SEED_EXAMPLE_RE = re.compile(r"\b(seed|example)\b", re.IGNORECASE)

# Defensive cap on an agent-authored per-topic lead (one line; ~12-22 words).
LEAD_MAX_CHARS = synthesis.LEAD_MAX_CHARS


# --------------------------------------------------------------------------- #
# Frontmatter / date parsing helpers
# --------------------------------------------------------------------------- #


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a markdown file into (flat frontmatter scalars, body).

    Thin adapter over `scripts.fm`: the `---` boundary rule and the minimal
    `key: value` reader (sufficient for the flat keys this builder needs —
    `collected`, `category`, `title`, `last_updated`, `tags`) both live there.
    """
    return parsing.split_flat_frontmatter(text)


def _parse_iso_date(value: str | None) -> date | None:
    """Parse a `YYYY-MM-DD` (date or datetime) string into a date, else None.

    Surrounding quotes are tolerated; anything unparseable yields None so a bad
    date never crashes a scan — the item is simply treated as out of window.
    """
    return parsing.parse_iso_date(value)


# Matches a "> **Last updated:** YYYY-MM-DD" body line (concept-note style).
_BODY_LAST_UPDATED_RE = parsing.BODY_LAST_UPDATED_RE


def _concept_last_updated(fields: dict[str, str], body: str) -> date | None:
    """Find a concept's `last_updated` date from frontmatter, then body fallback."""
    return parsing.concept_last_updated(fields, body)


def _within_lookback(value: date | None, *, today: date, lookback_days: int) -> bool:
    """True when `value` falls in the window of exactly `lookback_days` dates.

    The window is the `lookback_days` most recent calendar dates ending today —
    i.e. `[today - (lookback_days - 1), today]`. Using `lookback_days - 1` keeps a
    "7 days" window at 7 distinct dates (not 8); an inclusive both-ends span of
    `lookback_days` would leak the boundary day into two consecutive digests.
    """
    return parsing.within_lookback(value, today=today, lookback_days=lookback_days)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


def read_lookback_days(schedule_path: Path) -> int:
    """Read `digest.lookback_days` from schedule.yaml; default if unreadable.

    PyYAML is imported lazily and optionally — a missing parser or file just
    yields the default rather than failing the build.
    """
    return schedule_config.read_lookback_days(schedule_path)


def _read_lookback_days_fallback(schedule_path: Path) -> int:
    """Regex `lookback_days` out of schedule.yaml when PyYAML is unavailable."""
    return schedule_config.read_lookback_days_fallback(schedule_path)


def read_daily_lookback_days(schedule_path: Path) -> int:
    """Read `daily_digest.lookback_days` from schedule.yaml; default 1 (ADR 0016).

    Mirrors :func:`read_lookback_days` but reads the optional `daily_digest` block.
    Kept separate (rather than generalized) so `read_lookback_days` keeps its
    PyYAML-absent regex fallback untouched; the daily path is new, so a missing
    parser simply yields the default-1 window rather than guessing between blocks.
    """
    return schedule_config.read_daily_lookback_days(schedule_path)


def read_technical_level(channels_path: Path) -> str:
    """Read `delivery.technical_level` from channels.yaml; 'balanced' if unreadable."""
    return schedule_config.read_technical_level(channels_path)


# --------------------------------------------------------------------------- #
# Scanners
# --------------------------------------------------------------------------- #


# A byline line ("*By Jane Doe · 2026-07-01*" / "By …") — metadata, not a summary.
_BYLINE_RE = summaries.BYLINE_RE
# An arXiv RSS preamble ("arXiv:1234v1 Announce Type: new Abstract: …") — the real
# summary is whatever follows "Abstract:", so strip everything up to and including it.
_ABSTRACT_PREFIX_RE = summaries.ABSTRACT_PREFIX_RE
# Longest a rendered one-line summary should run before we trim to a sentence.
_SUMMARY_MAX_CHARS = summaries.SUMMARY_MAX_CHARS


def _clean_summary(text: str) -> str:
    """Reduce a raw summary/abstract line to a trimmed 1–2 sentence takeaway.

    Strips an arXiv "…Abstract:" preamble, then trims to the last sentence end
    within `_SUMMARY_MAX_CHARS` (falling back to an ellipsis) so a long abstract
    renders as a scannable lead, not a wall of text.
    """
    return summaries.clean_summary(text)


def _first_takeaway(body: str) -> str:
    """A one-line summary for an article: its first "Key takeaways" bullet, else a
    trimmed lead pulled from the body/abstract.

    The fallback skips non-content lines — the byline, HTML capture comments,
    horizontal rules, and the trailing source line — so a headless RSS capture
    (title + byline + abstract) surfaces its ABSTRACT as the summary rather than
    echoing the author byline. Returns "" when nothing summary-worthy is found.
    """
    return summaries.first_takeaway(body)


def scan_incoming(
    incoming_dir: Path, registry_path: Path, *, today: date, lookback_days: int
) -> dict[str, list[IncomingItem]]:
    """Group in-window, NON-rejected incoming articles by topic (frontmatter `category`).

    The digest is a CURATED view: an article curation marked `rejected` in the
    registry (e.g. hype that didn't survive review) must NOT surface as a new source.
    Sanitized companions under `sanitized/` are derived copies, not separate sources,
    so they are skipped too.
    """
    grouped: dict[str, list[IncomingItem]] = {}
    if not incoming_dir.exists():
        return grouped
    statuses = _parse_registry_statuses(registry_path)
    for path in sorted(incoming_dir.rglob("*.md")):
        if path.name == "index.md":
            continue
        # Sanitized companions mirror their raw article — not a distinct source.
        if COMPANION_DIRNAME in path.parts:
            continue
        # Captured-but-unprocessed articles live under _inbox/ (the source-capture
        # queue); they are not a real topic yet, so they stay out of the digest
        # until /process routes them to their topic.
        if INBOX_TOPIC in path.parts:
            continue
        raw = path.read_text(encoding="utf-8")
        fields, body = _split_frontmatter(raw)
        # Render the SANITIZED companion whenever it is current (its recorded
        # source_hash still matches the raw bytes): the digest ships title/takeaway
        # text to a reader, so a raw-file render would deliver injection text the
        # S1–S9 pass already stripped. A stale companion (source re-collected,
        # nobody re-sanitized) falls back to the raw article — `--require-sanitized`
        # refuses that build outright before this scan runs.
        display_fields, display_body = fields, body
        companion = sanitized_path(path)
        if companion.exists():
            try:
                c_fields, c_body = _split_frontmatter(
                    companion.read_text(encoding="utf-8")
                )
                if c_fields.get("source_hash") == source_digest(raw):
                    display_fields, display_body = c_fields, c_body
            except OSError:
                pass  # unreadable companion -> raw fallback (the gate flags it)
        # IDENTITY fields (url, collected, category) come from the RAW frontmatter:
        # they key the registry-status and dedup lookups, and sanitization can
        # rewrite an injection-shaped url (e.g. `?x={inject}` → the S6 placeholder),
        # which would otherwise miss a `rejected` status and split the dedup key.
        # Only READER-FACING text (title, takeaway) is taken from the companion.
        collected = _parse_iso_date(fields.get("collected"))
        if not _within_lookback(collected, today=today, lookback_days=lookback_days):
            continue
        # Skip articles curation has rejected — the digest shows curated sources only.
        if statuses.get(_status_key(fields.get("url") or ""), "") == "rejected":
            continue
        # Topic comes from `category`; fall back to the parent folder name.
        topic = fields.get("category") or path.parent.name
        # Strip surrounding YAML quotes: a title with a colon (e.g. "GLM-5.2: …")
        # must be quoted in frontmatter, and the flat parser keeps the quotes —
        # without this the digest renders doubled quotes. Mirrors _concept_name.
        title = (display_fields.get("title") or path.stem).strip().strip("\"'")
        raw_title = (fields.get("title") or path.stem).strip().strip("\"'")
        grouped.setdefault(topic, []).append(
            IncomingItem(
                title=title,
                topic=topic,
                takeaway=_first_takeaway(display_body),  # reader-facing: sanitized
                tier=_normalize_tier(fields.get("tier")),
                url=(fields.get("url") or "").strip().strip("\"'"),  # identity: raw
                dedup_key=raw_title,  # identity fallback: raw title, not the display one
                text_chars=len(display_body),
            )
        )
    # Collapse re-collected articles (the same URL saved in more than one incoming
    # file) so every count downstream — the topic badge, the header total, the
    # TL;DR "most active" share — reflects DISTINCT sources, not raw file count.
    return {topic: _dedup_by_url(items) for topic, items in grouped.items()}


def _dedup_by_url(items: list[IncomingItem]) -> list[IncomingItem]:
    """Drop later items sharing a URL (or title, when no URL), keeping the first."""
    seen: set[str] = set()
    unique: list[IncomingItem] = []
    for item in items:
        # Normalise the URL so http/https/www twins collapse to one key, matching
        # the registry-status scan (which keys by the same normalized form). With no
        # URL, fall back to the RAW-title identity (`dedup_key`) so a sanitized
        # display title can't split two copies of the same source.
        key = normalize_or_raw(item.url) or item.dedup_key or item.title
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _is_seed_or_example(fields: dict[str, str], body: str) -> bool:
    """True when a concept note is a shipped SEED/EXAMPLE rather than real content."""
    tags = fields.get("tags", "")
    if _SEED_EXAMPLE_RE.search(tags):
        return True
    # Body marker, e.g. "⚠️ **SEED / EXAMPLE NOTE.**" — only check the first
    # ~15 lines so the words appearing later in prose don't trip the filter.
    head = "\n".join(body.splitlines()[:15])
    return bool(re.search(r"SEED\s*/\s*EXAMPLE|SEED NOTE|EXAMPLE NOTE", head))


def _concept_name(fields: dict[str, str], body: str, path: Path) -> str:
    """Concept display name: frontmatter title, else first `# heading`, else stem."""
    title = fields.get("title")
    if title:
        return title.strip().strip("\"'")
    for line in body.splitlines():
        if line.strip().startswith("# "):
            return line.strip()[2:].strip()
    return path.stem


def _concept_definition(body: str) -> str:
    """The first PARAGRAPH of the "What it is" / definition section, one line.

    Taking only the first physical line amputated every hard-wrapped note
    mid-word in the delivered digest ("…synthesis → citation-"), so all the
    paragraph's lines are joined: a trailing hyphen re-joins its split word,
    and `>` blockquote lines contribute their inner text (BUG L4). The
    paragraph ends at the first blank line, `---` rule, or next heading.
    """
    in_section = False
    parts: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(("## what it is", "## definition")):
            in_section = True
            continue
        if not in_section:
            continue
        if stripped.startswith("#"):  # next section
            break
        if not stripped or stripped == "---":
            if parts:
                break  # the paragraph ended
            continue  # still before the paragraph
        parts.append(stripped.lstrip(">").strip())

    definition = ""
    for part in parts:
        if not definition:
            definition = part
        elif definition.endswith("-"):
            definition += part  # re-join a word the hard wrap split at a hyphen
        else:
            definition += f" {part}"
    return definition


# Rank used to pick the strongest tier when a concept cites several sources.
# Distinct from the curation SORT rank in `scripts.digest.render` (where lower
# leads) — here a HIGHER value means a stronger tier, so `max` selects the best
# evidence. Kept under its own name so the two ranks can't be confused.
_CONCEPT_TIER_RANK = {"high": 3, "medium": 2, "low": 1}

# A `tier:`/`url:` KEY at the start of a (possibly `- `-bulleted) line. Anchored
# so an incidental substring inside a value — e.g. `tier:high` buried in an
# `archive:` path or a `url:` query — is never mistaken for the field (BUG M4).
_SOURCE_TIER_RE = re.compile(r"^\s*-?\s*tier\s*:\s*([A-Za-z]+)", re.IGNORECASE | re.MULTILINE)
_SOURCE_URL_RE = re.compile(r"^\s*-?\s*url\s*:\s*(.+?)\s*$", re.MULTILINE)


def _sources_block(fm_text: str) -> str:
    """Return only the `sources:` block of a concept's frontmatter.

    Walks the frontmatter lines, enters at the top-level `sources:` key, and stops
    at the next top-level key, so a concept-level `url:`/`tier:` field outside the
    block can never inflate the source count or fake a credibility tier (BUG M4).
    """
    out: list[str] = []
    in_block = False
    for line in fm_text.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if not in_block:
            if indent == 0 and stripped.split(":", 1)[0].strip() == "sources":
                in_block = True
            continue
        if stripped and indent == 0:  # next top-level key ends the block
            break
        out.append(line)
    return "\n".join(out)


def _concept_sources(fm_text: str) -> list[dict[str, str]]:
    """Extract `sources:` entries (just their `url`) from a concept's frontmatter.

    The flat frontmatter reader can't see the nested `sources:` list, so we scan
    the `sources:` block for `url:` lines and return one `{"url": ...}` dict per
    source. Quotes around the URL are stripped. This is all
    :func:`scripts.corroborate.corroboration` needs to derive the trust line
    (CONVENTIONS §16) — it counts distinct registrable domains.
    """
    sources: list[dict[str, str]] = []
    for match in _SOURCE_URL_RE.finditer(_sources_block(fm_text)):
        url = match.group(1).strip().strip("\"'")
        if url:
            sources.append({"url": url})
    return sources


def _concept_source_tier(fm_text: str) -> str | None:
    """Best (highest) `tier:` among a concept's `sources:` entries, else None.

    A concept may cite several sources of differing credibility (CONVENTIONS §5.1
    `sources[].tier`); we surface the strongest so the marker reflects the best
    evidence backing the note. Scoped to the `sources:` block and anchored to the
    `tier:` key so an `archive:` path containing `tier:` never leaks in.
    """
    best: str | None = None
    for match in _SOURCE_TIER_RE.finditer(_sources_block(fm_text)):
        tier = _normalize_tier(match.group(1))
        if tier and (best is None or _CONCEPT_TIER_RANK[tier] > _CONCEPT_TIER_RANK[best]):
            best = tier
    return best


def _frontmatter_block(text: str) -> str:
    """Return just the raw frontmatter region (between the leading `---` fences)."""
    return split_frontmatter(text)[0]


def scan_concepts(
    concepts_dir: Path, *, today: date, lookback_days: int, language: str = "en"
) -> list[ConceptItem]:
    """List in-window concept notes, excluding SEED/EXAMPLE ones (CONVENTIONS §5.1)."""
    items: list[ConceptItem] = []
    if not concepts_dir.exists():
        return items
    for path in sorted(concepts_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        fields, body = _split_frontmatter(text)
        if _is_seed_or_example(fields, body):
            continue
        updated = _concept_last_updated(fields, body)
        if not _within_lookback(updated, today=today, lookback_days=lookback_days):
            continue
        fm_text = _frontmatter_block(text)
        # Derive the corroboration trust line from the concept's `sources:`
        # (CONVENTIONS §16): no separate counter is stored — it is derived here.
        sources = _concept_sources(fm_text)
        corr = corroboration(sources)
        items.append(
            ConceptItem(
                name=_concept_name(fields, body, path),
                definition=_concept_definition(body),
                tier=_concept_source_tier(fm_text),
                trust=trust_line(corr, language=language),
                source_url=sources[0]["url"] if sources else "",
            )
        )
    return items


def _vault_note_title(fields: dict[str, str], body: str, path: Path) -> str:
    """Display title for a lesson/playbook: frontmatter title, H1, else stem."""
    title = fields.get("title")
    if title:
        return summaries.strip_inline_markdown(title.strip().strip("\"'")).strip()
    for line in body.splitlines():
        if line.strip().startswith("# "):
            return summaries.strip_inline_markdown(line.strip()[2:]).strip()
    return path.stem


def _frontmatter_tags(fields: dict[str, str]) -> list[str]:
    """Parse the simple `tags: [a, b]` shape used by vault templates."""
    raw = fields.get("tags", "").strip().strip("[]")
    return [part.strip().strip("\"'") for part in raw.split(",") if part.strip()]


def _vault_note_date(fields: dict[str, str]) -> date | None:
    """Best-effort date for sorting vault notes."""
    for key in ("last_updated", "extracted_at", "created"):
        parsed = _parse_iso_date(fields.get(key))
        if parsed is not None:
            return parsed
    return None


# One leading list marker only — a char-set lstrip here once ate the opening
# `**` of the template's `- **Fact.** …` bullet (leaving "Fact.**") and the
# digits of facts that START with a number ("3 strikes…" became "strikes…").
_LIST_MARKER_RE = re.compile(r"^(?:[-*+]|\d{1,4}[.)])\s+")


def _vault_note_summary(body: str) -> str:
    """First useful prose/list line from a lesson/playbook body."""
    for line in body.splitlines():
        stripped = _LIST_MARKER_RE.sub("", line.strip()).strip()
        if not stripped or stripped.startswith("#") or not re.search(r"\w", stripped):
            continue
        return summaries.clean_summary(stripped)
    return ""


def scan_vault_notes(note_dir: Path, note_type: str) -> list[VaultNoteItem]:
    """List active lesson/playbook notes for the digest vault snapshot."""
    notes: list[tuple[date | None, VaultNoteItem]] = []
    if not note_dir.exists():
        return []
    for path in sorted(note_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        fields, body = _split_frontmatter(text)
        if fields.get("type", "").strip().strip("\"'") != note_type:
            continue
        if _is_seed_or_example(fields, body):
            continue
        metadata = ""
        if note_type == "lesson":
            metadata = fields.get("confidence", "").strip().strip("\"'")
            if metadata:
                metadata = f"{metadata} confidence"
        elif note_type == "playbook":
            metadata = fields.get("status", "").strip().strip("\"'")
        notes.append(
            (
                _vault_note_date(fields),
                VaultNoteItem(
                    title=_vault_note_title(fields, body, path),
                    note_type=note_type,
                    path=str(path),
                    metadata=metadata,
                    summary=_vault_note_summary(body),
                    tags=_frontmatter_tags(fields),
                ),
            )
        )
    # Two stable passes: title ascending, then date descending with undated (date.min)
    # falling to the END — so the newest dated notes lead and hand-authored undated
    # notes never displace them from the digest's top-of-list front door.
    notes.sort(key=lambda item: item[1].title)
    notes.sort(key=lambda item: item[0] or date.min, reverse=True)
    return [note for _, note in notes]


def load_topic_leads(synthesis_dir: Path, curated_dir: Path) -> dict[str, str]:
    """Map topic → one-line digest lead, for EVERY topic whose sidecar is current.

    Scans all `{synthesis_dir}/{topic}/digest-lead.md` sidecars and gates each
    per topic on `synthesis_freshness.is_fresh` — a lead describes one synthesis
    run, so a topic whose curated corpus changed since its stamp (or that was
    never stamped) is suppressed. The weekly render shows every returned lead
    under its topic badge.
    """
    return synthesis.load_topic_leads(synthesis_dir, curated_dir)


def synthesis_log_exists(synthesis_dir: Path, *, today: date) -> bool:
    """True when a recent synthesis run log (`synthesis-run_YYYY-MM-DD.md`) exists."""
    return synthesis.synthesis_log_exists(synthesis_dir, today=today)


def _newest_synthesis_run(synthesis_dir: Path, *, today: date | None = None) -> Path | None:
    """Newest date-stamped synthesis run log, ignoring invalid and future stamps."""
    return synthesis.newest_synthesis_run(synthesis_dir, today=today)


def latest_synthesis_summary(synthesis_dir: Path) -> str | None:
    """Summarize the newest `synthesis-run_*.md` log (best-effort) or return None."""
    return synthesis.latest_synthesis_summary(synthesis_dir)


_VALUE_EVIDENCE_KEYS = synthesis.VALUE_EVIDENCE_KEYS
_VALUE_EVIDENCE_RE = synthesis.VALUE_EVIDENCE_RE


def latest_value_evidence(
    synthesis_dir: Path, *, today: date | None = None
) -> tuple[int, int, int]:
    """Return (concepts created, concepts updated, existing concepts reused)."""
    return synthesis.latest_value_evidence(synthesis_dir, today=today)


def latest_brain_health(synthesis_dir: Path) -> str | None:
    """One-line health summary from the newest report.

    The standard headline includes `uncited-facts`; keep that term visible here
    because digest-format drift tests pin the machine-matched health vocabulary.
    """
    return synthesis.latest_brain_health(synthesis_dir)


def _status_key(url: str) -> str:
    """Normalized registry-status lookup key for `url` (matches the dedup contract).

    Registry de-duplication compares URLs via `normalize_url.normalize()` (http/https,
    `www.`/`m.`, trailing-slash and tracking-query variants all collapse together).
    The digest's status map and its lookups MUST use the SAME key — otherwise a
    `rejected` article reappears in the digest (and a `processed` one in attention)
    whenever its frontmatter URL is a mere variant of the registry's. Strips YAML
    quotes first; an empty/unparsable URL degrades to a stable raw key.
    """
    # Strip surrounding YAML quotes (frontmatter scalars keep them) before keying
    # through the shared, ValueError-safe normalizer.
    return normalize_or_raw((url or "").strip().strip("\"'"))


def _parse_registry_statuses(registry_path: Path) -> dict[str, str]:
    """Map normalized-url -> status from the registry markdown table (CONVENTIONS §9).

    The table columns are `collected | category | status | url | title`. Rows
    that are blank/commented are ignored. Status is lower-cased; a blank cell
    yields an empty string. The `url` column is keyed through `_status_key`
    (the dedup-normalized form) so lookups match regardless of URL variant.
    """
    statuses: dict[str, str] = {}
    for row in iter_registry_rows(registry_path):
        if row.url:
            statuses[_status_key(row.url)] = row.status.lower()
    return statuses


def scan_attention(
    incoming_dir: Path, registry_path: Path, *, today: date
) -> list[AttentionItem]:
    """Incoming files older than 14 days whose registry status is unhandled."""
    items: list[AttentionItem] = []
    if not incoming_dir.exists():
        return items
    statuses = _parse_registry_statuses(registry_path)
    cutoff = today - timedelta(days=STALE_INCOMING_DAYS)
    for path in sorted(incoming_dir.rglob("*.md")):
        if path.name == "index.md":
            continue
        # A sanitized companion mirrors its raw article; counting both would surface
        # one stale article as two separate "needs attention" entries.
        if COMPANION_DIRNAME in path.parts:
            continue
        fields, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
        collected = _parse_iso_date(fields.get("collected"))
        if collected is None or collected > cutoff:
            continue  # missing date or still fresh
        status = statuses.get(_status_key(fields.get("url", "")), "")
        if status in HANDLED_STATUSES:
            continue
        items.append(
            AttentionItem(
                relpath=str(path.relative_to(incoming_dir.parent.parent)),
                collected=collected,
            )
        )
    return items


# --------------------------------------------------------------------------- #
# Gather + gates
# --------------------------------------------------------------------------- #


def debut_topics(
    registry_path: Path,
    incoming_by_topic: dict[str, list[IncomingItem]],
    *,
    today: date,
    lookback_days: int,
) -> set[str]:
    """Topics in this digest whose collection history STARTS inside the window.

    A topic in its first week has no per-topic include/exclude rules settled
    yet, so its "top by credibility" picks can be junk (live-observed) — the
    digest marks these honestly. Evidence is the dedup registry: the EARLIEST
    `collected` date per category. A topic with any row older than the window
    is established; a topic with no parseable history at all is as unproven as
    a first week, so it counts as a debut too.
    """
    earliest: dict[str, date] = {}
    for row in iter_registry_rows(registry_path):
        try:
            collected = date.fromisoformat(row.collected)
        except ValueError:
            continue
        if not row.category:
            continue
        if row.category not in earliest or collected < earliest[row.category]:
            earliest[row.category] = collected
    window_start = today - timedelta(days=lookback_days - 1)
    debuts: set[str] = set()
    for topic in incoming_by_topic:
        first = earliest.get(topic)
        if first is None or first >= window_start:
            debuts.add(topic)
    return debuts


def gather(root: Path, *, today: date, lookback_days: int) -> DigestData:
    """Run every scan against `root` and assemble a DigestData."""
    synthesis_dir = root / "pipeline" / "3-synthesis"
    concepts_created, concepts_updated, existing_concepts_reused = latest_value_evidence(
        synthesis_dir, today=today
    )
    # Chrome language (delivery.language): read once; en on any read problem.
    language = schedule_config.read_language(root / "config" / "channels.yaml")
    incoming_by_topic = scan_incoming(
        root / "pipeline" / "1-incoming",
        root / "pipeline" / "registry.md",
        today=today, lookback_days=lookback_days,
    )
    return DigestData(
        built_on=today,
        lookback_days=lookback_days,
        language=language,
        incoming_by_topic=incoming_by_topic,
        debut_topics=debut_topics(
            root / "pipeline" / "registry.md",
            incoming_by_topic,
            today=today, lookback_days=lookback_days,
        ),
        concepts=scan_concepts(
            root / "brain" / "concepts",
            today=today, lookback_days=lookback_days, language=language,
        ),
        lessons=scan_vault_notes(root / "brain" / "lessons", "lesson"),
        playbooks=scan_vault_notes(root / "brain" / "playbooks", "playbook"),
        topic_leads=load_topic_leads(
            synthesis_dir, root / "pipeline" / "2-curated"
        ),
        synthesis_summary=latest_synthesis_summary(synthesis_dir),
        brain_health=latest_brain_health(synthesis_dir),
        concepts_created=concepts_created,
        concepts_updated=concepts_updated,
        existing_concepts_reused=existing_concepts_reused,
        ops_health=_ops_headline(root),
        attention=scan_attention(
            root / "pipeline" / "1-incoming",
            root / "pipeline" / "registry.md",
            today=today,
        ),
    )


def _ops_headline(root: Path) -> str | None:
    """The one-line DEGRADED summary from health.py, or None when healthy.

    Imported lazily and wrapped best-effort: `health` imports the build_digest
    facade at module level (for `latest_brain_health`), so a module-level import
    here would be a cycle — and a health-log read failure must never block a
    digest build.
    """
    try:
        from scripts import health  # noqa: PLC0415 — lazy: breaks the import cycle

        return health.ops_headline(health.health_summary(root))
    except Exception:  # noqa: BLE001 — observability is strictly best-effort
        return None


def _check_incoming_sanitized(incoming_dir: Path) -> None:
    """Fail closed unless every incoming article has a current sanitized companion.

    Reuses the `sanitize_incoming.gate_tree` primitive (same S1–S9 companion
    contract the agentic weekly-run.md gate enforces) rather than reimplementing
    gate logic. Raises :class:`IncomingNotSanitized` naming the offending article(s)
    and how to fix them when any companion is missing, stale, or corrupt.
    """
    gate = gate_tree(incoming_dir)
    if gate.ok:
        return
    # Collapse the failure buckets into one deduplicated, ordered list of the
    # raw source paths the operator must (re)sanitize or repair.
    offenders: list[Path] = []
    # `outdated` is included so a ruleset bump can never raise with an empty list.
    for path in (*gate.missing, *gate.stale, *gate.corrupt, *gate.unreadable, *gate.outdated):
        if path not in offenders:
            offenders.append(path)
    listing = "\n".join(f"  - {path}" for path in offenders)
    raise IncomingNotSanitized(
        f"refusing to build digest: {len(offenders)} incoming article(s) lack a "
        f"current sanitized companion (missing/stale/corrupt/unreadable/outdated) — run "
        f"`python3 scripts/sanitize_incoming.py sanitize --incoming {incoming_dir}` first:\n"
        f"{listing}"
    )
