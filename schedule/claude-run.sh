#!/usr/bin/env bash
# schedule/claude-run.sh — drive the gated weekly pipeline through Claude Code.
#
# This is the "D. Claude Code (local cron)" path in docs/scheduling.md: an OS-cron
# entry calls this wrapper, which runs `claude -p` non-interactively against
# schedule/weekly-run.md. It is the sibling of codex-run.sh — same task, same
# gating, a different agent CLI.
#
# WHY IT EXISTS, given Claude Code already has `/schedule`. A `/schedule` routine
# is a CLOUD agent: it runs off-box (docs/scheduling.md notes such routines
# "cannot be probed" by setup_check.py for exactly that reason), so it cannot
# reach a local, git-less install — its config/.env, its brain/, its delivery
# receipts. When the install you want run lives on THIS machine, the trigger has
# to live here too. Use `/schedule` when the install is reachable from the cloud
# agent; use this wrapper when it is a local folder.
#
# Advantage over the Codex path: MCP delivery works. If the session carries the
# Gmail / Telegram MCP servers, digest-deliver can send through them; Codex has
# no such servers by default and needs the headless transports.
#
# PERMISSIONS — least privilege by construction, not by trust:
#   --tools       is the HARD bound: the tools that EXIST for this run. It is
#                 the union of the pipeline-role allowlists in config/agents.yaml
#                 (ADR 0015) — the run can do no more than the roles are
#                 specified to need. Verified against the real CLI: with the
#                 tool withheld, the agent reports it has no such tool and the
#                 action does not happen.
#   --allowedTools pre-approves those same tools so nothing waits for a human.
#                 (Tighten per install if you like — e.g. Bash(python3 *) — but
#                 note an over-narrow rule makes a step FAIL rather than prompt.)
#   --permission-mode dontAsk answers permission questions without a TTY. It is
#                 deliberately NOT --dangerously-skip-permissions: a cron run
#                 must stay inside the allowlist, not escape the system.
#   The cwd is the trust boundary: paths outside the project root are refused
#   even for allowed tools, which is why the wrapper cd's to ROOT (the claude
#   CLI has no --cd flag).
#
# Hooks and settings from the operator's own Claude config still apply to a
# headless run — a PreToolUse hook that blocks a tool blocks it here too.
#
# One-time prerequisites:
#   - Claude Code CLI installed and authenticated for non-interactive use
#     (`claude -p 'say OK'` must answer without prompting).
#   - Delivery: MCP servers registered for the MCP transports, or
#     config/channels.yaml set to the headless ones (provider: smtp /
#     transport: bot-api). weekly-run.md serializes runs via scripts/run_lock.py,
#     so this is safe to schedule alongside a cron collect or a Codex run.
#
# WHO PAYS. A stray ANTHROPIC_API_KEY in the environment silently outranks a
# claude.ai login, so an unattended weekly run can bill API credits for hours
# while a paid subscription sits unused. The CLI does mention it — "connectors
# are disabled because ANTHROPIC_API_KEY … takes precedence over your claude.ai
# login" — but that reads as a connectors notice, not a billing one. So the
# wrapper decides on purpose: subscription first, API key only when asked
# (CLAUDE_RUN_AUTH=api). The probe is a local `claude auth status` read — no API
# call, nothing billed — run with the key already unset, because that is the
# only state that answers "would a run WITHOUT the key be logged in?" (with the
# key set the CLI reports authMethod claude.ai and a null subscriptionType,
# which is too ambiguous to bill against). Its JSON shape is observed, not a
# documented API, so an unrecognised or failing probe keeps the key and says so
# rather than guessing.
#
# Knobs (all optional, set in the crontab line):
#   CLAUDE_RUN_MODEL    --model value (e.g. sonnet) — omitted when unset/empty
#   CLAUDE_RUN_EFFORT   --effort value (low|medium|high|xhigh|max)
#   CLAUDE_RUN_MAX_USD  spend ceiling for one run (default below)
#   CLAUDE_RUN_AUTH     who pays: auto (default — subscription when a claude.ai
#                       login exists) | api (force ANTHROPIC_API_KEY) |
#                       subscription (force, without consulting the probe)
#
# Cron example (keep CRON_TZ equal to config/schedule.yaml `timezone`):
#   CRON_TZ=UTC
#   0 9 * * 1  /path/to/research-brain/schedule/claude-run.sh >> /tmp/rb-weekly.log 2>&1
#
# Exit status is claude's own, so a failed run is reported by cron.
set -euo pipefail

RB_WRAPPER_NAME="claude-run.sh"
# shellcheck source=schedule/_agentic-run.sh
. "$(dirname "${BASH_SOURCE[0]}")/_agentic-run.sh"

# ── capability surface: the union of the config/agents.yaml role allowlists ───
# Kept in step with that spec by tests/test_claude_run.py, which derives the
# expected set from the YAML rather than trusting this line.
TOOLS="Read,Write,Edit,Glob,Grep,Bash,WebFetch,WebSearch,Skill,Agent"

# ── spend ceiling: an unattended agentic loop bills real money ────────────────
MAX_USD="${CLAUDE_RUN_MAX_USD:-25}"

# ── who pays: the subscription by default, the API key only on request ────────
# `:-` covers both unset and empty, so a blank crontab variable means
# "not configured" rather than an invalid choice.
AUTH_CHOICE="${CLAUDE_RUN_AUTH:-auto}"
case "$AUTH_CHOICE" in
  auto | api | subscription) ;;
  *)
    echo "$RB_WRAPPER_NAME: CLAUDE_RUN_AUTH='$AUTH_CHOICE' is not one of auto|subscription|api." >&2
    exit 2
    ;;
esac

# `api` needs no action — it is the environment as it already stands.
if [ "$AUTH_CHOICE" = "subscription" ] && [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "$RB_WRAPPER_NAME: CLAUDE_RUN_AUTH=subscription — ignoring ANTHROPIC_API_KEY; this run bills the claude.ai subscription." >&2
  unset ANTHROPIC_API_KEY
elif [ "$AUTH_CHOICE" = "auto" ] && [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  # The probe runs in a subshell with the key already unset, so the answer
  # describes the run we are about to start rather than the current env.
  if AUTH_PROBE="$(unset ANTHROPIC_API_KEY; claude auth status 2>/dev/null)" &&
    printf '%s' "$AUTH_PROBE" | grep -q '"loggedIn"[[:space:]]*:[[:space:]]*true' &&
    printf '%s' "$AUTH_PROBE" | grep -q '"authMethod"[[:space:]]*:[[:space:]]*"claude\.ai"'; then
    unset ANTHROPIC_API_KEY
    echo "$RB_WRAPPER_NAME: billing this run to the claude.ai subscription (CLAUDE_RUN_AUTH=api to use ANTHROPIC_API_KEY instead)." >&2
  else
    echo "$RB_WRAPPER_NAME: the claude auth probe found no usable claude.ai login — keeping ANTHROPIC_API_KEY, so this run bills API credits." >&2
  fi
fi

# The claude CLI has no --cd: the cwd IS the workspace root it will trust.
cd "$ROOT"

ARGS=(-p --tools "$TOOLS" --allowedTools "$TOOLS" --permission-mode dontAsk
      --max-budget-usd "$MAX_USD")

# Optional flags only when set AND non-empty (an empty crontab variable must
# behave like unset — `--model ""` would be a parse error, not a default).
if [ -n "${CLAUDE_RUN_MODEL:-}" ]; then
  ARGS+=(--model "$CLAUDE_RUN_MODEL")
fi
if [ -n "${CLAUDE_RUN_EFFORT:-}" ]; then
  ARGS+=(--effort "$CLAUDE_RUN_EFFORT")
fi

# The prompt is the final argument — one argv entry naming the task FILE, so a
# de-quoting regression is visible (it would shatter into many words).
exec claude "${ARGS[@]}" "$RB_RUN_PROMPT"
