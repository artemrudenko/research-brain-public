from __future__ import annotations

from pathlib import Path
from types import ModuleType

from scripts.config_validation.yaml_helpers import get_path, load_yaml_mapping

SCHEDULE_REQUIRED = (
    "collect.cron",
    "collect.max_articles_per_topic",
    "digest.cron",
    "digest.lookback_days",
)

SCHEDULE_OPTIONAL_INT = (
    "curate.min_text_chars",
    "synthesis.min_sources_per_topic",
    "daily_digest.lookback_days",
)

SCHEDULE_OPTIONAL_BLOCKS = {
    "curate": ("curate.cron", "curate.min_text_chars"),
    "synthesis": ("synthesis.cron", "synthesis.min_sources_per_topic"),
    "daily_digest": ("daily_digest.cron", "daily_digest.lookback_days"),
    "weekly_trends": ("weekly_trends.cron",),
}

SCHEDULE_POSITIVE_INT = (
    "collect.max_articles_per_topic",
    "collect.candidate_pool_per_topic",
    "digest.lookback_days",
    "synthesis.min_sources_per_topic",
    "curate.min_text_chars",
    "daily_digest.lookback_days",
)

CRON_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def cron_field_ok(field: str, low: int, high: int) -> bool:
    """True if a single cron field is syntactically valid for its range."""
    for part in field.split(","):
        if not part:
            return False
        value, sep, step = part.partition("/")
        if sep == "/" and (not step.isdigit() or int(step) < 1):
            return False
        if value == "*":
            continue
        bounds = value.split("-")
        if len(bounds) > 2:
            return False
        nums = []
        for token in bounds:
            if not token.lstrip("-").isdigit():
                return False
            num = int(token)
            if num < low or num > high:
                return False
            nums.append(num)
        if len(nums) == 2 and nums[0] > nums[1]:
            return False
    return True


def is_valid_cron(expr: str) -> bool:
    """True if `expr` is a basic 5-field cron expression with in-range fields."""
    if not isinstance(expr, str):
        return False
    fields = expr.split()
    if len(fields) != 5:
        return False
    return all(
        cron_field_ok(field, low, high)
        for field, (low, high) in zip(fields, CRON_FIELD_RANGES, strict=True)
    )


def is_valid_timezone(name: str) -> bool:
    """True if `name` is a known IANA timezone.

    Fails OPEN when the tz database itself is unavailable: no `zoneinfo` module, or the
    module is present but no tz data is installed (native Windows without the `tzdata`
    package — which is not a runtime dependency). In that state `available_timezones()`
    is empty and `ZoneInfo(...)` raises for every name including the shipped default
    "UTC"; we cannot tell a valid zone from an invalid one, so we must not block the
    documented install/validation path on a supported platform.
    """
    try:
        from zoneinfo import ZoneInfo, available_timezones
    except ImportError:
        return True
    zones = available_timezones()
    if not zones:
        return True  # no tz database installed → unverifiable, don't block
    if name in zones:
        return True
    try:
        ZoneInfo(name)
    except Exception:  # noqa: BLE001
        return False
    return True


def validate_schedule(path: Path, yaml: ModuleType) -> list[str]:
    """Return a list of error strings for schedule.yaml."""
    errors, data = load_yaml_mapping(path, yaml)
    if errors or data is None:
        return errors

    for dotted in SCHEDULE_REQUIRED:
        found, _ = get_path(data, dotted)
        if not found:
            errors.append(f"{path.name}: missing required key `{dotted}`")

    for dotted in (
        "collect.max_articles_per_topic",
        "collect.candidate_pool_per_topic",
        "digest.lookback_days",
    ):
        found, value = get_path(data, dotted)
        if found and not isinstance(value, int):
            errors.append(f"{path.name}: `{dotted}` must be an integer")

    for block, required_keys in SCHEDULE_OPTIONAL_BLOCKS.items():
        block_found, _ = get_path(data, block)
        if not block_found:
            continue
        for dotted in required_keys:
            found, _ = get_path(data, dotted)
            if not found:
                errors.append(f"{path.name}: missing required key `{dotted}`")

    for dotted in SCHEDULE_OPTIONAL_INT:
        found, value = get_path(data, dotted)
        if found and not isinstance(value, int):
            errors.append(f"{path.name}: `{dotted}` must be an integer")

    for dotted in SCHEDULE_POSITIVE_INT:
        found, value = get_path(data, dotted)
        if found and isinstance(value, int) and not isinstance(value, bool) and value <= 0:
            errors.append(f"{path.name}: `{dotted}` must be a positive integer")

    for block in ("collect", "curate", "synthesis", "digest", "daily_digest", "weekly_trends"):
        found, value = get_path(data, f"{block}.cron")
        if found and (not isinstance(value, str) or not is_valid_cron(value)):
            errors.append(
                f"{path.name}: `{block}.cron` is not a valid 5-field cron "
                f"expression: {value!r}"
            )

    found, value = get_path(data, "timezone")
    if found:
        if not isinstance(value, str):
            errors.append(f"{path.name}: `timezone` must be a string")
        elif not is_valid_timezone(value):
            errors.append(
                f"{path.name}: `timezone` is not a known IANA zone: {value!r}"
            )
    return errors


__all__ = [
    "CRON_FIELD_RANGES",
    "SCHEDULE_OPTIONAL_BLOCKS",
    "SCHEDULE_OPTIONAL_INT",
    "SCHEDULE_POSITIVE_INT",
    "SCHEDULE_REQUIRED",
    "cron_field_ok",
    "is_valid_cron",
    "is_valid_timezone",
    "validate_schedule",
]
