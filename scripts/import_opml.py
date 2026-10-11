#!/usr/bin/env python3
"""Preview and import RSS/Atom subscriptions from OPML.

The module is intentionally deterministic and conservative:

- default execution prints a read-only preview;
- persistence requires `--apply --confirmed` or explicit `--automatic`;
- config writes go through `scripts.manage_sources`, never table surgery here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"

if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.manage_sources import (  # noqa: E402
    _validate_topic_name,
    add_source,
    add_topic,
)
from scripts.opml_import.cli import (  # noqa: E402
    _parse_assignments,
    _parse_csv_ids,
    _render_human,
)
from scripts.opml_import.model import (  # noqa: E402
    STATUSES,
    OpmlEntry,
    OpmlError,
    Status,
    UsageError,
)
from scripts.opml_import.parsing import (  # noqa: E402
    _SLUG_RE,
    MAX_OPML_BYTES,
    _is_http_url,
    _local_name,
    _outline_attr,
    _outline_children,
    _safe_slug,
    _short_hash,
    _stable_folder_slugs,
    parse_opml,
)
from scripts.opml_import.preview import (  # noqa: E402
    _ID_RE,
    _apply_assignments,
    _apply_selection,
    _base_items,
    _counts,
    _existing_state,
    _proposed_topics,
    _topic_label,
    _validate_id,
    _validate_repeated,
    build_preview,
)

__all__ = [
    "DEFAULT_CONFIG_DIR",
    "MAX_OPML_BYTES",
    "PROJECT_ROOT",
    "STATUSES",
    "OpmlEntry",
    "OpmlError",
    "Status",
    "UsageError",
    "_ID_RE",
    "_SLUG_RE",
    "_apply_assignments",
    "_apply_selection",
    "_base_items",
    "_counts",
    "_existing_state",
    "_is_http_url",
    "_local_name",
    "_outline_attr",
    "_outline_children",
    "_parse_assignments",
    "_parse_csv_ids",
    "_proposed_topics",
    "_render_human",
    "_safe_slug",
    "_short_hash",
    "_stable_folder_slugs",
    "_topic_label",
    "_validate_id",
    "_validate_repeated",
    "_validate_topic_name",
    "apply_preview",
    "build_preview",
    "main",
    "parse_opml",
]


def apply_preview(preview: dict[str, Any], config_dir: str | Path) -> dict[str, Any]:
    """Apply selected ready preview items through manage_sources APIs."""

    cfg = Path(config_dir)
    result_items: list[dict[str, Any]] = []
    for original in preview.get("items", []):
        item = dict(original)
        if not item.get("selected") or item.get("status") != "ready":
            result_items.append(item)
            continue

        try:
            topic = str(item["resulting_topic"])
            add_topic(cfg, topic)
            changed = add_source(
                cfg,
                topic=topic,
                url=str(item["url"]),
                source_type="rss",
                tier="medium",
                priority="medium",
                filter_note="Imported from OPML",
                active=True,
            )
            if changed:
                item["status"] = "added"
                item["reason"] = "Added"
            else:
                item["status"] = "already_existing"
                item["reason"] = "Already present in config"
            item["selected"] = False
        except Exception as exc:  # noqa: BLE001 - item failures are reported per item
            item["status"] = "failed"
            item["reason"] = str(exc)
        result_items.append(item)

    return {
        "mode": "applied",
        "items": result_items,
        "proposed_topics": preview.get("proposed_topics", []),
        "counts": _counts(result_items),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preview and import OPML subscriptions")
    parser.add_argument("opml_path", nargs="?", help="OPML file to preview/import")
    parser.add_argument(
        "--config-dir",
        default=str(DEFAULT_CONFIG_DIR),
        help="config directory (default: project config/)",
    )
    parser.add_argument("--select", help="comma-separated ready item IDs to import")
    parser.add_argument(
        "--assign",
        action="append",
        default=[],
        metavar="ID=topic-slug",
        help="override the resulting topic for a ready item; may be repeated",
    )
    parser.add_argument("--apply", action="store_true", help="persist selected ready items")
    parser.add_argument("--confirmed", action="store_true", help="confirm --apply")
    parser.add_argument(
        "--automatic",
        action="store_true",
        help="explicit automation mode; implies --apply and confirmation",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON report")

    args = parser.parse_args(argv)

    if not args.opml_path:
        parser.print_usage(sys.stderr)
        return 2

    apply_requested = bool(args.apply or args.automatic)
    if args.apply and not args.confirmed and not args.automatic:
        print("ERROR: --apply requires confirmation via --confirmed", file=sys.stderr)
        return 2

    try:
        entries = parse_opml(args.opml_path)
        preview = build_preview(
            entries,
            Path(args.config_dir),
            assignments=_parse_assignments(args.assign),
            selected=_parse_csv_ids(args.select),
        )
        report = apply_preview(preview, args.config_dir) if apply_requested else preview
    except (OpmlError, UsageError, ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_render_human(report))

    if any(item["status"] == "failed" for item in report["items"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
