"""Drift tests: every documented/emitted sanitize command must actually run.

The sanitize CLI takes its root only via ``--incoming`` (there is no positional
argument), so any example passing the root as a positional argument dies with
argparse exit 2 — killing the whole recommended cron chain on its first step.
These tests pin the CLI shape and forbid the broken form everywhere it can
mislead: docs, skills, docstrings, and the runtime gate error message itself.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

import pytest

from scripts import sanitize_incoming
from scripts.digest import scan
from scripts.digest.model import IncomingNotSanitized

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories that hold user/runtime data or third-party code, not our prose.
_SCAN_EXCLUDE = {
    ".git", ".venv", "__pycache__", "node_modules",
    "pipeline", "brain", "dist", ".remember", ".pytest_cache",
}

# The broken shapes: a positional path after `sanitize` (POSIX or Windows
# separators), or the f-string that used to interpolate one into the gate error.
_BROKEN = re.compile(r"sanitize\s+(?:pipeline[/\\]+1-incoming|\{incoming_dir\})")

# Active contracts that teach users or agents how the weekly pipeline runs.
# Historical records (CHANGELOG, BACKLOG, ADR superseded text) and audit reports
# are intentionally excluded: they may need to describe an old unsafe order.
_PIPELINE_ORDER_SURFACES = (
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "QUICKSTART.md",
    "FIRST-RUN.md",
    "USER_GUIDE.md",
    "docs/CONVENTIONS.md",
    "docs/architecture.md",
    "docs/scheduling.md",
    "docs/telegram-commands.md",
    "docs/adr/0009-single-gated-orchestrator-over-timers.md",
    "schedule/README.md",
    "schedule/weekly-run.md",
    "skills/digest-build/SKILL.md",
    "skills/run-now/SKILL.md",
    "skills/run-now/tests/acceptance.md",
    "skills/setup-wizard/SKILL.md",
)

_ONBOARDING_DOC_SURFACES = (
    "README.md",
    "FIRST-RUN.md",
    "QUICKSTART.md",
    "QUICKSTART.ru.md",
    "USER_GUIDE.md",
    "docs/scheduling.md",
    "docs/OPERATIONS.md",
    "skills/capabilities/SKILL.md",
)

_ACTIVATION_LABELS = (
    "Source:",
    "Config:",
    "Delivery:",
    "Schedule:",
    "First value:",
    "Next action:",
)

# Curation is model-facing and must consume sanitized companions. Match only
# explicit arrow sequences so prose can still explain the historical bug.
_UNSAFE_PIPELINE_ORDER = re.compile(
    r"\bcurate\b(?:\*\*)?\s*(?:\([^)\n]*\))?\s*(?:→|->)\s*(?:\*\*)?\s*\bsanitiz",
    re.IGNORECASE,
)


def _scannable_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if path.suffix not in {".md", ".py"} or not path.is_file():
            continue
        if _SCAN_EXCLUDE.intersection(part for part in path.relative_to(REPO_ROOT).parts):
            continue
        files.append(path)
    return files


def test_sanitize_cli_accepts_documented_form_and_rejects_positional() -> None:
    parser = sanitize_incoming._build_parser()

    # The documented forms parse.
    args = parser.parse_args(["sanitize"])
    assert args.command == "sanitize"
    args = parser.parse_args(["sanitize", "--incoming", "pipeline/1-incoming"])
    assert args.incoming == "pipeline/1-incoming"

    # The broken positional form is rejected — this is why the docs must not show it.
    with pytest.raises(SystemExit):
        parser.parse_args(["sanitize", "pipeline/1-incoming"])


def test_no_broken_positional_sanitize_form_anywhere() -> None:
    offenders: list[str] = []
    for path in _scannable_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _BROKEN.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "broken `sanitize <path>` examples (the CLI only accepts --incoming):\n"
        + "\n".join(offenders)
    )


def test_active_contracts_never_teach_curate_before_sanitize() -> None:
    offenders: list[str] = []
    for relative in _PIPELINE_ORDER_SURFACES:
        path = REPO_ROOT / relative
        text = path.read_text(encoding="utf-8")
        match = _UNSAFE_PIPELINE_ORDER.search(text)
        if match:
            excerpt = " ".join(match.group(0).split())
            offenders.append(f"{relative}: {excerpt}")
    assert not offenders, (
        "unsafe pipeline order documented (sanitize must precede model-facing curation):\n"
        + "\n".join(offenders)
    )


def test_gate_error_message_command_is_runnable(tmp_path: Path) -> None:
    """The remediation command inside the gate's own error must parse."""
    incoming = tmp_path / "1-incoming"
    topic = incoming / "ai-news"
    topic.mkdir(parents=True)
    (topic / "2026-07-01_article.md").write_text(
        "---\ntitle: t\nurl: https://example.com/a\n---\nbody\n", encoding="utf-8"
    )

    with pytest.raises(IncomingNotSanitized) as excinfo:
        scan._check_incoming_sanitized(incoming)

    message = str(excinfo.value)
    match = re.search(r"`(python3 scripts/sanitize_incoming\.py [^`]+)`", message)
    assert match, f"gate error carries no runnable command: {message!r}"
    argv = shlex.split(match.group(1))[2:]  # drop `python3 scripts/sanitize_incoming.py`
    args = sanitize_incoming._build_parser().parse_args(argv)  # must not SystemExit
    assert args.command == "sanitize"


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _paragraphs(text: str) -> list[str]:
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]


def test_onboarding_docs_name_supported_default_and_advanced_fallback() -> None:
    for relative in ("README.md", "FIRST-RUN.md", "QUICKSTART.md", "USER_GUIDE.md"):
        text = _read(relative)
        assert "full agentic" in text, f"{relative} must name the supported full agentic path"
        assert ("RSS Digest Lite" in text) or ("advanced" in text), (
            f"{relative} must describe RSS Digest Lite or advanced fallback"
        )


def test_onboarding_docs_include_activation_checklist_fields() -> None:
    for relative in ("FIRST-RUN.md", "QUICKSTART.md", "USER_GUIDE.md"):
        text = _read(relative)
        missing = [label for label in _ACTIVATION_LABELS if label not in text]
        assert not missing, f"{relative} missing activation labels: {missing}"


def test_onboarding_docs_do_not_claim_config_write_is_complete_setup() -> None:
    offenders: list[str] = []
    for relative in _ONBOARDING_DOC_SURFACES:
        text = _read(relative)
        for lineno, line in enumerate(text.splitlines(), start=1):
            normalized = line.casefold()
            if not re.search(r"\b(setup is complete|you're done)\b", normalized):
                continue
            paragraph = next(
                (p for p in _paragraphs(text) if line.strip() and line.strip() in p),
                line,
            ).casefold()
            if "schedule" not in paragraph and "activation" not in paragraph:
                offenders.append(f"{relative}:{lineno}: {line.strip()}")
    assert not offenders, (
        "docs must not imply written config alone completes setup:\n" + "\n".join(offenders)
    )


def test_scheduler_docs_name_weekly_run_registration() -> None:
    for relative in ("docs/scheduling.md", "FIRST-RUN.md"):
        text = _read(relative)
        assert "schedule/weekly-run.md" in text, f"{relative} must name schedule/weekly-run.md"
        assert "register one recurring run" in text, (
            f"{relative} must tell users to register one recurring run"
        )


def test_collect_base_documents_final_dedup_gate() -> None:
    text = _read("schedule/collect-base.md")

    assert "Final exact-dedup gate before every write" in text
    assert "already registered before save" in text


def test_docs_keep_mcp_secrets_out_of_env_guidance() -> None:
    combined = "\n".join(_read(relative) for relative in _ONBOARDING_DOC_SURFACES)
    assert not re.search(r"GMAIL.{0,80}\.env|\.env.{0,80}GMAIL", combined, re.IGNORECASE | re.DOTALL)
    assert not re.search(
        r"Telegram plugin.{0,120}config/\.env|config/\.env.{0,120}Telegram plugin",
        combined,
        re.IGNORECASE | re.DOTALL,
    )

    allowed_context = {
        "SMTP_PASSWORD": re.compile(r"\b(headless|advanced|smtp|cron)\b", re.IGNORECASE),
        "TELEGRAM_BOT_TOKEN": re.compile(r"\b(headless|advanced|bot-api|cron)\b", re.IGNORECASE),
        "ROCKETCHAT_WEBHOOK_URL": re.compile(r"\b(rocket\.?chat|webhook)\b", re.IGNORECASE),
    }
    offenders: list[str] = []
    for relative in _ONBOARDING_DOC_SURFACES:
        text = _read(relative)
        for paragraph in _paragraphs(text):
            for token, pattern in allowed_context.items():
                if token in paragraph and not pattern.search(paragraph):
                    offenders.append(f"{relative}: {token} outside allowed context")
    assert not offenders, "\n".join(offenders)


# A crontab entry: five schedule fields, then a command that touches scripts/.
_CRON_LINE = re.compile(r"^\s*(?:[\d*/,\-]+\s+){5}.*scripts/")


def test_cron_examples_use_venv_interpreter_not_bare_python3() -> None:
    """Cron runs with a minimal PATH: bare `python3` is the system interpreter,
    which typically lacks PyYAML — and deliver.py hard-requires it. Every
    documented cron line must call the project venv's interpreter instead
    (this exact trap broke delivery on a live box)."""
    offenders: list[str] = []
    for relative in ("docs/scheduling.md", "docs/OPERATIONS.md", "QUICKSTART.md"):
        path = REPO_ROOT / relative
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _CRON_LINE.match(line) and re.search(r"(?<![\w/.])python3?\s+scripts/", line):
                offenders.append(f"{relative}:{lineno}: {line.strip()}")
    assert not offenders, (
        "cron examples must use .venv/bin/python3 (system python3 lacks PyYAML):\n"
        + "\n".join(offenders)
    )


def test_headless_weekly_cron_records_run_heartbeat() -> None:
    """The run-overdue health signal keys on `run` events; only the agentic
    weekly-run recorded them. The documented headless weekly cron chain must
    stamp the heartbeat too, or a silently dead cron is caught only by the
    much later digest_stale signal."""
    text = _read("docs/scheduling.md")
    assert "health.py record --kind run --status ok" in text


def test_decoupled_health_watchdog_is_shipped_and_documented() -> None:
    """The in-run Step 7.5 alert cannot report a run that crashed early or a
    scheduler that stopped firing. The decoupled daily watchdog is the fix —
    the task file must ship and scheduling docs must register it."""
    watchdog = _read("schedule/health-watchdog.md")
    assert "health_alert.py" in watchdog
    assert "DEGRADED" in watchdog
    scheduling = _read("docs/scheduling.md")
    assert "schedule/health-watchdog.md" in scheduling
    assert re.search(r"(?m)^\s*>?\s*(?:[\d*/,\-]+\s+){5}.*health_alert\.py", scheduling), (
        "scheduling.md must carry a cron line for the daily watchdog"
    )
    assert "health-watchdog.md" in _read("schedule/README.md")


def test_watchdog_doc_does_not_overclaim_same_day_detection() -> None:
    """A run that crashed before recording anything — or a scheduler that
    silently stopped — leaves no event, so the watchdog only sees it once the
    last success ages past EXPECTED_RUN_DAYS. The doc must name that window
    instead of promising a same-day ping for exactly the no-trace failures."""
    from scripts.health import EXPECTED_RUN_DAYS

    watchdog = _read("schedule/health-watchdog.md")
    assert "failure pings the same day" not in watchdog.replace("\n", " "), (
        "health-watchdog.md still promises same-day detection for failures that record no event"
    )
    assert f"{EXPECTED_RUN_DAYS}-day" in watchdog, (
        "health-watchdog.md must state the real run-overdue window"
    )


def test_wizard_hands_over_routine_spec_and_blocked_crontab_fallback() -> None:
    """The cloud path must hand the user a filled-in, ready-to-paste routine
    spec (not just a pointer), and the crontab one-tap must say what to do
    when the runtime's permission layer refuses the in-session write."""
    skill = _read("skills/setup-wizard/SKILL.md")
    assert "{{DIGEST_CRON}}" in skill and "{{TIMEZONE}}" in skill, (
        "cloud-path handoff must render the user's digest.cron + timezone into a paste-ready spec"
    )
    assert "permission layer" in skill and "re-run the detection probe" in skill, (
        "one-tap crontab must state the blocked-write fallback"
    )


def test_telegram_launcher_ships_and_is_wired() -> None:
    """Telegram inbound used to require pasting a shell function into ~/.zshrc
    with a hand-edited cd path — the #1 "bot won't answer" trap. The launcher
    must ship as a script that resolves its own root (nothing to edit), be
    reachable as `make telegram`, and be what QUICKSTART leads with."""
    script = REPO_ROOT / "scripts" / "telegram-launch.sh"
    assert script.exists(), "scripts/telegram-launch.sh must ship"
    assert os.access(script, os.X_OK), "telegram-launch.sh must be executable"
    text = script.read_text(encoding="utf-8")
    assert "TELEGRAM_STATE_DIR" in text
    assert "--channels" in text
    assert "cd ~/projects" not in text, "the launcher must resolve its own root, not a sample path"
    assert "telegram-launch.sh" in _read("Makefile")
    assert "make telegram" in _read("QUICKSTART.md")


def test_installers_and_onboarding_point_to_doctor() -> None:
    """doctor.py is the one composed read-only "is everything OK?" check, but it
    was invisible exactly where a new user needs it: neither installer ran or
    named it, and no onboarding doc mentioned it. Pin the discoverability."""
    for relative in ("install.sh", "install.ps1", "FIRST-RUN.md", "QUICKSTART.md"):
        assert "doctor.py" in _read(relative), f"{relative} must reference scripts/doctor.py"


def test_install_default_is_dependencies_only_and_docs_say_so() -> None:
    """`make install` used to end in the FULL config interview while FIRST-RUN
    billed the step as deps-only — and then step 4 configured AGAIN via the
    spoken wizard. Pin the flipped contract on both installers and the docs:
    bare install = dependencies only; the interview is opt-in (--configure)."""
    install = _read("install.sh")
    assert re.search(r"(?m)^RUN_CONFIGURE=0\b", install), (
        "bare install.sh must default to dependencies-only (RUN_CONFIGURE=0)"
    )
    assert "--configure" in install, "install.sh must offer the interview behind --configure"
    ps1 = _read("install.ps1")
    assert re.search(r"\[switch\]\s*\$Configure\b", ps1), (
        "install.ps1 must gate the interview behind an explicit -Configure switch"
    )
    # Both installers' deps-only ending must name the recommended spoken wizard.
    for relative in ("install.sh", "install.ps1"):
        assert "let's set up sources" in _read(relative), (
            f"{relative} must end by pointing at the spoken setup wizard"
        )
    # FIRST-RUN's install step must promise deps-only, not an interview.
    first_run = _read("FIRST-RUN.md")
    install_paragraphs = [p for p in _paragraphs(first_run) if "make install" in p]
    assert install_paragraphs, "FIRST-RUN.md lost its `make install` step"
    for paragraph in install_paragraphs:
        assert not re.search(r"configurator|interactive config", paragraph, re.IGNORECASE), (
            "FIRST-RUN's install step must not promise the config interview "
            "(configuration is step 4):\n" + paragraph
        )


def test_ru_quickstart_first_path_is_the_spoken_wizard() -> None:
    """QUICKSTART.ru's «Кратчайший путь» used to open with `make install` — the
    EN-only advanced terminal interview that EN QUICKSTART says most people
    never touch. The RU happy path must mirror EN: the spoken setup wizard
    leads; the terminal route lives in an advanced appendix."""
    text = _read("QUICKSTART.ru.md")
    # NB: don't key on "терминал" — the happy-path heading legitimately says
    # «без терминала»; the appendix is recognised by its "advanced" label.
    match = re.search(r"(?mi)^##[^\n]*(продвинут|advanced)", text)
    assert match, "QUICKSTART.ru.md must carry an advanced/terminal appendix section"
    happy_path, advanced = text[: match.start()], text[match.start():]

    assert "Cowork" in happy_path
    assert "давай настроим источники" in happy_path, (
        "the RU happy path must lead with the spoken setup-wizard trigger"
    )
    assert "make install" not in happy_path, (
        "the RU happy path must not route novices into the terminal installer"
    )
    assert "make install" in advanced, (
        "the terminal path must still be documented — in the advanced appendix"
    )
    assert "--configure" in advanced, (
        "the appendix must name the explicit interview flag (bare install is deps-only)"
    )
    # The interview is English-only — a RU reader must be told before choosing it.
    assert re.search(r"по-английски|на английском", advanced), (
        "the RU appendix must say the terminal interview runs in English"
    )


def test_first_run_step_one_offers_the_no_terminal_path() -> None:
    """README routes newcomers to FIRST-RUN and QUICKSTART promises 'no terminal
    and no coding' — so FIRST-RUN's step 1 must open with the assistant path,
    not demand a terminal as the only way in."""
    text = _read("FIRST-RUN.md")
    step1 = re.search(r"(?ms)^1\.\s.*?(?=^2\.\s)", text)
    assert step1, "FIRST-RUN.md lost its numbered steps"
    assert re.search(r"Cowork\s*/\s*Claude Code", step1.group(0)), (
        "FIRST-RUN step 1 must offer opening the folder in Cowork / Claude Code"
    )


def test_wiki_query_vault_only_answer_template_is_sourced() -> None:
    text = _read("skills/wiki-query/SKILL.md")

    assert "Vault answer" in text
    assert "Source: `brain/concepts/<slug>.md` § <section>; underlying source: <url-or-path>" in text
    assert "Confidence:" in text
    assert "Gaps:" in text


def test_wiki_query_vault_only_miss_template_does_not_auto_research() -> None:
    text = _read("skills/wiki-query/SKILL.md")

    assert "Vault-only miss" in text
    assert "I checked `brain/INDEX.md` and `brain/concepts/` for: <query>" in text
    assert "No matching concept exists in the local vault." in text
    assert "I can research this separately if you want." in text
    assert "Do not start research-grep, web search, or raw-corpus inventory for VAULT_ONLY=true." in text


def test_wiki_query_acceptance_pins_vault_only_no_broadening() -> None:
    text = _read("skills/wiki-query/tests/acceptance.md")

    assert "VAULT_ONLY=true" in text
    assert "research-grep, the raw corpus, and the web are not opened" in text
    assert "External research is offered as a separate next action" in text


# ── sources/topics config-format drift guard (CONVENTIONS §2.3) ───────────────
#
# Since the YAML migration, config/sources.yaml + config/topics.yaml are the
# ACTIVE config and the .md pipe tables are a frozen legacy fallback. The active
# contracts below must (a) name the YAML config, and (b) never mention the .md
# files as a bare instruction — every remaining `sources.md`/`topics.md` mention
# must sit next to a qualifier (yaml / legacy / fallback / active / migrat…) so
# no surface quietly teaches hand-editing the ignored .md as the primary path.

_CONFIG_FORMAT_SURFACES = (
    "AGENTS.md",
    "README.md",
    "USER_GUIDE.md",
    "QUICKSTART.md",
    "FIRST-RUN.md",
    "config/README.md",
    "docs/CONVENTIONS.md",
    "docs/scheduling.md",
    "docs/telegram-commands.md",
    "docs/decks/research-brain-showcase.html",
    "schedule/weekly-run.md",
    "schedule/collect-base.md",
    "schedule/collect-topic.md",
    "schedule/weekly-curate.md",
    "skills/setup-wizard/SKILL.md",
    "skills/source-manage/SKILL.md",
    "skills/pipeline-curate/SKILL.md",
    "skills/brain-ask/SKILL.md",
    "skills/run-now/SKILL.md",
)

# A mention of the legacy config files (NOT the starter packs, and NOT the
# unrelated repo-root `sources/*.md` tier registry).
_LEGACY_CONFIG_MENTION = re.compile(r"(?<![\w.\-])(?:sources|topics)\.md\b")

# Words that mark a mention as format-aware (the YAML story is acknowledged).
_FORMAT_QUALIFIER = re.compile(
    r"yaml|legacy|fallback|active|migrat|frozen", re.IGNORECASE
)


def test_active_contracts_name_the_yaml_config() -> None:
    missing = [
        relative
        for relative in _CONFIG_FORMAT_SURFACES
        if (REPO_ROOT / relative).exists()
        if "sources.yaml" not in _read(relative) and "topics.yaml" not in _read(relative)
    ]
    assert not missing, (
        "surfaces that teach the sources/topics config must name the active YAML "
        "format (sources.yaml/topics.yaml):\n" + "\n".join(missing)
    )


def test_active_contracts_never_teach_bare_md_config_editing() -> None:
    offenders: list[str] = []
    for relative in _CONFIG_FORMAT_SURFACES:
        if not (REPO_ROOT / relative).exists():
            continue  # contributor-only deck is absent from the clean public snapshot
        lines = _read(relative).splitlines()
        for lineno, line in enumerate(lines, start=1):
            if "example-starter" in line:
                continue  # the starter packs are .md by design (copied, then migrated)
            if not _LEGACY_CONFIG_MENTION.search(line):
                continue
            # The mention itself, or its immediate context (±2 lines), must
            # acknowledge the format story.
            context = " ".join(lines[max(0, lineno - 3): lineno + 2])
            if _FORMAT_QUALIFIER.search(context):
                continue
            offenders.append(f"{relative}:{lineno}: {line.strip()}")
    assert not offenders, (
        "bare `sources.md`/`topics.md` teaching (the .md is a legacy fallback — "
        "mention the YAML/active-config story or drop the reference):\n"
        + "\n".join(offenders)
    )


def test_support_upgrade_policy_matches_shipped_migrations() -> None:
    """SUPPORT.md's upgrade policy kept claiming "None shipped yet" after the
    0.7.0 config migrators shipped — the support contract must track the
    schema-migration registry, not a snapshot of it."""
    from scripts import schema

    support = _read("docs/SUPPORT.md")
    if schema.MIGRATIONS:
        assert "None shipped yet" not in support, (
            "SUPPORT.md denies shipped migrators while schema.MIGRATIONS is non-empty"
        )
        assert "migrate-config" in support, (
            "SUPPORT.md must name the shipped migration command"
        )


def test_updating_doc_matches_shipped_migrations() -> None:
    """docs/updating.md — THE page the update flow links to — kept telling a
    0.6.x user "there is no automatic rewriter yet" after 0.7.0 shipped
    `schema.py migrate-config` (and update.sh/ps1 started offering it). The
    update guide must track the same registry SUPPORT.md does."""
    from scripts import schema

    updating = _read("docs/updating.md")
    if schema.MIGRATIONS:
        assert "no automatic rewriter yet" not in updating, (
            "docs/updating.md denies shipped migrators while schema.MIGRATIONS "
            "is non-empty"
        )
        assert "migrate-config" in updating, (
            "docs/updating.md must name the shipped migration command"
        )


def test_public_changelog_documents_first_run_contract() -> None:
    """The public candidate must explain the installer mode and legacy config
    import because both affect someone upgrading or installing from source."""
    changelog = _read("CHANGELOG.md")
    assert "## [Unreleased]" in changelog
    assert "--configure" in changelog, (
        "the newest release notes must name the installer default flip "
        "(deps-only bare install; interview behind --configure)"
    )
    assert "migrate-config" in changelog, (
        "the newest release notes must carry the .md-retirement action for "
        "unmigrated legacy installs"
    )


def test_shipped_config_is_yaml_only() -> None:
    # 0.8.0: the .md config tables are retired — the archive ships the YAML
    # twins (empty structures the wizard/configurator fill in) and NO
    # sources.md/topics.md templates (starter packs are a different thing).
    for relative in ("config/sources.yaml", "config/topics.yaml"):
        text = _read(relative)
        assert "migrate-config" in text, (
            f"{relative} must name the legacy-import command in its header"
        )
    for retired in ("config/sources.md", "config/topics.md"):
        assert not (REPO_ROOT / retired).exists(), (
            f"{retired} is retired — the runtime no longer reads it, so shipping "
            "it would only invite hand-edits that change nothing"
        )


def test_update_scripts_surface_the_migration_offer() -> None:
    # Both installers surface (never auto-apply) the one-time migration.
    for relative in ("update.sh", "update.ps1"):
        text = _read(relative)
        assert "migrate-config" in text, f"{relative} lost the YAML migration offer"


def test_intake_handles_telegram_forwards_and_attachments() -> None:
    """The most natural mobile capture gesture — forwarding a post or photo to
    the bot — used to be silently ignored: intake only knew bare URLs/OPML.
    The skill must name the plugin's attachment surfaces and the forward path."""
    intake = _read("skills/intake/SKILL.md")
    assert "image_path" in intake, "intake must handle Telegram photo messages"
    assert "attachment_file_id" in intake, "intake must handle Telegram file attachments"
    assert re.search(r"forward", intake, re.IGNORECASE), (
        "intake must handle forwarded posts"
    )


def test_feedback_surfaces_do_not_promise_tap_reactions() -> None:
    """Tapping 👍/👎 ON the digest message never reaches the agent (the plugin's
    react tool is outbound-only) — every surface advertising 👍/👎 must say the
    emoji works as a SENT MESSAGE, so the promise matches reality."""
    for relative in ("docs/feedback.md", "skills/digest-feedback/SKILL.md"):
        text = _read(relative)
        if "👍" not in text:
            continue
        assert re.search(r"tap[- ]reaction|тап|реакци[юяи][^\n]*не до", text, re.IGNORECASE), (
            f"{relative} advertises 👍/👎 without the tap-reaction limitation"
        )
