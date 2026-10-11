"""config_schema.py — the single source of truth for CLOSED config enums.

The delivery/audience config keys whose value must be one of a fixed set live
here so every consumer agrees on one list:

  - ``scripts.validate_config`` enforces it against the user's ``channels.yaml``
    — an off-enum value (a typo like ``stmp``) is a config error, not a silently
    dropped channel.
  - the schema comments in ``docs/CONVENTIONS.md`` / ``docs/audience-levels.md``
    that enumerate these values are pinned to it by
    ``tests/test_config_schema_drift.py``, so a doc can never drift from the
    validator.

Only genuinely CLOSED enums belong here. Open-ended fields — ``delivery.language``
(en | ru | …), cron expressions, timezones — are validated by *shape* in
``validate_config``, not by enumeration, so they have no entry.
"""

from __future__ import annotations

# delivery.email.provider — how email is sent (CONVENTIONS §2.1 / §3).
# `gmail-mcp` is sent by the agent skill via the Gmail MCP; `smtp` by the
# headless deliverer. An unknown value is a config error.
EMAIL_PROVIDERS = ("smtp", "gmail-mcp")

# delivery.telegram.transport — how Telegram is sent (CONVENTIONS §2.1 / §3).
# `mcp` is sent by the agent skill via the Telegram MCP; `bot-api` by the
# headless deliverer.
TELEGRAM_TRANSPORTS = ("mcp", "bot-api")

# delivery.technical_level — render-time audience detail level (CONVENTIONS §2.1,
# ADR 0013). A presentation knob only: it changes how much is explained vs
# assumed, never the stored knowledge. Absent → downstream defaults to `balanced`.
TECHNICAL_LEVELS = ("technical", "balanced", "non-technical")

# authors[].monitoring — HOW one followed author is watched (CONVENTIONS §2.4).
# Four variants, because a person's output reaches us through four different
# shapes of handle, and each needs a different companion field to be actionable:
#
#   rss                 an author-specific feed → collected as an ordinary RSS source
#   publication-filter  a shared publication feed, narrowed to one stable identity
#   scholarly           OpenAlex / Semantic Scholar / ORCID, queried BY identifier
#   search              retired legacy row; never collected in any mode
#
# The validator refuses an entry whose variant has no usable handle — see
# `scripts/config_validation/authors_cfg.py`.
AUTHOR_MONITORING_VARIANTS = ("rss", "publication-filter", "scholarly")
# Existing rosters may still contain this retired variant. Keep them readable and
# editable, but never offer it for a new follow decision: it never collected work.
LEGACY_AUTHOR_MONITORING_VARIANTS = ("search",)
