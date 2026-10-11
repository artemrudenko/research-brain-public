"""CLI orchestration for read-only URL intake."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from scripts.intake_flow.classification import classify_url
from scripts.intake_flow.models import Classification
from scripts.intake_flow.rendering import render_human, render_json

ClassifyUrl = Callable[[str, Path], Classification]


def build_parser(default_config_dir: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify one URL for unified intake")
    parser.add_argument("url", nargs="?", help="HTTP(S) URL to classify")
    parser.add_argument(
        "--config-dir",
        default=str(default_config_dir),
        help="config directory (default: project config/)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    return parser


def run_cli(
    argv: list[str] | None,
    *,
    default_config_dir: Path,
    classify: ClassifyUrl = classify_url,
) -> int:
    parser = build_parser(default_config_dir)
    args = parser.parse_args(argv)

    if not args.url:
        parser.print_usage(sys.stderr)
        return 2

    try:
        result = classify(args.url, Path(args.config_dir))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(render_json(result))
    else:
        print(render_human(result))
    return 0
