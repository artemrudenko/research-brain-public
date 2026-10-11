"""Schedule lookback + delivery-audience readers for digest scans."""

from __future__ import annotations

import re
from pathlib import Path

from scripts._yaml import optional_yaml

DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_DAILY_LOOKBACK_DAYS = 1
DEFAULT_TECHNICAL_LEVEL = "balanced"
VALID_TECHNICAL_LEVELS = ("technical", "balanced", "non-technical")


def read_lookback_days(schedule_path: Path) -> int:
    """Read `digest.lookback_days` from schedule.yaml; default if unreadable."""
    if not schedule_path.exists():
        return DEFAULT_LOOKBACK_DAYS
    yaml = optional_yaml()
    if yaml is None:
        return read_lookback_days_fallback(schedule_path)
    try:
        raw = yaml.safe_load(schedule_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — any parse error -> safe default
        return DEFAULT_LOOKBACK_DAYS
    digest = raw.get("digest") if isinstance(raw, dict) else None
    if isinstance(digest, dict):
        value = digest.get("lookback_days")
        if isinstance(value, int) and value > 0:
            return value
    return DEFAULT_LOOKBACK_DAYS


def read_lookback_days_fallback(schedule_path: Path) -> int:
    """Regex `lookback_days` out of schedule.yaml when PyYAML is unavailable."""
    match = re.search(
        r"^\s*lookback_days\s*:\s*(\d+)",
        schedule_path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match:
        value = int(match.group(1))
        if value > 0:
            return value
    return DEFAULT_LOOKBACK_DAYS


def read_daily_lookback_days(schedule_path: Path) -> int:
    """Read `daily_digest.lookback_days` from schedule.yaml; default 1."""
    if not schedule_path.exists():
        return DEFAULT_DAILY_LOOKBACK_DAYS
    yaml = optional_yaml()
    if yaml is None:
        return DEFAULT_DAILY_LOOKBACK_DAYS
    try:
        raw = yaml.safe_load(schedule_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — any parse error -> safe default
        return DEFAULT_DAILY_LOOKBACK_DAYS
    block = raw.get("daily_digest") if isinstance(raw, dict) else None
    if isinstance(block, dict):
        value = block.get("lookback_days")
        if isinstance(value, int) and value > 0:
            return value
    return DEFAULT_DAILY_LOOKBACK_DAYS


def read_technical_level(channels_path: Path) -> str:
    """Read `delivery.technical_level` from channels.yaml; default when unreadable.

    Only the documented enum values pass through — anything else (missing file,
    malformed YAML, unknown level) falls back to the default so the digest build
    never fails on a config problem the validator reports elsewhere.
    """
    if not channels_path.exists():
        return DEFAULT_TECHNICAL_LEVEL
    yaml = optional_yaml()
    if yaml is None:
        return read_technical_level_fallback(channels_path)
    try:
        raw = yaml.safe_load(channels_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — any parse error -> safe default
        return DEFAULT_TECHNICAL_LEVEL
    delivery = raw.get("delivery") if isinstance(raw, dict) else None
    if isinstance(delivery, dict):
        value = delivery.get("technical_level")
        if isinstance(value, str) and value in VALID_TECHNICAL_LEVELS:
            return value
    return DEFAULT_TECHNICAL_LEVEL


def read_technical_level_fallback(channels_path: Path) -> str:
    """Regex `technical_level` out of channels.yaml when PyYAML is unavailable."""
    match = re.search(
        r"^\s*technical_level\s*:\s*([a-z-]+)",
        channels_path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match and match.group(1) in VALID_TECHNICAL_LEVELS:
        return match.group(1)
    return DEFAULT_TECHNICAL_LEVEL


DEFAULT_LANGUAGE = "en"


def read_language(channels_path: Path) -> str:
    """Read `delivery.language` from channels.yaml; 'en' when unreadable.

    The raw configured token is returned (lowercased) — the chrome string
    tables (`scripts.digest.strings.resolve`) decide whether a language has a
    localized chrome or falls back to en. Mirrors `read_technical_level`,
    including the no-PyYAML regex fallback.
    """
    if not channels_path.exists():
        return DEFAULT_LANGUAGE
    yaml = optional_yaml()
    if yaml is None:
        return read_language_fallback(channels_path)
    try:
        raw = yaml.safe_load(channels_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — any parse error -> safe default
        return DEFAULT_LANGUAGE
    delivery = raw.get("delivery") if isinstance(raw, dict) else None
    if isinstance(delivery, dict):
        value = delivery.get("language")
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return DEFAULT_LANGUAGE


def read_language_fallback(channels_path: Path) -> str:
    """Regex `language` out of channels.yaml when PyYAML is unavailable."""
    match = re.search(
        r"^\s*language\s*:\s*([A-Za-z-]+)",
        channels_path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return match.group(1).lower() if match else DEFAULT_LANGUAGE


__all__ = [
    "DEFAULT_DAILY_LOOKBACK_DAYS",
    "DEFAULT_LANGUAGE",
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_TECHNICAL_LEVEL",
    "VALID_TECHNICAL_LEVELS",
    "read_daily_lookback_days",
    "read_language",
    "read_language_fallback",
    "read_lookback_days",
    "read_lookback_days_fallback",
    "read_technical_level",
    "read_technical_level_fallback",
]
