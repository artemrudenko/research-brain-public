#!/usr/bin/env python3
"""
state.py — one resolver for research-brain's durable runtime state.

Why: the idempotency memory of the pipeline — delivery receipts + the
`.delivery.lock` (deliver.py), the health event log (health.py), and the
per-topic synthesis-freshness sidecars (synthesis_freshness.py) — normally lives
in *gitignored, in-repo* runtime dirs under `pipeline/`. On a clone, redeploy, or
state-wipe that memory is gone, so (worst case) a channel re-sends a digest it
already delivered. This module lets a deployment relocate that state onto a
*persistent volume* so it survives redeploys — WITHOUT changing the default.

Contract (the whole point — one decision in one place):
  - `RESEARCH_BRAIN_STATE_DIR` UNSET (default): every runtime-state path resolves
    EXACTLY where it does in-repo today. Pure identity — zero behavior change.
  - `RESEARCH_BRAIN_STATE_DIR` SET: a runtime-state path relocates under it,
    preserving its substructure *relative to the project root*. So an in-repo
    `…/pipeline/3-synthesis/.delivered` becomes `{STATE_DIR}/pipeline/3-synthesis/
    .delivered` — the relative layout is identical, just re-rooted onto a volume.

All three callers route their state path through `state_root(...)`, so the
on/off switch and the relocation rule live here and nowhere else.

stdlib only; no side effects (it computes a path, it does not create it).
"""

from __future__ import annotations

import os
from pathlib import Path

# The env var that opts a deployment into durable, out-of-repo runtime state.
STATE_DIR_ENV = "RESEARCH_BRAIN_STATE_DIR"

# The package's repo root (scripts/ -> repo). Used as the default `project_root`
# so callers that pass an in-repo default need not also pass the root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def configured_state_dir() -> Path | None:
    """The relocation root from the env, or None when the feature is off.

    Returns None when `RESEARCH_BRAIN_STATE_DIR` is unset OR blank/whitespace-only
    — a blank value must NOT be read as "relocate to the current dir" (that would
    silently move state). A `~` prefix is expanded so a deployment can point at
    `~/state`. No filesystem access: this only parses the configured value.
    """
    raw = os.environ.get(STATE_DIR_ENV)
    if raw is None or not raw.strip():
        return None
    return Path(raw.strip()).expanduser()


def state_root(in_repo_default: Path, *, project_root: Path | None = None) -> Path:
    """Resolve one runtime-state path, honoring `RESEARCH_BRAIN_STATE_DIR`.

    `in_repo_default` is exactly where the path lives in-repo today (e.g.
    `…/pipeline/3-synthesis/.delivered`). With the env unset this is returned
    unchanged — the default path, byte-for-byte. With the env set, the path's
    location *relative to `project_root`* is re-rooted under the state dir, so the
    in-repo substructure is preserved on the persistent volume.

    `project_root` defaults to this package's repo root; a caller computing the
    default from a different root (or a test using a tmp root) passes its own.

    A path that is not under `project_root` (a defensive edge — every real caller
    passes an in-repo default) relocates by its final component, so the resolver
    never raises mid-pipeline.
    """
    target = configured_state_dir()
    if target is None:
        return in_repo_default  # feature off — exact in-repo default, no change
    root = project_root or PROJECT_ROOT
    try:
        relative = in_repo_default.relative_to(root)
    except ValueError:
        # Not under the project root — preserve at least the leaf name so a
        # surprising input still lands somewhere deterministic under the volume.
        relative = Path(in_repo_default.name)
    return target / relative
