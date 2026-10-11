from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from research_brain_mcp.server import mcp


def test_mcp_protocol_exposes_only_read_tools(tmp_path: Path, monkeypatch) -> None:
    brain = tmp_path / "brain"
    concepts = brain / "concepts"
    concepts.mkdir(parents=True)
    (brain / "INDEX.md").write_text(
        "# Map\n\n## Protocols\n- [[concepts/retry-safety|Retry safety]]\n",
        encoding="utf-8",
    )
    template = (
        "---\ntitle: Retry safety\ntype: concept\ntags: [engineering/protocols]\n"
        "last_updated: 2026-09-01\nsources:\n  - url: https://example.org/spec\n"
        "---\n# Retry safety\n> **Confidence:** high\n\n"
        "## What it is\n\nA bounded rule.\n\n"
        "## Open questions / gaps\n\n- Check newer versions.\n"
    )
    (concepts / "retry-safety.md").write_text(template, encoding="utf-8")
    (concepts / "other-note.md").write_text(
        template.replace("Retry safety", "Other note"), encoding="utf-8"
    )
    (concepts / "retry-safety.md").write_text(
        (concepts / "retry-safety.md").read_text(encoding="utf-8").replace(
            "A bounded rule.",
            "Idempotency keys let clients safely retry requests after a timeout.",
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RESEARCH_BRAIN_ROOT", str(tmp_path))

    async def exercise_client() -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} == {"search_knowledge", "get_concept"}
            for tool in tools.tools:
                assert tool.annotations is not None
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.destructive_hint is False
                assert tool.annotations.open_world_hint is False
            assert client.instructions and "read-only" in client.instructions
            result = await client.call_tool("search_knowledge", {"query": "retry safety"})
            assert result.is_error is False
            assert len(result.content) == 1
            assert "https://example.org/spec" in result.content[0].text
            assert "Open questions / gaps" in result.content[0].text

            body_match = await client.call_tool(
                "search_knowledge", {"query": "idempotency keys"}
            )
            assert "Match path: concept text" in body_match.content[0].text
            assert "Idempotency keys let clients safely retry" in body_match.content[0].text

            research_result = await client.call_tool(
                "search_knowledge", {"query": "retry safety", "request_mode": "research"}
            )
            assert "Request mode: research" in research_result.content[0].text
            assert "prior context, not a complete answer" in research_result.content[0].text

    asyncio.run(exercise_client())


def test_mcp_stdio_subprocess_returns_vault_only_miss(tmp_path: Path) -> None:
    brain = tmp_path / "brain"
    concepts = brain / "concepts"
    concepts.mkdir(parents=True)
    (brain / "INDEX.md").write_text("# Empty synthetic index\n", encoding="utf-8")
    (concepts / "concept-one.md").write_text(
        "---\ntitle: One\ntype: concept\n---\n", encoding="utf-8"
    )
    (concepts / "concept-two.md").write_text(
        "---\ntitle: Two\ntype: concept\n---\n", encoding="utf-8"
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "research_brain_mcp"],
        env={"RESEARCH_BRAIN_ROOT": str(tmp_path)},
    )

    async def exercise_stdio() -> None:
        async with Client(parameters) as client:
            result = await client.call_tool("search_knowledge", {"query": "missing topic"})
            assert result.is_error is False
            assert "Vault-only miss" in result.content[0].text
            assert "No raw corpus or web search was accessed" in result.content[0].text
            research_result = await client.call_tool(
                "search_knowledge", {"query": "missing topic", "request_mode": "research"}
            )
            assert "Request mode: research" in research_result.content[0].text
            assert "continue the existing research workflow" in research_result.content[0].text

    asyncio.run(exercise_stdio())
