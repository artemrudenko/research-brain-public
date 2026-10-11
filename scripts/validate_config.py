#!/usr/bin/env python3
"""
validate_config.py — validates the config/ set against docs/CONVENTIONS.md.

Checks:
  - config/channels.yaml parses and matches the fixed §2.1 schema
    (delivery.language + email/telegram/rocketchat channels with their keys,
    including smtp host/port/user/password_env and telegram token_env).
  - config/schedule.yaml parses and matches the fixed §2.2 schema
    (collect + digest required; curate/synthesis validated when present;
    optional `timezone` string validated when present).
  - config/sources.yaml parses to the schema-2 categories shape (an unmigrated
    separator + at least one row).
  - Warns (non-fatal) when config still carries EXAMPLE placeholders, so a
    freshly cloned product can be told it is unconfigured.
  - Scans config files for inline secrets (a token/password/webhook/api-key
    pasted as a literal value instead of a `*_env: NAME` reference) and fails
    if one is found, per CONVENTIONS §8 (secrets live only in .env).

Layout: this file is still the stable CLI/import facade. Validation logic and
CLI orchestration live in `scripts/config_validation/`; this module preserves
the public command path and compatibility import surface.

Usage:
    python3 scripts/validate_config.py [CONFIG_DIR]

Arguments:
    CONFIG_DIR   Directory holding the config files (default: config/,
                 relative to the project root).

Exit codes:
    0  schema valid (placeholders only -> warnings).
    1  schema violation (missing file/key, wrong type, malformed table).
    2  PyYAML is not installed.
"""
import sys
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scripts.config_validation.api import ConfigValidationApi

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = "config"

# Make `scripts` importable when run directly, for the shared schema-version helper.
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))
from scripts._yaml import optional_yaml as _optional_yaml_module  # noqa: E402
from scripts.config_schema import (  # noqa: E402 — the closed-enum SSOT (docs pinned to it)
    EMAIL_PROVIDERS,
    TECHNICAL_LEVELS,
    TELEGRAM_TRANSPORTS,
)
from scripts.config_validation import (  # noqa: E402
    authors_cfg as authors_validation,
)
from scripts.config_validation import (  # noqa: E402
    channels as channel_validation,
)
from scripts.config_validation import (  # noqa: E402
    cli as config_cli,
)
from scripts.config_validation import (  # noqa: E402
    optional_yaml,
    yaml_helpers,
)
from scripts.config_validation import (  # noqa: E402
    schedule as schedule_validation,
)
from scripts.config_validation.feeds import (  # noqa: E402
    FetchFn,
    _default_fetch,
    check_feed_liveness,
    extract_source_urls,
)
from scripts.config_validation.markdown import (  # noqa: E402
    _CATEGORY_HEADER,
    _TOPIC_HEADER,
    _category_names,
    _topic_names,
    validate_sources,
    validate_topics,
)
from scripts.config_validation.scans import (  # noqa: E402
    PLACEHOLDER_PATTERN,
    SECRET_ENV_REF_PATTERN,
    SECRET_LEAK_PATTERN,
    _strip_comments_for_scan,
    detect_inline_secrets,
    detect_placeholders,
)
from scripts.config_validation.sources_cfg import (  # noqa: E402
    check_config_format_sync,
    check_topics_sources_sync,  # format-aware (either side .md or .yaml)
    validate_sources_yaml,
    validate_topics_yaml,
)
from scripts.sources.store import (  # noqa: E402 — active-format resolution (§2.3)
    active_sources_path,
    active_topics_path,
    legacy_md_needs_migration,
)

YamlMapping = yaml_helpers.YamlMapping


def _load_yaml() -> ModuleType:
    """Import PyYAML lazily with a clear, actionable message on failure."""
    # `_optional_yaml_module` is the shared seam (scripts._yaml.optional_yaml),
    # aliased because this package also has a `config_validation.optional_yaml`
    # MODULE (optional search/research config validation) — unrelated concern.
    yaml = _optional_yaml_module()
    if yaml is None:
        print(
            "ERROR: PyYAML is required to validate YAML config.\n"
            "       Install it with: pip install pyyaml "
            "(or: pip install -r requirements.txt)",
            file=sys.stderr,
        )
        # Exit NON-ZERO: the script cannot actually validate without PyYAML, so a
        # caller that treats "exit 0 == validated ✓" must never be told it passed
        # when validation never ran (FIX 5).
        sys.exit(2)
    return yaml


# --------------------------------------------------------------------------- #
# Schema definitions (docs/CONVENTIONS.md §2.1 / §2.2)
# --------------------------------------------------------------------------- #

# Re-export moved constants/helpers from the stable facade. Tests and downstream
# scripts still import these names from scripts.validate_config during the
# transition to domain modules.
CHANNELS_REQUIRED = channel_validation.CHANNELS_REQUIRED
CHANNELS_SECRET_ENV_KEYS = channel_validation.CHANNELS_SECRET_ENV_KEYS
LANGUAGE_CODE = channel_validation.LANGUAGE_CODE
NON_CHANNEL_DELIVERY_KEYS = channel_validation.NON_CHANNEL_DELIVERY_KEYS

SCHEDULE_REQUIRED = schedule_validation.SCHEDULE_REQUIRED
SCHEDULE_OPTIONAL_INT = schedule_validation.SCHEDULE_OPTIONAL_INT
SCHEDULE_OPTIONAL_BLOCKS = schedule_validation.SCHEDULE_OPTIONAL_BLOCKS
SCHEDULE_POSITIVE_INT = schedule_validation.SCHEDULE_POSITIVE_INT
_CRON_FIELD_RANGES = schedule_validation.CRON_FIELD_RANGES


_get_path = yaml_helpers.get_path
_cron_field_ok = schedule_validation.cron_field_ok
_is_valid_cron = schedule_validation.is_valid_cron
_is_valid_timezone = schedule_validation.is_valid_timezone
validate_channels = channel_validation.validate_channels
_configured_channels = channel_validation.configured_channels
_check_alerts = channel_validation.check_alerts
_check_channel_enums = channel_validation.check_channel_enums
_check_secret_env_refs = channel_validation.check_secret_env_refs
_is_empty = channel_validation.is_empty
_check_enabled_channels = channel_validation.check_enabled_channels
validate_schedule = schedule_validation.validate_schedule
_load_yaml_mapping = yaml_helpers.load_yaml_mapping
_check_yaml_mapping = yaml_helpers.check_yaml_mapping

validate_search = optional_yaml.validate_search
validate_glossary = optional_yaml.validate_glossary
validate_tags = optional_yaml.validate_tags
validate_authors_yaml = authors_validation.validate_authors_yaml

__all__ = [
    "DEFAULT_CONFIG_DIR",
    "PROJECT_ROOT",
    "YamlMapping",
    "EMAIL_PROVIDERS",
    "TECHNICAL_LEVELS",
    "TELEGRAM_TRANSPORTS",
    "CHANNELS_REQUIRED",
    "CHANNELS_SECRET_ENV_KEYS",
    "LANGUAGE_CODE",
    "NON_CHANNEL_DELIVERY_KEYS",
    "SCHEDULE_OPTIONAL_BLOCKS",
    "SCHEDULE_OPTIONAL_INT",
    "SCHEDULE_POSITIVE_INT",
    "SCHEDULE_REQUIRED",
    "FetchFn",
    "PLACEHOLDER_PATTERN",
    "SECRET_ENV_REF_PATTERN",
    "SECRET_LEAK_PATTERN",
    "_CATEGORY_HEADER",
    "_CRON_FIELD_RANGES",
    "_TOPIC_HEADER",
    "_category_names",
    "_check_alerts",
    "_check_channel_enums",
    "_check_enabled_channels",
    "_check_secret_env_refs",
    "_check_yaml_mapping",
    "_configured_channels",
    "_cron_field_ok",
    "_default_fetch",
    "_get_path",
    "_is_empty",
    "_is_valid_cron",
    "_is_valid_timezone",
    "_load_yaml",
    "_load_yaml_mapping",
    "_strip_comments_for_scan",
    "_topic_names",
    "active_sources_path",
    "legacy_md_needs_migration",
    "active_topics_path",
    "check_config_format_sync",
    "check_feed_liveness",
    "check_topics_sources_sync",
    "detect_inline_secrets",
    "detect_placeholders",
    "extract_source_urls",
    "main",
    "validate_authors_yaml",
    "validate_channels",
    "validate_glossary",
    "validate_schedule",
    "validate_search",
    "validate_sources",
    "validate_sources_yaml",
    "validate_tags",
    "validate_topics",
    "validate_topics_yaml",
]


def main() -> None:
    # This module is the api seam — attribute reads happen at call time, so
    # monkeypatched facade names are honored; the TYPE_CHECKING conformance
    # assignment below keeps the cast honest.
    sys.exit(config_cli.run(cast("ConfigValidationApi", sys.modules[__name__])))


if TYPE_CHECKING:
    # Static conformance check: mypy verifies this module satisfies
    # ConfigValidationApi, so the cast in main() can never hide facade drift.
    import scripts.validate_config as _facade_for_typecheck

    _API_CONFORMANCE: ConfigValidationApi = _facade_for_typecheck


if __name__ == "__main__":
    main()
