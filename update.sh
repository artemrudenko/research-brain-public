#!/usr/bin/env bash
#
# update.sh — safely upgrade an existing research-brain install to a newer archive.
#
# The distribution model is a zip handoff (docs/adr/0004): there is no auto-update
# channel, you take a fresh archive to update. The risk that stops people from
# updating is "will this wipe my data?" — this script removes that risk. It overlays
# the new release's CODE onto your install while KEEPING everything that is yours:
#
#   Preserved (never overwritten): brain/ (your vault), pipeline/ (registry,
#   archives, synthesis, receipts), and ALL of config/ — your secrets, schedule/
#   timezone, channels, sources, topics, tags and glossary. An existing config file
#   is never touched; only config files a NEW release introduces are added.
#
#   Updated: scripts/, skills/, docs/, and the top-level docs.
#
# It refuses a silent DOWNGRADE, prints the exact version transition, and takes a
# full backup before touching anything — so an update is reversible.
#
# Two ways to run it:
#   A) From your install, pointing at the new release:
#        ./update.sh [opts] SOURCE
#   B) From the NEW archive, pointing at an old install (the ONLY way to make the
#      FIRST hop — a pre-0.2.0 install has no update.sh of its own):
#        /path/to/new/research-brain/update.sh --target /path/to/old/install
#
# Options:
#     SOURCE        the new release: a directory (unpacked archive) OR a .zip.
#                   Defaults to this script's own directory (mode B).
#     --target DIR  the install to update (default: this script's own directory).
#     --dry-run     rehearse: show what WOULD change, copy nothing, no backup.
#     --yes         don't prompt for confirmation before applying.
#     --force       allow a downgrade / same-version reinstall (default: refuse).
#     --backup-dir  where to write the pre-update backup (default: system temp).
#
# Re-runnable and safe. macOS + Linux (POSIX bash), no non-stdlib dependencies.
#
set -euo pipefail

# Where this script physically lives — the default for BOTH the install (mode A:
# the archive shipped this script into the install) and the source (mode B: this
# script ships inside the new archive).
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

DRY_RUN=0
ASSUME_YES=0
FORCE=0
BACKUP_DIR="${TMPDIR:-/tmp}"
SOURCE_ARG=""
TARGET_ARG=""
_PENDING=""
for arg in "$@"; do
  if [ "$_PENDING" = "backup" ]; then BACKUP_DIR="$arg"; _PENDING=""; continue; fi
  if [ "$_PENDING" = "target" ]; then TARGET_ARG="$arg"; _PENDING=""; continue; fi
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -y|--yes)  ASSUME_YES=1 ;;
    --force)   FORCE=1 ;;
    --backup-dir=*) BACKUP_DIR="${arg#*=}" ;;
    --backup-dir)   _PENDING="backup" ;;
    --target=*)     TARGET_ARG="${arg#*=}" ;;
    --target)       _PENDING="target" ;;
    -h|--help) sed -n '2,34p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) SOURCE_ARG="$arg" ;;
  esac
done
# A trailing --target/--backup-dir with no value must fail loudly, not silently
# fall back to mode A / the default backup dir.
case "$_PENDING" in
  backup) printf 'error: --backup-dir requires a value\n' >&2; exit 1 ;;
  target) printf 'error: --target requires a value\n' >&2; exit 1 ;;
esac

# The install to update: --target if given, else this script's own dir (mode A).
if [ -n "$TARGET_ARG" ]; then
  # -P resolves symlinks so the SOURCE==INSTALL self-guard below compares physical
  # paths (a symlinked or differently-cased target must not slip past it).
  INSTALL="$(cd "$TARGET_ARG" 2>/dev/null && pwd -P || true)"
  [ -n "$INSTALL" ] || { printf 'error: --target dir not found: %s\n' "$TARGET_ARG" >&2; exit 1; }
else
  INSTALL="$SELF_DIR"
fi

say()  { printf '\033[36m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$1" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 1; }

# SOURCE defaults to this script's own dir: in mode B the script IS the new archive.
# (In mode A you must pass the new release explicitly, or SOURCE would equal INSTALL.)
[ -n "$SOURCE_ARG" ] || SOURCE_ARG="$SELF_DIR"

# A python3 is present after install.sh (uv fetched it); version.py is stdlib-only,
# so we call it directly without the venv.
command -v python3 >/dev/null 2>&1 || die "python3 not found — needed to compare versions."

# ── resolve SOURCE to a directory holding the new release root ────────────────
CLEANUP_DIR=""
# Must return 0 even when there is nothing to clean, or its status would become
# the script's exit code on the EXIT trap.
cleanup() { if [ -n "$CLEANUP_DIR" ]; then rm -rf "$CLEANUP_DIR"; fi; }
trap cleanup EXIT

resolve_source_dir() {
  local src="$1"
  if [ -d "$src" ]; then
    printf '%s\n' "$(cd "$src" && pwd -P)"
    return
  fi
  if [ -f "$src" ] && printf '%s' "$src" | grep -qiE '\.zip$'; then
    command -v unzip >/dev/null 2>&1 || die "unzip not found — needed to open a .zip SOURCE."
    CLEANUP_DIR="$(mktemp -d)"
    unzip -q "$src" -d "$CLEANUP_DIR"
    # `make dist` wraps everything under a single research-brain/ prefix dir. Ignore
    # macOS zip cruft (__MACOSX/, .DS_Store) when counting the top level; if exactly
    # one real dir remains, descend into it — else use the temp root.
    local entries
    entries=$(find "$CLEANUP_DIR" -mindepth 1 -maxdepth 1 \
      ! -name '__MACOSX' ! -name '.DS_Store')
    if [ "$(printf '%s\n' "$entries" | wc -l | tr -d ' ')" = "1" ] && [ -d "$entries" ]; then
      printf '%s\n' "$(cd "$entries" && pwd -P)"
    else
      printf '%s\n' "$CLEANUP_DIR"
    fi
    return
  fi
  die "SOURCE is neither a directory nor a .zip: $src"
}

SOURCE="$(resolve_source_dir "$SOURCE_ARG")"
[ -f "$SOURCE/pyproject.toml" ] || die "SOURCE has no pyproject.toml — not a research-brain archive: $SOURCE"
[ -f "$INSTALL/pyproject.toml" ] || die "this install has no pyproject.toml — run update.sh from inside the install."

# SOURCE and INSTALL must be fully disjoint trees, not just unequal: overlaying a
# parent onto its child (or vice versa) copies a tree into itself and leaves a
# recursive junk copy. Physical paths (pwd -P) already resolved above.
case "$SOURCE" in
  "$INSTALL") die "SOURCE is the install itself — nothing to update from. In mode B, pass --target <old install>." ;;
  "$INSTALL"/*) die "SOURCE is INSIDE the install ($INSTALL) — move the new archive outside it first." ;;
esac
case "$INSTALL" in
  "$SOURCE"/*) die "the install is INSIDE the SOURCE ($SOURCE) — unpack the new archive outside your install." ;;
esac

# ── version preflight (refuse a silent downgrade) ─────────────────────────────
# SECURITY: the version is DATA — the single `[project] version` in pyproject.toml
# — so we read it with a TRUSTED inline reader, NEVER by executing the incoming
# archive's scripts/version.py. Running code shipped inside an unverified archive
# BEFORE the user confirms (below) would let a tampered ZIP execute on sight; a
# data-only read closes that. The logic mirrors scripts/version.py (which stays for
# `make dist` and is unit-tested); the two are exercised by tests/test_update.py.
_ver_read() {
  # Print the [project] version of the pyproject.toml under $1, or exit 1. Reads
  # the file as DATA (never imports it), scoping to [project] like version.py does.
  python3 - "$1" <<'PY'
import re, sys
from pathlib import Path
try:
    text = Path(sys.argv[1], "pyproject.toml").read_text(encoding="utf-8")
except OSError:
    sys.exit(1)
_, sep, rest = text.partition("[project]")
if not sep:
    sys.exit(1)
body = re.split(r"\n\[", rest, maxsplit=1)[0]
m = re.search(r'^\s*version\s*=\s*"([^"]+)"', body, re.MULTILINE)
if not m:
    sys.exit(1)
print(m.group(1).strip())
PY
}
_ver_relation() {
  # Print older|same|newer for incoming ($2) relative to installed ($1); exit 2 on
  # a non-numeric component (a clean error, never a traceback under `set -e`).
  python3 - "$1" "$2" <<'PY'
import sys
try:
    inst = [int(p) for p in sys.argv[1].split(".")]
    inc = [int(p) for p in sys.argv[2].split(".")]
except ValueError:
    sys.exit(2)
width = max(len(inst), len(inc))
inst += [0] * (width - len(inst))
inc += [0] * (width - len(inc))
print("newer" if inc > inst else "older" if inc < inst else "same")
PY
}
# The incoming version must always be readable (it drives the whole preflight).
INCOMING_VER="$(_ver_read "$SOURCE")" \
  || die "cannot read the incoming version — is $SOURCE a valid research-brain archive?"
# A corrupt/unreadable INSTALLED version normally halts, but --force treats it as
# "unknown → allow" so a broken install can still be repaired by an update.
if INSTALLED_VER="$(_ver_read "$INSTALL")" \
   && RELATION="$(_ver_relation "$INSTALLED_VER" "$INCOMING_VER")"; then
  :
elif [ "$FORCE" -eq 1 ]; then
  warn "installed version unreadable — proceeding because --force was given."
  INSTALLED_VER="unknown"; RELATION="newer"
else
  die "cannot read the installed version (corrupt pyproject?) — use --force to repair-update anyway."
fi

say "installed: $INSTALLED_VER"
say "incoming : $INCOMING_VER  ($RELATION)"

case "$RELATION" in
  newer) say "updating $INSTALLED_VER → $INCOMING_VER" ;;
  same)
    if [ "$FORCE" -ne 1 ]; then
      die "incoming is the SAME version ($INCOMING_VER) — nothing to do (use --force to reinstall)."
    fi
    warn "reinstalling the same version ($INCOMING_VER) because --force was given."
    ;;
  older)
    if [ "$FORCE" -ne 1 ]; then
      die "incoming ($INCOMING_VER) is a DOWNGRADE from installed ($INSTALLED_VER) — refused (use --force to override)."
    fi
    warn "DOWNGRADING $INSTALLED_VER → $INCOMING_VER because --force was given."
    ;;
esac

# ── the code/data boundary ────────────────────────────────────────────────────
# The overlay overwrites CODE but never your data. brain/ and pipeline/ are your
# vault and run history. ALL of config/ is treated as yours (config/README: "all
# user configuration lives here") — an existing config file is never overwritten;
# a new release's config files are ADDED, but your schedule/timezone, channels,
# sources, topics, tags, glossary and secrets stay exactly as you set them. This
# is an allowlist-preserve of config/, not a denylist of a few known files, so a
# config file we forget to list can never be silently clobbered.
# Paths are anchored with a leading `/` so they match ONLY at the tree root — an
# unanchored `brain/` would also skip a future `skills/x/brain/`, silently dropping
# code from the overlay.
DATA_EXCLUDES=(
  --exclude='/.git'
  --exclude='.venv'
  --exclude='__pycache__'
  --exclude='*.pyc'
  --exclude='.pytest_cache'
  --exclude='.mypy_cache'
  --exclude='.ruff_cache'
  --exclude='.DS_Store'
  # sources/*.example.md are shipped defaults (overlaid); the non-example versions are
  # USER-created opt-in registries (tier grading). The include MUST precede the exclude
  # (first-match wins in rsync) so examples still overlay while the user's own sources
  # files are treated as data — never overwritten, never flagged as orphans to delete.
  --include='/sources/*.example.md'
  --exclude='/sources/*.md'
  --exclude='/brain/'
  --exclude='/pipeline/'
  --exclude='/config/'
)

command -v rsync >/dev/null 2>&1 || die "rsync not found — needed to overlay the update."

# ── orphaned-files report (informational only — nothing is ever deleted) ──────
# The overlay never removes files, so a file dropped/renamed in the new release
# lingers in the install. Surface those leftovers by running the SAME rsync
# boundary in REVERSE (--dry-run, INSTALL → SOURCE, --ignore-existing): anything
# rsync would have to "create" in the new release exists only here — an orphan.
# Reusing DATA_EXCLUDES keeps user data (brain/, pipeline/, config/ incl. .env)
# out of the report by construction; only `>f` (file) lines are kept, and the
# sed strips through the first space so names with spaces survive.
list_orphans() {
  rsync -an --itemize-changes --ignore-existing "${DATA_EXCLUDES[@]}" \
    "$INSTALL/" "$SOURCE/" | LC_ALL=C sed -n 's/^>f[^ ]* //p'
}

# Prints the labeled orphan block; the "none" line only when asked (dry run).
report_orphans() {
  local show_empty="$1" orphans
  orphans="$(list_orphans)"
  if [ -n "$orphans" ]; then
    echo "orphaned (present here, not in the new release):"
    printf '%s\n' "$orphans" | LC_ALL=C sed 's/^/  /'
    echo "(leftovers from files removed or renamed upstream — review & delete manually if unwanted)"
  elif [ "$show_empty" = "yes" ]; then
    echo "no orphaned files."
  fi
}

echo
say "install : $INSTALL"
say "source  : $SOURCE"
say "preserved: your brain/ notes, pipeline/, and all existing config/ (only NEW config + brain/ scaffolding files are added)"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "=== DRY RUN — no files copied, no backup taken ==="
  echo "--- code overlay (config/ and data excluded) ---"
  rsync -ac --dry-run --itemize-changes "${DATA_EXCLUDES[@]}" "$SOURCE/" "$INSTALL/"
  echo "--- new config files only (existing config never overwritten) ---"
  rsync -a --dry-run --itemize-changes --ignore-existing "$SOURCE/config/" "$INSTALL/config/"
  echo "--- new brain/ scaffolding only (your notes never overwritten, concepts/ untouched) ---"
  if [ -d "$SOURCE/brain" ]; then
    rsync -a --dry-run --itemize-changes --ignore-existing --exclude='/concepts/' "$SOURCE/brain/" "$INSTALL/brain/"
  fi
  echo "--- orphan check (files here that the new release no longer ships) ---"
  report_orphans yes
  echo "(dry run complete — re-run without --dry-run to apply)"
  exit 0
fi

# Refuse a backup dir INSIDE the install — tar would try to read the archive it is
# still writing ("file changed as we read it") and it would land in the backup.
# (Checked here, after the dry-run exit, so a dry run never trips on it.)
case "$BACKUP_DIR" in
  "$INSTALL"|"$INSTALL"/*) die "--backup-dir must be OUTSIDE the install ($INSTALL)." ;;
esac
command -v tar >/dev/null 2>&1 || die "tar not found — needed for the pre-update backup."

if [ "$ASSUME_YES" -ne 1 ]; then
  printf 'Apply this update to %s? [y/N] ' "$INSTALL"
  read -r reply
  case "$reply" in y|Y|yes|YES) ;; *) die "aborted." ;; esac
fi

# ── full backup before mutating (an update is reversible) ─────────────────────
mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$BACKUP_DIR/research-brain-backup-${INSTALLED_VER}-${STAMP}.tgz"
say "backup → $BACKUP"
# The backup contains config/.env (secrets), so create it private (0600) — a shared
# /tmp with the default umask would otherwise leave it group/world-readable. If the
# backup fails (e.g. no space), abort BEFORE touching the install.
( umask 077; tar -czf "$BACKUP" -C "$(dirname "$INSTALL")" "$(basename "$INSTALL")" ) \
  || die "backup failed — aborting before any change. Free space or set --backup-dir."

# ── overlay code (rsync WITHOUT --delete — never removes your files) ──────────
# `-c` compares by checksum, not size+mtime, so a same-size fix (a one-character
# code change is common) is never skipped by rsync's quick-check heuristic.
say "applying update (rsync, no --delete)…"
rsync -ac "${DATA_EXCLUDES[@]}" "$SOURCE/" "$INSTALL/"
# Add only config files this release introduces; never overwrite existing config.
# The shipped EMPTY sources.yaml/topics.yaml twins are excluded: injecting them
# onto an unmigrated legacy install would make the config look migrated and
# bypass every migrate-config pointer (silently orphaning sources.md/topics.md).
# Migrated installs already have their own twins (--ignore-existing keeps them);
# the migrator/wizard/configurator create them everywhere else.
rsync -a --ignore-existing \
  --exclude='/sources.yaml' --exclude='/topics.yaml' \
  "$SOURCE/config/" "$INSTALL/config/"
# Add only brain/ scaffolding a release introduces (templates, .base views, front-door
# READMEs) — so a flagship vault feature isn't broken on updated installs. --ignore-existing
# never overwrites the user's notes; /concepts/ is excluded so example concepts are never
# injected into the user's curated concept space. Guarded: not every archive ships brain/.
if [ -d "$SOURCE/brain" ]; then
  rsync -a --ignore-existing --exclude='/concepts/' "$SOURCE/brain/" "$INSTALL/brain/"
fi

echo
# Short informational summary only — a real update never deletes these.
report_orphans no
say "done — updated to $INCOMING_VER, your data and config preserved."
say "backup kept at: $BACKUP"
say "if anything looks wrong, restore with: tar -xzf \"$BACKUP\" -C \"$(dirname "$INSTALL")\""
say "note: an old file removed in the new release is NOT deleted (safe overlay); the CHANGELOG flags any that matters."

# ── post-update config check (best-effort, never fails the update) ───────────
# Run the NEW release's validator against the preserved config so a schema
# change surfaces NOW, in plain language — not at the next failed cron run.
if [ -f "$INSTALL/scripts/validate_config.py" ]; then
  echo
  say "post-update config check…"
  # Prefer the install's virtualenv python: it has PyYAML, so the config SCHEMA
  # checks run at full fidelity instead of the reduced stdlib-fallback path. Fall
  # back to a bare python3 when there is no venv. (The inline version readers above
  # stay on bare python3 on purpose — they are stdlib-only and need no venv.)
  CFG_PY="python3"
  for _cand in "$INSTALL/.venv/bin/python3" "$INSTALL/.venv/bin/python"; do
    if [ -x "$_cand" ]; then CFG_PY="$_cand"; break; fi
  done
  if ( cd "$INSTALL" && "$CFG_PY" scripts/validate_config.py ); then
    say "config check: OK — your preserved config is compatible with $INCOMING_VER."
  else
    say "config check: findings above — the update itself succeeded; adjust config/ as indicated before the next run."
  fi
fi

# ── config-format migration offer (surfaced only — NEVER auto-applied) ───────
# Since schema 2 the sources/topics config lives in config/sources.yaml +
# config/topics.yaml. Since 0.8.0 the runtime READS ONLY the YAML config — an
# install still on the .md format must migrate once (the migrator leaves the
# .md files untouched, so the step is reversible by deleting the YAML twins).
if [ -f "$INSTALL/config/sources.md" ] && [ ! -f "$INSTALL/config/sources.yaml" ]; then
  echo
  say "ACTION NEEDED: config/sources.md + config/topics.md use the retired markdown format."
  say "since 0.8.0 the runtime reads ONLY the YAML config — collection and validation"
  say "will stop with this same pointer until you migrate (one command, .md kept):"
  say "  cd \"$INSTALL\" && python3 scripts/schema.py migrate-config"
fi
