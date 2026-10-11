"""Concept note scanning for the deterministic weekly trends report."""
from __future__ import annotations

import re
from pathlib import Path

from scripts.fm import parse_frontmatter, split_frontmatter
from scripts.trend_report.metrics import parse_date
from scripts.trend_report.model import ConceptRecord

# Frontmatter marker / tags that flag a shipped SEED/EXAMPLE concept (CONVENTIONS
# §5.1) -- excluded from trends so sample notes never skew knowledge growth.
_SEED_TAGS = frozenset({"seed", "example"})
_SEED_BODY_RE = re.compile(r"SEED\s*/\s*EXAMPLE|SEED NOTE|EXAMPLE NOTE")
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _as_list(value: object) -> list[str]:
    """Coerce a frontmatter scalar/list into a list of strings (empty when None)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _link_stem(raw: str) -> str:
    """Normalize a wikilink target to a bare file stem.

    Handles both `related_concept` values that keep the wikilink brackets
    (`"[[concepts/x]]"`) and inline-body captures without them (`concepts/x`),
    plus an optional `|Alias` display suffix -- all reduce to `x`.
    """
    target = raw.strip().strip("\"'").strip("[]")
    target = target.split("|", 1)[0]
    return target.rsplit("/", 1)[-1].strip()


def _is_seed(tags: list[str], body: str) -> bool:
    """True for a shipped SEED/EXAMPLE sample note (excluded from trends)."""
    if _SEED_TAGS & {tag.lower() for tag in tags}:
        return True
    head = "\n".join(body.splitlines()[:15])
    return bool(_SEED_BODY_RE.search(head))


def _safe_read_text(path: Path) -> str | None:
    """Read a file as UTF-8, returning None on any OS error (skip, don't crash)."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def load_concept_records(concepts_dir: Path) -> list[ConceptRecord]:
    """Parse real concept notes into records (SEED/EXAMPLE excluded).

    Frontmatter is read via `scripts.fm.parse_frontmatter`, which prefers PyYAML but
    falls back to a stdlib line-based reader when it is absent — so the documented
    headless (no-PyYAML) runtime still counts concept growth / tags instead of
    silently reporting zero. An unreadable file just skips that note.
    """
    if not concepts_dir.exists():
        return []
    records: list[ConceptRecord] = []
    for path in sorted(concepts_dir.glob("*.md")):
        text = _safe_read_text(path)
        if text is None:
            continue
        block, body = split_frontmatter(text)
        data = parse_frontmatter(block)
        tags = _as_list(data.get("tags"))
        if _is_seed(tags, body):
            continue
        # Outbound links: explicit related_concept entries + inline body wikilinks.
        targets = {_link_stem(t) for t in _as_list(data.get("related_concept"))}
        targets |= {_link_stem(m) for m in _WIKILINK_RE.findall(body)}
        targets.discard("")
        name = str(data.get("title") or path.stem).strip().strip("\"'")
        records.append(
            ConceptRecord(
                name=name,
                stem=path.stem,
                created=parse_date(data.get("created")),
                last_updated=parse_date(data.get("last_updated")),
                tags=tags,
                out_targets=frozenset(targets),
            )
        )
    return records
