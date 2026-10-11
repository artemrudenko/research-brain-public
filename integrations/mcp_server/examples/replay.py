"""Replay the public retrieval contract against disposable, explicitly synthetic notes.

Run from the checkout root with the adapter's isolated environment. This starts
the actual stdio server, not a model host. It performs no network research or
approved ingest and never opens the operator's vault.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

SOURCE = "https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3"


def note(title: str, verified: date, fact: str) -> str:
    return (
        f"---\ntitle: {title}\ntype: concept\ntags: [tech, tech/dev]\n"
        f"created: {date.today()}\nlast_updated: {date.today()}\n"
        f"last_verified: {verified}\nttl_days: 30\ndataset: synthetic\n"
        f"sources:\n  - url: {SOURCE}\n    date: 2026-10-11\n    tier: medium\n"
        "---\n"
        f"# {title}\n\n> **Confidence:** medium\n\n"
        "## What it is\n\nSynthetic replay note; dates simulate freshness only.\n\n"
        f"## Key facts\n\n- {fact} Source: {SOURCE}\n\n"
        "## Open questions / gaps\n\n- Check the consuming client's retry rules.\n"
    )


def digest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


async def replay(root: Path) -> dict[str, str]:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "research_brain_mcp"],
        env={"RESEARCH_BRAIN_ROOT": str(root)},
    )
    checks = {}
    async with Client(parameters) as client:
        tools = (await client.list_tools()).tools
        if {tool.name for tool in tools} != {"search_knowledge", "get_concept"}:
            raise RuntimeError("Unexpected tool surface")
        if not all(tool.annotations and tool.annotations.read_only_hint for tool in tools):
            raise RuntimeError("Read-only annotations missing")
        checks["tool_surface"] = "two read-only tools"

        cases = (
            ("hit", "search_knowledge", {"query": "HTTP Retry-After"}, "retry-after.md"),
            (
                "natural_miss", "search_knowledge",
                {"query": "What do we know about quantum error correction?"}, "Vault-only miss",
            ),
            (
                "stale_control", "get_concept",
                {"slug": "stale-control", "request_mode": "research"}, "review_due",
            ),
            (
                "research_handoff", "search_knowledge",
                {"query": "HTTP Retry-After", "request_mode": "research"}, "prior context",
            ),
        )
        for label, tool, arguments, expected in cases:
            response = await client.call_tool(tool, arguments)
            text = "\n".join(block.text for block in response.content if block.type == "text")
            if response.is_error or expected not in text:
                raise RuntimeError(f"{label} failed: {text}")
            if label == "hit" and SOURCE not in text:
                raise RuntimeError("Source provenance missing")
            checks[label] = "pass"
    return checks


def main() -> None:
    with TemporaryDirectory(prefix="research-brain-replay-") as temporary:
        root = Path(temporary)
        concepts = root / "brain" / "concepts"
        concepts.mkdir(parents=True)
        (root / "brain" / "INDEX.md").write_text(
            "# Synthetic map\n\n- [[concepts/retry-after|HTTP Retry-After]]\n"
            "- [[concepts/stale-control|Intentionally stale control]]\n", encoding="utf-8",
        )
        (concepts / "retry-after.md").write_text(
            note(
                "HTTP Retry-After", date.today(),
                "The header describes a wait before a follow-up request; its value may be "
                "an HTTP date or a nonnegative whole number of seconds.",
            ), encoding="utf-8",
        )
        (concepts / "stale-control.md").write_text(
            note("Intentionally stale control", date.today() - timedelta(days=31),
                 "This deliberately old date tests review-due handling, not a stale incident."),
            encoding="utf-8",
        )
        before = digest(root)
        checks = asyncio.run(replay(root))
        if before != digest(root):
            raise RuntimeError("Retrieval changed the synthetic vault")
        print(json.dumps({
            "scope": "Synthetic stdio replay; no model, research, or ingest",
            "checks": checks, "vault_unchanged": True,
        }, indent=2))


if __name__ == "__main__":
    main()
