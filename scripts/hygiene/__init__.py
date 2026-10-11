"""hygiene — the brain-hygiene pass (CONVENTIONS §13), split by responsibility.

`scripts/validate_brain.py` is the public entry point (CLI + compatibility
facade); it re-exports everything defined here, so callers and tests keep
importing `scripts.validate_brain`. The package splits the scan by layer:

  - :mod:`scripts.hygiene.model`  — the result types (``Concept``,
    ``Warning``, ``BrainHealth``).
  - :mod:`scripts.hygiene.load`   — frontmatter parsing (PyYAML + stdlib
    fallback) and concept-note loading.
  - :mod:`scripts.hygiene.tags`   — the ``config/tags.yaml`` registry
    (loaders, the comment-preserving text-surgery primitives shared with
    promote_tags / manage_sources) and tag normalization (CONVENTIONS §11).
  - :mod:`scripts.hygiene.checks` — every hygiene check, the write-time
    ``gate_concepts`` contract gate, and the quarantine mover.
  - :mod:`scripts.hygiene.report` — the summary renderer, the JSON
    serializer, and the durable brain-health report writer.

Import from `scripts.validate_brain` (the stable surface), not from these
modules directly — the internal layout may keep moving.
"""
