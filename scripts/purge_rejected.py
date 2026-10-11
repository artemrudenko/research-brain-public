#!/usr/bin/env python3
"""
purge_rejected.py — evict curation-rejected articles from `pipeline/1-incoming`.

When curation marks an article `rejected` in the registry, the registry row is the
durable audit record — but the article FILE (and its sanitized companion under
`{topic}/sanitized/`) used to linger in `1-incoming`. That leftover content was then
re-sanitized, fed to synthesis (so rejected hype could re-enter `brain/`), folded
into the per-topic freshness hash, and surfaced by the digest as a "new source".

This tool enforces the reject decision at the filesystem level: it removes every
rejected article and its companion, so EVERY downstream consumer (synthesis,
`synthesis_freshness`, `build_digest`) is correct without each needing to re-check
the registry. The registry row stays (rejected URLs remain known, so they are never
re-collected). Idempotent: a second run finds nothing left to purge.

Usage (CLI):
    python3 scripts/purge_rejected.py            # purge under the default pipeline
    python3 scripts/purge_rejected.py --incoming pipeline/1-incoming \\
        --registry pipeline/registry.md
    python3 scripts/purge_rejected.py --dry-run  # list what WOULD be removed
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.normalize_url import normalize_or_raw  # noqa: E402
from scripts.registry import iter_registry_rows  # noqa: E402
from scripts.sanitize_incoming import COMPANION_DIRNAME, sanitized_path  # noqa: E402

DEFAULT_INCOMING = _PROJECT_ROOT / "pipeline" / "1-incoming"
DEFAULT_REGISTRY = _PROJECT_ROOT / "pipeline" / "registry.md"

# Top-level frontmatter `url:` reader (tolerant of surrounding quotes), matching the
# minimal style used elsewhere so this module needs no heavy frontmatter parser.
_URL_RE = re.compile(r"(?m)^url:\s*(.+?)\s*$")


def _article_url(path: Path) -> str:
    """The `url:` frontmatter value of an article (empty when absent/unreadable)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = _URL_RE.search(text)
    return match.group(1).strip().strip("\"'") if match else ""


def rejected_keys(registry_path: Path) -> set[str]:
    """Normalized URLs whose registry status is `rejected`."""
    return {
        normalize_or_raw(row.url)
        for row in iter_registry_rows(registry_path)
        if row.url and row.status.strip().lower() == "rejected"
    }


def purge_rejected(
    incoming_root: Path, registry_path: Path, *, dry_run: bool = False
) -> list[Path]:
    """Remove every rejected article (and its sanitized companion) from incoming.

    Returns the list of paths removed (or that WOULD be removed, when `dry_run`).
    Raw articles are matched to the registry by their normalized `url:`; the
    companion is the same filename under `{topic}/sanitized/`.
    """
    rejected = rejected_keys(registry_path)
    removed: list[Path] = []
    if not rejected or not incoming_root.exists():
        return removed
    for path in sorted(incoming_root.rglob("*.md")):
        # Walk only raw articles; companions are removed alongside their article.
        if COMPANION_DIRNAME in path.parts or path.name == "index.md":
            continue
        url = _article_url(path)
        if not url or normalize_or_raw(url) not in rejected:
            continue
        companion = sanitized_path(path)
        for victim in (path, companion):
            if victim.exists():
                removed.append(victim)
                if not dry_run:
                    victim.unlink()
    return removed


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Always returns 0; prints what was (or would be) removed."""
    parser = argparse.ArgumentParser(
        description="Evict curation-rejected articles + companions from 1-incoming."
    )
    parser.add_argument("--incoming", default=str(DEFAULT_INCOMING), help="pipeline/1-incoming")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="pipeline/registry.md")
    parser.add_argument("--dry-run", action="store_true", help="list, remove nothing")
    args = parser.parse_args(argv)

    removed = purge_rejected(
        Path(args.incoming), Path(args.registry), dry_run=args.dry_run
    )
    verb = "would remove" if args.dry_run else "removed"
    if not removed:
        print("no rejected articles to purge")
    else:
        print(f"{verb} {len(removed)} file(s):")
        for path in removed:
            print(f"  {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
