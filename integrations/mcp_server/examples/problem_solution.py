"""Disposable actual-stdio replay of the exact proposal/approval/retrieval path."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "scripts/problem_solution.py"


def snapshot(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def command(project: Path, *args: str, expected: int = 0) -> str:
    result = subprocess.run(
        [sys.executable, str(CLI), *args], cwd=project, capture_output=True, text=True, check=False
    )
    assert result.returncode == expected, result.stderr
    return result.stdout


async def lookup(vault: Path, consumer: Path, saved: bool) -> None:
    before = snapshot(vault)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "research_brain_mcp"],
        env={"RESEARCH_BRAIN_ROOT": str(vault)},
        cwd=str(consumer),
    )
    async with Client(params) as client:
        tools = await client.list_tools()
        assert {t.name for t in tools.tools} == {"search_knowledge", "get_concept"}
        result = await client.call_tool(
            "search_knowledge",
            dict(
                query="",
                programming_language="Python",
                problem_type="http-retry",
                knowledge_kind="problem_solution",
            ),
        )
        assert not result.is_error
        text = result.content[0].text
        if saved:
            assert "Synthetic bounded retry finding" in text
            assert "non-idempotent writes" in text
            assert "problem_type=http-retry" in text
            full = await client.call_tool("get_concept", {"slug": "synthetic-retry"})
            assert "pipeline/3-synthesis/synthetic-retry-evidence.md" in full.content[0].text
            assert "not evidence of a real implementation fix" in full.content[0].text
        else:
            assert "Vault-only miss" in text
        miss = await client.call_tool(
            "search_knowledge", dict(query="retry", programming_language="rust")
        )
        assert not miss.is_error and "Vault-only miss" in miss.content[0].text
    assert snapshot(vault) == before


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="research-brain-solutions-") as temporary:
        parent = Path(temporary)
        vault, producer, consumer = (parent / name for name in ("vault", "project-a", "project-b"))
        for path in (vault / "brain/concepts", vault / "config", producer, consumer):
            path.mkdir(parents=True)
        (vault / "config/tags.yaml").write_text(
            "domains:\n  tech: [dev]\nsynonyms: {}\npending: []\n"
        )
        (vault / "brain/INDEX.md").write_text("# Map\n- [[one]]\n- [[two]]\n")
        for slug in ("one", "two"):
            (vault / f"brain/concepts/{slug}.md").write_text(
                f"---\ntype: concept\ntitle: {slug}\n---\n# Seed\n"
            )
        record = (
            (Path(__file__).parent / "fixtures/problem-solution.md")
            .read_text()
            .replace("DATE", date.today().isoformat())
        )
        (producer / "candidate.md").write_text(record)
        (producer / "evidence.md").write_text(
            "# Synthetic evidence\nManually authored fixture; no engineering test result is claimed.\n"
        )
        command(producer, "validate", "candidate.md")
        staged = json.loads(
            command(
                producer,
                "propose",
                "--root",
                str(vault),
                "--slug",
                "synthetic-retry",
                "--body-file",
                "candidate.md",
                "--artifact",
                "pipeline/3-synthesis/synthetic-retry-evidence.md",
                "evidence.md",
            )
        )
        review = command(producer, "review", staged["id"], "--root", str(vault))
        assert staged["digest"] in review and "brain/INDEX.md" in review
        await lookup(vault, consumer, False)
        command(
            producer,
            "apply",
            staged["id"],
            "--root",
            str(vault),
            "--approved-digest",
            "bad",
            "--approval-reference",
            "Synthetic rejected digest",
            expected=2,
        )
        assert not (vault / "brain/concepts/synthetic-retry.md").exists()
        # This is simulated authorization for a disposable fixture, not real user consent.
        applied = json.loads(
            command(
                producer,
                "apply",
                staged["id"],
                "--root",
                str(vault),
                "--approved-digest",
                staged["digest"],
                "--approval-reference",
                "Synthetic fixture approval; not a human consent event",
            )
        )
        assert applied["status"] == "applied"
        assert (vault / "brain/concepts/synthetic-retry.md").read_text() == record
        command(producer, "validate", "candidate.md", "--root", str(vault))
        await lookup(vault, consumer, True)
        print(
            json.dumps(
                dict(
                    scope="Synthetic project-to-vault replay; no personal knowledge or real consent",
                    validation="pass",
                    candidate_excluded="pass",
                    digest_binding="pass",
                    retained_evidence="pass",
                    approved_package_applied="pass",
                    filtered_actual_stdio="pass",
                    retrieval_read_only="pass",
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
