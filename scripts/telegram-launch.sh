#!/usr/bin/env bash
# telegram-launch.sh — start a Claude session with the Telegram channel LIVE.
#
# Plain `claude` leaves the Telegram plugin send-only: digests arrive, but the bot
# never answers /save, help, … because nothing listens for inbound messages. This
# launcher bundles the two things inbound needs — with no shell-rc editing:
#   • a per-project TELEGRAM_STATE_DIR, so THIS project's bot token has its own
#     listener and doesn't steal another project's bot (a Telegram token allows
#     exactly one live listener — docs/telegram-multiproject.md);
#   • the --channels flag that actually turns inbound on.
#
#   make telegram                        # the everyday form
#   scripts/telegram-launch.sh [args…]   # same, extra args go to `claude`
#
# The project root is resolved from this script's own location — nothing to edit.
# To point several installs at different bots, each install's launcher derives its
# own state dir from the folder name; override explicitly with TELEGRAM_STATE_DIR.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v claude >/dev/null 2>&1; then
  printf 'claude CLI not found on PATH — install Claude Code first: https://claude.com/claude-code\n' >&2
  exit 1
fi

# Per-project state dir keyed by the install folder's name: two installs → two
# listeners → two bots that never steal each other.
STATE_DIR="${TELEGRAM_STATE_DIR:-$HOME/.claude/channels/telegram-$(basename "$ROOT")}"

exec env TELEGRAM_STATE_DIR="$STATE_DIR" \
  claude --channels plugin:telegram@claude-plugins-official "$@"
