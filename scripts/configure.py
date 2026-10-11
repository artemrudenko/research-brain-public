#!/usr/bin/env python3
"""
configure.py — interactive, no-agent config installer for research-brain.

The `setup-wizard` skill writes the whole `config/` interactively, but only
inside an agent (Claude Code / Cowork). A headless / Codex / cron user has no
interactive config tool — they hand-edit files. This script fills that gap: a
terminal installer that asks the same questions and writes `config/`, reusing
the SAME deterministic backend the skill uses (`manage_sources`). It complements
(does not replace) the wizard.

Design for testability: ALL prompting goes through an injectable `ask` callable
(`ask(prompt) -> str`, defaulting to `input`). Tests pass a scripted `ask` that
pops queued answers, so the whole flow is hermetic — `input()` is never called
directly anywhere except as that default arg.

The two commented YAML templates (`channels.yaml`, `schedule.yaml`) are edited
value-by-value via `set_block_field`, which preserves their structure and inline
comments (it swaps only the value of a matched field). Secrets are never written
into YAML — only an env-var NAME stays there; the real value goes to `config/.env`
via `write_env` (CONVENTIONS §8).

CLI:
    python3 scripts/configure.py [--config-dir PATH]
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import subprocess  # the project's own validator only, fixed argv, no shell  # nosec B404
import sys
from collections.abc import Callable
from pathlib import Path

# Resolve the project root from this file's location (scripts/ -> root) so the
# module works no matter the current working directory (CONVENTIONS §1).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"

# Make `scripts` importable when run directly as a script (mirrors the rest of
# the scripts/ tree), so the shared manage_sources backend resolves.
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import manage_sources as ms  # noqa: E402
from scripts import setup_check  # noqa: E402
from scripts.sources import store as sources_store  # noqa: E402

# An injected prompt function: takes the prompt text, returns the user's reply.
# `input` is the production default; tests inject a scripted closure.
AskFn = Callable[[str], str]


# --------------------------------------------------------------------------- #
# Pure, testable text helpers (no I/O) — names are part of the test contract.
# --------------------------------------------------------------------------- #


def set_block_field(text: str, parent: str | None, field: str, value: str) -> str:
    """Comment-preserving YAML value edit.

    When `parent` is given, find the block introduced by `^(\\s*)parent:` and edit
    the FIRST `^(\\s+)field:` line strictly inside it (the block runs until the next
    non-blank line whose indent is <= the parent's indent, or EOF). When `parent`
    is None, edit the FIRST root-level `^field:` line directly.

    Only the value is swapped: the `<indent>field:` lead and any trailing inline
    `# comment` are preserved byte-for-byte. Raises KeyError if the parent or the
    field is not found (a typo must fail loudly, not silently no-op).
    """
    lines = text.splitlines(keepends=True)

    # Determine the [start, end) line span to search for `field:` within.
    if parent is None:
        search_start, search_end, indent_floor = 0, len(lines), -1
    else:
        parent_idx, parent_indent = _find_block(lines, parent)
        if parent_idx is None:
            raise KeyError(f"parent block {parent!r} not found")
        search_start = parent_idx + 1
        # The block ends at the first later line whose indent is <= the parent's.
        search_end = _block_end(lines, search_start, parent_indent)
        # Inside a block we still want only deeper-indented fields (defensive).
        indent_floor = parent_indent

    field_re = re.compile(rf"^(\s*){re.escape(field)}:(.*)$")
    for i in range(search_start, search_end):
        match = field_re.match(lines[i].rstrip("\n"))
        if not match:
            continue
        line_indent = len(match.group(1))
        # A root edit (parent is None) requires column-0; a nested edit requires
        # the field be deeper than its parent (not the parent line itself).
        if parent is None and line_indent != 0:
            continue
        if parent is not None and line_indent <= indent_floor:
            continue
        lines[i] = _replace_value(match.group(1), field, match.group(2), value)
        return "".join(lines)

    where = "root" if parent is None else f"block {parent!r}"
    raise KeyError(f"field {field!r} not found in {where}")


def insert_block_field(
    text: str, parent: str, field: str, value: str, *, after: str
) -> str:
    """Insert `<indent>field: value` into `parent`'s block, right after its
    `after:` line (matching that line's indent).

    Forward-compat companion to `set_block_field`: a config file written before a
    given field existed has no line to edit, so editing would raise. This adds the
    missing field instead, so reconfiguring an older install never crashes. Raises
    KeyError if the parent block or the `after` anchor line is not found.
    """
    lines = text.splitlines(keepends=True)
    parent_idx, parent_indent = _find_block(lines, parent)
    if parent_idx is None:
        raise KeyError(f"parent block {parent!r} not found")
    end = _block_end(lines, parent_idx + 1, parent_indent)
    anchor_re = re.compile(rf"^(\s+){re.escape(after)}:")
    for i in range(parent_idx + 1, end):
        match = anchor_re.match(lines[i].rstrip("\n"))
        if match and len(match.group(1)) > parent_indent:
            lines.insert(i + 1, f"{match.group(1)}{field}: {value}\n")
            return "".join(lines)
    raise KeyError(f"anchor field {after!r} not found in block {parent!r}")


def _find_block(lines: list[str], parent: str) -> tuple[int | None, int]:
    """Return (line_index, indent) of the `^(\\s*)parent:` line (or (None, -1))."""
    block_re = re.compile(rf"^(\s*){re.escape(parent)}:\s*$")
    # Also accept `parent:` carrying an inline value/comment after the colon, so a
    # block header like `delivery:` and a scalar parent both resolve.
    block_re_any = re.compile(rf"^(\s*){re.escape(parent)}:(\s|$)")
    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        match = block_re.match(line) or block_re_any.match(line)
        if match:
            return i, len(match.group(1))
    return None, -1


def _block_end(lines: list[str], start: int, parent_indent: int) -> int:
    """Index where a block ends: the first non-blank line indented <= the parent."""
    for i in range(start, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            continue
        indent = len(lines[i]) - len(lines[i].lstrip(" "))
        if indent <= parent_indent:
            return i
    return len(lines)


def _replace_value(indent: str, field: str, tail: str, value: str) -> str:
    """Rebuild a `field:` line with a new value, keeping a trailing `# comment`.

    `tail` is everything after `field:` on the original line (value + comment).
    """
    comment = ""
    comment_match = re.search(r"(\s+#.*)$", tail)
    if comment_match:
        comment = comment_match.group(1)
    return f"{indent}{field}: {value}{comment}\n"


def write_env(env_path: Path, secrets: dict[str, str], *, template: Path) -> None:
    """Create `config/.env` from the template if absent, then set supplied keys.

    For each non-empty `KEY: value` in `secrets`, replace the template's
    placeholder line `KEY=...` with `KEY=value`; every other line is left at its
    template default. Only keys the user actually supplied are written, so an
    unconfigured channel keeps its harmless placeholder. The secret value is
    never echoed — it is written to the gitignored .env only, which is locked to
    owner-only (0600) so other local users can't read the credentials.
    """
    if not env_path.exists():
        # Create with 0o600 from the first byte: open the fd with the owner-only mode
        # so the secret is never written into a world/group-readable file (closing a
        # race where another local user could read it between write_text and chmod).
        fd = os.open(str(env_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(template.read_text(encoding="utf-8"))
    env_path.chmod(0o600)  # re-assert owner-only (existing file may predate this)

    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    for key, value in secrets.items():
        if not value:
            continue  # blank == "I'll fill .env later" — don't touch the line
        key_re = re.compile(rf"^{re.escape(key)}=")
        replaced = False
        for i, line in enumerate(lines):
            if key_re.match(line):
                lines[i] = f"{key}={value}\n"
                replaced = True
                break
        if not replaced:
            # Key absent from the template entirely — append it (no duplicates,
            # since the loop above only reaches here when no line matched).
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines.append(f"{key}={value}\n")
    # Atomic + owner-only rewrite: write the secrets to a same-dir temp opened at
    # 0o600 (so the secret is never group/world-readable, even transiently), then
    # os.replace so a crash mid-write can't truncate the existing .env. A plain
    # write_text would leave both windows open; atomic_write_text would close the
    # truncation window but expose the secret in a default-mode temp file.
    tmp = env_path.with_name(f"{env_path.name}.tmp.{os.getpid()}")
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("".join(lines))
        os.replace(tmp, env_path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    env_path.chmod(0o600)  # re-assert owner-only after the rewrite


def enabled_channels(answers: dict[str, bool]) -> list[str]:
    """Return the channel names the user toggled on (stable order)."""
    return [name for name in ("email", "telegram", "rocketchat") if answers.get(name)]


# --------------------------------------------------------------------------- #
# Interactive prompt helpers (thin wrappers around the injected `ask`)
# --------------------------------------------------------------------------- #


def _ask_yes_no(ask: AskFn, prompt: str) -> bool:
    """Prompt until the reply is an unambiguous yes/no; return the boolean."""
    while True:
        reply = ask(f"{prompt} [y/n]: ").strip().lower()
        if reply in ("y", "yes"):
            return True
        if reply in ("n", "no"):
            return False
        print("  Please answer y or n.")


def _yaml_str(value: str) -> str:
    """Quote a scalar for YAML so values like `@channel` / leading-zero ids are safe.

    A leading `@`, `#`, or `*`, or a value that isn't a plain word, is wrapped in
    double quotes; a simple token (letters/digits/.-_/:) is left bare so the
    template stays readable.
    """
    if value and re.fullmatch(r"[A-Za-z0-9_.:\-]+", value) and value[0].isalnum():
        return value
    return '"' + value.replace('"', '\\"') + '"'


# --------------------------------------------------------------------------- #
# Interactive flow steps
# --------------------------------------------------------------------------- #


def _seed_yaml_config(config_dir: Path) -> bool:
    """Ensure the YAML config twins exist (YAML-only since 0.8.0).

    Fresh dirs get empty twins so every `manage_sources` write has its files.
    An UNMIGRATED legacy dir (.md with real content, no YAML) raises with the
    one-command pointer — this installer never silently flips or orphans a
    working config; `schema.py migrate-config` is the explicit user action.
    Returns True when anything was created.
    """
    return sources_store.ensure_yaml_config(config_dir)


def _configure_topics_and_sources(ask: AskFn, config_dir: Path) -> None:
    """Ask for topics, then for each topic ask for its sources; write via backend."""
    topics: list[str] = []
    print("\nTopics — what subjects should the brain monitor? (blank to finish)")
    while True:
        name = ask("  Topic name (blank to finish): ").strip()
        if not name:
            break
        try:
            ms.add_topic(config_dir, name)
        except ValueError as exc:
            print(f"  {exc}")
            continue
        topics.append(name)

    # Once the user has added real topics, drop the shipped EXAMPLE sections so the
    # agentic weekly-run (which lists every `## Topic:`) never collects example-topic.
    if topics:
        ms.strip_example_sections(config_dir)

    for topic in topics:
        print(f"\nSources for `{topic}` — add feeds/pages (blank URL to finish).")
        while True:
            url = ask("  Source URL (blank to finish): ").strip()
            if not url:
                break
            source_type = ask(f"    Type {ms.SOURCE_TYPES}: ").strip()
            tier = ask(f"    Tier {ms.TIERS}: ").strip()
            try:
                ms.add_source(
                    config_dir,
                    topic=topic,
                    url=url,
                    source_type=source_type,
                    tier=tier,
                    priority="medium",
                    filter_note="all",
                    active=True,
                )
            except ValueError as exc:
                # Validation rejected one of the values — report and re-ask the URL.
                print(f"    {exc}")


def _configure_email(ask: AskFn, ask_secret: AskFn, text: str, secrets: dict[str, str]) -> str:
    """Edit channels.yaml text for the email channel; collect any SMTP secret.

    The blank-answer default is `smtp` — the transport that actually delivers on
    the cron/headless path this no-agent installer sets up. `gmail-mcp` stays
    choosable for users who deliver from inside an agent, with an inline note
    that headless runs skip it.
    """
    if not _ask_yes_no(ask, "Enable email digests?"):
        # Explicitly DISABLE so re-running the installer can turn a channel off.
        return set_block_field(text, "email", "enabled", "false")
    text = set_block_field(text, "email", "enabled", "true")
    provider = (
        ask("  Email provider [smtp | gmail-mcp] (default smtp — works on cron): ").strip()
        or "smtp"
    )
    if provider == "gmail-mcp":
        print(
            "  note: gmail-mcp delivers only inside an agent (Cowork / Claude Code) — "
            "a headless/cron run skips this channel."
        )
    text = set_block_field(text, "email", "provider", provider)
    recipient = ask("  Recipient address: ").strip()
    text = set_block_field(text, "email", "to", f'["{recipient}"]')
    if provider == "smtp":
        host = ask("  SMTP host (e.g. smtp.gmail.com): ").strip()
        text = set_block_field(text, "smtp", "host", _yaml_str(host))
        user = ask("  SMTP user: ").strip()
        text = set_block_field(text, "smtp", "user", _yaml_str(user))
        # Secret prompt is no-echo (getpass) so the password isn't shown on screen.
        password = ask_secret("  SMTP password (blank to fill .env later): ").strip()
        if password:
            secrets["SMTP_PASSWORD"] = password
    return text


def _configure_telegram(ask: AskFn, ask_secret: AskFn, text: str, secrets: dict[str, str]) -> str:
    """Edit channels.yaml text for the telegram channel; collect any bot token.

    Blank-answer default is `bot-api` (delivers under cron/headless — what this
    installer targets); `mcp` stays choosable with an agent-only inline note.
    """
    if not _ask_yes_no(ask, "Enable Telegram digests?"):
        return set_block_field(text, "telegram", "enabled", "false")
    text = set_block_field(text, "telegram", "enabled", "true")
    transport = (
        ask("  Telegram transport [bot-api | mcp] (default bot-api — works on cron): ").strip()
        or "bot-api"
    )
    if transport == "mcp":
        print(
            "  note: the mcp transport delivers only inside an agent (Cowork / "
            "Claude Code) — a headless/cron run skips this channel."
        )
    text = set_block_field(text, "telegram", "transport", transport)
    chat_id = ask("  Chat id (numeric) or @channel: ").strip()
    # chat_id is an identifier, never a number to compute with — always quote it so
    # a numeric id stays a YAML string (matching the shipped template / schema and
    # the working live config), not an int.
    text = set_block_field(text, "telegram", "chat_id", f'"{chat_id}"')
    if transport == "bot-api":
        token = ask_secret("  Bot token (blank to fill .env later): ").strip()
        if token:
            secrets["TELEGRAM_BOT_TOKEN"] = token
    return text


def _configure_rocketchat(ask: AskFn, ask_secret: AskFn, text: str, secrets: dict[str, str]) -> str:
    """Edit channels.yaml text for rocketchat; collect any webhook URL secret."""
    if not _ask_yes_no(ask, "Enable Rocket.Chat digests?"):
        return set_block_field(text, "rocketchat", "enabled", "false")
    text = set_block_field(text, "rocketchat", "enabled", "true")
    webhook = ask_secret("  Incoming webhook URL (blank to fill .env later): ").strip()
    if webhook:
        secrets["ROCKETCHAT_WEBHOOK_URL"] = webhook
    return text


def _run_validator(config_dir: Path) -> bool:
    """Run validate_config.py against the written config; print + return its verdict."""
    # B603 rationale: fixed argv (this interpreter + our own validator script + a path),
    # no shell, no untrusted input — it cannot be steered to run anything else.
    result = subprocess.run(  # nosec B603
        [sys.executable, str(PROJECT_ROOT / "scripts" / "validate_config.py"), str(config_dir)],
        capture_output=True,
        text=True,
    )
    output = (result.stdout + result.stderr).strip()
    print(output)
    return result.returncode == 0


def _print_activation_check(config_dir: Path) -> None:
    """Render the shared headless activation checklist for this config directory."""
    result = setup_check.run_setup_check(
        config_dir.parent,
        runtime="headless",
        scheduler_state="ready-not-registered",
    )
    print("\nActivation checklist:")
    print(setup_check.render_human(result))


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(
    argv: list[str] | None = None,
    *,
    ask: AskFn = input,
    ask_secret: AskFn = getpass.getpass,
    config_dir: Path | None = None,
) -> int:
    """Run the interactive installer. Returns 0 on success, non-zero on a fatal error.

    `ask` is the injectable prompt function (defaults to `input`); `ask_secret` is
    the no-echo prompt for credentials (defaults to `getpass.getpass`) so passwords
    and tokens are never shown on screen. Both are injectable so tests pass scripted
    closures. `config_dir` overrides the target directory directly (tests use a tmp
    copy of the templates); the CLI `--config-dir` is the user-facing path.
    """
    parser = argparse.ArgumentParser(
        description="Interactive, no-agent config installer for research-brain."
    )
    parser.add_argument(
        "--config-dir",
        default=str(DEFAULT_CONFIG_DIR),
        help="config directory to write (default: project config/)",
    )
    args = parser.parse_args(argv)

    if config_dir is None:
        config_dir = Path(args.config_dir)

    # Guard a non-interactive shell: if stdin is not a TTY AND no scripted `ask`
    # was injected, we'd block forever on input — refuse clearly instead.
    if ask is input and not sys.stdin.isatty():
        print(
            "configure.py needs a terminal. Run me in an interactive shell, or use "
            "the setup-wizard skill inside an agent (Claude Code / Cowork).",
            file=sys.stderr,
        )
        return 1

    if sources_store.legacy_md_needs_migration(config_dir):
        print(
            "configure.py: your config is still in the retired .md format — run "
            "`python3 scripts/schema.py migrate-config` first (it converts "
            "sources.md/topics.md to the YAML config; the .md files are left "
            "untouched), then re-run this installer.",
            file=sys.stderr,
        )
        return 1

    print("research-brain — interactive config installer")
    print(
        "This is the advanced no-agent / RSS Digest Lite installer. For the full "
        'agentic research-brain path, open the project in Cowork or Claude Code and say '
        '"let\'s set up sources".'
    )
    print(f"Writing config to: {config_dir}\n")

    channels_path = config_dir / "channels.yaml"
    schedule_path = config_dir / "schedule.yaml"
    env_template = config_dir / ".env.example"

    # Transactional snapshot: configure mutates several files (topics/sources/tags
    # via the manage_sources backend, plus channels/schedule/.env). Capture every
    # one up front so a failure — an exception, a Ctrl-C, or an invalid final config
    # — restores the previous state exactly, instead of leaving a half-applied mess.
    managed = [
        channels_path, schedule_path,
        config_dir / "topics.md", config_dir / "sources.md",
        config_dir / "topics.yaml", config_dir / "sources.yaml",
        config_dir / "tags.yaml", config_dir / ".env",
    ]
    snapshot = {p: (p.read_bytes() if p.exists() else None) for p in managed}

    def _restore() -> None:
        for path, data in snapshot.items():
            if data is None:
                path.unlink(missing_ok=True)  # it didn't exist before — remove it
            else:
                path.write_bytes(data)

    try:
        # Read the existing commented templates as the base text to edit (so comments
        # and structure are preserved — we edit values, not the files' shape).
        channels_text = channels_path.read_text(encoding="utf-8")
        schedule_text = schedule_path.read_text(encoding="utf-8")

        # 1) Language.
        language = ask("Digest language [en | ru | ...] (default en): ").strip() or "en"
        channels_text = set_block_field(channels_text, "delivery", "language", language)

        # 1.5) Audience level — render-time presentation knob (docs/audience-levels.md).
        # A less-technical reader sees MORE explanation, not more raw detail. Off-enum
        # input falls back to the default rather than writing an invalid value.
        level = ask(
            "Audience level [technical | balanced | non-technical] (default balanced): "
        ).strip() or "balanced"
        if level not in ("technical", "balanced", "non-technical"):
            level = "balanced"
        try:
            channels_text = set_block_field(
                channels_text, "delivery", "technical_level", level
            )
        except KeyError:
            # Forward-compat: a channels.yaml predating this key (older install)
            # has no line to edit — insert it under delivery so reconfigure never
            # crashes on an upgrade.
            channels_text = insert_block_field(
                channels_text, "delivery", "technical_level", level, after="language"
            )

        # 2) Topics + sources (delegated to the manage_sources backend). A fresh
        # install is initialized onto the YAML config format first, so every
        # write below lands in config/sources.yaml + config/topics.yaml; a
        # legacy install with real .md content keeps its format (§2.3).
        if _seed_yaml_config(config_dir):
            print(
                "\nConfig format: YAML (config/sources.yaml + config/topics.yaml; "
                "the shipped .md templates stay as a dormant fallback)."
            )
        _configure_topics_and_sources(ask, config_dir)

        # 3) Channels — each edits the channels.yaml TEXT; secrets collected aside.
        secrets: dict[str, str] = {}
        print("\nDelivery channels:")
        channels_text = _configure_email(ask, ask_secret, channels_text, secrets)
        channels_text = _configure_telegram(ask, ask_secret, channels_text, secrets)
        channels_text = _configure_rocketchat(ask, ask_secret, channels_text, secrets)

        # 4) Schedule — only the shared timezone is prompted; crons keep defaults.
        timezone = ask('\nTimezone (IANA, default "UTC"): ').strip() or "UTC"
        schedule_text = set_block_field(schedule_text, None, "timezone", f'"{timezone}"')

        # 5) Write everything, then materialise any supplied secrets into .env.
        channels_path.write_text(channels_text, encoding="utf-8")
        schedule_path.write_text(schedule_text, encoding="utf-8")
        if secrets:
            write_env(config_dir / ".env", secrets, template=env_template)

        # 6) Final confirmation: run the validator. On failure, roll back so an
        # invalid config never persists (transactional contract).
        print()
        if not _run_validator(config_dir):
            _restore()
            print(
                "\nconfiguration invalid — your previous config was restored unchanged. "
                "Fix the reported issues and re-run.",
                file=sys.stderr,
            )
            return 1

        # Secret hygiene: lock the .env to owner-only whenever it exists — not just
        # when this run wrote a new secret. A legacy 0644 .env left from an earlier
        # setup must be migrated to 0600, or the credentials stay world/group readable.
        # A chmod failure is surfaced as a WARNING (not a fatal traceback) so the user
        # is told their secrets may still be readable rather than left guessing.
        env_path = config_dir / ".env"
        if env_path.exists():
            try:
                env_path.chmod(0o600)
            except OSError as exc:
                print(
                    f"WARNING: could not lock {env_path} to 0600 ({exc}); secrets may "
                    f"be group/world-readable — fix the file permissions by hand.",
                    file=sys.stderr,
                )
        _print_activation_check(config_dir)

        # 7) Headless-collectability advisory. This is the NO-AGENT installer and
        # the headless collector only processes `rss` sources — a config whose
        # active sources are all paused or non-RSS would let `collect.py` gather
        # nothing. That is a WARNING, not a failure: everything the user typed is
        # valid (the validator above passed) and fully usable by the agentic
        # collector, so the config is KEPT — never rolled back — and only the
        # exit code signals "not headless-collectable" to wrapping automation.
        all_sources = [s for c in ms.list_state(config_dir).categories for s in c.sources]
        active_rss = [s for s in all_sources if s.active and s.type == "rss"]
        if not active_rss:
            other = sorted({s.type for s in all_sources if s.active and s.type != "rss"})
            if other:
                detail = (
                    f"your only active sources are {', '.join(other)}, so the "
                    f"headless Lite collector will collect nothing. Add an `rss` "
                    f"feed, or use the agentic collector (Cowork / Claude Code) — "
                    f"it handles those source types."
                )
            else:
                detail = (
                    "the headless Lite collector will collect nothing. Add at "
                    "least one topic with an active `rss` source, or set up via "
                    "the agentic setup-wizard (Cowork / Claude Code)."
                )
            print(
                f"\nWARNING: no active RSS source configured — {detail} "
                f"(Everything you entered was kept.)",
                file=sys.stderr,
            )
            return 1
    except BaseException:
        # ANY unexpected failure (incl. KeyboardInterrupt, a validator/list_state
        # crash, or a write error) rolls the config back so the configurator is
        # all-or-nothing — the validator return-1 path above already restored.
        _restore()
        print(
            "\nconfiguration aborted — your previous config was restored unchanged.",
            file=sys.stderr,
        )
        raise

    print(
        "\nNext: register one recurring run for schedule/weekly-run.md, or run a "
        "one-time digest after collection with scripts/collect.py and "
        "scripts/build_digest.py."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
