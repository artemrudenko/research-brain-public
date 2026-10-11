# update.ps1 — assisted in-place update for Windows (PowerShell port of update.sh).
#
# Same contract as update.sh (ADR 0019): overlay the new release's code onto an
# existing install, PRESERVE all user data (brain/, pipeline/, every file in
# config/ including .env), take a full backup zip BEFORE any change, refuse a
# silent downgrade, and never delete anything (safe overlay — no mirror mode).
#
# Usage (run from PowerShell, inside the existing install):
#   .\update.ps1 path\to\research-brain-<new>.zip        # or an unpacked dir
#   .\update.ps1 -DryRun path\to\new                     # rehearse, change nothing
#   path\to\new\update.ps1 -Target path\to\old\install   # run from the new copy
#
# Flags mirror update.sh: -Target DIR, -DryRun, -Yes, -Force (allow downgrade /
# same-version reinstall), -BackupDir DIR.

[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $false)] [string]$Source = "",
    [string]$Target = "",
    [switch]$DryRun,
    [switch]$Yes,
    [switch]$Force,
    [string]$BackupDir = ""
)

$ErrorActionPreference = "Stop"

function Say([string]$msg) { Write-Host "update: $msg" }
function Fail([string]$msg) { Write-Error "update: $msg"; exit 1 }

# ── resolve the install (default: this script's own directory) ───────────────
$Install = if ($Target) { $Target } else { $PSScriptRoot }
$Install = (Resolve-Path $Install).Path
if (-not (Test-Path (Join-Path $Install "pyproject.toml"))) {
    Fail "target does not look like a research-brain install (no pyproject.toml): $Install"
}

# The incoming release defaults to THIS script's directory — so the documented
# "run from the new copy" hop (`path\to\new\update.ps1 -Target path\to\old`) works
# without also repeating the source path.
if (-not $Source) { $Source = $PSScriptRoot }

# ── resolve the incoming release (zip → temp extract; nested dir tolerated) ──
$Cleanup = $null
if ((Test-Path $Source -PathType Leaf) -and ($Source -like "*.zip")) {
    $Extract = Join-Path ([IO.Path]::GetTempPath()) ("rb-update-" + [Guid]::NewGuid().ToString("N"))
    Expand-Archive -LiteralPath $Source -DestinationPath $Extract
    $Cleanup = $Extract
    $Source = $Extract
    # A zip that wraps everything in one top-level folder: descend into it.
    if (-not (Test-Path (Join-Path $Source "pyproject.toml"))) {
        $children = @(Get-ChildItem -LiteralPath $Source -Directory)
        if ($children.Count -eq 1 -and (Test-Path (Join-Path $children[0].FullName "pyproject.toml"))) {
            $Source = $children[0].FullName
        }
    }
}
$Source = (Resolve-Path $Source).Path
if (-not (Test-Path (Join-Path $Source "pyproject.toml"))) {
    Fail "cannot read the incoming version — is $Source a valid research-brain archive?"
}
# Refuse a self-overlay (source == install): with Source now defaulting to this
# script's dir, running from inside the install with no argument would otherwise copy
# the tree onto itself. Mirrors update.sh's disjoint-tree guard.
if ($Source -eq $Install) {
    Fail "source and install are the same directory ($Install) — pass the new archive as the argument, or run this script FROM the new copy with -Target pointing at your install"
}

# ── python for version compare + post-update check ────────────────────────────
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) { $Python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $Python) { Fail "python not found on PATH — install Python 3.11+ first" }

$VerPy = Join-Path $Source "scripts\version.py"
if (-not (Test-Path $VerPy)) { $VerPy = Join-Path $Install "scripts\version.py" }
$InstalledVer = & $Python $VerPy current --root $Install
$IncomingVer = & $Python $VerPy current --root $Source
$Relation = & $Python $VerPy relation --installed $Install --incoming $Source
if ($LASTEXITCODE -ne 0) { Fail "version comparison failed — aborting before any change" }

Say "installed: $InstalledVer"
Say "incoming : $IncomingVer ($Relation)"
# Same semantics as update.sh: `relation` prints newer|same|older.
switch ($Relation) {
    "newer" { Say "updating $InstalledVer -> $IncomingVer" }
    "same" {
        if (-not $Force) { Fail "incoming is the SAME version ($IncomingVer) — nothing to do (use -Force to reinstall)" }
        Say "reinstalling the same version ($IncomingVer) because -Force was given."
    }
    "older" {
        if (-not $Force) { Fail "incoming ($IncomingVer) is OLDER than installed ($InstalledVer) — refusing a silent downgrade (use -Force to override)" }
        Say "downgrading to $IncomingVer because -Force was given."
    }
    default { Fail "unexpected version relation '$Relation' — aborting before any change" }
}

# ── what stays untouched: the same exclusion set as update.sh DATA_EXCLUDES ──
$ExcludeDirs = @(".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache",
                 ".ruff_cache", "brain", "pipeline", "config")
$ExcludeFiles = @("*.pyc", ".DS_Store")

function Invoke-Overlay([switch]$List) {
    # Safe overlay: /E copies subdirs, NO mirror mode — nothing is ever deleted.
    $flags = @("/E", "/NJH", "/NJS", "/NDL", "/NP")
    if ($List) { $flags += "/L" }
    robocopy $Source $Install @flags /XD @($ExcludeDirs | ForEach-Object { Join-Path $Source $_ }) /XF @ExcludeFiles | Out-Host
    if ($LASTEXITCODE -ge 8) { Fail "robocopy overlay failed (exit $LASTEXITCODE)" }
    # config/: ADD ONLY files this release introduces — never overwrite existing
    # user config (/XC /XN /XO skip every already-existing file, changed or not).
    # The shipped EMPTY sources.yaml/topics.yaml twins are excluded (/XF):
    # injecting them onto an unmigrated legacy install would make the config
    # look migrated and bypass every migrate-config pointer (silent orphan).
    $srcConfig = Join-Path $Source "config"
    if (Test-Path $srcConfig) {
        $cfgFlags = $flags + @("/XC", "/XN", "/XO")
        robocopy $srcConfig (Join-Path $Install "config") @cfgFlags /XF sources.yaml topics.yaml | Out-Host
        if ($LASTEXITCODE -ge 8) { Fail "robocopy config merge failed (exit $LASTEXITCODE)" }
    }
    # brain/: ADD ONLY scaffolding a release introduces (templates, .base views,
    # front-door READMEs) — mirrors update.sh. /XC /XN /XO never overwrite the
    # user's notes; concepts/ is excluded so example concepts are never injected
    # into the user's curated concept space. Guarded: not every archive ships brain/.
    $srcBrain = Join-Path $Source "brain"
    if (Test-Path $srcBrain) {
        $brainFlags = $flags + @("/XC", "/XN", "/XO")
        robocopy $srcBrain (Join-Path $Install "brain") @brainFlags /XD (Join-Path $srcBrain "concepts") | Out-Host
        if ($LASTEXITCODE -ge 8) { Fail "robocopy brain scaffolding merge failed (exit $LASTEXITCODE)" }
    }
}

# ── orphaned-files report (informational only — nothing is ever deleted) ──────
# The overlay never removes files, so a file dropped/renamed in the new release
# lingers in the install. Walk the install over the SAME data boundary as the
# overlay and report any file the incoming release no longer ships. User data
# (brain/, pipeline/, config/, and user-created sources/*.md — everything except
# the shipped sources/*.example.md) is excluded by construction: never listed,
# never deleted. Mirrors update.sh's list_orphans/report_orphans.
function Get-Orphans {
    $orphans = @()
    Get-ChildItem -LiteralPath $Install -Recurse -File -Force | ForEach-Object {
        $rel = $_.FullName.Substring($Install.Length).TrimStart('\', '/')
        $top = ($rel -split '[\\/]')[0]
        if ($ExcludeDirs -contains $top) { return }
        if ($_.Name -like "*.pyc" -or $_.Name -eq ".DS_Store") { return }
        if ($top -eq "sources" -and $_.Name -notlike "*.example.md") { return }
        if (-not (Test-Path -LiteralPath (Join-Path $Source $rel))) { $orphans += $rel }
    }
    return @($orphans)
}

function Show-Orphans([bool]$ShowEmpty) {
    $orphans = Get-Orphans
    if ($orphans.Count -gt 0) {
        Say "orphaned (present here, not in the new release):"
        $orphans | ForEach-Object { Write-Host "  $_" }
        Say "(leftovers from files removed or renamed upstream — review & delete manually if unwanted)"
    } elseif ($ShowEmpty) {
        Say "no orphaned files."
    }
}

if ($DryRun) {
    Say "dry-run — the files below WOULD be copied; nothing changes, no backup is taken."
    Invoke-Overlay -List
    Say "orphan check (files here that the new release no longer ships):"
    Show-Orphans $true
    if ($Cleanup) { Remove-Item -Recurse -Force $Cleanup }
    Say "dry-run complete."
    exit 0
}

if (-not $Yes) {
    $answer = Read-Host "update $InstalledVer -> $IncomingVer in $Install ? [y/N]"
    if ($answer -notmatch "^[Yy]") { Say "aborted — nothing changed."; exit 0 }
}

# ── full backup BEFORE any change (a failed backup aborts the update) ────────
if (-not $BackupDir) { $BackupDir = [IO.Path]::GetTempPath() }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Backup = Join-Path $BackupDir "research-brain-backup-$InstalledVer-$stamp.zip"
Say "backing up the whole install to $Backup …"
Compress-Archive -Path (Join-Path $Install "*") -DestinationPath $Backup
if (-not (Test-Path $Backup)) { Fail "backup failed — aborting before any change" }

Say "applying update (safe overlay, nothing deleted)…"
Invoke-Overlay

# Short informational summary only — a real update never deletes these.
Show-Orphans $false

Say "done — updated to $IncomingVer, your data and config preserved."
Say "backup kept at: $Backup"
Say "if anything looks wrong, restore by extracting that zip over the install."
Say "note: an old file removed in the new release is NOT deleted (safe overlay); the CHANGELOG flags any that matters."

# ── post-update config check (best-effort, never fails the update) ───────────
$ValidateCfg = Join-Path $Install "scripts\validate_config.py"
if (Test-Path $ValidateCfg) {
    Say "post-update config check…"
    Push-Location $Install
    & $Python scripts\validate_config.py
    $cfgExit = $LASTEXITCODE
    Pop-Location
    if ($cfgExit -eq 0) {
        Say "config check: OK — your preserved config is compatible with $IncomingVer."
    } else {
        Say "config check: findings above — the update itself succeeded; adjust config\ as indicated before the next run."
    }
}

# ── config-format migration offer (surfaced only — NEVER auto-applied) ───────
# Since schema 2 the sources/topics config lives in config/sources.yaml +
# config/topics.yaml; the legacy .md pipe tables keep working as a read-only
# fallback. The update itself never rewrites config.
$LegacySources = Join-Path $Install "config\sources.md"
$YamlSources   = Join-Path $Install "config\sources.yaml"
if ((Test-Path $LegacySources) -and -not (Test-Path $YamlSources)) {
    Say "note: config\sources.md + config\topics.md use the legacy markdown format."
    Say "this release prefers the YAML config (config\sources.yaml + config\topics.yaml)."
    Say "migrate once (your .md files are kept untouched as a fallback) with:"
    Say "  cd `"$Install`"; python3 scripts\schema.py migrate-config"
}

if ($Cleanup) { Remove-Item -Recurse -Force $Cleanup }
