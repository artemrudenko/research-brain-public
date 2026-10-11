"""
test_configure.py — hermetic tests for the headless config installer.

`scripts/configure.py` is the no-agent counterpart to the `setup-wizard` skill:
a terminal installer that asks the same questions and writes `config/`, reusing
the deterministic `manage_sources` backend. All prompting is injected behind an
`ask` callable, so the whole flow runs offline with a scripted answer queue —
no real stdin, no network, no live `config/` touched.
"""
import os
import re
from collections.abc import Callable
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

from scripts import (
    configure,  # noqa: E402
    validate_config,  # noqa: E402
)
from scripts import manage_sources as ms  # noqa: E402

# Test-owned snapshot of the EXAMPLE topics/sources/tags (not the live config/),
# plus the SHIPPED commented templates for channels.yaml / schedule.yaml (whose
# comment-preservation is part of the contract under test).
EXAMPLE_CONFIG = Path(__file__).resolve().parent / "fixtures" / "example_config"
SHIPPED_CONFIG = _PROJECT_ROOT / "config"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A throwaway config/ seeded with copies of the shipped templates."""
    d = tmp_path / "config"
    d.mkdir()
    for name, src in (
        ("sources.md", EXAMPLE_CONFIG / "sources.md"),
        ("topics.md", EXAMPLE_CONFIG / "topics.md"),
        ("tags.yaml", EXAMPLE_CONFIG / "tags.yaml"),
        ("channels.yaml", SHIPPED_CONFIG / "channels.yaml"),
        ("schedule.yaml", SHIPPED_CONFIG / "schedule.yaml"),
        (".env.example", SHIPPED_CONFIG / ".env.example"),
    ):
        (d / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return d


@pytest.fixture(autouse=True)
def no_network_setup_probe(monkeypatch):
    """Keep configure.py tests hermetic while production uses the real probe."""

    def _verified_probe(_root: Path, fetch_fn=None):  # noqa: ARG001
        return configure.setup_check.CheckItem(
            "source",
            "verified",
            "RSS source produced at least one item",
            ["test fixture: RSS probe skipped"],
        )

    monkeypatch.setattr(configure.setup_check, "probe_rss_sources", _verified_probe)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ROCKETCHAT_WEBHOOK_URL", raising=False)


def scripted_ask(answers: list[str]) -> Callable[[str], str]:
    """Return an `ask` that pops the next queued answer, ignoring the prompt."""
    queue = list(answers)

    def _ask(_prompt: str) -> str:
        if not queue:
            raise AssertionError("scripted ask ran out of answers")
        return queue.pop(0)

    return _ask


# --------------------------------------------------------------------------- #
# set_block_field — comment-preserving YAML value edits
# --------------------------------------------------------------------------- #


SAMPLE = """\
delivery:
  language: en              # digest language
  email:
    enabled: false
    provider: gmail-mcp     # gmail-mcp | smtp
  telegram:
    enabled: false
    transport: mcp          # mcp | bot-api
timezone: "UTC"
"""


def test_set_block_field_edits_nested_field():
    out = configure.set_block_field(SAMPLE, "telegram", "enabled", "true")
    # telegram.enabled flips; email.enabled (same field name) is untouched.
    assert "  telegram:\n    enabled: true\n" in out
    assert "  email:\n    enabled: false\n" in out


def test_set_block_field_block_scoping_picks_right_block():
    """A field name shared by two blocks edits only the named block's copy."""
    out = configure.set_block_field(SAMPLE, "email", "enabled", "true")
    assert "  email:\n    enabled: true\n" in out
    assert "  telegram:\n    enabled: false\n" in out


def test_set_block_field_preserves_trailing_comment():
    out = configure.set_block_field(SAMPLE, "telegram", "transport", "bot-api")
    assert "transport: bot-api          # mcp | bot-api" in out


def test_set_block_field_root_scalar_with_parent_none():
    out = configure.set_block_field(SAMPLE, None, "timezone", '"Europe/Minsk"')
    assert 'timezone: "Europe/Minsk"' in out


def test_set_block_field_missing_parent_raises_keyerror():
    with pytest.raises(KeyError):
        configure.set_block_field(SAMPLE, "nope", "enabled", "true")


def test_set_block_field_missing_field_raises_keyerror():
    with pytest.raises(KeyError):
        configure.set_block_field(SAMPLE, "telegram", "ghost", "x")


def test_set_block_field_missing_root_field_raises_keyerror():
    with pytest.raises(KeyError):
        configure.set_block_field(SAMPLE, None, "ghost", "x")


def test_set_block_field_on_real_channels_template(config_dir: Path):
    text = (config_dir / "channels.yaml").read_text(encoding="utf-8")
    out = configure.set_block_field(text, "delivery", "language", "ru")
    assert "language: ru" in out
    # The block's documentation comment survives the value swap.
    assert "# digest language" in out
    # Nested channel blocks are left intact.
    assert "provider: gmail-mcp" in out


def test_set_block_field_on_real_schedule_template(config_dir: Path):
    text = (config_dir / "schedule.yaml").read_text(encoding="utf-8")
    out = configure.set_block_field(text, None, "timezone", '"Europe/Minsk"')
    assert 'timezone: "Europe/Minsk"' in out
    # Crons untouched.
    assert '0 9 * * 1' in out


# --------------------------------------------------------------------------- #
# write_env — secret materialisation from the template
# --------------------------------------------------------------------------- #


def test_write_env_creates_from_template(config_dir: Path):
    env_path = config_dir / ".env"
    assert not env_path.exists()
    configure.write_env(
        env_path,
        {"TELEGRAM_BOT_TOKEN": "123:abc"},
        template=config_dir / ".env.example",
    )
    text = env_path.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=123:abc" in text


def test_write_env_creates_file_0600_atomically(config_dir: Path, monkeypatch):
    # The secret file must be created with 0o600 from the first byte — never created
    # world-readable and chmod'd afterwards (a race window where another local user
    # could read the secret). We assert the create mode by capturing the os.open mode.
    import os as _os

    env_path = config_dir / ".env"
    assert not env_path.exists()
    real_open = _os.open
    open_modes: list[int] = []

    def spy_open(path, flags, mode=0o777, *args, **kwargs):
        # Record the mode used to create the .env file specifically.
        if Path(path) == env_path and (flags & _os.O_CREAT):
            open_modes.append(mode)
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(configure.os, "open", spy_open)
    configure.write_env(
        env_path,
        {"TELEGRAM_BOT_TOKEN": "123:abc"},
        template=config_dir / ".env.example",
    )
    # The file was created via os.open with an owner-only creation mode.
    assert open_modes, "write_env must create the .env via os.open with an explicit mode"
    assert all(mode == 0o600 for mode in open_modes)
    # And the final on-disk mode is owner-only.
    assert (env_path.stat().st_mode & 0o077) == 0


def test_write_env_sets_only_supplied_keys(config_dir: Path):
    env_path = config_dir / ".env"
    configure.write_env(
        env_path,
        {"TELEGRAM_BOT_TOKEN": "123:abc"},
        template=config_dir / ".env.example",
    )
    text = env_path.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=123:abc" in text
    # Untouched keys keep the template default (empty by design, not duplicated).
    assert "SMTP_PASSWORD=\n" in text
    assert text.count("TELEGRAM_BOT_TOKEN=") == 1


def test_write_env_no_duplicate_keys_on_rewrite(config_dir: Path):
    env_path = config_dir / ".env"
    configure.write_env(
        env_path, {"SMTP_PASSWORD": "first"}, template=config_dir / ".env.example"
    )
    configure.write_env(
        env_path, {"SMTP_PASSWORD": "second"}, template=config_dir / ".env.example"
    )
    text = env_path.read_text(encoding="utf-8")
    assert text.count("SMTP_PASSWORD=") == 1
    assert "SMTP_PASSWORD=second" in text


def test_write_env_rewrite_is_atomic_and_owner_only(config_dir: Path, monkeypatch):
    # The existing-file rewrite path must replace the .env via os.replace (atomic
    # same-dir rename) so a crash mid-write can't truncate the file — and the
    # replace must target the real .env from a 0o600 temp. Asserting os.replace is
    # actually invoked is what distinguishes the atomic path from a plain
    # write_text (which would pass the content/mode checks but corrupt on crash).
    env_path = config_dir / ".env"
    configure.write_env(
        env_path, {"SMTP_PASSWORD": "first"}, template=config_dir / ".env.example"
    )
    env_path.chmod(0o644)  # a pre-existing, world-readable .env that we then rewrite

    replaced: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy_replace(src, dst, *args, **kwargs):
        replaced.append((str(src), str(dst)))
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(configure.os, "replace", spy_replace)
    configure.write_env(
        env_path, {"SMTP_PASSWORD": "second"}, template=config_dir / ".env.example"
    )
    # The rewrite went through an atomic same-dir replace onto the real .env.
    assert any(dst == str(env_path) for _, dst in replaced)
    assert "SMTP_PASSWORD=second" in env_path.read_text(encoding="utf-8")
    assert (env_path.stat().st_mode & 0o077) == 0  # owner-only after rewrite
    assert not list(config_dir.glob(".env.tmp.*"))  # no leftover temp


# --------------------------------------------------------------------------- #
# main — end-to-end with a scripted answer queue
# --------------------------------------------------------------------------- #


def test_main_full_flow_writes_topics_sources_channels(config_dir: Path):
    answers = [
        "en",                # delivery.language
        "",                  # delivery.technical_level (blank -> balanced)
        "ai-agents",         # topic 1 name
        "",                  # finish topics
        # sources for ai-agents
        "https://example.com/feed.xml",  # url
        "rss",                            # type
        "high",                           # tier
        "",                               # blank url -> finish this topic's sources
        # channels: email
        "n",                 # enable email? no
        # telegram
        "y",                 # enable telegram? yes
        "mcp",               # transport
        "@mychannel",        # chat_id
        # (mcp transport -> no secret prompt)
        # rocketchat
        "n",                 # enable rocketchat? no
        # schedule
        "",                  # timezone (blank -> default UTC)
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)],
        ask=scripted_ask(answers),
        config_dir=config_dir,
    )
    assert rc == 0

    state = ms.list_state(config_dir)
    assert "ai-agents" in [t.name for t in state.topics]
    cats = {c.name: c for c in state.categories}
    assert "ai-agents" in cats
    urls = [s.url for s in cats["ai-agents"].sources]
    assert "https://example.com/feed.xml" in urls

    channels = (config_dir / "channels.yaml").read_text(encoding="utf-8")
    assert "language: en" in channels
    # telegram enabled with mcp transport + chat_id.
    assert "  telegram:\n    enabled: true\n" in channels
    assert 'chat_id: "@mychannel"' in channels or "chat_id: @mychannel" in channels

    schedule = (config_dir / "schedule.yaml").read_text(encoding="utf-8")
    assert 'timezone: "UTC"' in schedule


def test_main_prints_headless_activation_checklist_without_secret(
    config_dir: Path, capsys
):
    answers = [
        "en",                 # delivery.language
        "",                   # delivery.technical_level (blank -> balanced)
        "ai-agents",          # topic
        "",                   # finish topics
        "https://example.com/feed.xml",  # source url
        "rss",                # type
        "high",               # tier
        "",                   # finish sources
        "y",                  # enable email
        "smtp",               # provider
        "reader@example.com",  # recipient
        "smtp.example.com",    # SMTP host
        "reader@example.com",  # SMTP user
        "n",                  # telegram off
        "n",                  # rocketchat off
        "",                   # timezone
    ]
    secret = "smtp-password-value"

    rc = configure.main(
        ["--config-dir", str(config_dir)],
        ask=scripted_ask(answers),
        ask_secret=scripted_ask([secret]),
        config_dir=config_dir,
    )

    assert rc == 0
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "advanced no-agent / RSS Digest Lite installer" in output
    assert "Activation checklist:" in output
    assert "Setup status: ready_schedule_not_registered" in output
    assert "Source:" in output
    assert "Config:" in output
    assert "Delivery:" in output
    assert "Schedule:" in output
    assert "First value:" in output
    assert "Next action:" in output
    assert "register one recurring run for schedule/weekly-run.md" in output
    assert "SMTP_PASSWORD=SET" in output
    assert secret not in output


def test_main_telegram_botapi_writes_yaml_and_env(config_dir: Path):
    answers = [
        "en",                # language
        "",                  # audience level (blank -> balanced)
        "ai-agents",         # topic
        "",                  # finish topics
        "https://example.com/feed.xml",  # one source url
        "rss",               # type
        "high",              # tier
        "",                  # finish ai-agents sources
        "n",                 # email off
        "y",                 # telegram on
        "bot-api",           # transport
        "123456",            # chat_id
        "n",                 # rocketchat off
        "UTC",               # timezone
    ]
    # The bot token is read through the NO-ECHO `ask_secret`, never the visible `ask`.
    rc = configure.main(
        ["--config-dir", str(config_dir)],
        ask=scripted_ask(answers),
        ask_secret=scripted_ask(["999:SECRETTOKEN"]),
        config_dir=config_dir,
    )
    assert rc == 0

    channels = (config_dir / "channels.yaml").read_text(encoding="utf-8")
    assert "  telegram:\n    enabled: true\n" in channels
    assert "transport: bot-api" in channels
    # A numeric chat_id must stay a quoted string, not a bare YAML int.
    assert 'chat_id: "123456"' in channels

    env_path = config_dir / ".env"
    assert "TELEGRAM_BOT_TOKEN=999:SECRETTOKEN" in env_path.read_text(encoding="utf-8")
    # Secrets file must be owner-only (0600), not world/group readable.
    assert (env_path.stat().st_mode & 0o077) == 0


def test_write_env_locks_permissions_to_owner_only(config_dir: Path):
    env_path = config_dir / ".env"
    configure.write_env(
        env_path, {"SMTP_PASSWORD": "s3cr3t"}, template=config_dir / ".env.example"
    )
    assert (env_path.stat().st_mode & 0o077) == 0  # no group/other bits


def test_answering_no_disables_a_previously_enabled_channel(config_dir: Path):
    # Reconfiguration: a channel left enabled from a prior run must be turned OFF
    # when the user answers "no" — not silently kept enabled.
    channels_path = config_dir / "channels.yaml"
    pre = channels_path.read_text(encoding="utf-8").replace(
        "  telegram:\n    enabled: false\n", "  telegram:\n    enabled: true\n"
    )
    channels_path.write_text(pre, encoding="utf-8")
    assert "  telegram:\n    enabled: true\n" in channels_path.read_text(encoding="utf-8")

    # A complete install (one topic + source) so the empty-config gate passes; the
    # point of THIS test is the channel toggle, not topic entry.
    answers = [
        "en", "",  # language, then audience level (blank -> balanced)
        "ai-agents", "",
        "https://example.com/feed.xml", "rss", "high", "",
        "n", "n", "n", "",
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)], ask=scripted_ask(answers), config_dir=config_dir,
    )
    assert rc == 0
    assert "  telegram:\n    enabled: false\n" in channels_path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Review findings: headless-collectability advisory (was a wipe — see below)
# + transactional rollback (P2).
#
# The no-active-RSS outcome used to _restore() everything (topics, sources,
# channels, schedule, .env) — a non-dev whose only source is a blog lost every
# answer they typed. The contract now: the config is KEPT (it is valid, and the
# agentic collector handles non-RSS sources), an honest warning explains that
# the headless Lite collector would collect nothing, and only the EXIT CODE
# stays non-zero as the machine signal for wrapping automation.
# --------------------------------------------------------------------------- #


def test_empty_install_with_no_sources_warns_and_keeps_answers(config_dir: Path, capsys):
    # No sources at all: still not headless-collectable (non-zero exit), but the
    # answers the user DID give (a delivery channel here) must survive, not be
    # silently reverted to the template.
    answers = [
        "en", "",            # language, audience
        "",                  # no topics
        "n",                 # email off
        "y", "mcp", "@mychannel",  # telegram ON — real typed input to preserve
        "n",                 # rocketchat off
        "",                  # timezone
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)], ask=scripted_ask(answers), config_dir=config_dir,
    )
    assert rc != 0
    channels = (config_dir / "channels.yaml").read_text(encoding="utf-8")
    assert "  telegram:\n    enabled: true\n" in channels  # kept, not restored
    assert 'chat_id: "@mychannel"' in channels
    err = capsys.readouterr().err
    assert "no active RSS source" in err
    assert "Nothing was written" not in err  # the wipe-era wording must be gone


def test_validator_failure_rolls_back_partial_config(config_dir: Path, monkeypatch):
    # If the final validation fails, the configurator must be all-or-nothing: a
    # half-applied topic/source/channel set must NOT persist.
    before_topics = (config_dir / "topics.md").read_text(encoding="utf-8")
    before_channels = (config_dir / "channels.yaml").read_text(encoding="utf-8")
    monkeypatch.setattr(configure, "_run_validator", lambda _cfg: False)
    answers = [
        "en", "",  # language, then audience level (blank -> balanced)
        "ai-agents", "",
        "https://example.com/feed.xml", "rss", "high", "",
        "n", "n", "n", "",
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)], ask=scripted_ask(answers), config_dir=config_dir,
    )
    assert rc != 0
    assert (config_dir / "topics.md").read_text(encoding="utf-8") == before_topics
    assert (config_dir / "channels.yaml").read_text(encoding="utf-8") == before_channels


def test_successful_configure_removes_shipped_example_topic(config_dir: Path):
    # After a real install, the EXAMPLE topic/category must be gone from the
    # ACTIVE config so the agentic weekly-run never enumerates example-topic and
    # collects for it. On a fresh install the active config is the YAML twins
    # (which never carry the shipped placeholders); the .md templates stay only
    # as a dormant, ignored fallback.
    assert "## Topic: example-topic" in (config_dir / "topics.md").read_text(encoding="utf-8")
    answers = [
        "en", "",  # language, then audience level (blank -> balanced)
        "ai-agents", "",
        "https://example.com/feed.xml", "rss", "high", "",
        "n", "n", "n", "",
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)], ask=scripted_ask(answers), config_dir=config_dir,
    )
    assert rc == 0
    state = ms.list_state(config_dir)
    topic_names = [t.name for t in state.topics]
    category_names = [c.name for c in state.categories]
    assert "example-topic" not in topic_names
    assert "example-topic" not in category_names
    assert "ai-agents" in topic_names


def test_headless_advisory_counts_only_active_sources(config_dir: Path):
    # A config whose ONLY source is paused (inactive) is as headless-unusable as
    # none — the advisory must flag it (non-zero), while the paused row itself is
    # of course kept.
    ms.add_topic(config_dir, "ai-agents")
    ms.add_source(
        config_dir, topic="ai-agents", url="https://example.com/feed.xml",
        source_type="rss", tier="high", priority="medium", filter_note="all", active=True,
    )
    ms.set_source_active(config_dir, "https://example.com/feed.xml", False)  # pause it
    answers = ["en", "", "", "n", "n", "n", ""]  # audience after lang; add no new topics/sources
    rc = configure.main(
        ["--config-dir", str(config_dir)], ask=scripted_ask(answers), config_dir=config_dir,
    )
    assert rc != 0  # paused-only config is not headless-collectable
    assert "https://example.com/feed.xml" in (config_dir / "sources.md").read_text(
        encoding="utf-8"
    )  # the paused source is still there — kept, not wiped


def test_non_rss_only_sources_are_kept_with_agentic_pointer(config_dir: Path, capsys):
    # The headless collector only processes `rss`. A config whose only active
    # source is a non-RSS type (blog/webpage/medium-tag) is fully usable by the
    # AGENTIC collector, so the answers must be KEPT; the warning explains the
    # Lite limitation and names both ways out (add an RSS feed / use the agent).
    answers = [
        "en", "",  # language, then audience level (blank -> balanced)
        "ai-agents", "",
        "https://blog.example.com/", "blog", "high", "",  # one NON-rss source
        "n", "n", "n", "",
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)], ask=scripted_ask(answers), config_dir=config_dir,
    )
    assert rc != 0

    # Everything typed survives (fresh install -> the active YAML twins).
    from scripts.sources import store

    cats = store.load_categories(config_dir / "sources.yaml")
    assert [s.url for c in cats for s in c.sources] == ["https://blog.example.com/"]
    assert [t.name for t in store.load_topics(config_dir / "topics.yaml")] == ["ai-agents"]

    captured = capsys.readouterr()
    # The config was still validated and the activation checklist still shown.
    assert "Activation checklist:" in captured.out
    # Honest warning: what won't work, why, and both ways out.
    assert "no active RSS source" in captured.err
    assert "collect nothing" in captured.err
    assert "blog" in captured.err
    assert "agentic" in captured.err
    assert "kept" in captured.err
    assert "Nothing was written" not in captured.err


def test_non_rss_only_keeps_channels_and_env_secret(config_dir: Path):
    # The wipe also reverted config/.env — a typed bot token vanished with it.
    # The keep-contract covers secrets and channel config too.
    answers = [
        "en", "",
        "ai-agents", "",
        "https://blog.example.com/", "blog", "high", "",
        "n",                       # email off
        "y", "bot-api", "123456",  # telegram on, headless transport, chat id
        "n",                       # rocketchat off
        "",                        # timezone
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)],
        ask=scripted_ask(answers),
        ask_secret=scripted_ask(["999:SECRETTOKEN"]),
        config_dir=config_dir,
    )
    assert rc != 0
    channels = (config_dir / "channels.yaml").read_text(encoding="utf-8")
    assert "  telegram:\n    enabled: true\n" in channels
    assert "transport: bot-api" in channels
    env_text = (config_dir / ".env").read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=999:SECRETTOKEN" in env_text


def test_existing_env_is_hardened_even_without_new_secrets(config_dir: Path):
    # A pre-existing, world-readable .env (0644) must be locked to owner-only even
    # when this run supplies no new secret — secret hygiene applies to the file that
    # is already there, not only to freshly-written ones.
    env_path = config_dir / ".env"
    env_path.write_text("SMTP_PASSWORD=already-here\n", encoding="utf-8")
    env_path.chmod(0o644)  # simulate the exposed legacy state
    answers = [
        "en", "",  # language, then audience level (blank -> balanced)
        "ai-agents", "",
        "https://example.com/feed.xml", "rss", "high", "",
        "n", "n", "n", "",  # no secret-bearing channel enabled
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)], ask=scripted_ask(answers), config_dir=config_dir,
    )
    assert rc == 0
    assert (env_path.stat().st_mode & 0o077) == 0  # group/other bits cleared


def test_validator_raising_also_rolls_back(config_dir: Path, monkeypatch):
    # Transactional contract must hold even when the validator *raises* (not just
    # returns False) — e.g. a subprocess OSError. The partial config must roll back.
    before_topics = (config_dir / "topics.md").read_text(encoding="utf-8")

    def _boom(_cfg: Path) -> bool:
        raise RuntimeError("validator crashed")

    monkeypatch.setattr(configure, "_run_validator", _boom)
    answers = [
        "en", "",  # language, then audience level (blank -> balanced)
        "ai-agents", "",
        "https://example.com/feed.xml", "rss", "high", "",
        "n", "n", "n", "",
    ]
    with pytest.raises(RuntimeError):
        configure.main(
            ["--config-dir", str(config_dir)], ask=scripted_ask(answers), config_dir=config_dir,
        )
    assert (config_dir / "topics.md").read_text(encoding="utf-8") == before_topics


def test_keyboard_interrupt_rolls_back_partial_config(config_dir: Path):
    # Interrupting mid-run (Ctrl-C) must not leave a half-written topic behind.
    before = (config_dir / "topics.md").read_text(encoding="utf-8")
    queue = ["en", "", "ai-agents"]  # lang, audience, one topic, then interrupt next

    def _ask(_prompt: str) -> str:
        if queue:
            return queue.pop(0)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        configure.main(["--config-dir", str(config_dir)], ask=_ask, config_dir=config_dir)
    # The partial `ai-agents` topic was rolled back.
    assert (config_dir / "topics.md").read_text(encoding="utf-8") == before


def test_main_invalid_source_type_reprompts(config_dir: Path):
    answers = [
        "en",
        "",                  # audience level (blank -> balanced)
        "ai-agents",
        "",                  # finish topics
        # First attempt: invalid type -> add_source raises -> re-ask the whole row.
        "https://example.com/feed.xml",
        "bogus-type",        # invalid type
        "high",
        # Retry the row with a valid type.
        "https://example.com/feed.xml",
        "rss",
        "high",
        "",                  # blank url -> finish sources
        "n",                 # email off
        "n",                 # telegram off
        "n",                 # rocketchat off
        "",                  # timezone
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)],
        ask=scripted_ask(answers),
        config_dir=config_dir,
    )
    assert rc == 0
    cats = {c.name: c for c in ms.list_state(config_dir).categories}
    assert any(
        s.url == "https://example.com/feed.xml" for s in cats["ai-agents"].sources
    )


def test_main_final_config_validates(config_dir: Path):
    answers = [
        "en", "", "ai-agents", "",   # lang, audience, topic, finish topics
        "https://example.com/feed.xml", "rss", "high", "",  # one source, then finish
        "n", "n", "n",              # all channels off
        "",                          # timezone
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)],
        ask=scripted_ask(answers),
        config_dir=config_dir,
    )
    assert rc == 0
    # The validator agrees the written config is schema-valid.
    yaml = pytest.importorskip("yaml")
    assert validate_config.validate_channels(config_dir / "channels.yaml", yaml) == []
    assert validate_config.validate_schedule(config_dir / "schedule.yaml", yaml) == []


def test_main_writes_chosen_audience_level(config_dir: Path):
    # A non-default audience answer is written to delivery.technical_level verbatim.
    answers = [
        "en", "non-technical",  # language, audience level
        "ai-agents", "",
        "https://example.com/feed.xml", "rss", "high", "",
        "n", "n", "n", "",
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)], ask=scripted_ask(answers), config_dir=config_dir,
    )
    assert rc == 0
    channels = (config_dir / "channels.yaml").read_text(encoding="utf-8")
    assert "technical_level: non-technical" in channels


def test_main_invalid_audience_falls_back_to_balanced(config_dir: Path):
    # An off-enum audience answer must not write an invalid value — it defaults to
    # `balanced` so the final config stays schema-valid.
    answers = [
        "en", "expert",  # language, then an UNSUPPORTED audience value
        "ai-agents", "",
        "https://example.com/feed.xml", "rss", "high", "",
        "n", "n", "n", "",
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)], ask=scripted_ask(answers), config_dir=config_dir,
    )
    assert rc == 0
    channels = (config_dir / "channels.yaml").read_text(encoding="utf-8")
    assert "technical_level: balanced" in channels
    assert "expert" not in channels


def test_main_reconfigure_legacy_channels_without_audience_key(config_dir: Path):
    # Backward-compat: a channels.yaml predating delivery.technical_level (no such
    # line, as on an install created before the knob existed) must not crash
    # reconfigure — the key is inserted under delivery rather than raising KeyError.
    channels_path = config_dir / "channels.yaml"
    legacy = "".join(
        f"{ln}\n"
        for ln in channels_path.read_text(encoding="utf-8").splitlines()
        if "technical_level" not in ln
    )
    assert "technical_level" not in legacy
    channels_path.write_text(legacy, encoding="utf-8")

    answers = [
        "en", "non-technical",  # language, audience
        "ai-agents", "",
        "https://example.com/feed.xml", "rss", "high", "",
        "n", "n", "n", "",
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)], ask=scripted_ask(answers), config_dir=config_dir,
    )
    assert rc == 0
    channels = channels_path.read_text(encoding="utf-8")
    assert "technical_level: non-technical" in channels


# --------------------------------------------------------------------------- #
# Headless-capable channel defaults. This is the self-described "advanced
# no-agent / RSS Digest Lite installer": its blank-answer defaults must be the
# transports that actually deliver under cron (smtp / bot-api), not the
# agent-only ones (gmail-mcp / mcp) that a headless run skips.
# --------------------------------------------------------------------------- #


def test_blank_email_provider_defaults_to_smtp(config_dir: Path):
    answers = [
        "en", "",
        "ai-agents", "",
        "https://example.com/feed.xml", "rss", "high", "",
        "y",                   # enable email
        "",                    # provider: BLANK -> must default to smtp
        "reader@example.com",  # recipient
        "smtp.example.com",    # SMTP host (the smtp default leads here)
        "reader@example.com",  # SMTP user
        "n", "n", "",          # telegram off, rocketchat off, timezone
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)],
        ask=scripted_ask(answers),
        ask_secret=scripted_ask([""]),  # blank password -> fill .env later
        config_dir=config_dir,
    )
    assert rc == 0
    channels = (config_dir / "channels.yaml").read_text(encoding="utf-8")
    # Anchor to the value line — the template's inline comments also name the
    # alternative transports, so a substring match would lie.
    assert re.search(r"(?m)^\s+provider: smtp\b", channels)
    assert not re.search(r"(?m)^\s+provider: gmail-mcp\b", channels)


def test_blank_telegram_transport_defaults_to_bot_api(config_dir: Path):
    answers = [
        "en", "",
        "ai-agents", "",
        "https://example.com/feed.xml", "rss", "high", "",
        "n",         # email off
        "y",         # enable telegram
        "",          # transport: BLANK -> must default to bot-api
        "123456",    # chat id
        "n", "",     # rocketchat off, timezone
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)],
        ask=scripted_ask(answers),
        ask_secret=scripted_ask([""]),  # blank token -> fill .env later
        config_dir=config_dir,
    )
    assert rc == 0
    channels = (config_dir / "channels.yaml").read_text(encoding="utf-8")
    assert re.search(r"(?m)^\s+transport: bot-api\b", channels)
    assert not re.search(r"(?m)^\s+transport: mcp\b", channels)


def test_explicit_agent_only_transports_get_an_inline_note(config_dir: Path, capsys):
    # Choosing gmail-mcp / mcp here is legitimate (the user may run digests from
    # an agent and only use this installer for the interview) — but the prompt
    # must say out loud that a cron/headless run skips those channels.
    answers = [
        "en", "",
        "ai-agents", "",
        "https://example.com/feed.xml", "rss", "high", "",
        "y", "gmail-mcp", "reader@example.com",  # email via agent-only provider
        "y", "mcp", "@mychannel",                # telegram via agent-only transport
        "n", "",
    ]
    rc = configure.main(
        ["--config-dir", str(config_dir)], ask=scripted_ask(answers), config_dir=config_dir,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert out.count("only inside an agent") >= 2, (
        "picking gmail-mcp / mcp in the no-agent installer must note that "
        "cron/headless runs skip those channels"
    )


def test_main_non_tty_no_input_guard(config_dir: Path, monkeypatch):
    """A non-interactive shell with no scripted ask exits non-zero, not blocked."""
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(""))  # not a TTY
    rc = configure.main(["--config-dir", str(config_dir)], config_dir=config_dir)
    assert rc != 0


# --------------------------------------------------------------------------- #
# YAML config format (CONVENTIONS §2.3): fresh installs get the YAML twins;
# legacy installs with real .md content keep their format (update.sh offers
# the migration — the installer never silently flips a working config).
# --------------------------------------------------------------------------- #

_FRESH_ANSWERS = [
    "en", "",                                  # language, audience
    "ai-agents", "",                           # one topic
    "https://example.com/feed.xml", "rss", "high", "",  # one source
    "n", "n", "n", "",                         # channels off, timezone default
]


def test_fresh_install_writes_yaml_config(config_dir: Path):
    rc = configure.main(
        ["--config-dir", str(config_dir)], ask=scripted_ask(list(_FRESH_ANSWERS)),
        config_dir=config_dir,
    )
    assert rc == 0
    assert (config_dir / "sources.yaml").exists()
    assert (config_dir / "topics.yaml").exists()
    from scripts.sources import store

    cats = store.load_categories(config_dir / "sources.yaml")
    assert [c.name for c in cats] == ["ai-agents"]
    assert [s.url for s in cats[0].sources] == ["https://example.com/feed.xml"]
    topics = store.load_topics(config_dir / "topics.yaml")
    assert [t.name for t in topics] == ["ai-agents"]
    # The shipped .md templates are untouched (dormant fallback, ignored).
    assert "## Topic: example-topic" in (config_dir / "topics.md").read_text(encoding="utf-8")


def test_unmigrated_legacy_install_is_refused_with_pointer(config_dir: Path, capsys):
    # 0.8.0 (YAML-only): an existing install whose real config still lives in
    # the retired .md files is REFUSED before any prompt or write — with the
    # one-command migration pointer. Never a silent flip, never an orphaned
    # config, never an interview over a config the runtime can't read.
    (config_dir / "sources.md").write_text(
        "## Category: existing-topic\n\n"
        "| URL | Type | Tier | Priority | Filter | Active |\n"
        "|---|---|---|---|---|---|\n"
        "| https://old.example.com/feed | rss | medium | medium | all | yes |\n",
        encoding="utf-8",
    )
    rc = configure.main(
        ["--config-dir", str(config_dir)], ask=scripted_ask([]), config_dir=config_dir,
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "migrate-config" in err
    # Nothing was created or touched.
    assert not (config_dir / "sources.yaml").exists()
    assert not (config_dir / "topics.yaml").exists()


def test_failed_fresh_install_rolls_back_seeded_yaml(config_dir: Path, monkeypatch):
    # The transactional contract covers the new YAML twins too: a failed run
    # must remove the seeded files, not leave a half-initialized YAML config.
    monkeypatch.setattr(configure, "_run_validator", lambda _cfg: False)
    rc = configure.main(
        ["--config-dir", str(config_dir)], ask=scripted_ask(list(_FRESH_ANSWERS)),
        config_dir=config_dir,
    )
    assert rc != 0
    assert not (config_dir / "sources.yaml").exists()
    assert not (config_dir / "topics.yaml").exists()
