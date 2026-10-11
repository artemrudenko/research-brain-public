#!/usr/bin/env python3
"""
search_trail.py — durable, machine-readable search-trail log (CONVENTIONS §15b).

A manual research session can run several web searches across several providers.
This module records, per search, ONE JSON object — *which query ran against which
provider, how many results came back, and the registrable domains of those
results* — so a reviewer can audit a session's web-research provenance after the
fact. It is the auditable-grounding companion of the verification-log: the
verification-log records *what claims were checked*, the search-trail records
*what was searched to find them*.

Artifact (sibling of the brief, same `{date}_{slug}` prefix as the
verification-log / critique-log):

    planning/research/{date}_{slug}.search-trail.jsonl   (one JSON object/line)

Two paths feed it, both through `append_search_entry`:
  (a) the API-provider path — auto-wired into `search.py` / `cross_check.py`, so
      tavily / perplexity / sonar calls self-record when a trail target is set;
  (b) the agent's own `claude-websearch` — recorded by the research skills calling
      this helper directly (the default provider's results never flow through the
      scripts, so the scripts cannot see them — the skill wiring completes the
      trail). See `skills/research-frame` / `skills/research-build`.

Gating — OFF by default: nothing is written unless a trail target is configured,
either via the `RESEARCH_TRAIL_DIR` env var (which dir the trail lives in) or an
explicit path passed by a caller. So unit tests and the headless cron path write
no trail files.

Soft-skip discipline (mirrors search.py / deliver.py, CONVENTIONS §8/§10): a
trail-logging failure NEVER raises — it is swallowed with a printed note, because
a logging hiccup must not abort a search. Append is line-atomic: each entry is one
`os.write` of a single newline-terminated line to an `O_APPEND` fd, so concurrent
appends never tear a line (POSIX guarantees atomicity for a small append write).

Stdlib only; no SDK, no network.

CLI:
    python3 scripts/search/search_trail.py <trail.jsonl>     # print a summary
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Reuse the canonical eTLD+1 extractor — never reimplement public-suffix logic
# (DRY, CONVENTIONS §16).
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.corroborate import registrable_domain

# The env var that names the directory the search-trail is written into. Unset ->
# the feature is OFF (no trail files), matching the off-by-default contract.
TRAIL_DIR_ENV = "RESEARCH_TRAIL_DIR"

# Suffix appended to a `{date}_{slug}` prefix to form the trail filename — the
# same sibling-with-shared-prefix convention as `.verification-log.md`.
TRAIL_SUFFIX = ".search-trail.jsonl"

# Max length of a query-derived slug (filename safety; KISS).
_SLUG_MAX = 60


@dataclass(frozen=True)
class SearchEntry:
    """One recorded search: a query against a provider and what it returned.

    `ts` is an ISO-8601 UTC timestamp; `domains` are the registrable domains
    (eTLD+1) of the result URLs, de-duplicated in first-seen order with blanks
    dropped. Frozen so a read entry is an immutable record.
    """

    ts: str
    query: str
    provider: str
    n_results: int
    domains: tuple[str, ...]


def _domains_of(urls: Sequence[str]) -> list[str]:
    """Registrable domains (eTLD+1) of `urls`, de-duplicated, blanks dropped.

    Reuses `corroborate.registrable_domain`, which returns "" for junk input —
    those are dropped so the trail records only real publishers.
    """
    seen: list[str] = []
    for url in urls:
        domain = registrable_domain(url)
        if domain and domain not in seen:
            seen.append(domain)
    return seen


def append_search_entry(
    trail_path: Path,
    *,
    query: str,
    provider: str,
    n_results: int,
    urls: Sequence[str],
) -> None:
    """Append one search record to `trail_path` (JSONL); soft-skip on any error.

    Best-effort and line-atomic: builds the entry, then does a single `os.write`
    of one newline-terminated JSON line to an `O_APPEND` fd, so overlapping
    appends never interleave into a torn line. ANY IO error (a non-directory
    parent, a permission problem) is swallowed with a printed note — a trail
    write must never abort the search that produced it.
    """
    entry = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "query": query,
        "provider": provider,
        "n_results": int(n_results),
        "domains": _domains_of(urls),
    }
    line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        trail_path.parent.mkdir(parents=True, exist_ok=True)
        # O_APPEND makes the single write atomic w.r.t. other appenders (POSIX),
        # so a concurrent writer can never split this line.
        fd = os.open(trail_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except OSError as error:
        # Observability is never load-bearing: log and move on, never raise.
        print(f"search-trail: could not record entry ({error}) — soft-skip")


def read_trail(trail_path: Path) -> list[SearchEntry]:
    """Read `trail_path` into `SearchEntry` records; soft-skip on any problem.

    A missing file yields `[]`. A corrupt or partial line is skipped (the trail
    is observability, never load-bearing) rather than crashing the reader. Any
    IO error also degrades to `[]`.
    """
    try:
        raw = trail_path.read_text(encoding="utf-8")
    except OSError:
        return []
    entries: list[SearchEntry] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue  # corrupt / half-written line — skip, don't crash
        if not isinstance(obj, dict):
            continue
        domains = obj.get("domains")
        entries.append(
            SearchEntry(
                ts=str(obj.get("ts", "")),
                query=str(obj.get("query", "")),
                provider=str(obj.get("provider", "")),
                n_results=int(obj.get("n_results", 0) or 0),
                domains=tuple(str(d) for d in domains) if isinstance(domains, list) else (),
            )
        )
    return entries


def summarize_trail(entries: Sequence[SearchEntry]) -> str:
    """Render a short, human-readable summary of a trail (one line per search)."""
    if not entries:
        return "search-trail: (empty)"
    header = f"search-trail: {len(entries)} search(es)"
    lines = [
        f"  [{e.provider}] {e.query} -> {e.n_results} result(s)"
        + (f" from {', '.join(e.domains)}" if e.domains else "")
        for e in entries
    ]
    return "\n".join([header, *lines])


def slug_for_query(query: str) -> str:
    """Derive a filesystem-safe slug from a free-text query.

    Lowercase, non-alphanumerics collapsed to single hyphens, trimmed, capped at
    `_SLUG_MAX`. Used to name a per-query trail file when no explicit session slug
    is supplied (the auto-wired script path). An empty/punctuation-only query maps
    to the stable placeholder `query` so a file can always be named.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:_SLUG_MAX].strip("-")
    return slug or "query"


def trail_path_for_brief(brief_path: Path) -> Path:
    """The trail file that sits beside a research brief, sharing its prefix.

    `planning/research/2026-06-22_topic.md` ->
    `planning/research/2026-06-22_topic.search-trail.jsonl`.
    """
    return brief_path.with_name(brief_path.stem + TRAIL_SUFFIX)


def resolve_trail_target(slug: str) -> Path | None:
    """Resolve where a trail for `slug` should be written, honoring the gate.

    Returns `None` when `RESEARCH_TRAIL_DIR` is unset / blank — the off-by-default
    contract, so the auto-wired script path writes nothing during unrelated unit
    tests or the headless cron path. When set, the trail is
    `{RESEARCH_TRAIL_DIR}/{slug}{TRAIL_SUFFIX}` (a `~` prefix is expanded).
    """
    raw = os.environ.get(TRAIL_DIR_ENV)
    if raw is None or not raw.strip():
        return None
    return Path(raw.strip()).expanduser() / f"{slug}{TRAIL_SUFFIX}"


def main(argv: list[str] | None = None) -> int:
    """CLI entry: `search_trail.py <trail.jsonl>` — print a summary. Exits 0."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: search_trail.py <trail.jsonl>", file=sys.stderr)
        return 2
    print(summarize_trail(read_trail(Path(args[0]))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
