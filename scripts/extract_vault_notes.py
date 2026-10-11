#!/usr/bin/env python3
"""
extract_vault_notes.py — deterministic lesson/playbook generator.

This is the headless counterpart for the lessons/playbooks front doors. It does
not infer hidden meaning from prose. Instead, it scans existing concept notes for
explicit operator-authored sections:

  - `## Lessons` / `## Key lessons` / `## Extracted lessons`
  - `## Playbook: Title` / `## Playbook draft: Title`

Every bullet under a lessons section becomes one additive lesson note. Every
playbook section with at least one ordered/unordered step becomes one draft
playbook. Re-running the command is idempotent: a candidate whose content (the
lesson fact / the playbook title+steps) was already extracted into its slug
family is skipped — matched by content, not filename, so inserting or
reordering bullets never swallows a new candidate or duplicates an old one.
An EDITED bullet is a new candidate by design: extraction is additive.

CLI:
    python3 scripts/extract_vault_notes.py [--root .] [--today YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import schema  # noqa: E402
from scripts.fm import parse_frontmatter, split_frontmatter  # noqa: E402
from scripts.registry import atomic_write_text  # noqa: E402

_LESSON_HEADINGS = {"lessons", "key lessons", "extracted lessons"}
_PLAYBOOK_HEADING_RE = re.compile(r"^playbook(?:\s+draft)?(?::\s*(.+))?$", re.I)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
_ORDERED_RE = re.compile(r"^\s*\d+[.)]\s+(.+?)\s*$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SOURCE_FIELD_RE = re.compile(r"^\s*(url|archive|date|tier)\s*:\s*(.+?)\s*$", re.I)


@dataclass(frozen=True)
class SourceRef:
    url: str = ""
    archive: str = ""
    date: str = ""
    tier: str = ""


@dataclass(frozen=True)
class ConceptSource:
    path: Path
    relpath: str
    stem: str
    title: str
    tags: list[str]
    sources: list[SourceRef]
    body: str


@dataclass(frozen=True)
class LessonCandidate:
    title: str
    fact: str
    concept: ConceptSource


@dataclass(frozen=True)
class PlaybookCandidate:
    title: str
    when_to_use: str
    steps: list[str]
    concept: ConceptSource


@dataclass
class ExtractResult:
    lessons_written: int = 0
    playbooks_written: int = 0
    lessons_skipped: int = 0
    playbooks_skipped: int = 0
    lesson_paths: list[Path] = field(default_factory=list)
    playbook_paths: list[Path] = field(default_factory=list)


def _strip_quotes(value: object) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_strip_quotes(item) for item in value if _strip_quotes(item)]
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            inner = text[1:-1].strip()
            if not inner:
                return []
            return [_strip_quotes(part) for part in inner.split(",") if part.strip()]
        return [_strip_quotes(text)] if text else []
    return []


def _yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _slug(value: str, *, max_len: int = 72) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    if not slug:
        slug = "note"
    return slug[:max_len].strip("-") or "note"


def _clean_inline_markup(value: str) -> str:
    text = value.strip()
    text = re.sub(r"^\*\*(.+?)\*\*[:.]\s*", r"\1. ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


_TITLE_MAX = 96

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")
# A period inside these abbreviations does not end a sentence — splitting a
# title there shipped the live '…"X vs' artifact. Word-bounded on the left so
# a word merely ENDING in the letters (e.g. "Jarvis.") still splits. Err on
# the NOT-splitting side: an over-long sentence is clipped at a word boundary.
_NON_TERMINAL_ABBREV_RE = re.compile(
    r"""(?:^|[\s("'“‘])(?:vs|v|e\.g|i\.e|cf|etc|ca|approx|et\s+al)\.$""",
    re.IGNORECASE,
)


def _first_sentence(text: str) -> str:
    """The first sentence of `text`, treating known abbreviations as non-final."""
    for match in _SENTENCE_BOUNDARY_RE.finditer(text):
        if _NON_TERMINAL_ABBREV_RE.search(text[: match.start()]):
            continue
        return text[: match.start()]
    return text


def _title_from_fact(fact: str) -> str:
    cleaned = _clean_inline_markup(fact)
    sentence = _first_sentence(cleaned).rstrip(".!?").strip()
    if not sentence:
        return "Untitled lesson"
    if len(sentence) <= _TITLE_MAX:
        return sentence
    # Clip on a word boundary, never mid-word ("…context disc"), and mark the
    # cut with an ellipsis; dangling separators before the cut are dropped too.
    clipped = sentence[: _TITLE_MAX - 1].rsplit(" ", 1)[0].rstrip(" ,;:—–-")
    if not clipped:  # a single unbroken 95+-char token — hard cut is all we have
        clipped = sentence[: _TITLE_MAX - 1]
    return f"{clipped}…"


def _concept_title(fields: dict[str, object], body: str, path: Path) -> str:
    title = _strip_quotes(fields.get("title"))
    if title:
        return title
    for line in body.splitlines():
        if line.strip().startswith("# "):
            return line.strip()[2:].strip()
    return path.stem.replace("-", " ").title()


def _source_refs_from_frontmatter(fm_block: str, fields: dict[str, object]) -> list[SourceRef]:
    sources = fields.get("sources")
    if isinstance(sources, list):
        parsed: list[SourceRef] = []
        for source in sources:
            if isinstance(source, dict):
                parsed.append(
                    SourceRef(
                        url=_strip_quotes(source.get("url")),
                        archive=_strip_quotes(source.get("archive")),
                        date=_strip_quotes(source.get("date")),
                        tier=_strip_quotes(source.get("tier")),
                    )
                )
        if parsed:
            return parsed

    refs: list[SourceRef] = []
    current: dict[str, str] = {}
    in_sources = False
    for raw in fm_block.splitlines():
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip(" "))
        if not in_sources:
            if indent == 0 and stripped == "sources:":
                in_sources = True
            continue
        if stripped and indent == 0:
            break
        if stripped.startswith("- "):
            if current:
                refs.append(SourceRef(**current))
                current = {}
            stripped = stripped[2:].strip()
        match = _SOURCE_FIELD_RE.match(stripped)
        if match:
            key, value = match.groups()
            current[key.lower()] = _strip_quotes(value)
    if current:
        refs.append(SourceRef(**current))
    return refs


def _load_concepts(root: Path) -> list[ConceptSource]:
    concepts_dir = root / "brain" / "concepts"
    if not concepts_dir.exists():
        return []
    concepts: list[ConceptSource] = []
    for path in sorted(concepts_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        fm_block, body = split_frontmatter(text)
        fields = parse_frontmatter(fm_block)
        if _strip_quotes(fields.get("type")) != "concept":
            continue
        tags = _as_list(fields.get("tags"))
        relpath = path.relative_to(root).as_posix()
        concepts.append(
            ConceptSource(
                path=path,
                relpath=relpath,
                stem=path.stem,
                title=_concept_title(fields, body, path),
                tags=tags,
                sources=_source_refs_from_frontmatter(fm_block, fields),
                body=body,
            )
        )
    return concepts


def _section_blocks(body: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    lines = body.splitlines()
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if not match:
            continue
        level = len(match.group(1))
        title = match.group(2).strip()
        content: list[str] = []
        for follow in lines[index + 1 :]:
            next_heading = _HEADING_RE.match(follow)
            if next_heading and len(next_heading.group(1)) <= level:
                break
            content.append(follow)
        sections.append((title, content))
    return sections


def lesson_candidates(concept: ConceptSource) -> list[LessonCandidate]:
    candidates: list[LessonCandidate] = []
    for heading, lines in _section_blocks(concept.body):
        if heading.strip().lower() not in _LESSON_HEADINGS:
            continue
        for line in lines:
            match = _BULLET_RE.match(line)
            if not match:
                continue
            fact = _clean_inline_markup(match.group(1))
            if fact:
                candidates.append(
                    LessonCandidate(
                        title=_title_from_fact(fact),
                        fact=fact,
                        concept=concept,
                    )
                )
    return candidates


def playbook_candidates(concept: ConceptSource) -> list[PlaybookCandidate]:
    candidates: list[PlaybookCandidate] = []
    for heading, lines in _section_blocks(concept.body):
        match = _PLAYBOOK_HEADING_RE.match(heading.strip())
        if not match:
            continue
        title = (match.group(1) or f"{concept.title} playbook").strip()
        intro: list[str] = []
        steps: list[str] = []
        for line in lines:
            ordered = _ORDERED_RE.match(line)
            bullet = _BULLET_RE.match(line)
            if ordered or bullet:
                step = _clean_inline_markup((ordered or bullet).group(1))  # type: ignore[union-attr]
                if step:
                    steps.append(step)
                continue
            stripped = line.strip()
            if stripped and not steps and not stripped.startswith("#"):
                intro.append(stripped)
        if steps:
            candidates.append(
                PlaybookCandidate(
                    title=title,
                    when_to_use=" ".join(intro).strip()
                    or f"Use this when applying {concept.title}.",
                    steps=steps,
                    concept=concept,
                )
            )
    return candidates


def _tags_inline(tags: list[str]) -> str:
    cleaned = [tag for tag in tags if tag]
    return "[" + ", ".join(cleaned) + "]"


def _first_url(concept: ConceptSource) -> str:
    return next((source.url for source in concept.sources if source.url), "")


def _render_lesson(candidate: LessonCandidate, *, today: date) -> str:
    concept = candidate.concept
    url = _first_url(concept)
    url_line = f"url: {_yaml_quote(url)}\n" if url else "url: \"\"\n"
    return (
        "---\n"
        f"schema_version: {schema.CURRENT['lesson']}\n"
        "type: lesson\n"
        f"title: {_yaml_quote(candidate.title)}\n"
        f"source: {concept.relpath}\n"
        f"{url_line}"
        f"extracted_at: {today.isoformat()}\n"
        f"tags: {_tags_inline(concept.tags)}\n"
        # Quoted block-list item: an unquoted inline `[[...]]` is YAML flow syntax and
        # parses as a nested list, corrupting the machine-readable link property.
        "related_concept:\n"
        f"  - \"[[concepts/{concept.stem}]]\"\n"
        "confidence: medium\n"
        "---\n\n"
        f"# Lesson: {candidate.title}\n\n"
        "## Facts\n\n"
        f"- **Fact.** {candidate.fact}\n\n"
        "## Why kept\n\n"
        f"Extracted from [[concepts/{concept.stem}]] as a reusable atomic fact.\n\n"
        "## Suggested integration\n\n"
        f"- **UPDATE concept [[concepts/{concept.stem}]]** if this fact becomes durable.\n"
    )


def _render_sources(concept: ConceptSource) -> str:
    if not concept.sources:
        return "sources: []\n"
    lines = ["sources:"]
    for source in concept.sources:
        lines.append(f"  - url: {_yaml_quote(source.url)}")
        if source.archive:
            lines.append(f"    archive: {source.archive}")
        if source.date:
            lines.append(f"    date: {source.date}")
        if source.tier:
            lines.append(f"    tier: {source.tier}")
    return "\n".join(lines) + "\n"


def _render_steps(steps: list[str]) -> str:
    """The ordered-steps block — also the playbook's content-identity marker."""
    return "\n".join(f"{index}. {step}" for index, step in enumerate(steps, 1))


def _render_playbook(candidate: PlaybookCandidate, *, today: date) -> str:
    concept = candidate.concept
    steps = _render_steps(candidate.steps)
    return (
        "---\n"
        f"schema_version: {schema.CURRENT['playbook']}\n"
        f"title: {_yaml_quote(candidate.title)}\n"
        "type: playbook\n"
        "status: draft\n"
        f"tags: {_tags_inline(concept.tags)}\n"
        f"created: {today.isoformat()}\n"
        f"last_updated: {today.isoformat()}\n"
        "related_concept:\n"
        f"  - \"[[concepts/{concept.stem}]]\"\n"
        "source_concepts:\n"
        f"  - {concept.relpath}\n"
        f"{_render_sources(concept)}"
        "---\n\n"
        f"# {candidate.title}\n\n"
        "## When to use\n\n"
        f"{candidate.when_to_use}\n\n"
        "## Inputs\n\n"
        f"- [[concepts/{concept.stem}]]\n\n"
        "## Steps\n\n"
        f"{steps}\n\n"
        "## Outputs\n\n"
        "- Updated concept, lesson, or decision record.\n\n"
        "## Checks\n\n"
        "- [ ] Every claim or decision rule links back to a concept or source.\n"
        "- [ ] The playbook has at least one `related_concept`.\n"
        "- [ ] The result is reusable, not a one-off task note.\n\n"
        "## Related notes\n\n"
        f"- [[concepts/{concept.stem}]]\n\n"
        "## Change history\n\n"
        "| Date | Change | Source |\n"
        "|---|---|---|\n"
        f"| {today.isoformat()} | Created playbook draft | {concept.relpath} |\n"
    )


def _family_files(directory: Path, stem: str) -> list[Path]:
    """Existing notes named `{stem}.md` or `{stem}-<n>.md` (the slug family)."""
    files = [directory / f"{stem}.md"]
    files.extend(
        path
        for path in directory.glob(f"{stem}-*.md")
        if path.stem[len(stem) + 1 :].isdigit()
    )
    return [path for path in files if path.is_file()]


def _already_extracted(directory: Path, stem: str, markers: tuple[str, ...]) -> bool:
    """True when a note in the slug family already carries every marker.

    Idempotency keys on candidate CONTENT, not on filenames: positional -2/-3
    numbering shifts when a same-slug candidate is inserted above an existing
    one in a later run, which would silently swallow the new candidate (the
    original drop bug resurfacing) and duplicate an already-extracted one.
    """
    for path in _family_files(directory, stem):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue  # unreadable note — never treat as a match
        if all(marker in text for marker in markers):
            return True
    return False


def _claim_free_slot(directory: Path, stem: str, claimed: set[str]) -> Path:
    """First `{stem}[-n].md` name neither on disk nor claimed this run."""
    counter = 1
    while True:
        name = stem if counter == 1 else f"{stem}-{counter}"
        if name not in claimed and not (directory / f"{name}.md").exists():
            claimed.add(name)
            return directory / f"{name}.md"
        counter += 1


def extract_vault_notes(
    *, root: Path = PROJECT_ROOT, today: date | None = None, dry_run: bool = False
) -> ExtractResult:
    """Extract explicit lessons/playbooks from concept notes and write new notes."""
    if today is None:
        today = date.today()
    result = ExtractResult()
    lesson_dir = root / "brain" / "lessons"
    playbook_dir = root / "brain" / "playbooks"
    lesson_dir.mkdir(parents=True, exist_ok=True)
    playbook_dir.mkdir(parents=True, exist_ok=True)
    # One claimed-name namespace per note kind, spanning concepts: `{a-b}` + `c`
    # and `{a}` + `b-c` produce the same joined stem, so per-concept tracking
    # wouldn't do. The seen-sets deduplicate identical candidates within a run.
    lesson_claimed: set[str] = set()
    playbook_claimed: set[str] = set()
    lessons_seen: set[tuple[str, tuple[str, ...]]] = set()
    playbooks_seen: set[tuple[str, tuple[str, ...]]] = set()

    for concept in _load_concepts(root):
        for lesson in lesson_candidates(concept):
            stem = f"{concept.stem}-{_slug(lesson.title)}"
            markers: tuple[str, ...] = (f"- **Fact.** {lesson.fact}\n",)
            if (stem, markers) in lessons_seen or _already_extracted(
                lesson_dir, stem, markers
            ):
                result.lessons_skipped += 1
                continue
            lessons_seen.add((stem, markers))
            dest = _claim_free_slot(lesson_dir, stem, lesson_claimed)
            result.lesson_paths.append(dest)
            result.lessons_written += 1
            if not dry_run:
                atomic_write_text(dest, _render_lesson(lesson, today=today))

        for playbook in playbook_candidates(concept):
            stem = f"{concept.stem}-{_slug(playbook.title)}"
            markers = (f"# {playbook.title}\n", _render_steps(playbook.steps))
            if (stem, markers) in playbooks_seen or _already_extracted(
                playbook_dir, stem, markers
            ):
                result.playbooks_skipped += 1
                continue
            playbooks_seen.add((stem, markers))
            dest = _claim_free_slot(playbook_dir, stem, playbook_claimed)
            result.playbook_paths.append(dest)
            result.playbooks_written += 1
            if not dry_run:
                atomic_write_text(dest, _render_playbook(playbook, today=today))

    return result


def _parse_today(value: str | None) -> date:
    if not value:
        return datetime.now(UTC).date()
    return date.fromisoformat(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract explicit lesson/playbook sections into vault notes."
    )
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--today", help="Date stamp for generated notes (YYYY-MM-DD).")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = extract_vault_notes(
        root=args.root, today=_parse_today(args.today), dry_run=args.dry_run
    )
    suffix = " would be written" if args.dry_run else " written"
    print(
        f"lessons: {result.lessons_written}{suffix}, "
        f"{result.lessons_skipped} skipped"
    )
    print(
        f"playbooks: {result.playbooks_written}{suffix}, "
        f"{result.playbooks_skipped} skipped"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
