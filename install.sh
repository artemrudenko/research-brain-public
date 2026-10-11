#!/usr/bin/env bash
# install.sh — one-command dependency bootstrap for research-brain.
#
# Bootstraps what a fresh machine needs, in order:
#   1. installs uv (the package/venv manager) if it's missing,
#   2. creates .venv and installs the runtime dependencies (uv sync --no-dev),
#   3. seeds config/.env from the template.
#
# Configuration is a separate, explicit step. Recommended: open the folder in
# Cowork / Claude Code and say "let's set up sources" (the spoken setup wizard).
# Advanced no-agent path: --configure runs the terminal config interview here.
#
# Safe to re-run: each step is idempotent. Works on macOS and Linux (POSIX bash).
#
#   ./install.sh                # dependencies only (uv + .venv + deps + .env seed)
#   ./install.sh --configure    # …then run the terminal config interview (advanced)
#   ./install.sh --yes          # don't prompt before installing uv

set -euo pipefail

# Resolve the repo root (this script's directory) so the steps below run from the
# project root no matter where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ASSUME_YES=0
RUN_CONFIGURE=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes)        ASSUME_YES=1 ;;
    --configure)     RUN_CONFIGURE=1 ;;
    --no-configure)  RUN_CONFIGURE=0 ;;  # legacy spelling of the default
    -h|--help)
      # Print only the leading comment block (skip the shebang, stop at the first
      # non-comment line) — not the section dividers further down the file.
      awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
      exit 0 ;;
    *) printf 'unknown argument: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

say() { printf '\033[36m==>\033[0m %s\n' "$1"; }

# --- 1. uv ------------------------------------------------------------------ #
if ! command -v uv >/dev/null 2>&1; then
  say "uv is not installed."
  if [ "$ASSUME_YES" -ne 1 ]; then
    printf 'Install uv now via the official installer '
    printf '(curl -LsSf https://astral.sh/uv/install.sh | sh)? [y/N] '
    read -r reply
    case "$reply" in
      y|Y|yes|YES) ;;
      *) printf 'Aborted. Install uv manually, then re-run: https://docs.astral.sh/uv/\n'; exit 1 ;;
    esac
  fi
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # The installer drops uv in ~/.local/bin (or ~/.cargo/bin); make it visible for
  # the rest of THIS run without needing a new shell.
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || {
    printf 'uv installed but not on PATH — open a new terminal and re-run ./install.sh\n' >&2
    exit 1
  }
fi
say "uv $(uv --version | awk '{print $2}') ready"

# --- 2. environment + dependencies ------------------------------------------ #
say "Creating .venv and installing runtime dependencies (uv sync --no-dev)…"
# End users only need the runtime (pyyaml). --no-dev skips the contributor
# toolchain (ruff/mypy/bandit/pytest); developers use `make setup` for the full set.
uv sync --no-dev

# --- 3. secrets template ---------------------------------------------------- #
if [ ! -f config/.env ]; then
  cp config/.env.example config/.env
  say "Created config/.env — fill in secrets only for the channels you enable."
else
  say "config/.env already exists — leaving its contents untouched."
fi
# Secrets must not be world/group readable, whether we just created it or not.
chmod 600 config/.env

# --- 4. interactive configuration (opt-in) ----------------------------------- #
if [ "$RUN_CONFIGURE" -eq 1 ]; then
  say "Launching the interactive configurator…"
  # Propagate a non-clean configuration exit: don't print "Done" and exit 0 when
  # the configurator flagged something (automation must see the non-zero status).
  # Its exit can mean a hard failure (answers restored) or just "not headless-
  # collectable yet" (answers KEPT) — the configurator's own message says which,
  # so this envelope defers to it instead of overclaiming a failure.
  if ! uv run python scripts/configure.py; then
    printf 'the configurator did not finish cleanly — its message above says whether your answers were kept. Re-run: ./install.sh --configure (or make configure)\n' >&2
    exit 1
  fi
fi

# --- 5. verify ---------------------------------------------------------------- #
# Read-only post-install check (config schema, sources, delivery wiring, health).
# A fresh install legitimately shows warnings (no digest yet, secrets unset), so
# this is informational — it never fails the install.
say "Verifying the install (read-only check)…"
uv run python scripts/doctor.py || true

if [ "$RUN_CONFIGURE" -eq 1 ]; then
  say "Done. Re-check anytime with 'uv run python scripts/doctor.py'."
else
  say "Dependencies installed. Nothing is configured yet — pick what to monitor next:"
  say "  Recommended: open this folder in Cowork / Claude Code and say \"let's set up sources\"."
  say "  Advanced (no agent): ./install.sh --configure runs the terminal config interview (or: make configure)."
fi
