#!/usr/bin/env python3
"""
install_schedule.py — turn the declared cadence into a registered recurring run.

`config/schedule.yaml` declares WHEN the pipeline should run; it registers
nothing. Until now the remaining half was manual: copy a crontab block out of
the docs, fix the paths by hand, remember to escape `%`, paste it into
`crontab -e`. That gap is why an install can sit at
`Schedule: ready_schedule_not_registered` indefinitely while everything else is
configured — and why a hand-written crontab file can quietly drift from the
cadence the config declares.

This script closes it. It reads the cadence (never invents one), renders the
block for the run path you choose, writes a paste-ready file, and — with
`--apply` — merges it into your crontab.

The three run paths mirror docs/scheduling.md:

    claude    schedule/claude-run.sh  — the agentic loop via the Claude Code CLI
                                        (path D: local install, MCP delivery)
    codex     schedule/codex-run.sh   — the agentic loop via the Codex CLI (path C)
    headless  build_digest.py + deliver.py — the deterministic RSS-Lite chain
                                        (path B: no agent runtime on the box)

Whichever you pick, the block also registers the daily health watchdog, the one
alert that still fires when the weekly run crashed early or never started.

`scripts/setup_check.py` detects registration by looking for a crontab line that
names this install by absolute path — so a block written here makes the wizard's
`Schedule:` line flip to `registered` on its own.

CLI:
    python3 scripts/install_schedule.py --path claude            # write the file
    python3 scripts/install_schedule.py --path claude --apply    # ...and register it
    python3 scripts/install_schedule.py --path headless --print  # stdout only
"""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess  # registration only: fixed argv (crontab), never a shell  # nosec B404
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._yaml import optional_yaml  # noqa: E402

RUN_PATHS = ("claude", "codex", "headless")
DEFAULT_OUT_NAME = "crontab-research-brain.txt"

# Markers delimiting OUR block inside a crontab that may hold unrelated entries.
# Registration is a read-modify-write of the whole crontab, so the boundary has
# to be explicit: everything between the markers is ours to replace, everything
# outside is the user's to preserve.
BEGIN_MARKER = "# >>> research-brain schedule (managed by scripts/install_schedule.py) >>>"
END_MARKER = "# <<< research-brain schedule <<<"

# The watchdog has no cadence key in schedule.yaml — it is deliberately decoupled
# from the run it reports on. This is the daily time docs/scheduling.md uses in
# its "Health alerts (opt-in)" example.
WATCHDOG_CRON = "0 10 * * *"


class ScheduleInstallError(RuntimeError):
    """Configuration or environment problem the operator must fix."""


def _load_schedule(root: Path) -> dict[str, object]:
    path = root / "config" / "schedule.yaml"
    if not path.is_file():
        raise ScheduleInstallError(
            f"no cadence to install: {path} is missing — run the setup wizard "
            "(or `make configure`) before registering a schedule."
        )
    yaml = optional_yaml()
    if yaml is None:
        raise ScheduleInstallError(
            "PyYAML is required to read config/schedule.yaml — run 'make setup' "
            "(or `pip install -r requirements.txt`) first."
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ScheduleInstallError(f"{path} is not a YAML mapping")
    return data


def _cron_of(schedule: dict[str, object], block: str, *, default: str) -> str:
    section = schedule.get(block)
    if isinstance(section, dict):
        value = section.get("cron")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _escape(command: str) -> str:
    """Escape `%` for crontab.

    An unescaped `%` is where cron starts stdin for the command, so the rest of
    the line silently disappears — the classic way a `$(date +%F)` digest path
    turns into a truncated command that half-runs.
    """
    return command.replace("%", "\\%")


def render_block(*, root: Path, run_path: str) -> str:
    """The crontab block for this install, derived from its own config."""
    if run_path not in RUN_PATHS:
        raise ScheduleInstallError(
            f"unknown run path {run_path!r} — choose one of: {', '.join(RUN_PATHS)}"
        )
    root = root.resolve()
    schedule = _load_schedule(root)
    timezone = schedule.get("timezone")
    tz = timezone.strip() if isinstance(timezone, str) and timezone.strip() else "UTC"
    digest_cron = _cron_of(schedule, "digest", default="0 9 * * 1")
    collect_cron = _cron_of(schedule, "collect", default="0 9 */3 * *")

    py = f"{root}/.venv/bin/python3"
    lines = [
        BEGIN_MARKER,
        f"# Generated from {root}/config/schedule.yaml — re-run "
        "scripts/install_schedule.py after changing the cadence.",
        "# Cron times are interpreted in CRON_TZ, kept equal to the YAML `timezone`.",
        f"CRON_TZ={tz}",
    ]

    if run_path == "headless":
        digest_file = "pipeline/3-synthesis/digest_$(date +%F).md"
        lines += [
            f"# {collect_cron} (collect.cron) — scan sources, save new articles:",
            f"{collect_cron}  cd {root} && {py} scripts/collect.py",
            f"# {digest_cron} (digest.cron) — sanitize, build, deliver, stamp the heartbeat:",
            _escape(
                f"{digest_cron}  cd {root} && {py} scripts/sanitize_incoming.py sanitize"
                f" && {py} scripts/build_digest.py {digest_file}"
                f" && {py} scripts/delivery/deliver.py {digest_file}"
                f" && {py} scripts/health.py record --kind run --status ok"
            ),
        ]
    else:
        wrapper = f"{root}/schedule/{run_path}-run.sh"
        # A cron PATH is usually shorter than the interactive PATH that found
        # the CLI. Pin the selected Codex binary in the managed line when it is
        # available, leaving manual preview generation possible without Codex.
        cli_prefix = ""
        if run_path == "codex" and (cli_path := shutil.which("codex")):
            cli_prefix = f"CODEX_RUN_BIN={shlex.quote(str(Path(cli_path).resolve()))} "
        lines += [
            f"# {digest_cron} (digest.cron) — the whole gated loop, agentically:",
            f"{digest_cron}  {cli_prefix}{wrapper}",
        ]

    lines += [
        "# Daily — alert only when the health verdict is DEGRADED (opt-in; no-op until"
        " delivery.alerts is enabled):",
        f"{WATCHDOG_CRON}  cd {root} && {py} scripts/health_alert.py",
        END_MARKER,
    ]
    return "\n".join(lines) + "\n"


def _current_crontab() -> str:
    """The user's crontab, or "" when there is none (an empty crontab is not an
    error — `crontab -l` exits non-zero for it on most implementations)."""
    if shutil.which("crontab") is None:
        raise ScheduleInstallError(
            "no `crontab` on PATH — cannot register. Write the file without "
            "--apply and install it with your platform's scheduler "
            "(Windows: Task Scheduler, see docs/scheduling.md)."
        )
    # argv is built first (never a literal at the call site) and never a shell —
    # the same shape scripts/setup_check.py uses for its read-only probe.
    cmd = ["crontab", "-l"]
    try:
        # nosec B603 — fixed argv (`crontab -l`), no shell, no user-controlled args
        proc = subprocess.run(  # nosec B603
            cmd, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScheduleInstallError(f"could not read the current crontab: {exc}") from exc
    # A non-zero exit means "no crontab yet" on most implementations — not an error.
    return proc.stdout if proc.returncode == 0 else ""


def strip_block(crontab: str) -> str:
    """Remove a previously installed block, keeping every other entry."""
    out: list[str] = []
    inside = False
    for line in crontab.splitlines():
        if line.strip() == BEGIN_MARKER:
            inside = True
            continue
        if inside:
            if line.strip() == END_MARKER:
                inside = False
            continue
        out.append(line)
    text = "\n".join(out).strip("\n")
    return text + "\n" if text else ""


def apply_block(block: str) -> None:
    """Merge the block into the user's crontab (replacing an older one)."""
    merged = strip_block(_current_crontab()) + block
    cmd = ["crontab", "-"]
    try:
        # nosec B603 — fixed argv (`crontab -`); the block goes in on STDIN, never argv
        proc = subprocess.run(  # nosec B603
            cmd, input=merged, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScheduleInstallError(f"could not run `crontab -`: {exc}") from exc
    if proc.returncode != 0:
        raise ScheduleInstallError(
            f"`crontab -` refused the block (exit {proc.returncode}): "
            f"{proc.stderr.strip() or 'no error output'}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate (and optionally register) this install's crontab block."
    )
    parser.add_argument("--root", default=str(PROJECT_ROOT), help="install root (default: this one)")
    parser.add_argument(
        "--path",
        default="claude",
        choices=RUN_PATHS,
        help="which run path to schedule (default: claude)",
    )
    parser.add_argument("--out", default=None, help=f"output file (default: <root>/{DEFAULT_OUT_NAME})")
    parser.add_argument("--apply", action="store_true", help="register it with `crontab` now")
    parser.add_argument("--print", dest="to_stdout", action="store_true", help="print only, write no file")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        block = render_block(root=root, run_path=args.path)
    except ScheduleInstallError as exc:
        print(f"install_schedule: {exc}", file=sys.stderr)
        return 2

    if args.to_stdout:
        print(block, end="")
        return 0

    out_path = Path(args.out) if args.out else root / DEFAULT_OUT_NAME
    out_path.write_text(block, encoding="utf-8")
    print(f"wrote {out_path}")

    if not args.apply:
        # Print the merge form, not `crontab <file>` — that one REPLACES the
        # whole crontab, silently dropping unrelated entries.
        print(
            "\nNot registered yet. To install it (keeps your other entries):\n"
            f"  (crontab -l 2>/dev/null; cat {out_path}) | crontab -\n"
            "or re-run this command with --apply.\n"
            "Verify afterwards with: crontab -l | grep research-brain"
        )
        return 0

    try:
        apply_block(block)
    except ScheduleInstallError as exc:
        print(f"install_schedule: {exc}", file=sys.stderr)
        return 1
    print("registered — verify with: crontab -l | grep research-brain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
