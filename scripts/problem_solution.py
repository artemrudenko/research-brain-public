#!/usr/bin/env python3
"""Validate a record, stage/review exact changes, apply after direct owner approval."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.problem_solutions.profile import MAX_BYTES, validate_record
from scripts.problem_solutions.workflow import (
    apply_proposal,
    check_context,
    propose,
    review_proposal,
)
from scripts.run_lock import LockHeldError


def read_input(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("input must be a bounded regular UTF-8 file")
    return path.read_bytes().decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser(
        "validate", help="Read-only structural check; --root also checks retained evidence and tags"
    )
    validate.add_argument("note", type=Path)
    validate.add_argument("--root", type=Path)
    prepare = commands.add_parser(
        "propose", help="Stage a private package; does not save searchable knowledge"
    )
    prepare.add_argument("--slug", required=True)
    prepare.add_argument("--body-file", type=Path, required=True)
    prepare.add_argument(
        "--artifact", nargs=2, action="append", default=[], metavar=("VAULT_PATH", "LOCAL_FILE")
    )
    review = commands.add_parser(
        "review", help="Regenerate the exact review and digest from candidate bytes"
    )
    review.add_argument("id")
    apply = commands.add_parser(
        "apply",
        help="Trusted interactive operator only: apply an explicitly approved exact package",
    )
    apply.add_argument("id")
    apply.add_argument("--approved-digest", required=True)
    apply.add_argument(
        "--approval-reference",
        required=True,
        help="Direct human approval message/event reference; not authentication",
    )
    for cmd in (prepare, review, apply):
        cmd.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            text = read_input(args.note)
            errors = validate_record(text)
            if not errors and args.root is not None:
                check_context(args.root, text, {}, for_write=False)
            print(json.dumps(dict(valid=not errors, errors=errors)))
            return 2 if errors else 0
        if args.command == "propose":
            artifacts = {dest: read_input(Path(src)) for dest, src in args.artifact}
            if len(artifacts) != len(args.artifact):
                raise ValueError("duplicate artifact destination")
            result = propose(args.root, args.slug, read_input(args.body_file), artifacts)
        elif args.command == "review":
            result = review_proposal(args.root, args.id)
            print(result["review"])
            return 0
        else:
            result = apply_proposal(
                args.root, args.id, args.approved_digest, args.approval_reference
            )
        print(json.dumps(result))
        return 0
    except (ValueError, OSError, LockHeldError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
