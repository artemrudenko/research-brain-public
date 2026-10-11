"""Config and secret helpers for delivery."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """Raised for an unrecoverable delivery config or secret problem."""


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse `KEY=VALUE` lines from a .env file body."""
    parsed: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        parsed[key] = value
    return parsed


def load_dotenv(env_path: Path) -> None:
    """Load `env_path` into os.environ without overriding already-set vars."""
    if not env_path.exists():
        return
    for key, value in parse_dotenv(env_path.read_text(encoding="utf-8")).items():
        os.environ.setdefault(key, value)


def require_yaml() -> Any:  # Any: optional-dependency boundary (PyYAML)
    """Import PyYAML lazily; raise a clear error if it is missing."""
    try:
        import yaml  # noqa: PLC0415 — lazy import is intentional (optional dep)
    except ImportError as error:
        raise ConfigError(
            "PyYAML is required to read config/channels.yaml. "
            "Install it with: pip install pyyaml"
        ) from error
    return yaml


def load_config(path: Path) -> dict[str, object]:
    """Load and return the `delivery` mapping from a channels.yaml file."""
    if not path.exists():
        raise ConfigError(f"channels config not found: {path}")
    yaml = require_yaml()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise ConfigError(f"malformed YAML in {path}: {error}") from error
    delivery = raw.get("delivery")
    if not isinstance(delivery, dict):
        raise ConfigError(f"missing top-level 'delivery:' mapping in {path}")
    return delivery


def env_or_fail(channel: str, env_var: str) -> str:
    """Read a required env var; raise when it is absent or empty."""
    value = os.environ.get(env_var, "")
    if not value.strip():
        raise ConfigError(
            f"[{channel}] missing secret: set the {env_var} environment variable "
            "(see config/.env.example)."
        )
    return value


def secret_state(env_var: str) -> str:
    """Human-safe status for a secret env var."""
    value = os.environ.get(env_var, "")
    return "SET" if value.strip() else "MISSING"


__all__ = [
    "ConfigError",
    "env_or_fail",
    "load_config",
    "load_dotenv",
    "parse_dotenv",
    "require_yaml",
    "secret_state",
]
