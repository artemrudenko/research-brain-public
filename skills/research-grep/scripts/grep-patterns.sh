#!/usr/bin/env bash
# research-grep — reusable search patterns
# Idempotent + platform-agnostic (macOS / Linux / WSL).
# Invoked from SKILL.md Phase 2 or optional Phase 0 Step 2 (search-recipes).
#
# Usage:
#   bash scripts/grep-patterns.sh <pattern> [<zone>]
#
# Zone defaults to "all" (search target zones excluding archive/).
# Project root: set the ROOT env var, or it defaults to the current directory.

set -euo pipefail

PATTERN="${1:?Usage: grep-patterns.sh <pattern> [<zone>]}"
ZONE="${2:-all}"

# Project root — passed via the ROOT env var, defaults to the current directory.
ROOT="${ROOT:-.}"

# Search target zones per SKILL.md Phase 2 (excluding archive/, planning/, config/)
ZONES_DEFAULT=(
  "$ROOT/brain/"
  "$ROOT/pipeline/2-curated/"
  "$ROOT/pipeline/3-synthesis/"
)

# Deep zones (added at DEPTH=deep)
ZONES_DEEP=(
  "$ROOT/pipeline/1-incoming/"
  "$ROOT/pipeline/0-archive/"
)

# Search execution
case "$ZONE" in
  all)
    rg --type md -i "$PATTERN" "${ZONES_DEFAULT[@]}" 2>/dev/null || true
    ;;
  deep)
    rg --type md -i "$PATTERN" "${ZONES_DEFAULT[@]}" "${ZONES_DEEP[@]}" 2>/dev/null || true
    ;;
  brain)
    rg --type md -i "$PATTERN" "$ROOT/brain/" 2>/dev/null || true
    ;;
  *)
    echo "Unknown zone: $ZONE. Valid: all | deep | brain" >&2
    exit 1
    ;;
esac
