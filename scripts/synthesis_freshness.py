#!/usr/bin/env python3
"""
synthesis_freshness.py — content-hash re-synthesis trigger for weekly-synthesis.

Why: the old eligibility gate re-synthesized an already-covered topic only when
its synthesis doc was older than 30 days AND the curated index had changed. So
substantial new material on an existing topic could sit unused for up to ~30 days
(the synthesis was throttled by the clock, not by whether anything actually
changed). This replaces the time gate with a content gate: a topic is eligible
whenever it has no synthesis yet (NEW), or its curated `index.md` changed since
the last synthesis (STALE) — regardless of age.

The last-synthesized state is a sidecar JSON next to the synthesis output,
`pipeline/3-synthesis/{topic}/.synthesis-meta.json`, holding the hash of the
curated `index.md` at synthesis time. The plain-Markdown research doc is left
untouched (no frontmatter forced onto it).

Flow in weekly-synthesis:
  - `list`  → topics that are NEW or STALE and clear the source threshold;
  - synthesize each;
  - `stamp <topic>` after a topic's synthesis + ingest, recording the index hash
    so it reads FRESH until the curated corpus changes again.

stdlib only, deterministic (inject `when` for the stamp date in tests).

CLI:
    python3 scripts/synthesis_freshness.py list --min-sources 3
    python3 scripts/synthesis_freshness.py stamp <topic>
    python3 scripts/synthesis_freshness.py status <topic> --min-sources 3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Make `scripts` importable when run directly (`python3 scripts/synthesis_freshness.py`),
# mirroring health.py — so the durable-state resolver import below resolves either way.
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.registry import atomic_write_text  # noqa: E402 — shared atomic writer

# The ruleset version is owned by the sanitizer module (it is also recorded in
# every companion for skip-if-current); folded into the freshness hash here so a
# bump forces re-synthesis of every topic even when no content changed.
from scripts.sanitize_incoming import SANITIZER_VERSION  # noqa: E402
from scripts.state import state_root  # noqa: E402 — durable-state relocation (env opt-in)

DEFAULT_CURATED = _PROJECT_ROOT / "pipeline" / "2-curated"
DEFAULT_SYNTHESIS = _PROJECT_ROOT / "pipeline" / "3-synthesis"

SIDECAR_NAME = ".synthesis-meta.json"

# Where sanitized companion files for a topic live, relative to the incoming
# topic dir: pipeline/1-incoming/{topic}/sanitized/*.md.
_SANITIZED_SUBDIR = "sanitized"

# A curated source line, e.g. "- [title](../../1-incoming/topic/x.md) — summary".
_SOURCE_LINE = re.compile(r"^\s*-\s+\[[^\]]+\]\([^)]+\)")
_SOURCE_TARGET = re.compile(r"^\s*-\s+\[[^\]]+\]\(([^)]+)\)")


class Status(str, Enum):
    NEW = "new"                          # no prior synthesis for this topic
    STALE = "stale"                      # curated index changed since last synthesis
    FRESH = "fresh"                      # index unchanged since last synthesis
    BELOW_THRESHOLD = "below-threshold"  # fewer than min_sources curated sources


def index_hash(curated_index: Path) -> str:
    """sha256 of the curated index.md content — the change signal."""
    return hashlib.sha256(curated_index.read_bytes()).hexdigest()


def count_sources(curated_index: Path) -> int:
    """Number of curated source lines in an index.md."""
    text = curated_index.read_text(encoding="utf-8")
    return sum(1 for line in text.splitlines() if _SOURCE_LINE.match(line))


def _incoming_root(curated_root: Path) -> Path:
    """The incoming root that holds sanitized companions, a sibling of curated.

    Layout: pipeline/2-curated → pipeline/1-incoming. We derive it from the
    curated root so callers keep passing only --curated/--synthesis.
    """
    return curated_root.parent / "1-incoming"


def _curated_companions(curated_index: Path, incoming_root: Path, topic: str) -> list[Path]:
    """Sorted sanitized companions of the articles the curated index lists.

    Only these bytes are synthesis inputs. A freshly collected companion whose
    article was never curated must NOT read as corpus change — mid-cycle
    collects were killing every digest lead — it gets its invalidation moment
    when curate promotes it and the index itself changes."""
    sanitized_dir = incoming_root / topic / _SANITIZED_SUBDIR
    if not sanitized_dir.is_dir():
        return []
    names = set()
    for line in curated_index.read_text(encoding="utf-8").splitlines():
        match = _SOURCE_TARGET.match(line)
        if match:
            names.add(Path(match.group(1)).name)
    return sorted(
        p for p in sanitized_dir.glob("*.md") if p.is_file() and p.name in names
    )


def combined_hash(curated_index: Path, incoming_root: Path, topic: str) -> str:
    """The real freshness signal over all synthesized inputs for a topic.

    Folds together, deterministically:
      (a) the curated index.md content,
      (b) the bytes of the sanitized companions the curated index references
          (uncurated arrivals are not synthesis inputs), keyed by sorted
          relative path so the result is stable regardless of ordering, and
      (c) SANITIZER_VERSION, so bumping it invalidates every topic.

    Companions are hashed by reading their bytes directly (no import of the
    sanitizer) to avoid coupling. Topics with no companions degrade to
    index + version only.
    """
    hasher = hashlib.sha256()
    hasher.update(b"version\x00")
    hasher.update(SANITIZER_VERSION.encode("utf-8"))
    hasher.update(b"\x00index\x00")
    hasher.update(index_hash(curated_index).encode("ascii"))
    sanitized_dir = incoming_root / topic / _SANITIZED_SUBDIR
    for path in _curated_companions(curated_index, incoming_root, topic):
        relpath = path.relative_to(sanitized_dir).as_posix()
        hasher.update(b"\x00file\x00")
        hasher.update(relpath.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
    return hasher.hexdigest()


def _sidecar(synthesis_root: Path, topic: str) -> Path:
    """The per-topic freshness sidecar path, relocatable onto a persistent volume.

    Default (env unset): the in-repo `{synthesis_root}/{topic}/.synthesis-meta.json`.
    With `RESEARCH_BRAIN_STATE_DIR` set, it relocates under that volume preserving
    the `pipeline/3-synthesis/{topic}/...` substructure, so a redeploy / state-wipe
    doesn't lose the last-synthesized hash and re-synthesize every topic. The
    project root is the synthesis root's grandparent (`…/pipeline/3-synthesis`).
    """
    in_repo = synthesis_root / topic / SIDECAR_NAME
    return state_root(in_repo, project_root=synthesis_root.parents[1])


# Sidecar field names. The current field stores the broad combined hash; the
# legacy field stored only the curated-index hash. We keep reading both so old
# sidecars don't crash.
_COMBINED_FIELD = "combined_hash"
_LEGACY_FIELD = "source_index_hash"


def recorded_hash(synthesis_root: Path, topic: str) -> str | None:
    """The combined freshness hash recorded at the topic's last synthesis.

    Returns the current combined hash if present. For tolerance, an old sidecar
    that only has the legacy `source_index_hash` (no combined hash) returns None
    here — the caller treats that as STALE (the safe direction), since the
    legacy hash cannot prove the corpus content is unchanged. None is also
    returned when the sidecar is missing or unreadable.

    Reads through `_sidecar`, so a `RESEARCH_BRAIN_STATE_DIR`-relocated sidecar is
    found in the same place `stamp` wrote it.
    """
    sidecar = _sidecar(synthesis_root, topic)
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        value = data.get(_COMBINED_FIELD)
        return str(value) if value is not None else None
    except (FileNotFoundError, ValueError, TypeError):
        return None


def _sidecar_exists(synthesis_root: Path, topic: str) -> bool:
    """Whether a (any-shape) synthesis sidecar exists for the topic."""
    return _sidecar(synthesis_root, topic).is_file()


def topic_status(
    curated_root: Path, synthesis_root: Path, topic: str, *, min_sources: int
) -> Status:
    """Classify one topic's synthesis eligibility."""
    curated_index = curated_root / topic / "index.md"
    if not curated_index.exists():
        return Status.BELOW_THRESHOLD
    if count_sources(curated_index) < min_sources:
        return Status.BELOW_THRESHOLD
    recorded = recorded_hash(synthesis_root, topic)
    if recorded is None:
        # No combined hash on record. A missing sidecar means we never
        # synthesized this topic (NEW); an existing sidecar without the combined
        # hash is a legacy stamp we can't trust → STALE (the safe direction).
        return Status.STALE if _sidecar_exists(synthesis_root, topic) else Status.NEW
    current = combined_hash(curated_index, _incoming_root(curated_root), topic)
    return Status.STALE if recorded != current else Status.FRESH


def is_fresh(curated_root: Path, synthesis_root: Path, topic: str) -> bool:
    """True iff the topic's recorded synthesis still matches the current corpus.

    Threshold-independent (unlike `topic_status`): it answers only "is the last
    synthesis current?". The digest builder uses this to decide whether a per-topic
    `digest-lead.md` is still valid — a lead describes one synthesis run, so when the
    topic was skipped or its corpus changed (no longer FRESH) the lead is stale and
    must be suppressed. A missing index or stamp reads NOT fresh (safe direction)."""
    curated_index = curated_root / topic / "index.md"
    if not curated_index.exists():
        return False
    recorded = recorded_hash(synthesis_root, topic)
    if recorded is None:
        return False
    return recorded == combined_hash(curated_index, _incoming_root(curated_root), topic)


def _topics(curated_root: Path) -> list[str]:
    if not curated_root.exists():
        return []
    return sorted(
        d.name for d in curated_root.iterdir()
        if d.is_dir() and (d / "index.md").exists()
    )


def eligible_topics(
    curated_root: Path = DEFAULT_CURATED,
    synthesis_root: Path = DEFAULT_SYNTHESIS,
    *,
    min_sources: int,
) -> list[tuple[str, Status]]:
    """Topics that need (re)synthesis this run — NEW or STALE only."""
    out: list[tuple[str, Status]] = []
    for topic in _topics(curated_root):
        status = topic_status(curated_root, synthesis_root, topic, min_sources=min_sources)
        if status in (Status.NEW, Status.STALE):
            out.append((topic, status))
    return out


def stamp(
    curated_root: Path,
    synthesis_root: Path,
    topic: str,
    *,
    when: date | None = None,
) -> Path:
    """Record the current combined freshness hash for a topic after synthesis.

    The combined hash covers the curated index, the bytes of the companions
    that index references, and SANITIZER_VERSION, so the topic reads FRESH
    only until a real synthesized input changes. The legacy `source_index_hash` is kept alongside
    for human/debugging continuity.
    """
    curated_index = curated_root / topic / "index.md"
    sidecar = _sidecar(synthesis_root, topic)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            _COMBINED_FIELD: combined_hash(curated_index, _incoming_root(curated_root), topic),
            _LEGACY_FIELD: index_hash(curated_index),
            "sanitizer_version": SANITIZER_VERSION,
            # UTC date by default, matching health.py and the rest of the durability
            # layer so the persisted-date axis can't disagree by a calendar day near
            # midnight; tests inject `when=` for determinism.
            "synthesized_at": (when or datetime.now(UTC).date()).isoformat(),
        },
        indent=2,
    )
    atomic_write_text(sidecar, payload + "\n")
    return sidecar


# ── CLI ──────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Content-hash re-synthesis trigger for weekly-synthesis."
    )
    sub = parser.add_subparsers(dest="command")

    def _add_roots(p: argparse.ArgumentParser) -> None:
        p.add_argument("--curated", default=str(DEFAULT_CURATED), help="pipeline/2-curated/ root.")
        p.add_argument("--synthesis", default=str(DEFAULT_SYNTHESIS), help="pipeline/3-synthesis/ root.")

    p_list = sub.add_parser("list", help="List topics needing (re)synthesis (NEW/STALE).")
    _add_roots(p_list)
    p_list.add_argument("--min-sources", type=int, default=3, help="Curated-source threshold.")

    p_status = sub.add_parser("status", help="Print one topic's status.")
    _add_roots(p_status)
    p_status.add_argument("topic")
    p_status.add_argument("--min-sources", type=int, default=3, help="Curated-source threshold.")

    p_stamp = sub.add_parser("stamp", help="Record the curated-index hash after synthesizing a topic.")
    _add_roots(p_stamp)
    p_stamp.add_argument("topic")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        eligible = eligible_topics(
            Path(args.curated), Path(args.synthesis), min_sources=args.min_sources
        )
        if not eligible:
            print("No topics need synthesis this run (all FRESH or below threshold).")
            return 0
        print(f"{len(eligible)} topic(s) need synthesis:")
        for topic, status in eligible:
            print(f"  - {topic} ({status.value})")
        return 0

    if args.command == "status":
        status = topic_status(
            Path(args.curated), Path(args.synthesis), args.topic, min_sources=args.min_sources
        )
        print(f"{args.topic}: {status.value}")
        return 0

    if args.command == "stamp":
        sidecar = stamp(Path(args.curated), Path(args.synthesis), args.topic)
        print(f"OK: stamped {args.topic} → {sidecar}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
