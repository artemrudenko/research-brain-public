"""Drift tests: config enums are owned by scripts.config_schema; docs must match.

The delivery/audience config keys with a CLOSED set of values (email provider,
telegram transport, technical_level) are enumerated in two places: the validator's
SSOT (`scripts.config_schema`, enforced against the user's `channels.yaml`) and,
for humans, the schema comments in `docs/CONVENTIONS.md` and `docs/audience-levels.md`.
When the two drift, a doc tells the user a value the validator rejects — or omits
one it accepts. These tests parse the documented enum lists and pin them to the
SSOT, so any future enum change must update both sides in one commit (the same
guard `test_digest_format_drift.py` gives the digest format).

Only the authoritative config-block declarations are pinned; secondary prose
mentions elsewhere are intentionally not, to avoid brittle prose-parsing.
"""

from __future__ import annotations

import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

from scripts.config_schema import (  # noqa: E402
    AUTHOR_MONITORING_VARIANTS,
    EMAIL_PROVIDERS,
    TECHNICAL_LEVELS,
    TELEGRAM_TRANSPORTS,
)

_CONVENTIONS = (_PROJECT_ROOT / "docs" / "CONVENTIONS.md").read_text(encoding="utf-8")
_AUDIENCE = (_PROJECT_ROOT / "docs" / "audience-levels.md").read_text(encoding="utf-8")


def _comment_enum(text: str, key: str) -> set[str]:
    """Extract the ``{a, b, c}`` enum from the first ``key: default  # … a | b | c`` line.

    The line is found by its ``key:`` anchor (robust to line moves), not a number.
    The trailing comment is split on ``|``, dropping any ``label:`` prefix before
    the list, and the leading ``[\\w-]+`` token of each part is kept (so a
    ``value (parenthetical note)`` reduces to ``value``).
    """
    for line in text.splitlines():
        if re.match(rf"\s*{re.escape(key)}\s*:", line) and "#" in line:
            comment = line.split("#", 1)[1]
            tail = comment.rsplit(":", 1)[-1]  # drop a `label:` prefix if present
            tokens: set[str] = set()
            for part in tail.split("|"):
                match = re.match(r"\s*([\w-]+)", part)
                if match:
                    tokens.add(match.group(1))
            return tokens
    raise AssertionError(f"no `{key}: ... #` enum line found in the doc")


def test_conventions_email_provider_enum_matches_ssot() -> None:
    assert _comment_enum(_CONVENTIONS, "provider") == set(EMAIL_PROVIDERS)


def test_conventions_telegram_transport_enum_matches_ssot() -> None:
    assert _comment_enum(_CONVENTIONS, "transport") == set(TELEGRAM_TRANSPORTS)


def test_conventions_technical_level_enum_matches_ssot() -> None:
    assert _comment_enum(_CONVENTIONS, "technical_level") == set(TECHNICAL_LEVELS)


def test_audience_levels_technical_level_enum_matches_ssot() -> None:
    assert _comment_enum(_AUDIENCE, "technical_level") == set(TECHNICAL_LEVELS)


def test_conventions_author_monitoring_enum_matches_ssot() -> None:
    assert _comment_enum(_CONVENTIONS, "monitoring") == set(AUTHOR_MONITORING_VARIANTS)


def test_validate_config_consumes_the_shared_enums() -> None:
    # The validator must consume the SSOT, not re-declare the enums, so config
    # validation and the doc pins can never disagree (identity, not just equality).
    from scripts import config_schema, validate_config

    assert validate_config.EMAIL_PROVIDERS is config_schema.EMAIL_PROVIDERS
    assert validate_config.TELEGRAM_TRANSPORTS is config_schema.TELEGRAM_TRANSPORTS
    assert validate_config.TECHNICAL_LEVELS is config_schema.TECHNICAL_LEVELS
