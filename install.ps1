<#
install.ps1 — one-command dependency bootstrap for research-brain on native Windows (PowerShell).

The Windows counterpart of install.sh. Bootstraps what a fresh machine needs:
  1. installs uv (the package/venv manager) if it's missing,
  2. creates .venv and installs the runtime dependencies (uv sync --no-dev),
  3. seeds config/.env from the template.

Configuration is a separate, explicit step. Recommended: open the folder in
Cowork / Claude Code and say "let's set up sources" (the spoken setup wizard).
Advanced no-agent path: -Configure runs the terminal config interview here.

Safe to re-run: each step is idempotent.

  .\install.ps1                 # dependencies only (uv + .venv + deps + .env seed)
  .\install.ps1 -Configure      # ...then run the terminal config interview (advanced)
  .\install.ps1 -Yes            # don't prompt before installing uv

If PowerShell blocks the script, allow it for this run:
  powershell -ExecutionPolicy Bypass -File .\install.ps1
#>
[CmdletBinding()]
param(
    [switch]$Configure,
    [switch]$NoConfigure,  # legacy spelling of the default (deps only)
    [switch]$Yes
)

$ErrorActionPreference = "Stop"

# Run from the repo root (this script's directory) regardless of where it's invoked.
Set-Location -Path $PSScriptRoot

function Say($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# --- 1. uv ------------------------------------------------------------------ #
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Say "uv is not installed."
    if (-not $Yes) {
        $reply = Read-Host "Install uv now via the official installer (irm https://astral.sh/uv/install.ps1 | iex)? [y/N]"
        if ($reply -notmatch '^(y|yes)$') {
            Write-Error "Aborted. Install uv manually, then re-run: https://docs.astral.sh/uv/"
            exit 1
        }
    }
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    # The installer drops uv under %USERPROFILE%\.local\bin; make it visible for the
    # rest of THIS run without needing a new shell.
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Error "uv installed but not on PATH — open a new terminal and re-run .\install.ps1"
        exit 1
    }
}
Say "uv $((uv --version).Split(' ')[1]) ready"

# --- 2. environment + dependencies ------------------------------------------ #
Say "Creating .venv and installing runtime dependencies (uv sync --no-dev)..."
# End users only need the runtime (pyyaml). --no-dev skips the contributor
# toolchain (ruff/mypy/bandit/pytest); developers use `make setup` for the full set.
uv sync --no-dev
if ($LASTEXITCODE -ne 0) { Write-Error "uv sync failed"; exit 1 }

# --- 3. secrets template ---------------------------------------------------- #
if (-not (Test-Path "config\.env")) {
    Copy-Item "config\.env.example" "config\.env"
    Say "Created config\.env — fill in secrets only for the channels you enable."
} else {
    Say "config\.env already exists — leaving its contents untouched."
}
# (On Windows the file is already scoped to your user profile; there is no chmod.
#  Keep this folder out of any shared/synced location if it holds real secrets.)

# --- 4. interactive configuration (opt-in) ----------------------------------- #
if ($Configure) {
    Say "Launching the interactive configurator..."
    # The configurator's exit can mean a hard failure (answers restored) or just
    # "not headless-collectable yet" (answers KEPT) — its own message says which.
    uv run python scripts/configure.py
    if ($LASTEXITCODE -ne 0) {
        Write-Error "the configurator did not finish cleanly — its message above says whether your answers were kept. Re-run: .\install.ps1 -Configure (or: uv run python scripts/configure.py)"
        exit 1
    }
}

# --- 5. verify ---------------------------------------------------------------- #
# Read-only post-install check (config schema, sources, delivery wiring, health).
# A fresh install legitimately shows warnings (no digest yet, secrets unset), so
# this is informational — it never fails the install.
Say "Verifying the install (read-only check)..."
uv run python scripts/doctor.py
if ($LASTEXITCODE -ne 0) { Say "doctor reported findings above — informational on a fresh install." }

if ($Configure) {
    Say "Done. Re-check anytime with 'uv run python scripts/doctor.py'."
} else {
    Say "Dependencies installed. Nothing is configured yet — pick what to monitor next:"
    Say "  Recommended: open this folder in Cowork / Claude Code and say `"let's set up sources`"."
    Say "  Advanced (no agent): .\install.ps1 -Configure runs the terminal config interview."
}
