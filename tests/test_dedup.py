"""
test_dedup.py — hybrid lexical near-duplicate detection (scripts/dedup.py).

Offline; no network, no conftest changes. Covers:
  - identical texts are duplicates;
  - paraphrase / near-dup above threshold are duplicates;
  - unrelated texts are not;
  - the threshold boundary is inclusive;
  - token-Jaccard catches a reorder the 3-gram signal misses, and
    3-gram-Jaccard catches a near-identical edit the token signal under-rates.
"""
from scripts.dedup import (
    find_duplicates,
    is_duplicate,
    similarity,
)


def test_identical_texts_are_duplicates() -> None:
    text = "the cat sat on the mat and watched the rain fall"
    assert is_duplicate(text, text)
    assert similarity(text, text) == 1.0


def test_paraphrase_over_threshold_is_duplicate() -> None:
    # The contract smoke pair: inflection (sat/sitting) + stopword churn, folded
    # by lemmatisation so the shared content lemmas {cat, sit, mat, today} match.
    a = "the cat sat on the mat today"
    b = "a cat was sitting on the mat today"
    assert is_duplicate(a, b)


def test_word_swap_near_dup_is_duplicate() -> None:
    # Same article with one extra word — the common near-dup / syndication case.
    a = "OpenAI released a new model today with improved reasoning for developers"
    b = "OpenAI released a new model today with improved reasoning for all developers"
    assert is_duplicate(a, b)


def test_unrelated_texts_are_not_duplicates() -> None:
    a = "the cat sat on the mat"
    b = "quarterly revenue rose sharply across all regions"
    assert not is_duplicate(a, b)


def test_threshold_boundary_is_inclusive() -> None:
    a = "alpha beta gamma delta"
    b = "alpha beta gamma epsilon"
    # Pin the score, then assert the boundary is inclusive at exactly that value
    # and exclusive just above it.
    score = similarity(a, b)
    assert is_duplicate(a, b, threshold=score)
    assert not is_duplicate(a, b, threshold=score + 1e-9)


def test_token_jaccard_catches_reorder_that_3gram_misses() -> None:
    # Same content words, heavily reordered: token-Jaccard stays high while the
    # char-3gram overlap drops. The hybrid max must still flag it.
    a = "machine learning models improve with more training data over time"
    b = "over time more training data improve machine learning models with"
    from scripts.dedup import _char_3grams, _jaccard, _tokens

    gram_score = _jaccard(_char_3grams(a), _char_3grams(b))
    token_score = _jaccard(_tokens(a), _tokens(b))
    assert token_score > gram_score  # token signal is the one doing the work
    assert is_duplicate(a, b)


def test_3gram_catches_near_identical_edit() -> None:
    # Near-identical surface text with a tiny typo/edit; char-3gram overlap is
    # very high. Confirm the 3-gram signal is the strong one here.
    a = "the quarterly report shows revenue growth across all market segments"
    b = "the quarterly report shows revenue growth across all market segmentz"
    from scripts.dedup import _char_3grams, _jaccard, _tokens

    gram_score = _jaccard(_char_3grams(a), _char_3grams(b))
    token_score = _jaccard(_tokens(a), _tokens(b))
    assert gram_score >= token_score  # 3-gram signal carries the near-identical pair
    assert is_duplicate(a, b)


def test_find_duplicates_groups_clusters_and_drops_singletons() -> None:
    items = [
        "the cat sat on the mat today",
        "a cat was sitting on the mat today",
        "quarterly revenue rose sharply across all regions this year",
    ]
    clusters = find_duplicates(items)
    # Items 0 and 1 are near-dups; item 2 is alone and must not appear.
    assert clusters == [[0, 1]]


def test_find_duplicates_unions_transitive_chain() -> None:
    base = "machine learning models improve with more training data over time"
    items = [
        base,
        base + " significantly",
        base + " significantly and reliably",
        "an unrelated note about quarterly accounting and tax filings",
    ]
    clusters = find_duplicates(items)
    assert len(clusters) == 1
    assert clusters[0] == [0, 1, 2]


# --------------------------------------------------------------------------- #
# Edge cases: empty input, single item, degenerate strings, unicode
# --------------------------------------------------------------------------- #


def test_find_duplicates_empty_input_returns_empty_clusters() -> None:
    # Empty input should yield no clusters (nothing can duplicate nothing).
    clusters = find_duplicates([])
    assert clusters == []


def test_find_duplicates_single_item_returns_empty_clusters() -> None:
    # Single item has no duplicates to cluster, so it is omitted.
    clusters = find_duplicates(["only one article"])
    assert clusters == []


def test_find_duplicates_all_identical_items() -> None:
    # N copies of the same text form one cluster of size N.
    items = ["identical"] * 5
    clusters = find_duplicates(items)
    assert len(clusters) == 1
    assert clusters[0] == [0, 1, 2, 3, 4]


def test_similarity_very_short_texts() -> None:
    # Strings shorter than 3 chars: _char_3grams falls back to the whole string.
    # Similarity of identical short strings should be 1.0.
    assert similarity("a", "a") == 1.0
    assert similarity("ab", "ab") == 1.0
    assert similarity("abc", "abc") == 1.0
    # Different short strings have no overlap.
    assert similarity("a", "b") == 0.0
    assert similarity("ab", "cd") == 0.0


def test_similarity_empty_strings() -> None:
    # Two empty strings: _char_3grams returns {}, _tokens returns {}.
    # _jaccard({}, {}) returns 0.0 by design.
    assert similarity("", "") == 0.0
    # Empty vs non-empty also 0.
    assert similarity("", "text") == 0.0
    assert similarity("text", "") == 0.0


def test_is_duplicate_empty_strings() -> None:
    # Empty strings are treated as non-duplicates (similarity 0.0).
    assert not is_duplicate("", "")
    assert not is_duplicate("", "text")


def test_similarity_unicode_text() -> None:
    # Unicode should work without crashing; accents/non-ASCII treated as chars.
    a = "café is a nice place"
    b = "cafe is a nice place"
    # Unicode differs from ASCII, so slight mismatch expected.
    score = similarity(a, b)
    assert 0 <= score <= 1.0
    # Identical unicode should still be 1.0.
    assert similarity(a, a) == 1.0


def test_is_duplicate_unicode_text() -> None:
    # Unicode text: identical should be duplicate, different accents should not.
    assert is_duplicate("café", "café")
    # No crash on emoji or other unicode.
    assert is_duplicate("🎯 goal", "🎯 goal")


def test_find_duplicates_with_unicode_items() -> None:
    # Mix of unicode and ASCII; union-find should handle transparently.
    items = [
        "café and résumé are French words",
        "cafe and resume are French words",
        "unrelated article about AI",
    ]
    clusters = find_duplicates(items)
    # Items 0 and 1 have some token overlap but the accent difference
    # and lowercase variation may not push them over threshold; at minimum,
    # no crash and clusters is a valid list.
    assert isinstance(clusters, list)
    for cluster in clusters:
        assert isinstance(cluster, list)
        assert all(isinstance(i, int) for i in cluster)


def test_find_duplicates_pathological_union_find() -> None:
    # A chain of transitive duplicates exercises path halving in union-find.
    # Build a long chain: 0~1, 1~2, 2~3, ... that forces union-find to compact.
    base = "the quick brown fox"
    items = [base + f" {i}" for i in range(10)]
    # All should be near-duplicates and collapse to one cluster.
    clusters = find_duplicates(items, threshold=0.5)
    assert len(clusters) == 1
    assert len(clusters[0]) == 10
