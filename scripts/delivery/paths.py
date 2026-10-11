"""Default path helpers for the delivery facade."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def channels_config(project_root: Path) -> Path:
    """Default channels.yaml path for headless delivery."""
    return project_root / "config" / "channels.yaml"


def env_file(project_root: Path) -> Path:
    """Default optional .env file loaded before delivery."""
    return project_root / "config" / ".env"


def receipt_dir(
    project_root: Path,
    *,
    state_root: Callable[[Path], Path],
) -> Path:
    """Default receipt directory, resolved lazily through the state resolver."""
    return state_root(project_root / "pipeline" / "3-synthesis" / ".delivered")


__all__ = [
    "channels_config",
    "env_file",
    "receipt_dir",
]
