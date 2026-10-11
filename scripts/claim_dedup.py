#!/usr/bin/env python3
"""
claim_dedup.py — deterministic, claim-level near-duplicate collapse.

Where ``scripts/normalize_url.py`` dedups on the *URL* and ``scripts/dedup.py``
dedups whole article *bodies*, this module works one level finer: the unit is a
single **claim** (a short assertion sentence), and it collapses claims that say
the same thing in slightly different words — the case where the same fact is
sourced from several places and would otherwise appear more than once.

Method (no LLM, no network, stdlib only — ADR 0002):
  1. Normalise each claim — lowercase, strip punctuation, collapse whitespace,
     drop a small English stopword set so only content words remain.
  2. Build a **word-shingle** set per claim: unigrams ∪ bigrams over the content
     tokens. Bigrams add local word order, so a reorder that keeps the same
     unigrams still loses shared bigrams and scores lower.
  3. Compare two claims by **Jaccard similarity** of their shingle sets. A pair
     at or above ``threshold`` (default 0.8, inclusive) is a near-duplicate.

Collapse rule: keep the **first** occurrence in input order and drop every later
claim that is a near-duplicate of an already-kept claim; survivors are returned
in original order. Fully deterministic — no randomness and no reliance on set
iteration order in the output.

Wiring (ADR 0018): the research-build synthesis path calls the ``main`` CLI over
the **accumulated cross-source ``key_claims``** (Phase 2b assembly) to collapse a
fact sourced from several feeds down to one claim before Phase 3 synthesis — the
level below the deterministic URL dedup (``normalize_url.py`` / ``dedup.py``). The
heavier *subagent* variant over the extract set stays deferred (advanced only).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from typing import TypeVar

# Default Jaccard threshold; a pair with similarity >= this is a near-duplicate.
# Higher than dedup.py's 0.7 body threshold because a single claim is short, so
# a looser bar would fold merely-related claims together.
DEFAULT_THRESHOLD = 0.8

# Small English stopword set — dropping these keeps the shingles focused on
# content words so "the model improves X" and "a model improves X" match. Kept
# deliberately small (KISS); extend only when a real recurring miss appears.
_STOPWORDS = frozenset(
    """
    a an the this that these those
    is are was were be been being am
    do does did doing done
    have has had having
    of in on at by to from with for as into onto over under
    and or but nor so yet
    it its they them their he she his her we us our you your i me my
    not no
    will would shall should can could may might must
    here there then than too very just also about up down out off
    """.split()
)

# A token = run of letters/digits; punctuation and apostrophes are folded out
# beforehand, so this also collapses "art's" → "arts"-style noise to bare words.
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Generic item type for the object-dedup convenience below.
_Item = TypeVar("_Item")


def _content_tokens(claim: str) -> list[str]:
    """Normalise ``claim`` to its ordered list of content tokens.

    Lowercase, drop apostrophes, split on non-alphanumerics, then remove
    stopwords. Order is preserved because bigram shingles depend on it.
    """
    lowered = claim.lower().replace("'", "")
    return [tok for tok in _TOKEN_RE.findall(lowered) if tok not in _STOPWORDS]


def _shingles(claim: str) -> set[str]:
    """Word-shingle set for ``claim``: unigrams ∪ bigrams of content tokens.

    Bigrams are prefixed so they can never collide with a unigram token
    (e.g. the bigram "new model" is stored as "new model", never mistaken for
    a single token).
    """
    tokens = _content_tokens(claim)
    shingles: set[str] = set(tokens)  # unigrams
    for first, second in zip(tokens, tokens[1:], strict=False):
        shingles.add(f"{first} {second}")  # bigrams keep local word order
    return shingles


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard index |a∩b| / |a∪b|; 0.0 when both sets are empty."""
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a) + len(b) - intersection
    return intersection / union if union else 0.0


def similarity(a_claim: str, b_claim: str) -> float:
    """Claim similarity in [0, 1]: Jaccard over unigram+bigram word shingles."""
    return _jaccard(_shingles(a_claim), _shingles(b_claim))


def dedup_claims(claims: list[str], *, threshold: float = DEFAULT_THRESHOLD) -> list[str]:
    """Collapse near-duplicate claims, keeping the first of each near-dup group.

    A later claim is dropped when its :func:`similarity` to any already-kept
    claim is at or above ``threshold`` (inclusive boundary, matching the ``>=``
    convention in ``scripts/dedup.py``). Survivors are returned in original
    input order. Deterministic and side-effect free.
    """
    kept: list[str] = []
    kept_shingles: list[set[str]] = []  # precomputed once per surviving claim
    for claim in claims:
        shingles = _shingles(claim)
        # Keep the claim unless it near-duplicates one we already kept.
        if any(
            _jaccard(shingles, prior) >= threshold for prior in kept_shingles
        ):
            continue
        kept.append(claim)
        kept_shingles.append(shingles)
    return kept


def dedup_items(
    items: Sequence[_Item],
    key: Callable[[_Item], str],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[_Item]:
    """Dedup arbitrary objects by the claim string that ``key`` extracts.

    Thin convenience over :func:`dedup_claims`: two items collapse when their
    extracted claims are near-duplicates. The first item of each near-dup group
    is kept and original order is preserved.
    """
    kept: list[_Item] = []
    kept_shingles: list[set[str]] = []
    for item in items:
        shingles = _shingles(key(item))
        if any(
            _jaccard(shingles, prior) >= threshold for prior in kept_shingles
        ):
            continue
        kept.append(item)
        kept_shingles.append(shingles)
    return kept


# --------------------------------------------------------------------------- #
# CLI — the deterministic entry point the synthesis path invokes over the
# accumulated cross-source key_claims (see the module docstring / ADR 0018).
# --------------------------------------------------------------------------- #

# The reader-contract key_claims field the object form dedups on by default.
_DEFAULT_CLAIM_KEY = "claim"


def _dedup_json(
    data: list[object], *, key_field: str, threshold: float
) -> tuple[list[object], int]:
    """Dedup a parsed JSON array of either claim strings or claim objects.

    Strings are deduped directly; objects (the reader-contract
    ``[{claim, attribution}]`` shape) dedup on ``key_field`` and keep the first
    object of each near-dup group intact. Returns ``(survivors, dropped_count)``.
    """
    if all(isinstance(item, str) for item in data):
        strings = [item for item in data if isinstance(item, str)]
        survivors: list[object] = list(dedup_claims(strings, threshold=threshold))
        return survivors, len(data) - len(survivors)
    if all(isinstance(item, dict) for item in data):
        objects = [item for item in data if isinstance(item, dict)]
        # The extracted key must be a string to shingle; missing/non-str -> "".
        def _claim_of(obj: dict[str, object]) -> str:
            value = obj.get(key_field, "")
            return value if isinstance(value, str) else ""

        kept = dedup_items(objects, _claim_of, threshold=threshold)
        return list(kept), len(data) - len(kept)
    raise ValueError(
        "input must be a JSON array of all strings or all objects, not a mix"
    )


def main(argv: list[str] | None = None) -> int:
    """Dedup near-duplicate claims read as a JSON array from a file or stdin.

    Reads a JSON array of claim strings — or claim objects (deduped on
    ``--key``, default ``claim``) — collapses cross-source near-duplicates, and
    writes the surviving array to stdout as JSON (a one-line count to stderr).
    """
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument(
        "path",
        nargs="?",
        help="JSON file of claims; omit to read the JSON array from stdin.",
    )
    ap.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Jaccard near-duplicate cutoff (default {DEFAULT_THRESHOLD}).",
    )
    ap.add_argument(
        "--key",
        default=_DEFAULT_CLAIM_KEY,
        help=f"object field to dedup on (default {_DEFAULT_CLAIM_KEY!r}).",
    )
    args = ap.parse_args(argv)

    # Robust input handling: every operator-facing failure (unreadable file,
    # malformed JSON, contract-violating array shape) is a clean exit 2 with a
    # one-line stderr message — never an uncaught traceback.
    try:
        if args.path:
            with open(args.path, encoding="utf-8") as fh:
                raw = fh.read()
        else:
            raw = sys.stdin.read()
    except OSError as exc:
        print(f"error: cannot read input: {exc}", file=sys.stderr)
        return 2

    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: input is not valid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(parsed, list):
        print("error: expected a JSON array of claims", file=sys.stderr)
        return 2

    try:
        survivors, dropped = _dedup_json(
            parsed, key_field=args.key, threshold=args.threshold
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(survivors, ensure_ascii=False, indent=2))
    print(
        f"claim-dedup: kept {len(survivors)}, collapsed {dropped} near-duplicate(s)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
