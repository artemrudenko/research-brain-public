"""
test_config.py — offline tests for the config validator.

Confirms the shipped config/ set validates against the fixed schema
(CONVENTIONS §2.1 / §2.2), that malformed config is rejected, and that
EXAMPLE-placeholder detection works. Skips cleanly if PyYAML is missing.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# The validator imports PyYAML lazily; the assertions here need it directly.
yaml = pytest.importorskip("yaml", reason="PyYAML required for config schema tests")

from scripts import validate_config  # noqa: E402
from scripts.config_validation import cli as config_cli  # noqa: E402

SHIPPED_CONFIG = _PROJECT_ROOT / "config"


# --------------------------------------------------------------------------- #
# Shipped config validates
# --------------------------------------------------------------------------- #


def test_shipped_channels_valid():
    errors = validate_config.validate_channels(
        SHIPPED_CONFIG / "channels.yaml", yaml
    )
    assert errors == [], errors


def test_shipped_schedule_valid():
    errors = validate_config.validate_schedule(
        SHIPPED_CONFIG / "schedule.yaml", yaml
    )
    assert errors == [], errors


def test_shipped_sources_yaml_valid():
    # 0.8.0 ships the YAML twin (empty structure) instead of the retired .md table.
    yaml = pytest.importorskip("yaml")
    errors = validate_config.validate_sources_yaml(SHIPPED_CONFIG / "sources.yaml", yaml)
    assert errors == [], errors


def test_cli_runner_validates_shipped_config(capsys):
    code = config_cli.run(validate_config, ["config"])

    out = capsys.readouterr().out
    assert code == 0
    assert "# Config Validation" in out
    assert "OK: channels.yaml" in out


# --------------------------------------------------------------------------- #
# Malformed fixtures fail
# --------------------------------------------------------------------------- #


def test_channels_missing_key_fails(tmp_path):
    # Valid YAML but missing the whole telegram channel + rocketchat.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: gmail-mcp\n"
        "    to: []\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert errors
    assert any("delivery.telegram" in e for e in errors)


def test_channels_wrong_type_fails(tmp_path):
    # `to` should be a list; give it a string. `enabled` should be bool.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en\n"
        "  email:\n"
        "    enabled: nope\n"
        "    provider: gmail-mcp\n"
        "    to: not-a-list\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("must be a list" in e for e in errors)
    assert any("must be a boolean" in e for e in errors)


def test_schedule_missing_key_fails(tmp_path):
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n  cron: '0 9 * * *'\n", encoding="utf-8"
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("max_articles_per_topic" in e for e in errors)
    assert any("digest" in e for e in errors)


def test_channels_missing_token_env_fails(tmp_path):
    # Full schema except telegram.token_env -> §2.1 requires it in the template.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: gmail-mcp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("delivery.telegram.token_env" in e for e in errors), errors


def test_channels_missing_password_env_fails(tmp_path):
    # Full schema except email.smtp.password_env -> §2.1 requires it.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: gmail-mcp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("delivery.email.smtp.password_env" in e for e in errors), errors


def test_channels_full_schema_valid(tmp_path):
    # All §2.1 keys present (incl. smtp host/port/user/password_env, token_env).
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: smtp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: smtp.example.com\n"
        "      port: 587\n"
        "      user: me\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: bot-api\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert errors == [], errors


def test_channels_smtp_port_non_int_fails(tmp_path):
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: smtp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: h\n"
        "      port: not-a-number\n"
        "      user: u\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("smtp.port` must be an integer" in e for e in errors), errors


def _channels_with(extra_delivery_line: str = "") -> str:
    """A minimal full-schema channels.yaml, optionally with an extra `delivery:` line.

    The extra line is inserted right under `delivery:` (already indented two spaces),
    used to exercise the optional `technical_level` knob without restating the schema.
    """
    return (
        "delivery:\n"
        "  language: en\n"
        f"{extra_delivery_line}"
        "  email:\n"
        "    enabled: false\n"
        "    provider: smtp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: smtp.example.com\n"
        "      port: 587\n"
        "      user: me\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n"
    )


def test_channels_technical_level_valid(tmp_path):
    # The optional audience knob, set to a supported value, validates clean.
    (tmp_path / "channels.yaml").write_text(
        _channels_with("  technical_level: non-technical\n"), encoding="utf-8"
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert errors == [], errors


def test_channels_technical_level_absent_ok(tmp_path):
    # Absent → optional → no error (downstream defaults to `balanced`); backward compat.
    (tmp_path / "channels.yaml").write_text(_channels_with(), encoding="utf-8")
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert errors == [], errors


def test_channels_technical_level_invalid_fails(tmp_path):
    # An off-enum value (e.g. `expert`) must be a FAIL finding, not a silent default.
    (tmp_path / "channels.yaml").write_text(
        _channels_with("  technical_level: expert\n"), encoding="utf-8"
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("technical_level" in e for e in errors), errors


def test_schedule_with_curate_and_synthesis_valid(tmp_path):
    # §2.2 with the new curate/synthesis blocks present and well-formed.
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 */3 * *'\n"
        "  max_articles_per_topic: 10\n"
        "curate:\n"
        "  cron: '0 8 * * 1'\n"
        "  min_text_chars: 500\n"
        "synthesis:\n"
        "  cron: '0 8 * * 1'\n"
        "  min_sources_per_topic: 3\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert errors == [], errors


def test_schedule_with_daily_digest_block_valid(tmp_path):
    # ADR 0016: the optional daily_digest block validates clean when well-formed.
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 */3 * *'\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n"
        "daily_digest:\n"
        "  cron: '0 8 * * *'\n"
        "  lookback_days: 1\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert errors == [], errors


def test_schedule_daily_digest_missing_key_fails(tmp_path):
    # daily_digest present but missing lookback_days -> must error.
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 */3 * *'\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n"
        "daily_digest:\n"
        "  cron: '0 8 * * *'\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("daily_digest.lookback_days" in e for e in errors), errors


def test_schedule_daily_digest_bad_cron_fails(tmp_path):
    # A junk cron in the daily_digest block is caught like any other block's.
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 */3 * *'\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n"
        "daily_digest:\n"
        "  cron: 'not cron'\n"
        "  lookback_days: 1\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("daily_digest.cron" in e for e in errors), errors


def test_schedule_with_weekly_trends_block_valid(tmp_path):
    # ADR 0017: the optional weekly_trends block (cron only) validates clean.
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 */3 * *'\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n"
        "weekly_trends:\n"
        "  cron: '0 10 * * 1'\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert errors == [], errors


def test_schedule_weekly_trends_bad_cron_fails(tmp_path):
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 */3 * *'\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n"
        "weekly_trends:\n"
        "  cron: 'nope'\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("weekly_trends.cron" in e for e in errors), errors


def test_schedule_curate_block_missing_key_fails(tmp_path):
    # curate present but missing min_text_chars -> must error.
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 */3 * *'\n"
        "  max_articles_per_topic: 10\n"
        "curate:\n"
        "  cron: '0 8 * * 1'\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("curate.min_text_chars" in e for e in errors), errors


def test_schedule_synthesis_non_int_fails(tmp_path):
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 */3 * *'\n"
        "  max_articles_per_topic: 10\n"
        "synthesis:\n"
        "  cron: '0 8 * * 1'\n"
        "  min_sources_per_topic: three\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("synthesis.min_sources_per_topic` must be an integer" in e for e in errors), errors


def test_schedule_non_int_fails(tmp_path):
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 * * *'\n"
        "  max_articles_per_topic: seven\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("must be an integer" in e for e in errors)


def test_schedule_candidate_pool_non_int_fails(tmp_path):
    # The optional candidate_pool_per_topic, when present, must be an integer.
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 * * *'\n"
        "  candidate_pool_per_topic: lots\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("candidate_pool_per_topic` must be an integer" in e for e in errors), errors


def test_malformed_yaml_fails(tmp_path):
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n  language: en\n  email: [unclosed\n", encoding="utf-8"
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("parse error" in e for e in errors)


def test_non_mapping_yaml_fails(tmp_path):
    (tmp_path / "schedule.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("must be a mapping" in e for e in errors)


def test_missing_file_fails(tmp_path):
    errors = validate_config.validate_channels(tmp_path / "nope.yaml", yaml)
    assert any("file not found" in e for e in errors)


def test_sources_no_table_fails(tmp_path):
    (tmp_path / "sources.md").write_text("# Sources\n\nNo table here.\n", encoding="utf-8")
    errors = validate_config.validate_sources(tmp_path / "sources.md")
    assert errors


# --------------------------------------------------------------------------- #
# Inline-secret detection (CONVENTIONS §8)
# --------------------------------------------------------------------------- #


def test_inline_secret_pasted_token_fails(tmp_path):
    # A real bot token pasted as a literal `token:` value must be flagged.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  telegram:\n"
        "    enabled: true\n"
        "    transport: bot-api\n"
        "    chat_id: '12345'\n"
        "    token: 123456:ABCdefGHIjklMNOpqr\n",
        encoding="utf-8",
    )
    errors = validate_config.detect_inline_secrets(tmp_path)
    assert any("inline secret" in e for e in errors), errors


def test_inline_secret_clean_env_ref_passes():
    # The shipped channels.yaml uses only `*_env: NAME` references — no leak.
    errors = validate_config.detect_inline_secrets(SHIPPED_CONFIG)
    assert errors == [], errors


def test_inline_secret_lowercase_env_ref_accepted(tmp_path):
    # A `*_env:` reference naming a lowercase/mixed-case env var is the sanctioned
    # form, not a pasted secret — it must NOT be flagged (FIX 1).
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  email:\n"
        "    smtp:\n"
        "      password_env: my_smtp_password\n"
        "      user_env: My_Mixed_Case_User\n",
        encoding="utf-8",
    )
    errors = validate_config.detect_inline_secrets(tmp_path)
    assert errors == [], errors


def test_inline_secret_pasted_token_still_flagged_alongside_env_form(tmp_path):
    # The env-ref broadening must not silence a genuine inline secret: a long
    # high-entropy literal pasted as a `password:` value is still flagged (FIX 1).
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  email:\n"
        "    smtp:\n"
        '      password: "' + "AKIA" + '1234567890ABCDEF"\n',
        encoding="utf-8",
    )
    errors = validate_config.detect_inline_secrets(tmp_path)
    assert any("inline secret" in e for e in errors), errors


def test_inline_secret_token_pasted_on_env_key_is_flagged(tmp_path):
    # Regression: the env-ref allow-list must not let a real token slip through just
    # because it sits on a `*_env:` key and contains no special chars. A token has a
    # long unbroken alphanumeric run that a real env-var name (short words) never has.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  email:\n"
        "    smtp:\n"
        "      password_env: ghp_16CharsTokenValueHere\n",
        encoding="utf-8",
    )
    errors = validate_config.detect_inline_secrets(tmp_path)
    assert any("inline secret" in e for e in errors), errors


def test_inline_secret_pasted_in_search_yaml_fails(tmp_path):
    # search.yaml is exactly where a Tavily/Perplexity api_key would be pasted —
    # a literal key there must be flagged the same as the other config files.
    (tmp_path / "search.yaml").write_text(
        "search:\n"
        "  provider: tavily\n"
        "  tavily:\n"
        "    api_key: " + "tvly-" + "1234567890ABCDEFghij\n",
        encoding="utf-8",
    )
    errors = validate_config.detect_inline_secrets(tmp_path)
    assert any("inline secret" in e for e in errors), errors
    assert any(e.startswith("search.yaml:") for e in errors), errors


def test_inline_secret_pasted_in_research_yaml_fails(tmp_path):
    # research.yaml is the Sonar cross-check slot — a pasted Perplexity key there
    # must be flagged too.
    (tmp_path / "research.yaml").write_text(
        "research:\n"
        "  cross_check:\n"
        "    provider: sonar\n"
        "    sonar:\n"
        "      api_key: " + "pplx-" + "9876543210ZYXWVUtsrq\n",
        encoding="utf-8",
    )
    errors = validate_config.detect_inline_secrets(tmp_path)
    assert any("inline secret" in e for e in errors), errors
    assert any(e.startswith("research.yaml:") for e in errors), errors


def test_inline_secret_clean_search_research_pass(tmp_path):
    # `api_key_env: NAME` references in search.yaml/research.yaml are the sanctioned
    # form and must NOT be flagged.
    (tmp_path / "search.yaml").write_text(
        "search:\n"
        "  tavily:\n"
        "    api_key_env: TAVILY_API_KEY\n",
        encoding="utf-8",
    )
    (tmp_path / "research.yaml").write_text(
        "research:\n"
        "  cross_check:\n"
        "    sonar:\n"
        "      api_key_env: PERPLEXITY_API_KEY\n",
        encoding="utf-8",
    )
    errors = validate_config.detect_inline_secrets(tmp_path)
    assert errors == [], errors


def test_inline_secret_shipped_search_research_clean():
    # The shipped search.yaml/research.yaml use only `*_env: NAME` references.
    errors = validate_config.detect_inline_secrets(SHIPPED_CONFIG)
    assert errors == [], errors


def test_inline_secret_absent_search_research_no_error(tmp_path):
    # Both files are optional — when neither exists the scan must not error.
    errors = validate_config.detect_inline_secrets(tmp_path)
    assert errors == [], errors


# --------------------------------------------------------------------------- #
# Placeholder detection
# --------------------------------------------------------------------------- #


def test_placeholder_detection_on_shipped_template(tmp_path):
    # The shipped STARTER template carries EXAMPLE rows that detection must flag.
    # Scan the canonical `sources.example-starter.md` (which setup never overwrites),
    # copied into a tmp config dir as `sources.md`, rather than the live
    # `config/sources.md` — so this passes on a CONFIGURED deployment too, not only
    # on a fresh template checkout (a configured config/sources.md has no placeholders).
    starter = (SHIPPED_CONFIG / "sources.example-starter.md").read_text(encoding="utf-8")
    (tmp_path / "sources.md").write_text(starter, encoding="utf-8")
    notes = validate_config.detect_placeholders(tmp_path)
    assert "sources.md" in notes


def test_placeholder_detection_clean(tmp_path):
    (tmp_path / "sources.md").write_text(
        "| URL | Type |\n|---|---|\n| https://real.feed/rss | rss |\n",
        encoding="utf-8",
    )
    notes = validate_config.detect_placeholders(tmp_path)
    assert notes == []


def test_placeholder_in_yaml_comment_is_not_flagged(tmp_path):
    # A shipped documentation comment (e.g. `# e.g. ["you@example.com"]`) carries
    # the placeholder pattern but stays in EVERY config, even a fully-configured
    # one — matching it would WARN forever. Only real CONTENT should be flagged.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  email:\n"
        "    provider: gmail-mcp\n"
        '    to: []                  # list of recipients, e.g. ["you@example.com"]\n',
        encoding="utf-8",
    )
    assert validate_config.detect_placeholders(tmp_path) == []


def test_real_yaml_placeholder_value_is_still_flagged(tmp_path):
    # A placeholder pasted as a real VALUE (not in a comment) must still be caught.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n  email:\n    to: [you@example.com]\n",
        encoding="utf-8",
    )
    assert "channels.yaml" in validate_config.detect_placeholders(tmp_path)


def test_doc_reference_example_subdomain_is_not_flagged(tmp_path):
    # The shipped "feed URL shapes" documentation table carries example subdomains
    # (e.g. `EXAMPLE.substack.com`) that stay even in a fully-configured instance —
    # they must NOT trip the template WARN. Only the canonical `# EXAMPLE — replace`
    # row marker (or example.com/.org/YYYY-MM-DD) signals an un-replaced template.
    (tmp_path / "sources.md").write_text(
        "## Feed URL shapes\n\n"
        "| URL pattern | Type |\n|---|---|\n"
        "| https://EXAMPLE.substack.com/feed | rss |\n"
        "| https://medium.com/feed/tag/TAG_SLUG | rss |\n\n"
        "## Category: ai\n\n"
        "| https://real.feed/rss | rss | high | high | all | yes |\n",
        encoding="utf-8",
    )
    assert validate_config.detect_placeholders(tmp_path) == []


def test_unreplaced_example_row_marker_is_flagged(tmp_path):
    # An un-replaced shipped example row (carrying the canonical marker) IS a
    # template signal and must be flagged.
    (tmp_path / "sources.md").write_text(
        "## Category: ai\n\n"
        "| https://example.com/feed.xml | rss | high | high | all | yes |"
        "  <!-- # EXAMPLE — replace -->\n",
        encoding="utf-8",
    )
    assert "sources.md" in validate_config.detect_placeholders(tmp_path)


# --------------------------------------------------------------------------- #
# Missing-PyYAML exit code (CONVENTIONS §8 / caller contract) — FIX 5
# --------------------------------------------------------------------------- #


def test_missing_pyyaml_exits_non_zero(tmp_path):
    # When PyYAML is unavailable the validator CANNOT actually validate, so it
    # must exit NON-ZERO — a caller treating "exit 0 == validated ✓" must never
    # be told validation passed when it never ran. FIX 5.
    #
    # We simulate the missing-PyYAML environment by running the validator under a
    # subprocess whose sys.path hides the `yaml` module (via a sitecustomize that
    # blocks the import), without touching the host interpreter's packages.
    blocker_dir = tmp_path / "blocker"
    blocker_dir.mkdir()
    # A sitecustomize that installs a modern MetaPathFinder which makes
    # `import yaml` raise ImportError, simulating an environment without PyYAML
    # without disturbing the host interpreter's real packages.
    (blocker_dir / "sitecustomize.py").write_text(
        "import sys\n"
        "from importlib.abc import MetaPathFinder\n"
        "class _Block(MetaPathFinder):\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'yaml' or name.startswith('yaml.'):\n"
        "            raise ImportError('yaml blocked for test')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Block())\n",
        encoding="utf-8",
    )
    script = _PROJECT_ROOT / "scripts" / "validate_config.py"
    env = {"PYTHONPATH": str(blocker_dir)}
    # Keep PATH so the interpreter can locate shared libs on all platforms.
    import os

    env = {**os.environ, **env}
    result = subprocess.run(
        [sys.executable, str(script), "config"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_PROJECT_ROOT),
    )
    assert result.returncode != 0, (result.returncode, result.stdout, result.stderr)
    assert "PyYAML" in result.stderr


# --------------------------------------------------------------------------- #
# Regression: tags.yaml is validated (M5)
# --------------------------------------------------------------------------- #


def test_shipped_tags_valid():
    errors = validate_config.validate_tags(SHIPPED_CONFIG / "tags.yaml", yaml)
    assert errors == [], errors


def test_tags_domains_not_mapping_fails(tmp_path):
    (tmp_path / "tags.yaml").write_text("domains:\n  - a\n  - b\n", encoding="utf-8")
    errors = validate_config.validate_tags(tmp_path / "tags.yaml", yaml)
    assert any("domains" in e for e in errors)


def test_tags_synonyms_wrong_type_fails(tmp_path):
    (tmp_path / "tags.yaml").write_text(
        "domains:\n  ai:\n    - agents\nsynonyms:\n  - not-a-mapping\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_tags(tmp_path / "tags.yaml", yaml)
    assert any("synonyms" in e for e in errors)


# --------------------------------------------------------------------------- #
# topics.md schema (semantic deepening)
# --------------------------------------------------------------------------- #


def test_shipped_topics_yaml_valid():
    # 0.8.0 ships the YAML twin (empty structure) instead of the retired .md template.
    yaml = pytest.importorskip("yaml")
    errors = validate_config.validate_topics_yaml(SHIPPED_CONFIG / "topics.yaml", yaml)
    assert errors == [], errors


def test_topics_missing_file_fails(tmp_path):
    # topics.md is a core config file (drives collection + digest) — absent → finding.
    errors = validate_config.validate_topics(tmp_path / "topics.md")
    assert any("file not found" in e for e in errors), errors


def test_topics_malformed_no_sections_fails(tmp_path):
    # A topics.md with no `## Topic:` section is malformed/empty → finding.
    (tmp_path / "topics.md").write_text(
        "# Monitored topics\n\nSome prose but no topic sections.\n", encoding="utf-8"
    )
    errors = validate_config.validate_topics(tmp_path / "topics.md")
    assert errors, errors


def test_topics_well_formed_passes(tmp_path):
    (tmp_path / "topics.md").write_text(
        "# Topics\n\n## Topic: tech-news\n\n- **Name:** `tech-news`\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_topics(tmp_path / "topics.md")
    assert errors == [], errors


# --------------------------------------------------------------------------- #
# topics ↔ sources sync (WARN, non-fatal)
# --------------------------------------------------------------------------- #


def test_shipped_topics_sources_in_sync():
    warnings = validate_config.check_topics_sources_sync(
        SHIPPED_CONFIG / "topics.md", SHIPPED_CONFIG / "sources.md"
    )
    assert warnings == [], warnings


def test_topic_without_source_warns(tmp_path):
    (tmp_path / "topics.md").write_text(
        "## Topic: tech-news\n\n## Topic: ai-ml\n", encoding="utf-8"
    )
    (tmp_path / "sources.md").write_text(
        "## Category: tech-news\n\n| URL | Type |\n|---|---|\n| x | rss |\n",
        encoding="utf-8",
    )
    warnings = validate_config.check_topics_sources_sync(
        tmp_path / "topics.md", tmp_path / "sources.md"
    )
    # ai-ml is monitored but has no source category.
    assert any("ai-ml" in w for w in warnings), warnings


def test_orphan_source_category_warns(tmp_path):
    (tmp_path / "topics.md").write_text("## Topic: tech-news\n", encoding="utf-8")
    (tmp_path / "sources.md").write_text(
        "## Category: tech-news\n\n## Category: orphan-cat\n", encoding="utf-8"
    )
    warnings = validate_config.check_topics_sources_sync(
        tmp_path / "topics.md", tmp_path / "sources.md"
    )
    assert any("orphan-cat" in w for w in warnings), warnings


# --------------------------------------------------------------------------- #
# cron syntax (schedule.yaml, semantic deepening)
# --------------------------------------------------------------------------- #


def test_schedule_junk_cron_fails(tmp_path):
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: 'not cron'\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("cron" in e for e in errors), errors


def test_schedule_cron_field_count_fails(tmp_path):
    # Too few fields (4 instead of 5).
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 * *'\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("cron" in e for e in errors), errors


def test_schedule_cron_out_of_range_fails(tmp_path):
    # minute 99 is out of the 0-59 range.
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '99 9 * * 1'\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("cron" in e for e in errors), errors


# --------------------------------------------------------------------------- #
# timezone validity (schedule.yaml, semantic deepening)
# --------------------------------------------------------------------------- #


def test_schedule_bad_timezone_fails(tmp_path):
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 * * 1'\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n"
        "timezone: 'Not/AZone'\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("timezone" in e for e in errors), errors


def test_is_valid_timezone_fails_open_without_tz_database(monkeypatch):
    # Native Windows without the `tzdata` package (not a runtime dep) has no tz
    # database: available_timezones() is empty AND ZoneInfo(...) raises for every name,
    # including the shipped default "UTC". Rejecting it would make the documented
    # install/validation path un-passable on a supported platform, so the check must
    # fail OPEN (unverifiable) when no database is present — mirroring the ImportError
    # branch.
    import zoneinfo

    from scripts.config_validation import schedule as schedule_validation

    monkeypatch.setattr(zoneinfo, "available_timezones", lambda: set())

    def _no_db(_name):
        raise zoneinfo.ZoneInfoNotFoundError("No time zone found")

    monkeypatch.setattr(zoneinfo, "ZoneInfo", _no_db)
    assert schedule_validation.is_valid_timezone("UTC") is True
    assert schedule_validation.is_valid_timezone("Europe/Minsk") is True


def test_schedule_good_timezone_passes(tmp_path):
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 * * 1'\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n"
        "timezone: 'Europe/Minsk'\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert errors == [], errors


# --------------------------------------------------------------------------- #
# numeric ranges (must be POSITIVE ints, semantic deepening)
# --------------------------------------------------------------------------- #


def test_schedule_negative_lookback_fails(tmp_path):
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 * * 1'\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: -7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("lookback_days" in e and "positive" in e for e in errors), errors


def test_schedule_zero_max_articles_fails(tmp_path):
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 * * 1'\n"
        "  max_articles_per_topic: 0\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("max_articles_per_topic" in e and "positive" in e for e in errors), errors


def test_schedule_negative_min_sources_fails(tmp_path):
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 * * 1'\n"
        "  max_articles_per_topic: 10\n"
        "synthesis:\n"
        "  cron: '0 8 * * 1'\n"
        "  min_sources_per_topic: -3\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("min_sources_per_topic" in e and "positive" in e for e in errors), errors


def test_schedule_zero_min_text_chars_fails(tmp_path):
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '0 9 * * 1'\n"
        "  max_articles_per_topic: 10\n"
        "curate:\n"
        "  cron: '0 8 * * 1'\n"
        "  min_text_chars: 0\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("min_text_chars" in e and "positive" in e for e in errors), errors


# --------------------------------------------------------------------------- #
# enabled-channel completeness (channels.yaml, semantic deepening)
# --------------------------------------------------------------------------- #


def test_channel_email_enabled_empty_fails(tmp_path):
    # Email enabled but `to` empty and smtp host empty (provider smtp) → unsendable.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en\n"
        "  email:\n"
        "    enabled: true\n"
        "    provider: smtp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("email" in e and ("to" in e or "host" in e) for e in errors), errors


def test_channel_telegram_enabled_empty_chat_id_fails(tmp_path):
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: gmail-mcp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: true\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("telegram" in e and "chat_id" in e for e in errors), errors


def test_channel_disabled_empty_fields_ok(tmp_path):
    # A DISABLED channel with empty fields is fine — completeness only bites enabled.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: smtp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert errors == [], errors


def test_channel_telegram_enabled_complete_ok(tmp_path):
    # Enabled + chat_id present → sendable, no completeness error.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: gmail-mcp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: true\n"
        "    transport: bot-api\n"
        "    chat_id: '12345'\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert errors == [], errors


# --------------------------------------------------------------------------- #
# cron step / reversed-range rejection (FIX 1)
# --------------------------------------------------------------------------- #


def test_schedule_zero_step_cron_fails(tmp_path):
    # `*/0` is a zero step — the job would never advance. Must be rejected.
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '*/0 9 * * 1'\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("cron" in e for e in errors), errors


def test_schedule_literal_zero_step_cron_fails(tmp_path):
    # `5/0` is also a zero step on a literal base — must be rejected.
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '5/0 9 * * 1'\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("cron" in e for e in errors), errors


def test_schedule_reversed_range_cron_fails(tmp_path):
    # A reversed range `5-2` (low > high) is empty/invalid — must be rejected.
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '5-2 9 * * 1'\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert any("cron" in e for e in errors), errors


def test_schedule_valid_step_cron_passes(tmp_path):
    # A legitimate `*/15` step and `1-5` forward range must still pass.
    (tmp_path / "schedule.yaml").write_text(
        "collect:\n"
        "  cron: '*/15 9 * * 1-5'\n"
        "  max_articles_per_topic: 10\n"
        "digest:\n"
        "  cron: '0 9 * * 1'\n"
        "  lookback_days: 7\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_schedule(tmp_path / "schedule.yaml", yaml)
    assert errors == [], errors


# --------------------------------------------------------------------------- #
# delivery enum values (FIX 2)
# --------------------------------------------------------------------------- #


def test_channels_unknown_email_provider_fails(tmp_path):
    # A typo like `stmp` for the email provider must be a config error.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: stmp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("provider" in e for e in errors), errors


def test_channels_unknown_telegram_transport_fails(tmp_path):
    # An unknown telegram transport must be a config error.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: gmail-mcp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: telegram-api\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("transport" in e for e in errors), errors


def test_channels_known_enum_values_pass(tmp_path):
    # Both supported provider/transport values must validate cleanly.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: gmail-mcp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: bot-api\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert errors == [], errors


# --------------------------------------------------------------------------- #
# empty env-reference (FIX 3)
# --------------------------------------------------------------------------- #


def test_channels_empty_password_env_fails(tmp_path):
    # A `password_env:` with no value cannot resolve to a secret → error.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: smtp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env:\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("password_env" in e and "empty" in e for e in errors), errors


def test_channels_blank_token_env_fails(tmp_path):
    # A `token_env: ""` (blank string) cannot resolve to a secret → error.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: gmail-mcp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        '    token_env: ""\n'
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("token_env" in e and "empty" in e for e in errors), errors


# --------------------------------------------------------------------------- #
# delivery.language shape (FIX 4)
# --------------------------------------------------------------------------- #


def test_channels_empty_language_fails(tmp_path):
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: ''\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: gmail-mcp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("language" in e for e in errors), errors


def test_channels_malformed_language_fails(tmp_path):
    # A clearly non-code value (spaces / uppercase prose) is malformed.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: English please\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: gmail-mcp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("language" in e for e in errors), errors


def test_channels_language_with_region_passes(tmp_path):
    # An open-ended but well-formed code like `en-US` must NOT be flagged.
    (tmp_path / "channels.yaml").write_text(
        "delivery:\n"
        "  language: en-US\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: gmail-mcp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert errors == [], errors


# --------------------------------------------------------------------------- #
# malformed optional search/research config (FIX 5)
# --------------------------------------------------------------------------- #


def test_malformed_search_yaml_fails(tmp_path):
    # search.yaml present but unparseable YAML → clear error.
    (tmp_path / "search.yaml").write_text(
        "search:\n  provider: [unclosed\n", encoding="utf-8"
    )
    errors = validate_config.validate_search(tmp_path / "search.yaml", yaml)
    assert any("parse error" in e for e in errors), errors


def test_non_mapping_research_yaml_fails(tmp_path):
    # research.yaml present but top level is a list, not a mapping → error.
    (tmp_path / "research.yaml").write_text(
        "- just\n- a\n- list\n", encoding="utf-8"
    )
    errors = validate_config.validate_search(tmp_path / "research.yaml", yaml)
    assert any("must be a mapping" in e for e in errors), errors


def test_absent_search_yaml_no_error(tmp_path):
    # search.yaml / research.yaml are optional — absence must not error.
    errors = validate_config.validate_search(tmp_path / "search.yaml", yaml)
    assert errors == [], errors


def test_shipped_search_research_valid():
    # The shipped optional configs are well-formed mappings.
    assert validate_config.validate_search(SHIPPED_CONFIG / "search.yaml", yaml) == []
    assert (
        validate_config.validate_search(SHIPPED_CONFIG / "research.yaml", yaml) == []
    )


def test_tags_pending_not_list_fails(tmp_path):
    (tmp_path / "tags.yaml").write_text(
        "domains:\n  ai:\n    - agents\npending: not-a-list\n", encoding="utf-8"
    )
    errors = validate_config.validate_tags(tmp_path / "tags.yaml", yaml)
    assert any("pending" in e for e in errors)


def test_tags_empty_domain_list_is_valid(tmp_path):
    # A seeded-but-empty domain (`robotics: []`) is legal.
    (tmp_path / "tags.yaml").write_text(
        "domains:\n  ai:\n    - agents\n  robotics: []\n", encoding="utf-8"
    )
    assert validate_config.validate_tags(tmp_path / "tags.yaml", yaml) == []


# --------------------------------------------------------------------------- #
# opt-in DEGRADED health alert (delivery.alerts) — MED
# --------------------------------------------------------------------------- #


def _channels_with_alerts(alerts_block: str) -> str:
    """Full §2.1 channels.yaml body with an `alerts:` block spliced under delivery.

    The block is given pre-indented (4 spaces) so callers pass just its contents;
    the rest is a complete, otherwise-valid config so only the alerts shape is
    under test.
    """
    return (
        "delivery:\n"
        "  language: en\n"
        f"{alerts_block}"
        "  email:\n"
        "    enabled: false\n"
        "    provider: gmail-mcp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n"
    )


def test_channels_alerts_absent_ok(tmp_path):
    # No `alerts:` block at all → opt-in is off, no error.
    (tmp_path / "channels.yaml").write_text(_channels_with_alerts(""), encoding="utf-8")
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert errors == [], errors


def test_channels_alerts_disabled_ok(tmp_path):
    # alerts present but disabled → no validation of `channel`, no error (even if
    # the channel name were bogus, a disabled block is a no-op).
    (tmp_path / "channels.yaml").write_text(
        _channels_with_alerts(
            "  alerts:\n"
            "    enabled: false\n"
            "    channel: nonexistent\n"
        ),
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert errors == [], errors


def _channels_alerts_telegram(
    *, telegram_enabled: bool, transport: str = "bot-api"
) -> str:
    """A channels.yaml whose alerts target telegram, parameterised by whether the
    telegram channel itself is enabled (an enabled target carries a chat_id) and its
    transport (health_alert always sends via the Bot API, so only bot-api can deliver)."""
    chat_id = "12345" if telegram_enabled else ""
    return (
        "delivery:\n"
        "  language: en\n"
        "  alerts:\n"
        "    enabled: true\n"
        "    channel: telegram\n"
        "  email:\n"
        "    enabled: false\n"
        "    provider: smtp\n"
        "    to: []\n"
        "    smtp:\n"
        "      host: ''\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        f"    enabled: {'true' if telegram_enabled else 'false'}\n"
        f"    transport: {transport}\n"
        f"    chat_id: '{chat_id}'\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n"
    )


def test_channels_alerts_telegram_mcp_transport_fails(tmp_path):
    # health_alert.py always sends telegram via the Bot API adapter (headless cron has
    # no MCP), so an alert pointed at a `transport: mcp` telegram channel — the shipped
    # default — has no usable transport and no token in .env → config error. Mirrors
    # the email `provider: smtp` alert constraint.
    (tmp_path / "channels.yaml").write_text(
        _channels_alerts_telegram(telegram_enabled=True, transport="mcp"),
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any(
        "alerts" in e and "telegram" in e and "bot-api" in e for e in errors
    ), errors


def test_channels_alerts_telegram_bot_api_ok(tmp_path):
    # A bot-api telegram channel is a valid alert target (the alert can actually send).
    (tmp_path / "channels.yaml").write_text(
        _channels_alerts_telegram(telegram_enabled=True, transport="bot-api"),
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert errors == [], errors


def test_channels_alerts_enabled_valid_channel_ok(tmp_path):
    # Enabled + `channel` names a configured AND enabled channel → valid.
    (tmp_path / "channels.yaml").write_text(
        _channels_alerts_telegram(telegram_enabled=True), encoding="utf-8"
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert errors == [], errors


def test_channels_alerts_disabled_target_channel_fails(tmp_path):
    # alerts.enabled: true but the target channel is disabled → the alert would try
    # to send through a channel the user turned off → config error.
    (tmp_path / "channels.yaml").write_text(
        _channels_alerts_telegram(telegram_enabled=False), encoding="utf-8"
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("alerts" in e and "enabled" in e.lower() for e in errors), errors


def test_channels_alerts_enabled_unknown_channel_fails(tmp_path):
    # Enabled but `channel` names a channel that isn't configured → error.
    (tmp_path / "channels.yaml").write_text(
        _channels_with_alerts(
            "  alerts:\n"
            "    enabled: true\n"
            "    channel: slack\n"
        ),
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("alerts" in e and "channel" in e for e in errors), errors


def test_channels_alerts_enabled_missing_channel_fails(tmp_path):
    # Enabled but no `channel` set → there is nowhere to send the alert → error.
    (tmp_path / "channels.yaml").write_text(
        _channels_with_alerts(
            "  alerts:\n"
            "    enabled: true\n"
        ),
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("alerts" in e and "channel" in e for e in errors), errors


def test_channels_alerts_non_bool_enabled_fails(tmp_path):
    # `enabled` must be a real boolean — a string like `yes` is a config error.
    (tmp_path / "channels.yaml").write_text(
        _channels_with_alerts(
            "  alerts:\n"
            "    enabled: yes-please\n"
            "    channel: telegram\n"
        ),
        encoding="utf-8",
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("alerts" in e and "enabled" in e and "boolean" in e for e in errors), errors


def _channels_with_alerts_email(provider: str) -> str:
    """A channels.yaml whose alerts target an ENABLED email channel, parameterised by
    the email provider — to cover the SMTP-only alert transport constraint. Email is
    enabled (with `to`/`smtp.host` populated) so the provider check is what's exercised,
    not the disabled-target or enabled-but-incomplete checks."""
    return (
        "delivery:\n"
        "  language: en\n"
        "  alerts:\n"
        "    enabled: true\n"
        "    channel: email\n"
        "  email:\n"
        "    enabled: true\n"
        f"    provider: {provider}\n"
        "    to: ['ops@example.com']\n"
        "    smtp:\n"
        "      host: 'smtp.example.com'\n"
        "      port: 587\n"
        "      user: ''\n"
        "      password_env: SMTP_PASSWORD\n"
        "  telegram:\n"
        "    enabled: false\n"
        "    transport: mcp\n"
        "    chat_id: ''\n"
        "    token_env: TELEGRAM_BOT_TOKEN\n"
        "  rocketchat:\n"
        "    enabled: false\n"
        "    webhook_url_env: ROCKETCHAT_WEBHOOK_URL\n"
    )


def test_channels_alerts_email_gmail_mcp_fails(tmp_path):
    # health_alert.py always sends email via the SMTP adapter, so an alert pointed
    # at a `gmail-mcp` email channel has no usable transport → config error.
    (tmp_path / "channels.yaml").write_text(
        _channels_with_alerts_email("gmail-mcp"), encoding="utf-8"
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("alerts" in e and "email" in e and "smtp" in e.lower() for e in errors), errors


def test_channels_alerts_email_smtp_ok(tmp_path):
    # An SMTP email channel is a valid alert target (the alert can actually send).
    (tmp_path / "channels.yaml").write_text(
        _channels_with_alerts_email("smtp"), encoding="utf-8"
    )
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert errors == [], errors


# --------------------------------------------------------------------------- #
# Feed liveness (opt-in, network) — schema validation can't see a dead feed URL,
# so extract the source URLs and probe them (BACKLOG: feed-liveness at setup).
# --------------------------------------------------------------------------- #

import urllib.error  # noqa: E402


def _sources_md(*rows: str) -> str:
    """A sources.md with the documented 6-column table + a template placeholder row."""
    head = (
        "## Category: ai-ml\n\n"
        "| URL | Type | Tier | Priority | Filter | Active |\n"
        "|-----|------|------|----------|--------|--------|\n"
        "| full URL | `rss` | `high` | `high` | note | `yes` / `no` |\n"
    )
    return head + "".join(row if row.endswith("\n") else row + "\n" for row in rows)


def test_extract_source_urls_returns_only_real_http_rows(tmp_path):
    src = tmp_path / "sources.md"
    src.write_text(
        _sources_md(
            "| https://hnrss.org/frontpage | rss | medium | high | HN | yes |",
            "| https://techcrunch.com/feed/ | rss | medium | medium | TC | yes |",
        ),
        encoding="utf-8",
    )
    urls = validate_config.extract_source_urls(src)
    # Header, dash separator, and the `full URL` template row all fall out.
    assert urls == ["https://hnrss.org/frontpage", "https://techcrunch.com/feed/"]


def test_extract_source_urls_skips_disabled_rows(tmp_path):
    src = tmp_path / "sources.md"
    src.write_text(
        _sources_md(
            "| https://live.example/feed | rss | medium | high | on | yes |",
            "| https://off.example/feed | rss | medium | high | off | no |",
        ),
        encoding="utf-8",
    )
    urls = validate_config.extract_source_urls(src)
    assert urls == ["https://live.example/feed"]  # the `Active: no` row is excluded


def test_extract_source_urls_empty_for_template_only(tmp_path):
    # The shipped template (only the `full URL` placeholder row) has no real URL.
    src = tmp_path / "sources.md"
    src.write_text(_sources_md(), encoding="utf-8")
    assert validate_config.extract_source_urls(src) == []


def test_check_feed_liveness_reports_unreachable(tmp_path):
    dead = "https://dead.example/feed"
    alive = "https://alive.example/feed"

    def fake_fetch(url: str) -> str:
        if url == dead:
            raise urllib.error.URLError("name resolution failed")
        return "<rss/>"

    warnings = validate_config.check_feed_liveness([dead, alive], fetch=fake_fetch)
    assert len(warnings) == 1
    assert dead in warnings[0]
    assert "unreachable" in warnings[0].lower()


def test_check_feed_liveness_all_alive_no_warnings(tmp_path):
    warnings = validate_config.check_feed_liveness(
        ["https://a.example", "https://b.example"], fetch=lambda url: "<rss/>"
    )
    assert warnings == []


# --------------------------------------------------------------------------- #
# Opt-in pre-send review flag (delivery.pre_send_review) — BACKLOG: pre-send gate.
# --------------------------------------------------------------------------- #


def _channels_with_presend(value: str) -> str:
    return _channels_with(f"  pre_send_review: {value}\n")


def test_channels_pre_send_review_bool_ok(tmp_path):
    (tmp_path / "channels.yaml").write_text(_channels_with_presend("true"), encoding="utf-8")
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert errors == [], errors


def test_channels_pre_send_review_non_bool_fails(tmp_path):
    (tmp_path / "channels.yaml").write_text(_channels_with_presend("yes-please"), encoding="utf-8")
    errors = validate_config.validate_channels(tmp_path / "channels.yaml", yaml)
    assert any("pre_send_review" in e for e in errors), errors


def test_pre_send_review_is_not_treated_as_a_channel(tmp_path):
    # The flag lives under delivery: but is not a delivery channel — it must not be
    # mistaken for one (which would demand an `enabled:`/secret and fail validation).
    (tmp_path / "channels.yaml").write_text(_channels_with_presend("false"), encoding="utf-8")
    _, data = validate_config._load_yaml_mapping(tmp_path / "channels.yaml", yaml)
    assert "pre_send_review" not in validate_config._configured_channels(data)
