from __future__ import annotations

import re
from pathlib import Path
from types import ModuleType

from scripts.config_schema import EMAIL_PROVIDERS, TECHNICAL_LEVELS, TELEGRAM_TRANSPORTS
from scripts.config_validation.yaml_helpers import YamlMapping, get_path, load_yaml_mapping

CHANNELS_REQUIRED = (
    "delivery.language",
    "delivery.email.enabled",
    "delivery.email.provider",
    "delivery.email.to",
    "delivery.email.smtp.host",
    "delivery.email.smtp.port",
    "delivery.email.smtp.user",
    "delivery.email.smtp.password_env",
    "delivery.telegram.enabled",
    "delivery.telegram.transport",
    "delivery.telegram.chat_id",
    "delivery.telegram.token_env",
    "delivery.rocketchat.enabled",
    "delivery.rocketchat.webhook_url_env",
)

CHANNELS_SECRET_ENV_KEYS = (
    "delivery.email.smtp.password_env",
    "delivery.telegram.token_env",
    "delivery.rocketchat.webhook_url_env",
)

LANGUAGE_CODE = re.compile(r"^[a-z]{2,8}(-[A-Za-z0-9]+)?$")
NON_CHANNEL_DELIVERY_KEYS = frozenset(
    {"language", "technical_level", "alerts", "pre_send_review"}
)


def validate_channels(path: Path, yaml: ModuleType) -> list[str]:
    """Return a list of error strings for channels.yaml."""
    errors, data = load_yaml_mapping(path, yaml)
    if errors or data is None:
        return errors

    for dotted in CHANNELS_REQUIRED:
        found, _ = get_path(data, dotted)
        if not found:
            errors.append(f"{path.name}: missing required key `{dotted}`")

    found, value = get_path(data, "delivery.email.to")
    if found and not isinstance(value, list):
        errors.append(f"{path.name}: `delivery.email.to` must be a list")

    for dotted in (
        "delivery.email.enabled",
        "delivery.telegram.enabled",
        "delivery.rocketchat.enabled",
    ):
        found, value = get_path(data, dotted)
        if found and not isinstance(value, bool):
            errors.append(f"{path.name}: `{dotted}` must be a boolean")

    found, value = get_path(data, "delivery.email.smtp.port")
    if found and not isinstance(value, int):
        errors.append(f"{path.name}: `delivery.email.smtp.port` must be an integer")

    found, value = get_path(data, "delivery.language")
    if found and (not isinstance(value, str) or not LANGUAGE_CODE.fullmatch(value)):
        errors.append(
            f"{path.name}: `delivery.language` is not a valid language code: {value!r}"
        )

    found, value = get_path(data, "delivery.pre_send_review")
    if found and not isinstance(value, bool):
        errors.append(f"{path.name}: `delivery.pre_send_review` must be a boolean")

    errors += check_channel_enums(path, data)
    errors += check_secret_env_refs(path, data)
    errors += check_enabled_channels(path, data)
    errors += check_alerts(path, data)
    return errors


def configured_channels(data: YamlMapping) -> set[str]:
    """Names of the delivery channels actually present under `delivery:`."""
    found, delivery = get_path(data, "delivery")
    if not found or not isinstance(delivery, dict):
        return set()
    return {
        name
        for name, value in delivery.items()
        if name not in NON_CHANNEL_DELIVERY_KEYS and isinstance(value, dict)
    }


def check_alerts(path: Path, data: YamlMapping) -> list[str]:
    """Validate the opt-in `delivery.alerts` block."""
    found, alerts = get_path(data, "delivery.alerts")
    if not found:
        return []
    if not isinstance(alerts, dict):
        return [f"{path.name}: `delivery.alerts` must be a mapping"]

    errors = []
    enabled = alerts.get("enabled")
    if "enabled" in alerts and not isinstance(enabled, bool):
        errors.append(f"{path.name}: `delivery.alerts.enabled` must be a boolean")
    if enabled is True:
        channel = alerts.get("channel")
        if is_empty(channel):
            errors.append(
                f"{path.name}: `delivery.alerts` is enabled but no `channel` is set — "
                "it must name a configured channel to alert through"
            )
        elif channel not in configured_channels(data):
            errors.append(
                f"{path.name}: `delivery.alerts.channel` names an unconfigured channel: "
                f"{channel!r} (expected one of {', '.join(sorted(configured_channels(data))) or 'none'})"
            )
        else:
            _, target_enabled = get_path(data, f"delivery.{channel}.enabled")
            if target_enabled is not True:
                errors.append(
                    f"{path.name}: `delivery.alerts.channel` is {channel!r} but "
                    f"`delivery.{channel}.enabled` is not true — the alert channel must "
                    "be enabled to send through it"
                )
            elif channel == "email":
                _, provider = get_path(data, "delivery.email.provider")
                if provider != "smtp":
                    errors.append(
                        f"{path.name}: `delivery.alerts.channel` is `email` but "
                        f"`delivery.email.provider` is {provider!r} — health alerts send via "
                        "SMTP, so the email channel must use `provider: smtp`"
                    )
            elif channel == "telegram":
                _, transport = get_path(data, "delivery.telegram.transport")
                if transport != "bot-api":
                    errors.append(
                        f"{path.name}: `delivery.alerts.channel` is `telegram` but "
                        f"`delivery.telegram.transport` is {transport!r} — health alerts send "
                        "via the Bot API (headless cron has no MCP), so the telegram channel "
                        "must use `transport: bot-api`"
                    )
    return errors


def check_channel_enums(path: Path, data: YamlMapping) -> list[str]:
    """Validate delivery enum values."""
    errors = []
    found, provider = get_path(data, "delivery.email.provider")
    if found and provider not in EMAIL_PROVIDERS:
        errors.append(
            f"{path.name}: `delivery.email.provider` is not a supported value "
            f"(expected one of {', '.join(EMAIL_PROVIDERS)}): {provider!r}"
        )
    found, transport = get_path(data, "delivery.telegram.transport")
    if found and transport not in TELEGRAM_TRANSPORTS:
        errors.append(
            f"{path.name}: `delivery.telegram.transport` is not a supported value "
            f"(expected one of {', '.join(TELEGRAM_TRANSPORTS)}): {transport!r}"
        )
    found, level = get_path(data, "delivery.technical_level")
    if found and level not in TECHNICAL_LEVELS:
        errors.append(
            f"{path.name}: `delivery.technical_level` is not a supported value "
            f"(expected one of {', '.join(TECHNICAL_LEVELS)}): {level!r}"
        )
    return errors


def check_secret_env_refs(path: Path, data: YamlMapping) -> list[str]:
    """A present `*_env:` key must name a non-empty env var."""
    errors = []
    for dotted in CHANNELS_SECRET_ENV_KEYS:
        found, value = get_path(data, dotted)
        if found and is_empty(value):
            errors.append(
                f"{path.name}: `{dotted}` is present but empty — it must name an "
                "env var holding the secret (CONVENTIONS §8)"
            )
    return errors


def is_empty(value: object) -> bool:
    """True for a config value that carries no payload."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list):
        return len(value) == 0
    return False


def check_enabled_channels(path: Path, data: YamlMapping) -> list[str]:
    """An enabled delivery channel must have its required send fields non-empty."""
    errors = []

    found, enabled = get_path(data, "delivery.email.enabled")
    if found and enabled is True:
        _, to = get_path(data, "delivery.email.to")
        if is_empty(to):
            errors.append(
                f"{path.name}: email is enabled but `delivery.email.to` is empty"
            )
        _, provider = get_path(data, "delivery.email.provider")
        if provider == "smtp":
            _, host = get_path(data, "delivery.email.smtp.host")
            if is_empty(host):
                errors.append(
                    f"{path.name}: email is enabled (provider: smtp) but "
                    "`delivery.email.smtp.host` is empty"
                )

    found, enabled = get_path(data, "delivery.telegram.enabled")
    if found and enabled is True:
        _, chat_id = get_path(data, "delivery.telegram.chat_id")
        if is_empty(chat_id):
            errors.append(
                f"{path.name}: telegram is enabled but "
                "`delivery.telegram.chat_id` is empty"
            )

    found, enabled = get_path(data, "delivery.rocketchat.enabled")
    if found and enabled is True:
        _, webhook = get_path(data, "delivery.rocketchat.webhook_url_env")
        if is_empty(webhook):
            errors.append(
                f"{path.name}: rocketchat is enabled but "
                "`delivery.rocketchat.webhook_url_env` is empty"
            )
    return errors


__all__ = [
    "CHANNELS_REQUIRED",
    "CHANNELS_SECRET_ENV_KEYS",
    "LANGUAGE_CODE",
    "NON_CHANNEL_DELIVERY_KEYS",
    "check_alerts",
    "check_channel_enums",
    "check_enabled_channels",
    "check_secret_env_refs",
    "configured_channels",
    "is_empty",
    "validate_channels",
]
