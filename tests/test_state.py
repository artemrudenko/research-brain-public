"""test_state.py — the runtime-state path resolver (scripts/state.py).

Covers the single env-driven relocation contract: when
`RESEARCH_BRAIN_STATE_DIR` is UNSET, runtime-state paths resolve EXACTLY where
they live in-repo (zero behavior change); when SET, they relocate under the
state dir, preserving their substructure relative to the project root — so a
persistent volume survives a clone / redeploy / state-wipe.

Hermetic: every test sets or clears the env explicitly via monkeypatch, so a
developer who has `RESEARCH_BRAIN_STATE_DIR` exported in their shell still sees
these pass.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import state  # noqa: E402

_ENV = "RESEARCH_BRAIN_STATE_DIR"


@pytest.fixture(autouse=True)
def _clear_state_env(monkeypatch):
    """Default every test to env-UNSET so an exported shell value can't leak in.

    Individual tests that need the relocated branch re-set the var explicitly.
    """
    monkeypatch.delenv(_ENV, raising=False)


# --------------------------------------------------------------------------- #
# env UNSET -> identity (the default, zero-behavior-change path)
# --------------------------------------------------------------------------- #


def test_state_root_unset_returns_in_repo_default_unchanged(tmp_path):
    in_repo = tmp_path / "pipeline" / "3-synthesis" / ".delivered"
    assert state.state_root(in_repo) == in_repo


def test_state_root_unset_ignores_project_root(tmp_path):
    # Even when a project_root is passed, env-unset is a pure identity.
    in_repo = tmp_path / "pipeline" / ".health"
    assert state.state_root(in_repo, project_root=tmp_path) == in_repo


# --------------------------------------------------------------------------- #
# env SET -> relocate under the state dir, preserving the relative substructure
# --------------------------------------------------------------------------- #


def test_state_root_set_relocates_preserving_substructure(tmp_path, monkeypatch):
    project_root = tmp_path / "repo"
    state_dir = tmp_path / "persistent"
    monkeypatch.setenv(_ENV, str(state_dir))
    in_repo = project_root / "pipeline" / "3-synthesis" / ".delivered"
    relocated = state.state_root(in_repo, project_root=project_root)
    # The path under the project root is preserved verbatim under the state dir.
    assert relocated == state_dir / "pipeline" / "3-synthesis" / ".delivered"


def test_state_root_set_relocates_health_dir(tmp_path, monkeypatch):
    project_root = tmp_path / "repo"
    state_dir = tmp_path / "vol"
    monkeypatch.setenv(_ENV, str(state_dir))
    in_repo = project_root / "pipeline" / ".health"
    assert state.state_root(in_repo, project_root=project_root) == (
        state_dir / "pipeline" / ".health"
    )


def test_state_root_set_relocates_freshness_sidecar(tmp_path, monkeypatch):
    project_root = tmp_path / "repo"
    state_dir = tmp_path / "vol"
    monkeypatch.setenv(_ENV, str(state_dir))
    in_repo = project_root / "pipeline" / "3-synthesis" / "ai-agents" / ".synthesis-meta.json"
    assert state.state_root(in_repo, project_root=project_root) == (
        state_dir / "pipeline" / "3-synthesis" / "ai-agents" / ".synthesis-meta.json"
    )


def test_state_root_set_expands_user_in_state_dir(tmp_path, monkeypatch):
    # A `~`-prefixed state dir is expanded so a deployment can use `~/state`.
    project_root = tmp_path / "repo"
    monkeypatch.setenv(_ENV, "~/rb-state")
    in_repo = project_root / "pipeline" / ".health"
    relocated = state.state_root(in_repo, project_root=project_root)
    assert relocated == Path.home() / "rb-state" / "pipeline" / ".health"


def test_state_root_blank_env_is_treated_as_unset(tmp_path, monkeypatch):
    # A blank / whitespace-only value must not relocate to the project's own root
    # (that would silently move state); treat it as unset (identity).
    monkeypatch.setenv(_ENV, "   ")
    in_repo = tmp_path / "pipeline" / ".health"
    assert state.state_root(in_repo, project_root=tmp_path) == in_repo


def test_state_root_set_default_project_root_is_repo_root(monkeypatch, tmp_path):
    # With no explicit project_root, the resolver uses the package's repo root, so
    # a real in-repo default (under that root) relocates cleanly.
    state_dir = tmp_path / "vol"
    monkeypatch.setenv(_ENV, str(state_dir))
    in_repo = state.PROJECT_ROOT / "pipeline" / ".health"
    assert state.state_root(in_repo) == state_dir / "pipeline" / ".health"


def test_state_root_path_outside_project_root_relocates_by_name(tmp_path, monkeypatch):
    # Defensive: a path that is NOT under the project root can't be made relative,
    # so it relocates by its final component rather than raising.
    project_root = tmp_path / "repo"
    state_dir = tmp_path / "vol"
    monkeypatch.setenv(_ENV, str(state_dir))
    outside = tmp_path / "elsewhere" / "weird.json"
    relocated = state.state_root(outside, project_root=project_root)
    assert relocated == state_dir / "weird.json"
