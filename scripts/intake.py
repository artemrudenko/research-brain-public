#!/usr/bin/env python3
"""Stable CLI/import facade for read-only URL intake."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"

if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.intake_flow import (  # noqa: E402
    CLARIFICATION_QUESTION,
    Classification,
    Kind,
    classify_url,
    render_human,
)
from scripts.intake_flow.cli import run_cli  # noqa: E402

__all__ = [
    "CLARIFICATION_QUESTION",
    "Classification",
    "Kind",
    "_render_human",
    "classify_url",
    "main",
]


def _render_human(result: Classification) -> str:
    return render_human(result)


def main(argv: list[str] | None = None) -> int:
    return run_cli(argv, default_config_dir=DEFAULT_CONFIG_DIR, classify=classify_url)


if __name__ == "__main__":
    sys.exit(main())
