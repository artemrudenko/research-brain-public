"""
test_gen_agents.py — the single-source role spec → per-runtime agent generator.

`config/agents.yaml` is the source of truth for the pipeline role agents (model
tier + tool allowlist + prompt). `scripts/gen_agents.py` renders it into the two
runtime-native artifacts — `.claude/agents/*.md` (Claude Code / Cowork subagents)
and `config/codex-profiles.example.toml` (Codex per-role model tiering) — so the
two formats can never drift. These tests pin the rendering and the `--check`
drift guard, and assert the committed artifacts match the committed spec.
"""
import tomllib
from pathlib import Path

import pytest
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

from scripts import gen_agents  # noqa: E402

# A tiny synthetic spec — exercises rendering without depending on the real roles.
SPEC = {
    "codex": {
        "base": {
            "approval_policy": "never",
            "sandbox_mode": "workspace-write",
            "network_access": True,
        },
        "models": {"strong": "m-strong", "cheap": "m-cheap"},
    },
    "roles": {
        "alpha": {
            "description": "Alpha role does A.",
            "tools": ["Read", "Bash", "WebSearch"],
            "claude_model": "opus",
            "codex_model": "strong",
            "codex_effort": "high",
            "prompt": "You are alpha.\nDo A.",
        },
        "beta": {
            "description": "Beta role does B.",
            "tools": ["Read", "Skill"],
            "claude_model": "haiku",
            "codex_model": "cheap",
            "codex_effort": "low",
            "prompt": "You are beta.",
        },
    },
}


def _frontmatter(text: str) -> dict:
    assert text.startswith("---\n"), "agent file must start with YAML frontmatter"
    fm = text.split("---\n", 2)[1]
    return yaml.safe_load(fm)


# --- Claude subagent rendering -------------------------------------------------

def test_claude_agent_frontmatter_carries_name_model_description():
    text = gen_agents.render_claude_agent("alpha", SPEC)
    fm = _frontmatter(text)
    assert fm["name"] == "alpha"
    assert fm["model"] == "opus"
    assert fm["description"] == "Alpha role does A."


def test_claude_agent_tools_are_comma_joined_in_spec_order():
    fm = _frontmatter(gen_agents.render_claude_agent("alpha", SPEC))
    assert fm["tools"] == "Read, Bash, WebSearch"


def test_claude_agent_body_contains_the_prompt():
    text = gen_agents.render_claude_agent("beta", SPEC)
    body = text.split("---\n", 2)[2]
    assert "You are beta." in body


def test_claude_agent_name_is_lowercase_hyphen_safe():
    # The generator must reject a role name Claude Code would refuse.
    bad = {**SPEC, "roles": {"Bad_Name": SPEC["roles"]["beta"]}}
    with pytest.raises(ValueError):
        gen_agents.render_claude_agent("Bad_Name", bad)


# --- Codex profile rendering ---------------------------------------------------

def test_codex_toml_is_parseable_with_base_and_profiles():
    data = tomllib.loads(gen_agents.render_codex_toml(SPEC))
    assert data["approval_policy"] == "never"
    assert data["sandbox_mode"] == "workspace-write"
    assert data["sandbox_workspace_write"]["network_access"] is True
    assert set(data["profiles"]) == {"rb-alpha", "rb-beta"}


def test_codex_profile_resolves_model_alias_and_effort():
    data = tomllib.loads(gen_agents.render_codex_toml(SPEC))
    assert data["profiles"]["rb-alpha"]["model"] == "m-strong"
    assert data["profiles"]["rb-alpha"]["model_reasoning_effort"] == "high"
    assert data["profiles"]["rb-beta"]["model"] == "m-cheap"
    assert data["profiles"]["rb-beta"]["model_reasoning_effort"] == "low"


def test_codex_unknown_model_alias_is_an_error():
    bad = {**SPEC, "roles": {"alpha": {**SPEC["roles"]["alpha"], "codex_model": "nope"}}}
    with pytest.raises(KeyError):
        gen_agents.render_codex_toml(bad)


# --- targets / write / check ---------------------------------------------------

def test_build_targets_covers_each_role_md_plus_one_toml(tmp_path):
    targets = gen_agents.build_targets(SPEC, tmp_path)
    rel = sorted(p.relative_to(tmp_path).as_posix() for p in targets)
    assert rel == [
        ".claude/agents/alpha.md",
        ".claude/agents/beta.md",
        "config/codex-profiles.example.toml",
    ]


def test_render_is_idempotent():
    assert gen_agents.render_claude_agent("alpha", SPEC) == gen_agents.render_claude_agent("alpha", SPEC)
    assert gen_agents.render_codex_toml(SPEC) == gen_agents.render_codex_toml(SPEC)


def test_write_then_check_reports_no_drift(tmp_path):
    written = gen_agents.write(SPEC, tmp_path)
    assert len(written) == 3
    assert gen_agents.check(SPEC, tmp_path) == []


def test_check_flags_a_drifted_file(tmp_path):
    gen_agents.write(SPEC, tmp_path)
    drifted = tmp_path / ".claude/agents/alpha.md"
    drifted.write_text(drifted.read_text() + "\nhand edit\n")
    result = gen_agents.check(SPEC, tmp_path)
    assert result == [drifted]


def test_check_flags_a_missing_file(tmp_path):
    gen_agents.write(SPEC, tmp_path)
    (tmp_path / "config/codex-profiles.example.toml").unlink()
    result = gen_agents.check(SPEC, tmp_path)
    assert (tmp_path / "config/codex-profiles.example.toml") in result


# --- committed artifacts match the committed spec (drift guard) ----------------

def test_committed_artifacts_match_the_spec():
    spec = gen_agents.load_spec(_PROJECT_ROOT / "config" / "agents.yaml")
    drifted = gen_agents.check(spec, _PROJECT_ROOT)
    assert drifted == [], (
        "regenerate with `python3 scripts/gen_agents.py` — committed agent "
        f"artifacts are out of sync with config/agents.yaml: {drifted}"
    )


def test_real_spec_has_the_six_pipeline_roles():
    spec = gen_agents.load_spec(_PROJECT_ROOT / "config" / "agents.yaml")
    assert set(spec["roles"]) == {
        "collector", "curator", "synthesizer", "critic", "digest-maker", "deliverer",
    }
    # Exactly one role carries a delivery surface posture in its prompt: deliverer.
    assert spec["roles"]["synthesizer"]["claude_model"] == "opus"
    assert spec["roles"]["deliverer"]["claude_model"] == "haiku"


def test_curator_role_reads_sanitized_and_carries_no_delivery_mcp():
    spec = gen_agents.load_spec(_PROJECT_ROOT / "config" / "agents.yaml")
    curator = spec["roles"]["curator"]
    # Curation judges untrusted article text — it must read the sanitized
    # companions, never raw bodies, and must not carry web or delivery surfaces.
    assert "sanitized" in curator["prompt"]
    assert "WebFetch" not in curator["tools"]
    assert "WebSearch" not in curator["tools"]
    assert curator["claude_model"] == "sonnet"
