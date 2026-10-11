from __future__ import annotations

import re
from pathlib import Path
from types import ModuleType

YamlMapping = dict[str, object]

# The shape a configured URL must have: plain http(s) with a host. Shared so the
# sources and authors validators agree on what counts as a URL — a value one
# accepts and the other rejects is a bug the user experiences as inconsistency.
URL_RE = re.compile(r"https?://[^\s/]+(?:/[^\s]*)?")


def url_error(where: str, key: str, value: object) -> str | None:
    """Return an error when `value` is not a plain http(s) URL, else None."""
    if not isinstance(value, str) or not URL_RE.fullmatch(value.strip()):
        return f"{where}: `{key}` must be a full http:// or https:// URL, got {value!r}"
    return None


def get_path(data: object, dotted: str) -> tuple[bool, object]:
    """Walk a dotted path through nested dicts; return (found, value)."""
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def load_yaml_mapping(path: Path, yaml: ModuleType) -> tuple[list[str], YamlMapping | None]:
    """Common YAML pre-flight: file exists, parses, top level is a mapping."""
    if not path.exists():
        return [f"{path.name}: file not found at {path}"], None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"{path.name}: YAML parse error: {exc}"], None
    if not isinstance(data, dict):
        return [f"{path.name}: top level must be a mapping/object"], None
    return [], data


def check_yaml_mapping(path: Path, yaml: ModuleType) -> list[str]:
    """Return only the YAML pre-flight errors."""
    errors, _ = load_yaml_mapping(path, yaml)
    return errors


__all__ = [
    "URL_RE",
    "YamlMapping",
    "check_yaml_mapping",
    "get_path",
    "load_yaml_mapping",
    "url_error",
]
