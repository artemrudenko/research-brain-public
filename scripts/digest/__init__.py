"""digest — the deterministic digest builder, split by responsibility.

`scripts/build_digest.py` is the public entry point (CLI + compatibility
facade); it re-exports everything defined here, so callers and tests keep
importing `scripts.build_digest`. The package splits the builder by layer:

  - :mod:`scripts.digest.model`  — the data types (``DigestData`` & friends),
    shared text primitives, exceptions, and output-contract constants.
  - :mod:`scripts.digest.scan`   — everything that READS the vault: frontmatter
    and date parsing, the config lookback readers, the incoming / concept /
    attention scanners, synthesis-log and brain-health lookups, the sanitize
    gate, and :func:`~scripts.digest.scan.gather`.
  - :mod:`scripts.digest.render` — everything that WRITES markdown: the digest
    renderer and its per-topic credibility curation.

Import from `scripts.build_digest` (the stable surface), not from these
modules directly — the internal layout may keep moving.
"""
