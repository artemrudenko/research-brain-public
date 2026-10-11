"""
test_help_card.py — integrity tests for the canned `/help` card.

The `capabilities` skill must emit a PREPARED, verbatim card (not an
LLM-assembled menu), so the help reply is deterministic and — crucially —
operationally accurate about which slash commands actually reach the agent.

These tests pin three properties of `skills/capabilities/help-card.md`:

1. Every project command that DOES reach the agent is advertised.
2. The card warns that `/help`, `/status`, `/start` are swallowed by the
   Telegram plugin and never reach the project (use the bare word instead).
3. The swallowed commands are NOT advertised as working project commands —
   they appear only inside the warning, so the card can't mislead the user
   (the exact bug the generated menu had: it listed `/help` and `/status`).

The command list is DERIVED from `docs/telegram-commands.md`, which declares
itself the source of truth for the menu — a hardcoded copy here went stale the
moment `/new`, `/trends`, `/know`, `/concept`, `/author` and `/audience` shipped.
The last section pins the whole four-surface chain (SSOT table ↔ BotFather block
↔ CLAUDE.md routing table ↔ both help cards), because a command advertised in one
place and missing from another is either a dead menu button or — via CLAUDE.md's
"unrecognized slash → auto-help" rule — a documented trigger that silently
answers with the help card instead of doing the work.
"""
import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

HELP_CARD = _PROJECT_ROOT / "skills" / "capabilities" / "help-card.md"
TELEGRAM_COMMANDS_DOC = _PROJECT_ROOT / "docs" / "telegram-commands.md"

# First inline-code token of a Markdown table row: `/new`, `status` (bare word), …
_ROW_TOKEN = re.compile(r"^\|\s*`([^`]+)`", re.MULTILINE)
# The BotFather `/setcommands` block: `new - What's new? …` (no leading slash).
_BOTFATHER_BLOCK = re.compile(r"```\n(new - .*?)```", re.DOTALL)


def _first_word(token: str) -> str:
    """`/concept <sub>` → `/concept`; `status` → `status`."""
    return token.split()[0]


def _slash_commands(tokens: list[str]) -> set[str]:
    """Base slash commands (`/concept new` and `/concept list` are one command)."""
    return {_first_word(t) for t in tokens if t.startswith("/")}


def _ssot_commands() -> set[str]:
    """Slash commands in the source-of-truth "What each command does" table."""
    text = TELEGRAM_COMMANDS_DOC.read_text(encoding="utf-8")
    return _slash_commands(_ROW_TOKEN.findall(text))


# Commands that route through to a project skill — read from the SSOT so this
# list cannot fall behind the product (sorted for stable failure messages).
WORKING_COMMANDS = sorted(_ssot_commands())

# Commands the official Telegram plugin intercepts before the agent sees them.
INTERCEPTED_COMMANDS = ["/help", "/status", "/start"]

# The card splits into a "working commands" half and a "warning" half at the
# first warning marker; the test reasons about each half independently.
WARNING_MARKER = "⚠️"


@pytest.fixture(scope="module")
def card_text() -> str:
    assert HELP_CARD.exists(), f"missing canned help card: {HELP_CARD}"
    return HELP_CARD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def card_halves(card_text: str) -> tuple[str, str]:
    """(commands_half, warning_half) split at the first warning marker."""
    assert WARNING_MARKER in card_text, "help card must contain a ⚠️ warning block"
    head, _, tail = card_text.partition(WARNING_MARKER)
    return head, tail


def test_advertises_every_working_command(card_halves: tuple[str, str]) -> None:
    commands_half, _ = card_halves
    for cmd in WORKING_COMMANDS:
        assert cmd in commands_half, f"{cmd} missing from the working-command list"


def test_warns_about_plugin_interception(card_halves: tuple[str, str]) -> None:
    _, warning_half = card_halves
    for cmd in INTERCEPTED_COMMANDS:
        assert cmd in warning_half, f"{cmd} not named in the interception warning"
    lowered = warning_half.lower()
    # Must explain WHY (plugin intercepts) and the workaround (bare word).
    assert "plugin" in lowered or "плагин" in lowered, "warning omits the plugin cause"


def test_does_not_advertise_intercepted_commands_as_working(
    card_halves: tuple[str, str],
) -> None:
    commands_half, _ = card_halves
    for cmd in INTERCEPTED_COMMANDS:
        assert cmd not in commands_half, (
            f"{cmd} is intercepted by the plugin but is advertised as a working "
            "project command — this is the exact bug the prepared card must avoid"
        )


def test_positive_bare_word_status_pointer(card_halves: tuple[str, str]) -> None:
    """The card must POSITIVELY point users to a health/status check, phrased as
    the bare word `status` (never `/status`), so status is discoverable outside
    the interception warning — not only mentioned as a thing that doesn't work.
    """
    commands_half, _ = card_halves
    assert "status" in commands_half.lower(), (
        "card gives no positive pointer to a health/status check"
    )
    # The positive pointer must use the BARE word, never re-introduce `/status`
    # (that would mislead the user — the exact bug we're guarding against).
    assert "/status" not in commands_half, (
        "the status pointer must use the bare word `status`, never `/status`"
    )


# --------------------------------------------------------------------------- #
# RU twin (2026-07-14 review P1): the auto-help card is the FIRST thing the bot
# ever says — for the RU-first persona it was a 45-line English wall. The RU
# twin must exist, advertise the SAME command set, carry the same ⚠️ warning
# contract, and be named by the auto-help rule so Russian chats get it.
# --------------------------------------------------------------------------- #

RU_HELP_CARD = _PROJECT_ROOT / "skills" / "capabilities" / "help-card.ru.md"

_CMD_RE = re.compile(r"`(/[a-z]+)")


@pytest.fixture(scope="module")
def ru_card_text() -> str:
    assert RU_HELP_CARD.exists(), f"missing RU help card twin: {RU_HELP_CARD}"
    return RU_HELP_CARD.read_text(encoding="utf-8")


def test_ru_card_is_actually_russian(ru_card_text: str) -> None:
    assert re.search(r"[а-яА-Я]", ru_card_text), "the RU card must be written in Russian"


def test_ru_card_mirrors_the_en_command_set(card_text: str, ru_card_text: str) -> None:
    en_commands = set(_CMD_RE.findall(card_text))
    ru_commands = set(_CMD_RE.findall(ru_card_text))
    assert ru_commands == en_commands, (
        "the RU card must advertise exactly the EN card's commands "
        f"(missing: {sorted(en_commands - ru_commands)}, "
        f"extra: {sorted(ru_commands - en_commands)})"
    )


def test_ru_card_keeps_the_bare_word_warning_contract(ru_card_text: str) -> None:
    assert WARNING_MARKER in ru_card_text
    head, _, tail = ru_card_text.partition(WARNING_MARKER)
    for command in INTERCEPTED_COMMANDS:
        assert command not in head, (
            f"RU card advertises intercepted {command} outside the warning block"
        )
        assert command in tail, f"RU card's warning must name {command}"
    # The bare words themselves are advertised.
    assert "`help`" in ru_card_text
    assert "`status`" in ru_card_text


def test_auto_help_rule_names_the_ru_card() -> None:
    claude_md = (_PROJECT_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "help-card.ru.md" in claude_md, (
        "CLAUDE.md auto-help must route Russian chats to the RU card"
    )
    docs = (_PROJECT_ROOT / "docs" / "telegram-commands.md").read_text(encoding="utf-8")
    assert "help-card.ru.md" in docs, (
        "docs/telegram-commands.md (source of truth) must name the RU twin"
    )


def test_cards_carry_the_bot_takeover_recovery_hint(
    card_text: str, ru_card_text: str
) -> None:
    """One bot token allows ONE live listener; the newest session silently
    steals the bot (docs-only knowledge until now). The card — what the user
    sees exactly when the bot 'stopped answering' — must name the recovery."""
    for text in (card_text, ru_card_text):
        assert "make telegram" in text, (
            "help cards must carry the token-steal recovery hint (make telegram)"
        )


# --------------------------------------------------------------------------- #
# Four-surface parity. `docs/telegram-commands.md` declares itself the source of
# truth; CLAUDE.md's table is what the agent actually routes on, the BotFather
# block is the menu the user registers, and the cards are what a new chat is
# shown. Any surface that falls behind produces a real defect: a menu button
# that does nothing, or a documented trigger that CLAUDE.md's "unrecognized
# slash command → auto-help" rule answers with the help card instead.
# --------------------------------------------------------------------------- #


def test_ssot_table_has_commands() -> None:
    """Guard the parser itself — an empty set would make every parity test pass."""
    assert _ssot_commands(), "parsed no slash commands out of the SSOT table"


def test_botfather_block_matches_the_ssot_table() -> None:
    text = TELEGRAM_COMMANDS_DOC.read_text(encoding="utf-8")
    block = _BOTFATHER_BLOCK.search(text)
    assert block, "docs/telegram-commands.md lost its BotFather `/setcommands` block"
    # The block is pasted verbatim into BotFather: `command - description`.
    registered = {f"/{line.split(' - ')[0].strip()}" for line in
                  block.group(1).strip().splitlines() if line.strip()}
    assert registered == _ssot_commands(), (
        "the BotFather menu block and the command table disagree "
        f"(only in menu: {sorted(registered - _ssot_commands())}, "
        f"only in table: {sorted(_ssot_commands() - registered)})"
    )


def test_claude_md_routing_table_matches_the_ssot_table() -> None:
    text = (_PROJECT_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    routed = _slash_commands(_ROW_TOKEN.findall(text))
    assert routed == _ssot_commands(), (
        "CLAUDE.md's Telegram command table drifted from the source of truth "
        f"(only in CLAUDE.md: {sorted(routed - _ssot_commands())}, "
        f"only in docs: {sorted(_ssot_commands() - routed)}) — a command missing "
        "here is swallowed by the auto-help rule instead of running"
    )


def test_user_guide_command_table_matches_the_ssot_table() -> None:
    """USER_GUIDE §6 reprints the menu for readers who never open docs/ — an
    omission there reads as "that command doesn't exist"."""
    text = (_PROJECT_ROOT / "USER_GUIDE.md").read_text(encoding="utf-8")
    listed = _slash_commands(_ROW_TOKEN.findall(text))
    assert listed == _ssot_commands(), (
        "USER_GUIDE's Telegram command table drifted from the source of truth "
        f"(only in USER_GUIDE: {sorted(listed - _ssot_commands())}, "
        f"only in docs: {sorted(_ssot_commands() - listed)})"
    )


@pytest.mark.parametrize("card", ["help-card.md", "help-card.ru.md"])
def test_help_cards_advertise_every_ssot_command(card: str) -> None:
    text = (_PROJECT_ROOT / "skills" / "capabilities" / card).read_text(encoding="utf-8")
    advertised = _slash_commands(_CMD_RE.findall(text))
    missing = sorted(_ssot_commands() - advertised)
    assert not missing, f"{card} does not advertise: {missing}"
