#!/usr/bin/env bash
# schedule/codex-run.sh — drive the gated weekly pipeline through the OpenAI Codex CLI.
#
# This is the "C. Codex" path in docs/scheduling.md: an OS-cron entry calls this wrapper,
# which runs `codex exec` non-interactively against schedule/weekly-run.md. It is the
# AGENTIC equivalent of the headless build_digest.py + deliver.py pair — use it when you
# want the LLM-dependent steps (collect ranking + "Key takeaways", synthesis) to run
# unattended on a box that has Codex instead of Claude Code's `/schedule` cloud agents.
#
# One-time prerequisites (see docs/scheduling.md "C. Codex" for the full setup):
#   - Codex CLI installed and authenticated (a ChatGPT login, or OPENAI_API_KEY in
#     config/.env for a fully headless cron run).
#   - The wrapper grants workspace-write + network egress for this run; without
#     network egress the agentic collector cannot fetch configured sources.
#   - Delivery set to the headless transports in config/channels.yaml
#     (provider: smtp / transport: bot-api), since Codex has no Gmail/Telegram MCP by
#     default. weekly-run.md already serializes runs via scripts/run_lock.py, so this is
#     safe to schedule alongside a Claude `/schedule` agent or a cron collect.py.
#
# Optional model tiering: set CODEX_PROFILE to a profile from
# config/codex-profiles.example.toml (e.g. CODEX_PROFILE=rb-synthesizer) to run the whole
# pipeline at that role's model tier. Per-STEP tiering needs the component cron jobs — see
# that file's "Applying the profiles".
#
# Cron example (keep CRON_TZ equal to config/schedule.yaml `timezone`):
#   CRON_TZ=UTC
#   0 9 * * 1  /path/to/research-brain/schedule/codex-run.sh
#   # or, at the synthesis model tier:
#   0 9 * * 1  CODEX_PROFILE=rb-synthesizer /path/to/research-brain/schedule/codex-run.sh
#
# Customize the model/flags by editing the `codex exec` line below (e.g. add `--model`).
# Exit status is Codex's own: a non-zero exit means the run failed, so cron reports it.
set -euo pipefail

# ── shared preamble: project ROOT, the locked python3, and the run prompt ─────
# ROOT resolution and the >=3.11 interpreter guard are identical for every
# agentic wrapper, so they live in ONE file that both this script and
# claude-run.sh source (see its header for why a second copy is a trap).
RB_WRAPPER_NAME="codex-run.sh"
# shellcheck source=schedule/_agentic-run.sh
. "$(dirname "${BASH_SOURCE[0]}")/_agentic-run.sh"

# ── secret: load OPENAI_API_KEY from config/.env for a headless cron run ──────
# docs/scheduling.md documents config/.env as the place to keep the key for a
# fully-headless run (Codex has no saved ChatGPT login under cron). Read ONLY
# that one key — the file is never sourced, so a booby-trapped .env cannot run
# code — and let an already-exported value win.
if [ -z "${OPENAI_API_KEY:-}" ] && [ -f "$ROOT/config/.env" ]; then
  _env_line="$(grep -E '^[[:space:]]*(export[[:space:]]+)?OPENAI_API_KEY=' "$ROOT/config/.env" | tail -n1 || true)"
  if [ -n "$_env_line" ]; then
    _val="${_env_line#*=}"
    case "$_val" in
      \"*\") _val="${_val#\"}"; _val="${_val%\"}" ;;  # strip surrounding "…"
      \'*\') _val="${_val#\'}"; _val="${_val%\'}" ;;  # strip surrounding '…'
    esac
    export OPENAI_API_KEY="$_val"
    unset _env_line _val
  fi
fi

# The task prompt comes from the shared preamble ($RB_RUN_PROMPT), so the two
# wrappers cannot drift into driving subtly different pipelines.

# Pass --profile only when CODEX_PROFILE is set (kept portable — no empty-array expansion).
CODEX_BIN="${CODEX_RUN_BIN:-codex}"
if [ -n "${CODEX_PROFILE:-}" ]; then
  exec "$CODEX_BIN" exec --profile "$CODEX_PROFILE" \
    --cd "$ROOT" --sandbox workspace-write -c approval_policy=never \
    -c sandbox_workspace_write.network_access=true "$RB_RUN_PROMPT"
else
  exec "$CODEX_BIN" exec \
    --cd "$ROOT" --sandbox workspace-write -c approval_policy=never \
    -c sandbox_workspace_write.network_access=true "$RB_RUN_PROMPT"
fi
