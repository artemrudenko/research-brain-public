#!/usr/bin/env python3
"""
gen_agents.py — render the role spec into per-runtime agent artifacts.

`config/agents.yaml` is the single source of truth for the pipeline role agents
(model tier + tool allowlist + system prompt). This script renders it into the
two runtime-native formats so they can never drift:

  * `.claude/agents/<role>.md`            — Claude Code / Cowork subagents
                                             (frontmatter `model` + `tools` allowlist).
  * `config/codex-profiles.example.toml`  — Codex per-role model + reasoning-effort
                                             tiering (Codex has no per-profile tool
                                             allowlist, so this is the cost lever only).

Usage:
    python3 scripts/gen_agents.py            # regenerate the artifacts
    python3 scripts/gen_agents.py --check     # exit 1 if artifacts drift from the spec

stdlib + pyyaml only (AGENTS.md runtime rule). See ADR 0015 and `.claude/agents/README.md`.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml

# Claude Code requires subagent names to be lowercase letters/digits + hyphens.
_NAME_RE = re.compile(r"[a-z][a-z0-9-]*")

_GENERATED_NOTE = (
    "<!-- Generated from config/agents.yaml by scripts/gen_agents.py — "
    "edit the spec, then regenerate; do not hand-edit. -->"
)

_CODEX_HEADER = """\
# config/codex-profiles.example.toml — GENERATED from config/agents.yaml by
# scripts/gen_agents.py. Do not hand-edit; edit the spec and regenerate.
#
# Maps the pipeline roles onto Codex per-profile MODEL + REASONING-EFFORT tiering
# (the cost lever). Codex has NO per-profile tool/MCP allowlist, so capability
# isolation on Codex is the S1-S9 sanitize gate, not the profile (moot for
# delivery — on Codex that is the headless deliver.py script, not an MCP tool).
#
# Apply: put the BASE block in ~/.codex/config.toml. Recent Codex selects a profile
# via `codex exec -p <name>`, layering $CODEX_HOME/<name>.config.toml on the base,
# so split each [profiles.rb-*] block into its own ~/.codex/rb-*.config.toml file
# (older Codex reads the [profiles.*] blocks straight from config.toml). Whole run
# at one tier: CODEX_PROFILE=rb-synthesizer schedule/codex-run.sh. Per-step tiering:
# run the component cron jobs, each `codex exec -p rb-<role>`. Full how-to:
# docs/scheduling.md "C. Codex". Model IDs are placeholders — set them in
# config/agents.yaml to models your account exposes (verify with `codex`).
"""


def load_spec(path: Path) -> dict[str, Any]:
    """Load and lightly validate the role spec."""
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or "roles" not in spec or "codex" not in spec:
        raise ValueError(f"{path}: spec must be a mapping with 'roles' and 'codex' keys")
    return spec


def render_claude_agent(name: str, spec: dict[str, Any]) -> str:
    """Render one `.claude/agents/<name>.md` file (frontmatter + body)."""
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"role name {name!r} is not a valid Claude Code subagent name "
                         "(lowercase letters/digits and hyphens only)")
    role = spec["roles"][name]
    # safe_dump (sort_keys=False) keeps key order and escapes the description correctly.
    frontmatter = yaml.safe_dump(
        {
            "name": name,
            "description": role["description"],
            "tools": ", ".join(role["tools"]),
            "model": role["claude_model"],
        },
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=4096,  # don't line-wrap the long description scalar
    )
    body = role["prompt"].rstrip("\n")
    return f"---\n{frontmatter}---\n\n{_GENERATED_NOTE}\n\n{body}\n"


def render_codex_toml(spec: dict[str, Any]) -> str:
    """Render the Codex profiles example (base block + one profile per role)."""
    base = spec["codex"]["base"]
    models = spec["codex"]["models"]
    lines = [
        _CODEX_HEADER.rstrip("\n"),
        "",
        f'approval_policy = "{base["approval_policy"]}"',
        f'sandbox_mode    = "{base["sandbox_mode"]}"',
        "",
        "[sandbox_workspace_write]",
        f"network_access = {'true' if base['network_access'] else 'false'}",
        "",
    ]
    for name, role in spec["roles"].items():
        model = models[role["codex_model"]]  # KeyError on an unknown alias — intentional.
        lines.append(f"[profiles.rb-{name}]")
        lines.append(f'model = "{model}"')
        lines.append(f'model_reasoning_effort = "{role["codex_effort"]}"')
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def build_targets(spec: dict[str, Any], root: Path) -> dict[Path, str]:
    """Map every output path to its rendered content."""
    root = Path(root)
    targets: dict[Path, str] = {}
    for name in spec["roles"]:
        targets[root / ".claude" / "agents" / f"{name}.md"] = render_claude_agent(name, spec)
    targets[root / "config" / "codex-profiles.example.toml"] = render_codex_toml(spec)
    return targets


def write(spec: dict[str, Any], root: Path) -> list[Path]:
    """Write every artifact to disk; return the written paths (sorted)."""
    written: list[Path] = []
    for path, content in build_targets(spec, root).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return sorted(written)


def check(spec: dict[str, Any], root: Path) -> list[Path]:
    """Return the paths whose on-disk content differs from the spec (missing counts)."""
    drifted: list[Path] = []
    for path, content in build_targets(spec, root).items():
        try:
            on_disk = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            drifted.append(path)
            continue
        if on_disk != content:
            drifted.append(path)
    return sorted(drifted)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render role agents from config/agents.yaml.")
    parser.add_argument("--check", action="store_true",
                        help="report drift and exit 1 instead of writing")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="project root (default: the repo this script lives in)")
    args = parser.parse_args(argv)

    spec = load_spec(args.root / "config" / "agents.yaml")

    if args.check:
        drifted = check(spec, args.root)
        if drifted:
            print("DRIFT: regenerate with `python3 scripts/gen_agents.py` — out of sync:")
            for p in drifted:
                print(f"  {p.relative_to(args.root)}")
            return 1
        print("OK: agent artifacts match config/agents.yaml")
        return 0

    written = write(spec, args.root)
    print(f"Wrote {len(written)} artifact(s) from config/agents.yaml:")
    for p in written:
        print(f"  {p.relative_to(args.root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
