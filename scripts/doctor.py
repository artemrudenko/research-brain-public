#!/usr/bin/env python3
"""
doctor.py — one command that answers "is everything set up and healthy?".

The individual checks already exist (`validate_config.py`, `deliver.py
--dry-run`, `health.py report`, `run_lock.py status`, `version.py`) but a user
has to know all five. Doctor composes them into one plain-language report:

    python3 scripts/doctor.py

Sections:
  1. Environment — product version, Python version, PyYAML availability.
  2. Config      — the same schema validators `validate_config.py` runs.
  3. Sources     — at least one real (non-EXAMPLE) monitored source; RSS note.
  4. Delivery    — enabled channels, transport, secret SET/MISSING (never values).
  5. Health      — the 4-state operational verdict from `health.py`.
  6. Run lock    — whether a run / delivery lock is currently held.

Read-only: sends nothing, writes nothing, resolves no secret values. Exit 0
when there is nothing the user MUST fix (warnings allowed — a fresh install is
unconfigured, not broken); exit 1 when at least one FAIL needs fixing.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import yaml
except ImportError:  # headless python3 without PyYAML — sections degrade politely
    yaml = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import brain_status, health, setup_check, validate_config  # noqa: E402
from scripts.version import read_version  # noqa: E402

# Levels, in escalation order. A section reports its worst finding.
_OK, _WARN, _FAIL = "OK", "WARN", "FAIL"

# Config files doctor treats as REQUIRED (a missing one fails the check) vs
# optional (validated only when present) — mirrors validate_config's coverage.
# The sources/topics pair is format-resolved at check time (YAML twins when
# — the only sources/topics format since 0.8.0, CONVENTIONS §2.3).
_REQUIRED_CONFIG = ("channels.yaml", "schedule.yaml")
_OPTIONAL_YAML = ("search.yaml", "glossary.yaml", "tags.yaml")


def _with_next_action(lines: list[str], action: str) -> list[str]:
    """Append one recovery action unless the section already supplied one."""
    if any(line.startswith("Next action:") for line in lines):
        return lines
    return [*lines, f"Next action: {action}"]


def _config_next_action(errors: list[str]) -> str:
    """Concrete config recovery based on the files named in validation errors."""
    actions: list[str] = []
    for error in errors:
        name, _, _detail = error.partition(":")
        if not name:
            continue
        action = f"restore config/{name}" if "missing" in error else f"fix config/{name}"
        if action not in actions:
            actions.append(action)
    if not actions:
        actions.append("fix the named config file")
    return f"{' and '.join(actions)}, then run python3 scripts/validate_config.py"


def _venv_python_with_pyyaml(root: Path) -> Path | None:
    """The install's virtualenv interpreter IF `root/.venv` exists and has PyYAML.

    Filesystem-only (no subprocess) so doctor stays read-only and fast: PyYAML
    installs a top-level `yaml` package into the venv's site-packages; we return the
    venv's own python so the caller can tell the user which interpreter to use.
    Returns None when there is no such venv — the caller then keeps the generic
    "install the toolchain" message. This never makes PyYAML *required* (ADR 0002);
    it only makes a wrong-interpreter invocation self-explaining.
    """
    venv = root / ".venv"
    has_yaml = any(venv.glob("lib/python*/site-packages/yaml")) or any(
        venv.glob("Lib/site-packages/yaml")  # Windows layout
    )
    if not has_yaml:
        return None
    for candidate in (
        venv / "bin" / "python3",
        venv / "bin" / "python",
        venv / "Scripts" / "python.exe",  # Windows
    ):
        if candidate.exists():
            return candidate
    return None


def _section_environment(root: Path) -> tuple[str, list[str]]:
    try:
        version = read_version(root)
    except OSError:
        version = "unknown (no readable pyproject.toml — is --root the install root?)"
    lines = [
        f"research-brain {version}",
        f"Python {platform.python_version()}",
    ]
    if yaml is None:
        venv_python = _venv_python_with_pyyaml(root)
        if venv_python is not None:
            # Common footgun: running with the system python instead of the venv.
            # Point at the interpreter that HAS PyYAML rather than just flagging its
            # absence — the config/delivery schema checks below need it.
            lines.append(
                "PyYAML isn't in THIS Python, but this install's virtualenv has it — "
                f"re-run via `{venv_python} scripts/doctor.py` (or `uv run python "
                "scripts/doctor.py`) for the full-fidelity checks."
            )
        else:
            lines.append(
                "PyYAML not installed — the dependency-free fallbacks are in use "
                "(fine for cron; `make setup` installs the full toolchain)."
            )
        return _WARN, lines
    lines.append("PyYAML available")
    return _OK, lines


def _section_config(root: Path) -> tuple[str, list[str]]:
    config = root / "config"
    lines: list[str] = []
    level = _OK
    if not config.is_dir():
        return _FAIL, [
            f"config/ directory not found under {root}",
            "Next action: restore config/, then run python3 scripts/validate_config.py",
        ]

    errors: list[str] = []
    for name in _REQUIRED_CONFIG:
        path = config / name
        if not path.exists():
            errors.append(f"{name}: missing (required)")
            continue
        if yaml is not None and name == "channels.yaml":
            errors.extend(f"{name}: {e}" for e in validate_config.validate_channels(path, yaml))
        elif yaml is not None and name == "schedule.yaml":
            errors.extend(f"{name}: {e}" for e in validate_config.validate_schedule(path, yaml))

    # sources/topics: YAML-only (0.8.0). An unmigrated legacy dir gets the
    # one-command pointer instead of a bare "missing (required)".
    sources = validate_config.active_sources_path(config)
    topics = validate_config.active_topics_path(config)
    if validate_config.legacy_md_needs_migration(config):
        errors.append(
            "sources/topics config is still in the retired .md format — run "
            "`python3 scripts/schema.py migrate-config` (the .md files are "
            "left untouched as the rollback)"
        )
    else:
        for path in (sources, topics):
            if not path.exists():
                errors.append(f"{path.name}: missing (required)")
    if yaml is None:
        lines.append("sources.yaml / topics.yaml schema checks skipped (no PyYAML).")
        level = _WARN
    else:
        if sources.exists():
            errors.extend(
                f"{sources.name}: {e}"
                for e in validate_config.validate_sources_yaml(sources, yaml)
            )
        if topics.exists():
            errors.extend(
                f"{topics.name}: {e}"
                for e in validate_config.validate_topics_yaml(topics, yaml)
            )

    if yaml is None:
        lines.append("channels.yaml / schedule.yaml schema checks skipped (no PyYAML).")
        level = _WARN
    else:
        for name, checker in (
            ("search.yaml", validate_config.validate_search),
            ("glossary.yaml", validate_config.validate_glossary),
            ("tags.yaml", validate_config.validate_tags),
        ):
            path = config / name
            if path.exists():
                errors.extend(f"{name}: {e}" for e in checker(path, yaml))
    if topics.exists() and sources.exists():
        errors.extend(validate_config.check_topics_sources_sync(topics, sources))

    if errors:
        return _FAIL, _with_next_action(lines + errors, _config_next_action(errors))
    if yaml is None:
        lines.append("config schema status unknown until PyYAML is available")
    else:
        lines.append("every present config file passes its schema check")
    return level, lines


def _section_sources(root: Path) -> tuple[str, list[str]]:
    if yaml is None:
        return _WARN, [
            "source count unknown — PyYAML is unavailable in this Python.",
            "Next action: run this install's .venv/bin/python scripts/doctor.py.",
        ]
    records = brain_status.monitored_sources(root=root)
    if not records:
        return _WARN, [
            "no real monitored sources yet (only the EXAMPLE placeholders or an "
            "empty file) — setup is unfinished.",
            "Next action: say \"let's set up sources\" or add a source with source-manage.",
        ]
    rss = sum(1 for r in records if "rss" in (r.type or "").lower())
    lines = [f"{len(records)} active monitored source(s), {rss} RSS"]
    if rss == 0:
        lines.append(
            "no RSS sources — the reliable headless collection rung is empty, "
            "so scheduled digests may stay quiet. Add at least one feed."
        )
        lines.append(
            "Next action: add at least one active rss source for the headless path, "
            "or use the full agentic setup."
        )
        return _WARN, lines
    return _OK, lines


def _section_collection_mode(root: Path) -> tuple[str, list[str]]:
    """Explain the full-agentic vs headless RSS-lite collection boundary."""
    if yaml is None:
        return _WARN, [
            "collection mode unknown until the source config can be read with PyYAML.",
            "Next action: run this install's .venv/bin/python scripts/doctor.py.",
        ]
    records = brain_status.monitored_sources(root=root)
    if not records:
        return _WARN, [
            "no active monitored sources yet, so collection capability is pending.",
            "Full agentic weekly-run: can use RSS, blog, medium-tag, and webpage sources once configured.",
            "Headless collect.py: RSS/Atom plus static article top-up; add at least one active rss source for cron-lite collection.",
        ]

    by_type = Counter((r.type or "unknown").strip().lower() or "unknown" for r in records)
    rss = by_type.get("rss", 0)
    non_rss = len(records) - rss
    breakdown = ", ".join(f"{name}={count}" for name, count in sorted(by_type.items()))
    lines = [
        f"{len(records)} active monitored source(s): {breakdown}",
        "Full agentic weekly-run: can use all active source types via schedule/weekly-run.md.",
        "Headless collect.py: RSS/Atom plus static article top-up; it does not run ranking, browser, or search collection.",
    ]
    if non_rss:
        lines.append(
            f"{non_rss} active non-RSS source(s) need the agentic collector and are skipped by collect.py."
        )
    return _OK, lines


def _section_delivery(root: Path) -> tuple[str, list[str]]:
    channels = root / "config" / "channels.yaml"
    if yaml is None:
        return _WARN, _with_next_action(
            ["skipped (needs PyYAML to read channels.yaml)"],
            "run uv run python scripts/doctor.py for the full delivery check",
        )
    if not channels.exists():
        return _FAIL, [
            "config/channels.yaml missing",
            "Next action: restore config/channels.yaml, then run python3 scripts/validate_config.py",
        ]
    # Import lazily: delivery pulls in its adapter modules.
    from scripts.delivery import deliver  # noqa: PLC0415

    try:
        delivery = deliver.load_config(channels)
    except deliver.DeliveryError as error:
        return _FAIL, [
            str(error),
            "Next action: fix config/channels.yaml, then run python3 scripts/delivery/deliver.py --rehearse",
        ]
    channel_cfgs = {
        ch: cfg
        for ch in ("email", "telegram", "rocketchat")
        if isinstance(cfg := delivery.get(ch), dict)
    }
    enabled = [ch for ch, cfg in channel_cfgs.items() if cfg.get("enabled")]
    if not enabled:
        return _WARN, [
            "no delivery channel enabled — digests will build but reach nobody. "
            "Enable one in config/channels.yaml (or via the setup wizard).",
            "Next action: enable one channel in config/channels.yaml or run the setup wizard.",
        ]
    import contextlib  # noqa: PLC0415 — only needed on this branch
    import io  # noqa: PLC0415

    env_path = root / "config" / ".env"
    parsed_env = deliver.parse_dotenv(env_path.read_text(encoding="utf-8")) if env_path.exists() else {}
    previous_env = {key: os.environ.get(key) for key in parsed_env}
    lines: list[str] = []
    try:
        deliver.load_dotenv(env_path)
        for ch in enabled:
            # Reuses the dry-run reporter: target + secret SET/MISSING, never values.
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                deliver._dry_run_channel(ch, channel_cfgs[ch])
            lines.extend(buf.getvalue().strip().splitlines())
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    level = _WARN if any("MISSING" in line or "CONFIG ERROR" in line for line in lines) else _OK
    if level == _WARN:
        missing = sorted(
            {
                match.group(1)
                for line in lines
                if (match := re.search(r"secret ([A-Za-z_][A-Za-z0-9_]*)=MISSING", line))
            }
        )
        if missing:
            envs = ", ".join(missing)
            lines.append(
                f"Next action: set {envs} in config/.env, then run "
                "python3 scripts/delivery/deliver.py --rehearse."
            )
        else:
            lines.append(
                "Next action: fix config/channels.yaml, then run "
                "python3 scripts/delivery/deliver.py --rehearse."
            )
    return level, lines


def _section_health(root: Path) -> tuple[str, list[str]]:
    summary = health.health_summary(root)
    rendered = health.render(summary).strip().splitlines()
    if summary.status is health.Status.DEGRADED:
        return _WARN, _with_next_action(
            rendered,
            "run python3 scripts/health.py report for details; retry delivery after "
            "fixing the channel if delivery failed; then run the pipeline now",
        )
    return _OK, rendered


def _section_schedule(root: Path) -> tuple[str, list[str]]:
    """Detected (not asserted) scheduler registration for this install.

    Advisory: only local schedulers (crontab / Task Scheduler) are probeable;
    a cloud-agent routine (Claude Code /schedule) is off-box, so its absence
    here is a WARN with an explanation, never a FAIL.
    """
    state, evidence = setup_check.probe_scheduler_registration(root)
    if state == "registered":
        return _OK, [f"recurring run detected: {evidence[0] if evidence else 'registered'}"]
    lines = list(evidence)
    lines.append(
        "No local cron/Task Scheduler entry references this install. If you use a "
        "cloud-agent routine (Claude Code /schedule), this is expected — otherwise "
        "register one recurring run for schedule/weekly-run.md (docs/scheduling.md)."
    )
    return _WARN, lines


def _section_run_lock(root: Path) -> tuple[str, list[str]]:
    lines: list[str] = []
    level = _OK
    for label, lock in (
        ("run lock", root / "pipeline" / ".run.lock"),
        ("delivery lock", root / "pipeline" / "3-synthesis" / ".delivered" / ".delivery.lock"),
    ):
        if lock.exists():
            lines.append(
                f"{label} is held ({lock}) — a run may be in progress; a crashed "
                "run frees it automatically when its lease lapses."
            )
            level = _WARN
        else:
            lines.append(f"{label}: free")
    if level == _WARN:
        lines.append(
            "Next action: run python3 scripts/run_lock.py status; if no run is active, "
            "wait for the lease to expire or release only a lock you own with "
            "python3 scripts/run_lock.py release --token <token>."
        )
    return level, lines


_SECTIONS = (
    ("Environment", _section_environment),
    ("Config", _section_config),
    ("Sources", _section_sources),
    ("Collection mode", _section_collection_mode),
    ("Delivery", _section_delivery),
    ("Schedule", _section_schedule),
    ("Health", _section_health),
    ("Run lock", _section_run_lock),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One read-only, plain-language health check for the whole install."
    )
    parser.add_argument(
        "--root", default=str(PROJECT_ROOT),
        help="install root to check (default: this checkout)",
    )
    args = parser.parse_args(argv)
    root = Path(args.root)

    worst = _OK
    print("research-brain doctor — read-only check\n")
    for title, section in _SECTIONS:
        try:
            level, lines = section(root)
        except Exception as error:  # noqa: BLE001 — doctor must never crash a
            # half-configured install; a broken check IS a finding.
            level, lines = _FAIL, [f"check crashed: {error}"]
        if level == _FAIL or (level == _WARN and worst != _FAIL):
            worst = level
        print(f"[{level}] {title}")
        for line in lines:
            print(f"    {line}")
        print()

    if worst == _FAIL:
        print("verdict: something needs fixing — see the FAIL section(s) above.")
        return 1
    if worst == _WARN:
        print(
            "verdict: needs attention — see the WARN section(s) and their next actions."
        )
        return 0
    print("verdict: everything looks good.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
