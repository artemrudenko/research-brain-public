#!/usr/bin/env python3
"""One lazy-PyYAML import seam for runtime scripts.

PyYAML is a hard runtime dependency (`pyproject.toml [project] dependencies`),
but the import stays lazy on purpose: a fresh box before `uv sync`, or a cron
line pointed at the system interpreter, still imports these modules and must
degrade per-site — line-parse fallbacks, advisory skips, or a clean CLI error —
instead of crashing at import time. Sixteen call sites used to hand-roll the
same ``try: import yaml`` block with three divergent failure idioms; this seam
keeps ONE import behavior while every caller keeps its own, deliberate handling
of the missing-YAML case.

Deliberate non-adopters (each has a structural reason to keep its own import):
``delivery/config.py`` and ``fm.py`` (dual import context — delivery's
direct-script fallback chain loads them BARE, with no ``scripts`` package
importable; pinned by ``test_delivery_health_hook_works_as_direct_script``),
``inbox_flow/queue.py`` (required-dependency semantics: ImportError must
propagate to the injectable default), ``doctor.py`` /
``validate-pipeline-frontmatter.py`` / ``search/search.py`` (standalone CLIs
whose yaml import must survive even when the ``scripts`` package bootstrap
itself is what's being diagnosed).
"""

from __future__ import annotations

import json
import re
from types import ModuleType


def optional_yaml() -> ModuleType | None:
    """Return the ``yaml`` module, or ``None`` when PyYAML is absent.

    Callers own the degradation: fall back, skip, or raise their domain error.
    """
    try:
        import yaml  # noqa: PLC0415 — the lazy import IS this helper's job
    except ImportError:
        return None
    return yaml


# A scalar safe to emit bare: a slug-ish token that no YAML parser can misread.
_BARE_SCALAR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_.-]*$")


def yaml_scalar(value: str) -> str:
    """Render a string scalar for YAML: bare when slug-safe, JSON-quoted otherwise.

    JSON string escaping is valid YAML double-quoted style, so arbitrary values
    (colons, quotes, `#`, unicode) round-trip through any YAML parser. Shared by
    every deterministic emitter (sources, topics, authors) so the config files
    quote alike — a value safe in one and mangled in another is a bug the user
    experiences as one file mysteriously corrupting.
    """
    if _BARE_SCALAR_RE.fullmatch(value):
        return value
    return json.dumps(value, ensure_ascii=False)
