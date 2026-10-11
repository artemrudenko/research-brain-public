"""
test_claim_dedup.py — deterministic claim-level near-duplicate collapse
(scripts/claim_dedup.py).

This sits ON TOP of the URL-level registry dedup (scripts/normalize_url.py) and
the article-body hybrid dedup (scripts/dedup.py): here the unit is a *claim*
sentence, and near-duplicates are folded by word-shingle Jaccard so the same
assertion sourced from several places collapses to its first occurrence.

Offline; no network. Covers:
  - an exact duplicate collapses;
  - a reworded near-duplicate above threshold collapses;
  - genuinely different claims all survive;
  - the surviving claims keep original input order;
  - empty input yields empty output;
  - a pair just below threshold both survive (boundary is inclusive at the
    exact score, exclusive just above it);
  - the dedup_items convenience dedups objects by a claim-extracting key.
"""
import json

from scripts.claim_dedup import (
    dedup_claims,
    dedup_items,
    main,
    similarity,
)


def test_exact_duplicate_collapses() -> None:
    claim = "The model achieves state of the art results on the benchmark"
    survivors = dedup_claims([claim, claim])
    # Two identical claims collapse to the single first occurrence.
    assert survivors == [claim]


def test_reworded_near_duplicate_collapses_above_threshold() -> None:
    # Same assertion, one trailing content word dropped — Jaccard over
    # unigram+bigram shingles clears the 0.8 default (9/11 ≈ 0.818).
    a = "the new model improves reasoning accuracy significantly"
    b = "the new model improves reasoning accuracy"
    survivors = dedup_claims([a, b])
    assert survivors == [a]


def test_genuinely_different_claims_all_survive() -> None:
    claims = [
        "The economy grew by three percent last quarter",
        "A new species of frog was discovered in Brazil",
        "Solar panel efficiency reached a record high this year",
    ]
    # Nothing overlaps enough to be a duplicate; all three remain, in order.
    assert dedup_claims(claims) == claims


def test_surviving_claims_preserve_input_order() -> None:
    apples = "First unique claim about apples and orchards"
    oranges = "Second unique claim about oranges and citrus"
    bananas = "Third unique claim about bananas and plantains"
    claims = [apples, oranges, apples, bananas]
    # The later duplicate of `apples` is dropped; survivors keep input order.
    assert dedup_claims(claims) == [apples, oranges, bananas]


def test_empty_list_returns_empty_list() -> None:
    assert dedup_claims([]) == []


def test_threshold_boundary_is_inclusive() -> None:
    # Pin the exact score of a reworded pair, then assert the boundary is
    # inclusive at that value (collapses) and exclusive just above it (both
    # survive) — matching the >= convention in scripts/dedup.py.
    a = "the new model improves reasoning accuracy significantly"
    b = "the new model improves reasoning accuracy"
    score = similarity(a, b)
    assert 0.0 < score < 1.0  # a genuine partial overlap, not trivial

    # At exactly the score, the pair is a duplicate → collapses to one.
    assert dedup_claims([a, b], threshold=score) == [a]
    # Just above the score, neither is a duplicate → both survive in order.
    assert dedup_claims([a, b], threshold=score + 1e-9) == [a, b]


def test_below_threshold_pair_both_survive() -> None:
    # A low-overlap pair (shares only "machine learning") stays well under the
    # 0.8 default, so both claims survive.
    a = "machine learning transforms modern software development"
    b = "machine learning changes traditional hardware manufacturing"
    assert similarity(a, b) < 0.8
    assert dedup_claims([a, b]) == [a, b]


def test_dedup_items_dedups_by_claim_key() -> None:
    # dedup_items collapses objects whose extracted claim is a near-duplicate,
    # keeping the first object and preserving order.
    items = [
        {"id": 1, "claim": "The new model improves reasoning accuracy significantly"},
        {"id": 2, "claim": "The new model improves reasoning accuracy"},
        {"id": 3, "claim": "An unrelated note about quarterly tax filings"},
    ]
    survivors = dedup_items(items, key=lambda item: item["claim"])
    # Item 2 is a near-dup of item 1 and is dropped; items 1 and 3 remain.
    assert [item["id"] for item in survivors] == [1, 3]


# --------------------------------------------------------------------------- #
# CLI — the deterministic entry point the synthesis (research-build) path calls
# over the accumulated cross-source key_claims before Phase 3 (ADR 0018).
# --------------------------------------------------------------------------- #


def test_cli_dedups_string_array(tmp_path, capsys) -> None:
    # A JSON array of claim strings on disk -> deduped array on stdout, order kept.
    src = tmp_path / "claims.json"
    src.write_text(
        json.dumps(
            [
                "The new model improves reasoning accuracy significantly",
                "The new model improves reasoning accuracy",  # near-dup of #1
                "An unrelated note about quarterly tax filings",
            ]
        )
    )
    code = main([str(src)])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out == [
        "The new model improves reasoning accuracy significantly",
        "An unrelated note about quarterly tax filings",
    ]


def test_cli_dedups_object_array_by_claim_key(tmp_path, capsys) -> None:
    # The reader-contract shape: [{claim, attribution}]. Objects dedup on the
    # claim field and the FIRST object (with its attribution) is preserved intact.
    src = tmp_path / "extract.json"
    src.write_text(
        json.dumps(
            [
                {"claim": "GLM-5.2 was released this week", "attribution": "a.com"},
                {"claim": "GLM 5.2 was released this week", "attribution": "b.com"},
                {"claim": "The chip shortage eased in Q2", "attribution": "c.com"},
            ]
        )
    )
    code = main([str(src)])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert [o["attribution"] for o in out] == ["a.com", "c.com"]


def test_cli_threshold_flag_keeps_borderline_pair(tmp_path, capsys) -> None:
    # A high --threshold makes a moderate near-dup pair both survive (the CLI
    # honours the flag, not just the default).
    src = tmp_path / "claims.json"
    src.write_text(
        json.dumps(
            [
                "The model improves reasoning on hard math benchmarks",
                "The model improves reasoning on coding benchmarks",
            ]
        )
    )
    code = main([str(src), "--threshold", "0.99"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out) == 2  # nothing collapses at a near-1.0 bar


def test_cli_reads_stdin(monkeypatch, capsys) -> None:
    # With no file arg the CLI reads JSON from stdin (pipe-friendly).
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(["one claim", "one claim"])))
    code = main([])
    assert code == 0
    assert json.loads(capsys.readouterr().out) == ["one claim"]


def test_cli_broken_json_exits_2_with_stderr_message(tmp_path, capsys) -> None:
    # Malformed JSON must be a clean, diagnosable failure: exit 2 plus a one-line
    # stderr message — never an uncaught JSONDecodeError traceback.
    src = tmp_path / "claims.json"
    src.write_text("{not json at all", encoding="utf-8")
    code = main([str(src)])
    assert code == 2
    captured = capsys.readouterr()
    assert captured.out == ""  # nothing on the data channel
    assert "error:" in captured.err


def test_cli_mixed_array_exits_2_with_stderr_message(tmp_path, capsys) -> None:
    # A mixed array of strings and objects is a contract violation _dedup_json
    # rejects; the CLI must surface it as exit 2, not an uncaught ValueError.
    src = tmp_path / "claims.json"
    src.write_text(
        json.dumps(["a bare claim string", {"claim": "an object claim"}]),
        encoding="utf-8",
    )
    code = main([str(src)])
    assert code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err


def test_cli_missing_input_file_exits_2_with_stderr_message(tmp_path, capsys) -> None:
    # A nonexistent input path is an operator mistake, not a crash: exit 2 plus
    # a stderr message — never a FileNotFoundError traceback.
    code = main([str(tmp_path / "does-not-exist.json")])
    assert code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err
