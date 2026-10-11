#!/usr/bin/env python3
"""
dedup.py — hybrid lexical near-duplicate detection for collected articles.

The registry dedup key (`scripts/normalize_url.py`) catches the *same* URL in
different shapes. It does NOT catch the same story republished at a different
URL — syndication, mirror posts, lightly-reworded reposts. This module fills
that gap with a cheap, embedding-free lexical similarity check.

Similarity = ``max(char-3gram Jaccard, token Jaccard (stopword-filtered))``.
Two complementary signals, whichever fires:
  - char-3gram Jaccard catches near-identical wording / minor edits / typos.
  - token Jaccard (stopwords removed) catches reorderings and paraphrases that
    keep the same content words.
A pair counts as duplicate when that max meets ``threshold`` (default 0.7).

Stdlib only. n-grams/tokens are precomputed once per text so pairwise
comparison over a batch stays cheap.

Usage (CLI, optional):
    python3 scripts/dedup.py a.txt b.txt [more.txt ...]
        → prints duplicate clusters (groups of indices/paths that match).
"""
from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

# Default similarity threshold; a pair >= this is treated as a duplicate.
# Fixed by CONVENTIONS §12 ("hybrid max(char-3gram-jaccard, token-jaccard) >= 0.7").
DEFAULT_THRESHOLD = 0.7

# Small, language-neutral-ish English stopword set. Removing these keeps the
# token-Jaccard signal focused on content words, so "the cat sat on the mat"
# and "a cat was sitting on the mat" share their meaningful tokens.
_STOPWORDS = frozenset(
    """
    a an the this that these those
    is are was were be been being am
    do does did doing done
    have has had having
    of in on at by to from with for as into onto over under
    and or but nor so yet
    it its it's they them their he she his her we us our you your i me my
    not no
    will would shall should can could may might must
    here there then than too very just also about up down out off
    """.split()
)

# A word = run of letters/digits (apostrophes folded out beforehand).
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Tiny irregular-form map for the most common English verbs/be-forms, so that
# "sat"/"sitting" or "was"/"is" collapse to one lemma. Lexical Jaccard cannot
# fold these otherwise. Kept deliberately small (KISS) — extend only when a
# real recurring miss shows up.
_IRREGULAR_LEMMA = {
    "sat": "sit",
    "sitting": "sit",
    "was": "be",
    "were": "be",
    "is": "be",
    "are": "be",
    "am": "be",
    "been": "be",
    "ran": "run",
    "running": "run",
    "said": "say",
    "made": "make",
    "went": "go",
}

# Regular inflectional suffixes, longest first so "-ing" wins over "-s".
_SUFFIXES = ("ing", "ed", "ly", "es", "s")


def _lemma(word: str) -> str:
    """Reduce a word to a crude lemma for token comparison.

    Irregular forms map via :data:`_IRREGULAR_LEMMA`; otherwise strip a common
    inflectional suffix and undo a doubled final consonant (``sitting`` →
    ``sitt`` → ``sit``). This is a cheap stemmer, not a real lemmatiser — good
    enough to fold inflection so paraphrases share content tokens.
    """
    if word in _IRREGULAR_LEMMA:
        return _IRREGULAR_LEMMA[word]
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            stem = word[: -len(suffix)]
            # Undo an English doubled-consonant spelling (run→running→runn→run).
            if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
                stem = stem[:-1]
            return stem
    return word


def _tokens(text: str) -> set[str]:
    """Content tokens of ``text``: stopword-filtered, lemmatised words.

    Stopwords are dropped both before and after lemmatisation (e.g. ``was`` →
    ``be`` is also a stopword) so only content-bearing lemmas remain.
    """
    lowered = text.lower().replace("'", "")
    out: set[str] = set()
    for raw in _TOKEN_RE.findall(lowered):
        if raw in _STOPWORDS:
            continue
        lemma = _lemma(raw)
        if lemma not in _STOPWORDS:
            out.add(lemma)
    return out


def _char_3grams(text: str) -> set[str]:
    """Set of character 3-grams over whitespace-collapsed, lowercased text."""
    # Collapse runs of whitespace to a single space so layout differences don't
    # create spurious n-grams, and lowercase for case-insensitive matching.
    collapsed = " ".join(text.lower().split())
    if len(collapsed) < 3:
        # Too short for any 3-gram; fall back to the whole string as one token.
        return {collapsed} if collapsed else set()
    return {collapsed[i : i + 3] for i in range(len(collapsed) - 2)}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard index |a∩b| / |a∪b|; 0.0 when both sets are empty."""
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a) + len(b) - intersection
    return intersection / union if union else 0.0


@dataclass
class _Fingerprint:
    """Precomputed similarity features for one text (built once, reused)."""

    grams: set[str] = field(default_factory=set)
    tokens: set[str] = field(default_factory=set)


def _fingerprint(text: str) -> _Fingerprint:
    """Precompute the 3-gram and token sets for ``text``."""
    return _Fingerprint(grams=_char_3grams(text), tokens=_tokens(text))


def similarity(a_text: str, b_text: str) -> float:
    """Hybrid similarity score in [0, 1] between two texts.

    Returns ``max`` of char-3gram Jaccard and stopword-filtered token Jaccard.
    """
    fa, fb = _fingerprint(a_text), _fingerprint(b_text)
    return max(_jaccard(fa.grams, fb.grams), _jaccard(fa.tokens, fb.tokens))


def is_duplicate(a_text: str, b_text: str, threshold: float = DEFAULT_THRESHOLD) -> bool:
    """True when ``a_text`` and ``b_text`` are near-duplicates.

    A pair is a duplicate when the hybrid :func:`similarity` score is at or
    above ``threshold`` (inclusive boundary).
    """
    return similarity(a_text, b_text) >= threshold


def find_duplicates(
    items: Sequence[str], threshold: float = DEFAULT_THRESHOLD
) -> list[list[int]]:
    """Group ``items`` (texts) into clusters of mutual near-duplicates.

    Returns a list of clusters; each cluster is a list of indices into
    ``items`` that are transitively linked by the duplicate relation (union-
    find). Singletons (items with no duplicate) are omitted — only clusters of
    size >= 2 are returned, ordered by first member.

    Fingerprints are computed once per item, so this is O(n^2) comparisons of
    precomputed sets rather than re-tokenising on every pair.
    """
    fingerprints = [_fingerprint(text) for text in items]
    n = len(items)

    # Union-find over item indices so chains of duplicates collapse to one
    # cluster (a~b and b~c → {a,b,c}).
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path halving
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for i in range(n):
        for j in range(i + 1, n):
            score = max(
                _jaccard(fingerprints[i].grams, fingerprints[j].grams),
                _jaccard(fingerprints[i].tokens, fingerprints[j].tokens),
            )
            if score >= threshold:
                union(i, j)

    # Collect members by representative root, preserving input order.
    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    return [members for members in clusters.values() if len(members) >= 2]


def _read_files(paths: Iterable[str]) -> list[tuple[str, str]]:
    """Read each path → (path, text). Helper for the CLI."""
    out: list[tuple[str, str]] = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                out.append((p, fh.read()))
        except OSError as error:
            print(f"dedup: cannot read {p}: {error}", file=sys.stderr)
            raise SystemExit(2) from error
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: dedup.py <file1> <file2> [more...]", file=sys.stderr)
        raise SystemExit(2)

    pairs = _read_files(sys.argv[1:])
    texts = [text for _, text in pairs]
    clusters = find_duplicates(texts)

    if not clusters:
        print("no near-duplicate clusters found")
    else:
        for n, cluster in enumerate(clusters, start=1):
            members = ", ".join(pairs[i][0] for i in cluster)
            print(f"cluster {n}: {members}")
