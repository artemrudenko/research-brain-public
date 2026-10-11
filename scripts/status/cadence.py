from __future__ import annotations

import re
from pathlib import Path

from scripts._yaml import optional_yaml
from scripts.build_digest import read_lookback_days
from scripts.status.model import CadenceBlock, CadenceSummary

# Default timezone when schedule.yaml is missing/unreadable (CONVENTIONS §2.2).
DEFAULT_TIMEZONE = "UTC"

# Blocks rendered, in pipeline order, with a friendly label for each.
_BLOCK_ORDER = ("collect", "curate", "synthesis", "digest", "daily_digest", "weekly_trends")
_BLOCK_LABELS = {
    "collect": "Collect new articles from your sources",
    "curate": "Curate collected articles into the curated stage",
    "synthesis": "Synthesize curated material into the knowledge base",
    "digest": "Build and deliver the weekly digest",
    # Opt-in cadences (ADR 0016 / 0017): omitted from /status when not configured.
    "daily_digest": "Build and deliver the daily inflow digest",
    "weekly_trends": "Build and deliver the weekly trends report",
}

# Day-of-week names for cron weekday rendering (0/7 = Sunday).
_WEEKDAYS = {
    "0": "Sunday",
    "1": "Monday",
    "2": "Tuesday",
    "3": "Wednesday",
    "4": "Thursday",
    "5": "Friday",
    "6": "Saturday",
    "7": "Sunday",
}


def describe_cron(cron: str) -> str:
    """Render a 5-field cron string as a short plain-language cadence phrase."""
    fields = cron.split()
    if len(fields) != 5:
        return cron  # not a standard 5-field cron — show it verbatim
    minute, hour, dom, _month, dow = fields

    time_str = _format_time(minute, hour)

    # Weekly: a concrete weekday is set (and not an every-N day-of-month step).
    if dow in _WEEKDAYS and dom in ("*", "?"):
        return f"every {_WEEKDAYS[dow]}{_at(time_str)}"

    # Every-N-days: day-of-month is a `*/N` step.
    step = re.fullmatch(r"\*/(\d+)", dom)
    if step:
        n = step.group(1)
        unit = "day" if n == "1" else "days"
        return f"every {n} {unit}{_at(time_str)}"

    # Sub-daily: a `*/N` step in the minute or hour field (must be checked BEFORE
    # the plain-daily fallback, which would otherwise mislabel `*/15 * * * *` as
    # "every day").
    min_step = re.fullmatch(r"\*/(\d+)", minute)
    if min_step and hour == "*":
        n = min_step.group(1)
        return f"every {n} minute{'' if n == '1' else 's'}"
    hour_step = re.fullmatch(r"\*/(\d+)", hour)
    if hour_step and minute in ("0", "*"):
        n = hour_step.group(1)
        return f"every {n} hour{'' if n == '1' else 's'}"

    # Plain daily.
    if dom in ("*", "?") and dow in ("*", "?"):
        return f"every day{_at(time_str)}"

    return cron


def _format_time(minute: str, hour: str) -> str:
    """Render minute/hour cron fields as `HH:MM`, or "" when not both fixed."""
    if minute.isdigit() and hour.isdigit():
        return f"{int(hour):02d}:{int(minute):02d}"
    return ""


def _at(time_str: str) -> str:
    """Render a trailing ` at HH:MM` clause, or empty when the time is unknown."""
    return f" at {time_str}" if time_str else ""


def cadence(*, root: Path) -> CadenceSummary:
    """Parse config/schedule.yaml into a plain-language cadence summary."""
    path = root / "config" / "schedule.yaml"
    raw = _load_schedule(path)

    blocks: list[CadenceBlock] = []
    for name in _BLOCK_ORDER:
        block = raw.get(name) if isinstance(raw, dict) else None
        if not isinstance(block, dict):
            continue
        cron = str(block.get("cron", "")).strip()
        if not cron:
            continue
        label = _BLOCK_LABELS[name]
        blocks.append(
            CadenceBlock(name=name, cron=cron, description=f"{label} {describe_cron(cron)}")
        )

    timezone = DEFAULT_TIMEZONE
    if isinstance(raw, dict):
        tz = raw.get("timezone")
        if isinstance(tz, str) and tz.strip():
            timezone = tz.strip()

    return CadenceSummary(
        blocks=blocks,
        timezone=timezone,
        lookback_days=read_lookback_days(path),
    )


def _load_schedule(path: Path) -> dict[str, object]:
    """Load schedule.yaml into a dict; empty dict on any failure (soft-skip)."""
    if not path.exists():
        return {}
    yaml = optional_yaml()
    if yaml is None:
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — any parse error -> empty/default
        return {}
    return loaded if isinstance(loaded, dict) else {}


__all__ = [
    "DEFAULT_TIMEZONE",
    "_BLOCK_LABELS",
    "_BLOCK_ORDER",
    "_WEEKDAYS",
    "_at",
    "_format_time",
    "_load_schedule",
    "cadence",
    "describe_cron",
]
