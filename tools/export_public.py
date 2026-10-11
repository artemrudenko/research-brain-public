#!/usr/bin/env python3
"""Export an allowlisted, clean-history GitHub source snapshot from a commit.

This copies committed blobs, not the working tree and not Git metadata. It never
creates a repository or pushes anywhere. New tracked paths require an explicit
allow/exclude decision before export can proceed.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess  # nosec B404
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROOT_FILES = {
    ".gitattributes", ".gitignore", ".python-version", "AGENTS.md", "CLAUDE.md",
    "CHANGELOG.md", "DEVELOPING.md", "FIRST-RUN.md", "LICENSE", "Makefile",
    "QUICKSTART.md", "QUICKSTART.ru.md", "README.md", "USER_GUIDE.md",
    "install.ps1", "install.sh", "pyproject.toml", "pytest.ini",
    "requirements-dev.txt", "requirements.txt", "update.ps1", "update.sh", "uv.lock",
}
ALLOWED_PREFIXES = (
    ".claude-plugin/", ".claude/agents/", ".github/workflows/", "docs/adr/",
    "integrations/mcp_server/", "schedule/",
    "scripts/", "skills/", "templates/", "tests/", "tools/",
)
DOC_FILES = {
    "CONVENTIONS.md", "MCP-PILOT.md", "OPERATIONS.md", "PILOT.md", "SUPPORT.md",
    "WALKTHROUGH.md", "architecture.md", "audience-levels.md", "feedback.md",
    "scheduling.md", "telegram-commands.md", "telegram-multiproject.md", "updating.md",
}
CONFIG_FILES = {
    ".env.example", "README.md", "agents.yaml", "channels.yaml",
    "codex-profiles.example.toml", "glossary.yaml", "research.yaml", "schedule.yaml",
    "search.yaml", "sources.example-starter.md", "sources.yaml", "tags.yaml",
    "topics.example-starter.md", "topics.yaml",
}
BRAIN_FILES = {
    "INDEX.md", "README.md", "author-template.md", "concept-template.md",
    "concepts.base", "concepts/example-concept-a.md", "concepts/example-concept-b.md",
    "lesson-template.md", "lessons.base", "lessons/README.md",
    "playbook-template.md", "playbooks.base", "playbooks/README.md",
}
SOURCE_FILES = {"always-volatile-domains.example.md", "trusted-registry.example.md"}
CLAUDE_AGENT_FILES = {
    "README.md", "collector.md", "critic.md", "curator.md", "deliverer.md",
    "digest-maker.md", "synthesizer.md",
}
EXCLUDED_FILES = {
    ".claude/settings.json", ".claude/agents/security-gate-reviewer.md",
    "RESUME.md", "docs/PUBLIC_RELEASE_PREP.md", "docs/product-audit-2026-07-05.md",
    "docs/BACKLOG.md", "docs/adr/0024-scholarly-author-ingestion.md",
}
EXCLUDED_PREFIXES = (
    ".planning/", "planning/", "docs/decks/", "docs/private-history/", "docs/publications/",
    "skills/release/",
)
REQUIRED_FILES = {
    ".gitignore", ".github/workflows/ci.yml", "AGENTS.md", "CHANGELOG.md",
    "DEVELOPING.md", "LICENSE", "README.md", "config/.env.example",
    "config/channels.yaml", "config/sources.yaml", "config/topics.yaml",
    "brain/INDEX.md", "brain/concepts/example-concept-a.md", "pipeline/README.md",
    "scripts/collect.py", "tests/test_dist.py", "tools/export_public.py",
}

# These files are changed by a configured installation. Explicit hashes keep a
# maintainer from accidentally exporting personal settings or a modified MOC.
# Update a hash only after inspecting the new seed value in a release review.
SEED_SHA256: dict[str, str] = {
    "brain/README.md": "8e1f98f5311121b39858b4a4d9e7aedd11778178490240911128e6f9a6fc9386",
    "brain/author-template.md": "10a74f45ecc4352739b3520a1ebee92a8a4082a7587eb729a53b9247d1d29702",
    "brain/concept-template.md": "eec6131aa8e8472f4937d27d95af7beffee8ded7dc813c813cb901c0b89572f1",
    "brain/concepts.base": "ec7cea85ccd0eadc5fe488147049b00d2b69cb58560f7e1cb1ce6d9b32972c93",
    "brain/concepts/example-concept-a.md": "afd2ce562f1dd3126cd998d7b8527bd855569145479488ad43f917f3c037b65a",
    "brain/concepts/example-concept-b.md": "71ea59409de598d1d96bc161c724b5dbc53c4f7ac554e1150b3d4003376ed11d",
    "config/channels.yaml": "8d19067568eb7736ba1bf0999ed3061c062e8b99fa4a57d3166301e70fab1a98",
    "brain/lesson-template.md": "a011e6d038ad7458cf87e064188b613fae747034bbcb6e3021beffe934a187b2",
    "brain/lessons.base": "789d973583a0681e7ace53e8df0f77316674f5619c15676da85e05802042d795",
    "brain/lessons/README.md": "feae0090e0832ba935d638a4fb6028494f717a7647d64ba096cec4230081f25d",
    "brain/playbook-template.md": "76e75a4f3a81b7ef786bbb1b2cc5deaac898c5d2db1cea7bc4ca042d3243699f",
    "brain/playbooks.base": "8fc242bc42c77ddd2eeab3104f86ffd42d9ddeff9cb3131acc9255986bd57ec1",
    "brain/playbooks/README.md": "08165be75dbf86d5e92925af4fbd6206ed54659fac5b44194c50a3277e6259eb",
    "config/.env.example": "84fe6cdcafa3e5770c8169eea6d84da60d696a923d9704fe44d4924e94a5e79d",
    "config/README.md": "2f0be117f68f36e975c020d4af95799cdc9a78161df5f0aad560ce13e09a1292",
    "config/agents.yaml": "afb73a4597abdd3345be55b79061e14d3b6910cd6101494343fadcec6aa6e186",
    "config/codex-profiles.example.toml": "21da9193e044b518a957ddb02d38d6de882710a34bec71df7110439d97055323",
    "config/schedule.yaml": "ae69d6172eae29ffea0d77b54b84daf21453557d71581ec85aacc70b3b28afdb",
    "config/sources.yaml": "732132c707fa17755c72f8aa5fbc5acaf032032f4855428248c48dfcfdffcd3c",
    "config/topics.yaml": "e612557c42e411bdbff6c7a4319de39744351473b3a889f16711ddd454a48908",
    "config/tags.yaml": "74c13cf6864e29342c97b325c2f57b047ae72b15750610feb76519d8c5118a23",
    "config/glossary.yaml": "060d32fba731a35033cefe1bf409cbccec11012fb6a53929f3ce4c086734f509",
    "config/search.yaml": "cbbd5e93ed6f0ee11cc1b9d4be79f9c4db64c5df50cd3dd0000e8ba687d46a28",
    "config/research.yaml": "459bfda303670b254e0fb48b8a71758d07cba0aafa47bfc1555439959dcdf456",
    "config/sources.example-starter.md": "d70bc51a0784d88acd4ba5aa10a0c266ba7f928428984a71fef1d3d17ef77e46",
    "config/topics.example-starter.md": "b6d47dd654baa659af37e3f379879739bd269155a20040459137371583533355",
    "brain/INDEX.md": "047fd63cacbbfc969b5f176d421ea1e7f956886bd1be7456fbf3032fbc56e153",
}

_NAME_PATTERNS = (
    re.compile(r"ari[\s._-]*st(?:ek|ech)", re.IGNORECASE),
    re.compile(r"ar[\s._-]*st[\s._-]*k", re.IGNORECASE),
    re.compile(r"арис[\s._-]*т(?:ек|ех)", re.IGNORECASE),
)
_PERSONAL_PATH = re.compile(
    r"/Users/(?!\.\.\.)(?:[A-Za-z0-9._-]{2,})|"
    r"[A-Za-z]:\\Users\\[A-Za-z0-9._-]{2,}"
)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@([\w.-]+\.[A-Za-z]{2,})")
# A few older test fixtures use short, non-personal domains. They are exact
# allowlist entries; any other address still stops the export for review.
_EXAMPLE_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "ex.com", "bar.com", "b.com"}
_CREDENTIAL_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}"),
    re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}"),
)
_PRIVATE_KEY_MARKERS = ("-----BEGIN " + "PRIVATE KEY-----", "-----BEGIN RSA " + "PRIVATE KEY-----")


def classify(path: str) -> str:
    """Return include/exclude, or raise for a new path needing review."""
    if path in EXCLUDED_FILES or any(path.startswith(p) for p in EXCLUDED_PREFIXES):
        return "exclude"
    if path in ROOT_FILES or any(path.startswith(p) for p in ALLOWED_PREFIXES):
        if path.startswith(".claude/agents/"):
            return "include" if path.removeprefix(".claude/agents/") in CLAUDE_AGENT_FILES else "review"
        return "include"
    for prefix, allowed in (
        ("docs/", DOC_FILES), ("config/", CONFIG_FILES),
        ("brain/", BRAIN_FILES), ("sources/", SOURCE_FILES),
    ):
        if path.startswith(prefix):
            return "include" if path.removeprefix(prefix) in allowed else "review"
    if path == "pipeline/README.md":
        return "include"
    return "review"


def content_issues(path: str, data: bytes) -> list[str]:
    try:
        body = data.decode("utf-8")
    except UnicodeDecodeError:
        return []  # binary assets get separate provenance review
    issues: list[str] = []
    if any(pattern.search(body) for pattern in _NAME_PATTERNS):
        issues.append("internal name")
    if _PERSONAL_PATH.search(body):
        issues.append("absolute personal path")
    for domain in _EMAIL.findall(body):
        if domain.lower() not in _EXAMPLE_EMAIL_DOMAINS:
            issues.append("non-example email address")
            break
    if any(pattern.search(body) for pattern in _CREDENTIAL_PATTERNS):
        issues.append("credential-shaped value")
    if any(marker in body for marker in _PRIVATE_KEY_MARKERS):
        issues.append("private key block")
    return issues


def git_bytes(*args: str) -> bytes:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("Git is required for a committed public export")
    # Fixed Git executable and argv list; no shell interpretation of user input.
    return subprocess.run(  # nosec B603
        [git, *args], cwd=ROOT, check=True, capture_output=True
    ).stdout


def committed_blobs(commit: str) -> dict[str, tuple[bytes, int]]:
    blobs: dict[str, tuple[bytes, int]] = {}
    for entry in git_bytes("ls-tree", "-r", "-z", commit).split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError(f"non-regular tracked entry requires review: {path}")
        blobs[path] = (git_bytes("cat-file", "blob", oid), 0o755 if mode == "100755" else 0o644)
    return blobs


def select_public(blobs: dict[str, tuple[bytes, int]]) -> dict[str, tuple[bytes, int]]:
    review = sorted(path for path in blobs if classify(path) == "review")
    if review:
        raise ValueError("classify these tracked paths before export: " + ", ".join(review))
    selected = {path: data for path, data in blobs.items() if classify(path) == "include"}
    missing = REQUIRED_FILES - selected.keys()
    if missing:
        raise ValueError("public snapshot missing required files: " + ", ".join(sorted(missing)))
    seed_paths = {path for path in selected if path.startswith(("config/", "brain/"))}
    if seed_paths != SEED_SHA256.keys():
        raise ValueError("review public seed coverage: " + ", ".join(sorted(seed_paths ^ SEED_SHA256.keys())))
    for path, expected in SEED_SHA256.items():
        if hashlib.sha256(selected[path][0]).hexdigest() != expected:
            raise ValueError(f"review changed public seed before export: {path}")
    problems = [
        f"{path}: {issue}"
        for path, (data, _) in selected.items()
        for issue in content_issues(path, data)
    ]
    if problems:
        raise ValueError("public content review failed: " + ", ".join(problems))
    return selected


def require_public_repository(blobs: dict[str, tuple[bytes, int]]) -> None:
    """Keep every committed path inside the reviewed public source tree."""
    selected = select_public(blobs)
    excluded = sorted(blobs.keys() - selected.keys())
    if excluded:
        raise ValueError("private paths are tracked in this repository: " + ", ".join(excluded))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path, help="empty output directory")
    action.add_argument(
        "--check-in-place", action="store_true",
        help="fail if HEAD tracks anything outside the reviewed public source tree",
    )
    parser.add_argument("--ref", default="HEAD", help="committed Git revision (default HEAD)")
    args = parser.parse_args()
    commit = git_bytes("rev-parse", "--verify", f"{args.ref}^{{commit}}").decode().strip()
    blobs = committed_blobs(commit)
    if args.check_in_place:
        require_public_repository(blobs)
        print(f"public repository check passed: {len(blobs)} files from {commit[:12]}")
        return 0
    if args.output is None:
        parser.error("--output is required for an export")
    output = args.output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("output path must be an empty directory")
    selected = select_public(blobs)
    output.mkdir(parents=True, exist_ok=True)
    for relative, (data, mode) in selected.items():
        dest = output / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        dest.chmod(mode)
    print(f"public source snapshot: {len(selected)} files from {commit[:12]} → {output}")
    print("No Git history was copied. Inspect, scan, and test before creating a public repo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
