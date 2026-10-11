"""Read-only cross-reference between author NODES and the followed ROSTER.

Author nodes (`brain/authors/*.md`, `type: author`) answer "here is what we know
of this person"; the roster (`config/authors.yaml`) answers "I want more of their
work". Stage 9, Q4 keeps them strictly separate — one is never auto-created from
the other. This module only *reads* both and reports, per node, whether it is
already followed, by intersecting the node's stored `identity_key` with the
roster's keys through the ONE shared identity ladder (`roster_identity_keys`).

No write ever crosses the boundary here — that separation is the whole point.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.authors.store import roster_identity_keys  # noqa: E402
from scripts.hygiene.load import load_authors as load_author_nodes  # noqa: E402


def followed_node_status(root: Path) -> dict[str, bool]:
    """Map each author node's stem → whether it is in the followed roster.

    An empty `identity_key` never matches (we do not guess who a node is); a
    missing/malformed roster marks everyone not-followed. Purely read-only.
    """
    followed = roster_identity_keys(root)
    return {
        node.stem: bool(node.identity_key) and node.identity_key in followed
        for node in load_author_nodes(root / "brain" / "authors")
    }
