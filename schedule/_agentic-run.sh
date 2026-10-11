#!/usr/bin/env bash
# schedule/_agentic-run.sh — shared preamble for the agentic cron wrappers.
#
# Sourced (never executed) by schedule/codex-run.sh and schedule/claude-run.sh.
# Both drive the SAME task — schedule/weekly-run.md — through different agent
# CLIs, and both need the same two things before they can hand off:
#
#   1. ROOT — the project root, resolved from this file's own location, so cron
#      needs no pre-set cwd and the wrappers never read config to find it.
#   2. A usable python3 — weekly-run.md's steps call a BARE `python3`, and a
#      minimal cron PATH resolves that to the system interpreter (macOS ships
#      3.9, which lacks datetime.UTC). The project venv goes first, then the
#      version is hard-checked so a stale interpreter fails HERE — with a cron
#      report — instead of cryptically deep inside a step.
#
# It lives in one file on purpose. ADR 0019's addendum recorded what the second
# copy costs: `sync-live.sh` kept its own copy of a contract that `.gitattributes`
# also owned, the two drifted, and the script was deleted for it. A preamble
# duplicated across two wrappers would drift the same way — silently, and only
# on the wrapper nobody ran that week.
#
# Callers set RB_WRAPPER_NAME before sourcing so error messages name the script
# the operator actually scheduled.

RB_WRAPPER_NAME="${RB_WRAPPER_NAME:-agentic-run}"

# BASH_SOURCE[0] is THIS file (schedule/_agentic-run.sh), so ../ is the root —
# the same answer whichever wrapper sourced it.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -x "$ROOT/.venv/bin/python3" ]; then
  PATH="$ROOT/.venv/bin:$PATH"
  export PATH
fi

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "$RB_WRAPPER_NAME: no python3 on PATH — run 'make setup' to create .venv, or install Python >=3.11." >&2
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)'; then
  echo "$RB_WRAPPER_NAME: python3 ($PY) is $("$PY" -V 2>&1) — the pipeline needs >=3.11 (datetime.UTC). Run 'make setup' to create .venv, or put a newer python3 first on PATH." >&2
  exit 1
fi

# The one instruction both runtimes give their agent. Kept here so the two
# wrappers cannot drift into driving subtly different pipelines: the task is a
# PATH (resolved inside the project root), never inlined file content.
RB_RUN_PROMPT='Execute schedule/weekly-run.md step by step, in order, with each step gated on the previous one finishing, exactly as written in that file. Take the run lock first; if a run is already in progress, stop cleanly without doing anything else. Stop the whole run if any step fails. Do not improvise beyond the steps in weekly-run.md.'
