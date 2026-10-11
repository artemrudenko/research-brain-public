#!/usr/bin/env python3
"""Read-only first-run activation checker for research-brain.

This script answers one setup question: can this install produce and deliver
value, and is recurring execution actually registered? It sends nothing and
writes nothing. It composes existing validators, source probing, delivery
dry-run reporting, and scheduler state into a concise activation receipt.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import io
import json
import os
import subprocess  # scheduler probe only: fixed argv (crontab/schtasks), no shell  # nosec B404
import sys
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import brain_status, collect, validate_config  # noqa: E402
from scripts._yaml import optional_yaml  # noqa: E402
from scripts.delivery import deliver  # noqa: E402
from scripts.sources import store as sources_store  # noqa: E402

SOURCE_STATUSES = {"verified", "missing", "empty", "unsupported", "failed"}
CONFIG_STATUSES = {"valid", "invalid"}
DELIVERY_STATUSES = {
    "rehearsed",
    "missing_secret",
    "unsupported_runtime",
    "config_error",
    "transient_failure",
    "disabled",
}
SCHEDULER_STATUSES = {"registered", "ready_not_registered", "unknown"}
FIRST_VALUE_STATUSES = {"available", "empty", "not_checked"}
FINAL_STATUSES = {"complete", "ready_schedule_not_registered", "needs_attention"}
RUNTIMES = {"agentic", "headless"}


@dataclass(frozen=True)
class CheckItem:
    """One activation checklist item."""

    name: str
    status: str
    summary: str
    detail: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SetupCheck:
    """Full setup activation result."""

    final_status: str
    runtime: str
    items: dict[str, CheckItem]

    def to_dict(self) -> dict[str, object]:
        return {
            "final_status": self.final_status,
            "runtime": self.runtime,
            "items": {name: item.to_dict() for name, item in self.items.items()},
        }


def _load_yaml() -> ModuleType | None:
    return optional_yaml()


def _config_item(root: Path) -> CheckItem:
    config = root / "config"
    errors: list[str] = []
    for name in ("channels.yaml", "schedule.yaml"):
        if not (config / name).exists():
            errors.append(f"{name}: missing")

    yaml = _load_yaml()

    # The sources/topics config may be in either format — validate whichever is
    # ACTIVE (the YAML twins win when present; CONVENTIONS §2.3).
    sources = sources_store.active_sources_path(config)
    topics = sources_store.active_topics_path(config)
    for path in (sources, topics):
        if not path.exists():
            errors.append(f"{path.name}: missing")
    if sources.suffix == ".yaml":
        if yaml is None:
            errors.append("sources.yaml/topics.yaml: PyYAML unavailable")
        else:
            if sources.exists():
                errors.extend(validate_config.validate_sources_yaml(sources, yaml))
            if topics.exists():
                errors.extend(validate_config.validate_topics_yaml(topics, yaml))
    else:
        if sources.exists():
            errors.extend(validate_config.validate_sources(sources))
        if topics.exists():
            errors.extend(validate_config.validate_topics(topics))

    if yaml is None:
        errors.append("channels.yaml/schedule.yaml/tags.yaml: PyYAML unavailable")
    else:
        channels = config / "channels.yaml"
        schedule = config / "schedule.yaml"
        if channels.exists():
            errors.extend(validate_config.validate_channels(channels, yaml))
        if schedule.exists():
            errors.extend(validate_config.validate_schedule(schedule, yaml))
        tags = config / "tags.yaml"
        if tags.exists():
            errors.extend(validate_config.validate_tags(tags, yaml))

    if topics.exists() and sources.exists():
        errors.extend(validate_config.check_topics_sources_sync(topics, sources))

    if errors:
        return CheckItem("config", "invalid", "configuration has validation errors", errors)
    return CheckItem("config", "valid", "configuration schema is valid", [])


def _categories_with_active_rss(root: Path) -> list[collect.Category]:
    sources_path = sources_store.active_sources_path(root / "config")
    if not sources_path.exists():
        return []
    try:
        categories = sources_store.load_categories(sources_path)
    except (ValueError, RuntimeError):
        # A malformed config yields no probeable categories here; the loud
        # schema error is _config_item's report, not the probe's.
        return []
    return [
        category
        for category in categories
        if any(source.active and source.type == "rss" for source in category.sources)
    ]


def probe_rss_sources(
    root: Path,
    fetch_fn: Callable[[str], str] | None = None,
) -> CheckItem:
    """Read RSS feeds in dry-run mode and classify whether one can produce value."""

    categories = _categories_with_active_rss(root)
    if not categories:
        return CheckItem("source", "missing", "no active rss source configured", [])

    incoming = root / "pipeline" / "1-incoming"
    registry = root / "pipeline" / "registry.md"
    today = _dt.date.today().isoformat()
    attempted = 0
    errors = 0
    would_save = 0
    details: list[str] = []

    for category in categories:
        try:
            result = collect.collect_category(
                category=category.name,
                sources=category.sources,
                incoming_dir=incoming,
                registry_path=registry,
                today=today,
                known_urls=set(),
                max_articles=1,
                dry_run=True,
                fetch_fn=fetch_fn,
            )
        except Exception as error:  # noqa: BLE001 — setup check reports, never crashes
            rss_count = sum(1 for source in category.sources if source.active and source.type == "rss")
            attempted += rss_count
            errors += rss_count
            details.append(f"{category.name}: probe failed: {error}")
            continue
        attempted += result.sources_attempted
        errors += result.source_errors
        would_save += result.saved
        details.append(
            f"{category.name}: attempted={result.sources_attempted}, "
            f"would_save={result.saved}, source_errors={result.source_errors}"
        )

    if would_save > 0:
        return CheckItem("source", "verified", "RSS source produced at least one item", details)
    if attempted > 0 and errors == attempted:
        return CheckItem("source", "failed", "every attempted RSS source failed", details)
    return CheckItem("source", "empty", "RSS sources responded but no qualifying item was found", details)


def _source_item(
    root: Path,
    runtime: str,
    source_probe: Callable[[Path, str], CheckItem] | None,
) -> CheckItem:
    if source_probe is not None:
        return source_probe(root, runtime)
    if _categories_with_active_rss(root):
        return probe_rss_sources(root)
    records = brain_status.monitored_sources(root=root)
    if not records:
        return CheckItem("source", "missing", "no active monitored source configured", [])
    if runtime == "agentic":
        return CheckItem(
            "source",
            "unsupported",
            "agentic source verification requires an agent runtime probe",
            [f"{len(records)} active non-RSS source(s) configured"],
        )
    return CheckItem(
        "source",
        "unsupported",
        "RSS Digest Lite requires an active rss source",
        [f"{len(records)} active non-RSS source(s) configured"],
    )


def _enabled_delivery_configs(delivery_cfg: dict[str, object]) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for channel in ("email", "telegram", "rocketchat"):
        raw = delivery_cfg.get(channel)
        if isinstance(raw, dict) and raw.get("enabled"):
            out[channel] = raw
    return out


@contextlib.contextmanager
def _temporary_dotenv(root: Path) -> Iterator[None]:
    """Load `root/config/.env` only for the current setup check.

    Delivery dry-run code reads secret *presence* from `os.environ`. Headless users
    normally keep those secrets in `config/.env`, so the setup checker must see
    that file. The checker is still read-only and hermetic: existing environment
    values win, and any variables loaded from `.env` are restored afterwards.
    """

    env_path = root / "config" / ".env"
    parsed = (
        deliver.parse_dotenv(env_path.read_text(encoding="utf-8"))
        if env_path.exists()
        else {}
    )
    previous = {key: os.environ.get(key) for key in parsed}
    try:
        deliver.load_dotenv(env_path)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _delivery_item(root: Path, runtime: str) -> CheckItem:
    config_path = root / "config" / "channels.yaml"
    try:
        delivery_cfg = deliver.load_config(config_path)
    except deliver.DeliveryError as error:
        return CheckItem("delivery", "config_error", str(error), [str(error)])

    enabled = _enabled_delivery_configs(delivery_cfg)
    if not enabled:
        return CheckItem("delivery", "disabled", "no delivery channel enabled", [])

    lines: list[str] = []
    with _temporary_dotenv(root):
        for channel, cfg in enabled.items():
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                deliver._dry_run_channel(channel, cfg)
            lines.extend(line for line in buf.getvalue().splitlines() if line.strip())

    if any("CONFIG ERROR" in line for line in lines):
        return CheckItem("delivery", "config_error", "delivery config error", lines)
    if any("MISSING" in line for line in lines):
        return CheckItem("delivery", "missing_secret", "delivery secret is missing", lines)
    if any("SKIPPED" in line for line in lines):
        summary = (
            "enabled channels are MCP-only in a headless runtime"
            if runtime == "headless"
            else "MCP delivery requires agent runtime connector verification"
        )
        return CheckItem(
            "delivery",
            "unsupported_runtime",
            summary,
            lines,
        )
    return CheckItem("delivery", "rehearsed", "delivery dry-run resolved", lines)


def _normalize_scheduler_state(value: str | None) -> str:
    if value is None:
        return "ready_not_registered"
    normalized = value.replace("-", "_")
    if normalized not in SCHEDULER_STATUSES:
        raise ValueError(f"invalid scheduler state: {value}")
    return normalized


def probe_scheduler_registration(
    root: Path,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    platform: str | None = None,
) -> tuple[str, list[str]]:
    """Best-effort, read-only detection of a registered recurring run.

    Looks for a scheduler entry that references THIS install by absolute path —
    the user crontab on POSIX, Task Scheduler (`schtasks`) on Windows. The
    path match keeps a sibling install's entry (e.g. a dev checkout next to
    the live one) from counting as registration here.

    Cloud-agent routines (Claude Code `/schedule`) live off-box and cannot be
    probed — pass an explicit ``--scheduler-state registered`` for those.

    Never raises: a probe that cannot run reports ``ready_not_registered``
    with the reason in the evidence, so a box without crontab is no worse off
    than before the probe existed (``unknown`` would flip the final status to
    ``needs_attention``).
    """
    runner = run if run is not None else subprocess.run
    plat = platform if platform is not None else os.name
    marker = str(root.resolve())
    if plat == "nt":
        cmd = ["schtasks", "/query", "/fo", "LIST", "/v"]
        miss = "schtasks: no task references this install"
        unavailable = "schtasks unavailable — cannot verify registration"
    else:
        cmd = ["crontab", "-l"]
        miss = "crontab: no entry references this install"
        unavailable = "crontab unavailable — cannot verify registration"
    try:
        result = runner(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "ready_not_registered", [unavailable]
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if plat != "nt" and stripped.startswith("#"):
                continue
            if marker in stripped:
                return "registered", [f"detected: {stripped[:160]}"]
    return "ready_not_registered", [miss]


def _scheduler_item(
    scheduler_state: str | None, evidence: list[str] | None = None
) -> CheckItem:
    status = _normalize_scheduler_state(scheduler_state)
    if status == "registered":
        return CheckItem(
            "scheduler", status, "recurring execution is registered", list(evidence or [])
        )
    if status == "ready_not_registered":
        detail = ["register one recurring run for schedule/weekly-run.md"]
        detail.extend(evidence or [])
        return CheckItem("scheduler", status, "ready, schedule not registered", detail)
    return CheckItem(
        "scheduler",
        status,
        "scheduler registration could not be verified",
        list(evidence or []),
    )


def _first_value_item(source: CheckItem) -> CheckItem:
    if source.status == "verified":
        return CheckItem("first_value", "available", "source produced first-value evidence", [])
    if source.status in {"empty", "missing"}:
        return CheckItem("first_value", "empty", "no first-value item available yet", [])
    return CheckItem("first_value", "not_checked", "first value was not checked", [])


def _final_status(items: dict[str, CheckItem]) -> str:
    source_ok = items["source"].status == "verified"
    config_ok = items["config"].status == "valid"
    delivery_ok = items["delivery"].status == "rehearsed"
    scheduler = items["scheduler"].status
    if source_ok and config_ok and delivery_ok and scheduler == "registered":
        return "complete"
    if source_ok and config_ok and delivery_ok and scheduler == "ready_not_registered":
        return "ready_schedule_not_registered"
    return "needs_attention"


def _next_action_item(final_status: str, items: dict[str, CheckItem]) -> CheckItem:
    if final_status == "complete":
        return CheckItem(
            "next_action",
            "available",
            "Run the next scheduled weekly-run or ask: run the pipeline now",
            [],
        )
    if final_status == "ready_schedule_not_registered":
        return CheckItem(
            "next_action",
            "available",
            "register one recurring run for schedule/weekly-run.md at digest.cron in config/schedule.yaml",
            [],
        )

    for name in ("config", "source", "delivery", "scheduler"):
        item = items[name]
        if item.status not in {"valid", "verified", "rehearsed", "registered"}:
            return CheckItem(
                "next_action",
                "not_checked",
                f"fix {name}: {item.status}",
                item.detail[:3],
            )
    return CheckItem("next_action", "not_checked", "review setup output", [])


def run_setup_check(
    root: Path,
    runtime: str = "agentic",
    scheduler_state: str | None = None,
    source_probe: Callable[[Path, str], CheckItem] | None = None,
    delivery_probe: Callable[[Path, str], CheckItem] | None = None,
    scheduler_probe: Callable[[Path], tuple[str, list[str]]] | None = None,
) -> SetupCheck:
    """Run all setup checks and return a machine-readable activation receipt.

    An explicit ``scheduler_state`` always wins; otherwise ``scheduler_probe``
    (when given) detects the state instead of asserting the static default.
    """

    if runtime not in RUNTIMES:
        raise ValueError(f"invalid runtime: {runtime}")
    if scheduler_state is None and scheduler_probe is not None:
        probed_state, probe_evidence = scheduler_probe(root)
        scheduler = _scheduler_item(probed_state, probe_evidence)
    else:
        scheduler = _scheduler_item(scheduler_state)
    config = _config_item(root)
    source = _source_item(root, runtime, source_probe)
    delivery = delivery_probe(root, runtime) if delivery_probe is not None else _delivery_item(root, runtime)
    first_value = _first_value_item(source)
    items = {
        "source": source,
        "config": config,
        "delivery": delivery,
        "scheduler": scheduler,
        "first_value": first_value,
    }
    final = _final_status(items)
    items["next_action"] = _next_action_item(final, items)
    return SetupCheck(final, runtime, items)


def _render_item(label: str, item: CheckItem) -> str:
    detail = f" — {'; '.join(item.detail[:3])}" if item.detail else ""
    return f"{label}: {item.status} — {item.summary}{detail}"


def render_human(result: SetupCheck) -> str:
    """Render a concise checklist for a first-run user."""

    return "\n".join(
        [
            f"Setup status: {result.final_status}",
            _render_item("Source", result.items["source"]),
            _render_item("Config", result.items["config"]),
            _render_item("Delivery", result.items["delivery"]),
            _render_item("Schedule", result.items["scheduler"]),
            _render_item("First value", result.items["first_value"]),
            _render_item("Next action", result.items["next_action"]),
        ]
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="setup_check.py",
        description="Read-only setup activation checklist.",
    )
    parser.add_argument("--root", default=str(PROJECT_ROOT), help="project root to check")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument(
        "--runtime",
        default="agentic",
        help="runtime path to check: agentic or headless",
    )
    parser.add_argument(
        "--scheduler-state",
        default=None,
        help=(
            "registered, ready-not-registered, or unknown. Default: auto-detect "
            "(crontab / Task Scheduler entries referencing this install; "
            "cloud-agent routines cannot be probed — pass registered explicitly)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    raw_args = sys.argv[1:] if argv is None else argv
    if "--help" in raw_args or "-h" in raw_args:
        parser.print_help()
        return 0
    try:
        args = parser.parse_args(raw_args)
        if args.runtime not in RUNTIMES:
            raise ValueError(f"invalid runtime: {args.runtime}")
        _normalize_scheduler_state(args.scheduler_state)
    except (SystemExit, ValueError) as error:
        if not isinstance(error, SystemExit):
            print(f"error: {error}", file=sys.stderr)
        return 2

    try:
        result = run_setup_check(
            Path(args.root),
            runtime=args.runtime,
            scheduler_state=args.scheduler_state,
            scheduler_probe=probe_scheduler_registration,
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(render_human(result))
    return 0 if result.final_status in {"complete", "ready_schedule_not_registered"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
