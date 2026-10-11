#!/usr/bin/env python3
"""
discover.py — propose new sources for a topic (ADR 0021 facade over `scripts/discovery/`).

Answers "who else should I be reading about X?" by searching, grouping results by
site, dropping everything already monitored, and proposing at most ten — each
with the reason it is proposed.

**It never adds anything.** Discovery proposes; `source-manage` is the only thing
that writes `config/sources.yaml`, and only after the user says yes. That split
is deliberate: a bug in ranking must not be able to enrol a site nobody chose.

CLI:
    python3 scripts/discover.py "ai agents" [--config-dir config]
    python3 scripts/discover.py "ai agents" --results results.json   # agent-supplied

`--results` accepts a JSON list of `{"url","title","snippet"}` — the path for
Claude's in-agent WebSearch, which a headless process cannot call itself.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.discovery.model import DiscoveryResult  # noqa: E402
from scripts.discovery.run import SearchFn, discover  # noqa: E402

DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"


def render(result: DiscoveryResult) -> str:
    """Plain-text proposals. The closing line is the point: nothing happened yet."""
    if result.needs_agent_search:
        return (
            f"{result.note}\n"
            "Run the search in-agent, then pass the results back:\n"
            f'  python3 scripts/discover.py "{result.topic}" --results results.json'
        )
    if not result.candidates:
        return result.note or "No new sources found."

    lines = [f"Possible new sources for “{result.topic}”:", ""]
    for index, candidate in enumerate(result.candidates, start=1):
        lines.append(f"{index}. {candidate.domain}")
        lines.append(f"   Why: {candidate.reason}")
        if candidate.feed_url:
            lines.append(f"   Feed: {candidate.feed_url}")
        for example in candidate.examples:
            lines.append(f"   e.g. {example}")
        lines.append("")
    lines.append(
        "Nothing has been added. Tell me which of these to monitor and I will "
        "add it through source-manage (trust tier is yours to set)."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topic", help="the topic to find sources for")
    parser.add_argument("--config-dir", default=str(DEFAULT_CONFIG_DIR))
    parser.add_argument(
        "--results", help="JSON file of search results (for the in-agent search path)"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    search_fn: SearchFn | None = None
    if args.results:
        try:
            supplied = json.loads(Path(args.results).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"error: could not read --results: {error}", file=sys.stderr)
            return 2
        if not isinstance(supplied, list):
            print("error: --results must contain a JSON list", file=sys.stderr)
            return 2
        # Already-fetched results: return them for the first query shape and
        # nothing after, so one supplied set is not counted three times.
        served = {"done": False}

        def search_fn(_query: str) -> list[dict[str, str]]:
            if served["done"]:
                return []
            served["done"] = True
            return [row for row in supplied if isinstance(row, dict)]

    result = discover(args.topic, config_dir=Path(args.config_dir), search_fn=search_fn)
    if args.json:
        print(json.dumps({
            "topic": result.topic,
            "needs_agent_search": result.needs_agent_search,
            "note": result.note,
            "candidates": [
                {
                    "domain": c.domain, "url": c.url, "hits": c.hits, "role": c.role,
                    "feed_url": c.feed_url, "reason": c.reason, "examples": list(c.examples),
                }
                for c in result.candidates
            ],
        }, indent=2))
        return 0
    print(render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
