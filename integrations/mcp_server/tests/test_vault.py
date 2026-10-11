from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from research_brain_mcp.vault import VaultReader


def _write_concept(
    root: Path, slug: str, *, topic: str = "protocols", updated: str = "2026-09-01"
) -> None:
    concepts = root / "brain" / "concepts"
    concepts.mkdir(parents=True, exist_ok=True)
    (concepts / f"{slug}.md").write_text(
        "---\n"
        f"title: {slug.replace('-', ' ').title()}\n"
        "type: concept\n"
        f"tags: [engineering/{topic}]\n"
        f"last_updated: {updated}\n"
        "last_verified: 2026-08-15\n"
        "ttl_days: 180\n"
        "sources:\n"
        "  - url: https://example.org/spec\n"
        "    date: 2026-08-15\n"
        "    tier: high\n"
        "    archive: pipeline/0-archive/example.md\n"
        "---\n"
        f"# {slug.replace('-', ' ').title()}\n\n"
        "> **Confidence:** high\n\n"
        "## What it is\n\nA concise synthetic definition.\n\n"
        "## Key facts\n\n- A synthetic fact. Source: https://example.org/spec\n\n"
        "## Open questions / gaps\n\n- Is this still valid for newer versions?\n",
        encoding="utf-8",
    )


def _write_index(root: Path, links: str) -> None:
    brain = root / "brain"
    brain.mkdir(parents=True, exist_ok=True)
    (brain / "INDEX.md").write_text(f"# Map\n\n## Protocols\n{links}\n", encoding="utf-8")


def test_search_returns_sources_freshness_gaps_and_at_most_two_notes(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "http-timeouts")
    _write_concept(tmp_path, "protocol-history")
    _write_index(
        tmp_path,
        "- [[concepts/retry-safety|Retry safety]]\n"
        "- [[concepts/http-timeouts|HTTP timeouts]]\n"
        "- [[concepts/protocol-history|Protocol history]]\n",
    )
    reader = VaultReader(tmp_path)

    result = reader.search("protocol retry")

    assert result.count("# Retry Safety") == 1
    assert result.count("# Protocol History") == 1
    assert "# HTTP Timeouts" not in result
    assert "https://example.org/spec" in result
    assert "archive=pipeline/0-archive/example.md" in result
    assert "last_verified=2026-08-15" in result
    assert "Open questions / gaps" in result
    assert "No web or raw-corpus search was performed" in result
    assert "Freshness status: within_ttl" in result
    assert "Request mode: vault_only" in result


def test_research_mode_marks_hits_as_context_and_hands_off_when_incomplete(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "other-note")
    _write_index(tmp_path, "- [[concepts/retry-safety|Retry safety]]\n")

    result = VaultReader(tmp_path).search("retry safety", request_mode="research")

    assert "Request mode: research" in result
    assert "prior context, not a complete answer" in result
    assert "Search the configured local corpus first" in result
    assert "External research still follows research-grep's user-choice gate" in result
    assert "No web or raw-corpus search was performed" in result


def test_topic_filter_limits_moc_matches(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "identity-basics", topic="identity")
    _write_index(
        tmp_path,
        "- [[concepts/retry-safety|Retry safety]]\n"
        "## Identity\n- [[concepts/identity-basics|Protocol identity]]\n",
    )

    result = VaultReader(tmp_path).search("protocol", topic_filter="identity")

    assert "Identity Basics" in result
    assert "Retry Safety" not in result


def test_filename_fallback_runs_only_after_no_moc_match(tmp_path: Path) -> None:
    _write_concept(tmp_path, "fault-tolerance")
    _write_concept(tmp_path, "other-note")
    note_path = tmp_path / "brain" / "concepts" / "fault-tolerance.md"
    note_path.write_text(
        note_path.read_text(encoding="utf-8")
        .replace("title: Fault Tolerance", "title: Timeout policy")
        .replace("# Fault Tolerance", "# Timeout policy"),
        encoding="utf-8",
    )
    _write_index(tmp_path, "- [[concepts/other-note|Other note]]\n")

    result = VaultReader(tmp_path).search("fault tolerance")

    assert "Timeout policy" in result
    assert "Match path: filename fallback" in result


def test_search_finds_and_quotes_a_term_only_in_concept_body(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "other-note")
    _write_index(tmp_path, "- [[concepts/other-note|Other note]]\n")
    note_path = tmp_path / "brain" / "concepts" / "retry-safety.md"
    note_text = note_path.read_text(encoding="utf-8").replace(
        "A synthetic fact.",
        "Idempotency keys let clients safely retry a request after a timeout.",
    )
    note_path.write_text(note_text, encoding="utf-8")

    result = VaultReader(tmp_path).search("idempotency keys")

    assert "Retry Safety" in result
    assert "Match path: concept text" in result
    assert "Idempotency keys let clients safely retry" in result
    assert "Other Note" not in result


def test_search_excerpt_quotes_a_fact_instead_of_repeating_the_heading(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "other-note")
    _write_index(tmp_path, "- [[concepts/retry-safety|Retry safety]]\n")
    note_path = tmp_path / "brain" / "concepts" / "retry-safety.md"
    note_path.write_text(
        note_path.read_text(encoding="utf-8").replace(
            "A synthetic fact.", "Retry safety depends on operation guarantees."
        ),
        encoding="utf-8",
    )

    result = VaultReader(tmp_path).search("retry safety")

    excerpt = result.split("## Matching excerpt\n", 1)[1].split("\n\n", 1)[0]
    assert "Retry safety depends on operation guarantees" in excerpt


def test_search_excerpt_preserves_identifiers_and_source_url_fragments(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-policy")
    _write_concept(tmp_path, "other-note")
    _write_index(tmp_path, "- [[concepts/retry-policy|Retry policy]]\n")
    source = "https://example.org/retry_policy#section_1"
    note_path = tmp_path / "brain" / "concepts" / "retry-policy.md"
    note_path.write_text(
        note_path.read_text(encoding="utf-8").replace(
            "A synthetic fact. Source: https://example.org/spec",
            f"Retry policy retains `retry_after`. Source: {source}",
        ),
        encoding="utf-8",
    )

    result = VaultReader(tmp_path).search("retry policy")

    excerpt = result.split("## Matching excerpt\n", 1)[1].split("\n\n", 1)[0]
    assert "retry_after" in excerpt
    assert source in excerpt


def test_synthetic_retrieval_cases_return_expected_concepts_and_clean_miss(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "access-boundaries", topic="security")
    _write_concept(tmp_path, "unrelated-concept", topic="education")
    notes = tmp_path / "brain" / "concepts"
    retry = notes / "retry-safety.md"
    retry.write_text(
        retry.read_text(encoding="utf-8").replace(
            "A synthetic fact.",
            "Idempotency keys let a client retry a timed-out request without repeating its effect.",
        ),
        encoding="utf-8",
    )
    access = notes / "access-boundaries.md"
    access.write_text(
        access.read_text(encoding="utf-8")
        .replace("title: Access Boundaries", "title: Authorization scope")
        .replace(
            "A synthetic fact.",
            "Privilege boundaries separate requested actions from permitted actions.",
        ),
        encoding="utf-8",
    )
    _write_index(
        tmp_path,
        "- [[concepts/retry-safety|Retry safety]]\n"
        "- [[concepts/unrelated-concept|Unrelated concept]]\n",
    )
    reader = VaultReader(tmp_path)

    cases = (("idempotency keys", "retry-safety"), ("privilege boundaries", "access-boundaries"))
    found = sum(
        1 for query, slug in cases if f"brain/concepts/{slug}.md" in reader.search(query)
    )
    miss = reader.search("exoplanet spectroscopy")

    assert found == 2  # recall@2 over the two known-positive synthetic queries
    assert "Vault-only miss" in miss
    assert "Unrelated concept" not in reader.search("idempotency keys")


def test_topic_filter_does_not_fall_back_outside_its_scope(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "other-note")
    _write_index(tmp_path, "- [[concepts/other-note|Other note]]\n")

    result = VaultReader(tmp_path).search("retry safety", topic_filter="security")

    assert "Vault-only miss" in result
    assert "within topic filter 'security'" in result
    assert "Retry Safety" not in result


def test_oversized_concept_is_not_read_or_returned(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "other-note")
    _write_index(tmp_path, "- [[concepts/retry-safety|Retry safety]]\n")
    note_path = tmp_path / "brain" / "concepts" / "retry-safety.md"
    note_path.write_text("x" * 1_000_001, encoding="utf-8")

    result = VaultReader(tmp_path).search("retry safety")

    assert "Vault scan incomplete" in result
    assert "xxxx" not in result


def test_search_keeps_large_gaps_within_a_compact_response(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "retry-policy")
    _write_index(
        tmp_path,
        "- [[concepts/retry-safety|Retry safety]]\n- [[concepts/retry-policy|Retry policy]]\n",
    )
    for slug in ("retry-safety", "retry-policy"):
        note_path = tmp_path / "brain" / "concepts" / f"{slug}.md"
        note_text = note_path.read_text(encoding="utf-8")
        note_path.write_text(
            note_text.replace("- Is this still valid for newer versions?", "x" * 30_000),
            encoding="utf-8",
        )

    result = VaultReader(tmp_path).search("retry")

    assert len(result) < 5_000
    assert "MCP response truncated at the adapter limit" not in result
    assert "Gap excerpt truncated at the search result limit" in result


def test_search_omits_overlong_source_url_with_clear_reason(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "other-note")
    _write_index(tmp_path, "- [[concepts/retry-safety|Retry safety]]\n")
    note_path = tmp_path / "brain" / "concepts" / "retry-safety.md"
    note_text = note_path.read_text(encoding="utf-8").replace(
        "https://example.org/spec", "https://example.org/" + ("x" * 1_100)
    )
    note_path.write_text(note_text, encoding="utf-8")

    result = VaultReader(tmp_path).search("retry safety")

    assert "source URL omitted: longer than the source URL limit" in result
    assert "x" * 200 not in result


def test_vault_only_miss_does_not_search_pipeline_or_network(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "other-note")
    _write_index(tmp_path, "- [[concepts/other-note|Other note]]\n")

    result = VaultReader(tmp_path).search("quantum widget")

    assert "Vault-only miss" in result
    assert "No raw corpus or web search was accessed" in result
    assert "Request mode: vault_only" in result


def test_natural_language_miss_ignores_question_boilerplate(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "other-note")
    _write_index(tmp_path, "- [[concepts/retry-safety|Retry safety]]\n")

    result = VaultReader(tmp_path).search("What do we know about quantum error correction?")

    assert "Vault-only miss" in result
    assert "Retry Safety" not in result


def test_research_mode_miss_hands_off_without_running_research(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "other-note")
    _write_index(tmp_path, "- [[concepts/other-note|Other note]]\n")

    result = VaultReader(tmp_path).search("quantum widget", request_mode="research")

    assert "Vault-only miss" in result
    assert "Request mode: research" in result
    assert "continue the existing research workflow" in result
    assert "No raw corpus or web search was accessed" in result


def test_get_concept_rejects_paths_and_does_not_change_vault(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "another-note")
    _write_index(tmp_path, "- [[concepts/retry-safety|Retry safety]]\n")
    outside = tmp_path / "secrets.md"
    outside.write_text("private fixture", encoding="utf-8")
    note_path = tmp_path / "brain" / "concepts" / "retry-safety.md"
    before = note_path.read_bytes()

    reader = VaultReader(tmp_path)
    rejected = reader.get_concept("../secrets")
    result = reader.get_concept("retry-safety")

    assert "not found" in rejected
    assert "private fixture" not in rejected
    assert "Retry Safety" in result
    assert note_path.read_bytes() == before


def test_source_metadata_does_not_forward_malformed_or_credentialed_urls(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "other-note")
    _write_index(tmp_path, "- [[concepts/retry-safety|Retry safety]]\n")
    note_path = tmp_path / "brain" / "concepts" / "retry-safety.md"
    original = note_path.read_text(encoding="utf-8")

    for unsafe_url in (
        "https://[malformed.example/spec",
        "https://reader:top-secret@example.org/spec",
        "https://example.org/spec?access_token=top-secret",
        "https://example.org/spec#token=top-secret",
    ):
        note_path.write_text(
            original.replace("https://example.org/spec", unsafe_url), encoding="utf-8"
        )
        result = VaultReader(tmp_path).get_concept("retry-safety")

        assert "[source URL omitted" in result
        assert "top-secret" not in result
        assert "reader" not in result


def test_source_metadata_omits_absolute_or_traversing_archive_paths(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "other-note")
    note_path = tmp_path / "brain" / "concepts" / "retry-safety.md"
    original = note_path.read_text(encoding="utf-8")

    for unsafe_archive in ("/private/notes.md", "../../private/notes.md"):
        note_path.write_text(
            original.replace("pipeline/0-archive/example.md", unsafe_archive), encoding="utf-8"
        )
        result = VaultReader(tmp_path).get_concept("retry-safety")

        assert "[archive path omitted" in result
        assert "private-user" not in result
        assert "../../private/notes.md" not in result


def test_search_preserves_internal_artifact_provenance_without_a_web_url(tmp_path: Path) -> None:
    _write_concept(tmp_path, "answer-boundary")
    _write_concept(tmp_path, "other-note")
    _write_index(tmp_path, "- [[concepts/answer-boundary|Answer boundary]]\n")
    note_path = tmp_path / "brain" / "concepts" / "answer-boundary.md"
    artifact = "pipeline/3-synthesis/method-review.md"
    note_path.write_text(
        note_path.read_text(encoding="utf-8").replace(
            "    archive: pipeline/0-archive/example.md\n",
            "    archive: pipeline/0-archive/example.md\n"
            f"  - archive: {artifact}\n    date: 2026-10-11\n    tier: medium\n",
        ),
        encoding="utf-8",
    )

    reader = VaultReader(tmp_path)
    for result in (reader.search("answer boundary"), reader.get_concept("answer-boundary")):
        sources = result.split("## Recorded sources\n", 1)[1].split("\n\n", 1)[0]
        assert f"archive={artifact}" in sources


def test_get_concept_rejects_symlinked_brain_root(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    outside_brain = tmp_path / "outside" / "brain"
    checkout.mkdir()
    _write_concept(tmp_path / "outside", "retry-safety")
    _write_concept(tmp_path / "outside", "other-note")
    (checkout / "brain").symlink_to(outside_brain, target_is_directory=True)

    result = VaultReader(checkout).get_concept("retry-safety")

    assert "Vault not populated" in result
    assert "A concise synthetic definition" not in result


def test_insufficient_vault_and_invalid_concept_frontmatter_are_reported(tmp_path: Path) -> None:
    concepts = tmp_path / "brain" / "concepts"
    concepts.mkdir(parents=True)
    (concepts / "one.md").write_text("---\ntype: concept\n---\n", encoding="utf-8")
    _write_index(tmp_path, "- [[concepts/one|One]]\n")
    assert "at least two concept notes" in VaultReader(tmp_path).search("one")

    _write_concept(tmp_path, "two")
    (concepts / "broken.md").write_text("---\ntype: [invalid\n---\n", encoding="utf-8")
    assert "not found" in VaultReader(tmp_path).get_concept("broken")


def test_last_updated_does_not_count_as_source_reverification(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "other-note")
    note_path = tmp_path / "brain" / "concepts" / "retry-safety.md"
    text = note_path.read_text(encoding="utf-8").replace("last_verified: 2026-08-15\n", "")
    note_path.write_text(text, encoding="utf-8")
    _write_index(tmp_path, "- [[concepts/retry-safety|Retry safety]]\n")

    result = VaultReader(tmp_path).search("retry safety")

    assert "Freshness unknown" in result
    assert "Freshness status: unknown" in result
    assert "not a source re-verification date" in result
    assert "within recorded TTL" not in result


def test_expired_verification_is_marked_review_due(tmp_path: Path) -> None:
    _write_concept(tmp_path, "retry-safety")
    _write_concept(tmp_path, "other-note")
    _write_index(tmp_path, "- [[concepts/retry-safety|Retry safety]]\n")
    note_path = tmp_path / "brain" / "concepts" / "retry-safety.md"
    note_text = note_path.read_text(encoding="utf-8")
    verified = (date.today() - timedelta(days=31)).isoformat()
    note_path.write_text(
        note_text.replace("last_verified: 2026-08-15", f"last_verified: {verified}").replace(
            "ttl_days: 180", "ttl_days: 30"
        ),
        encoding="utf-8",
    )

    result = VaultReader(tmp_path).search("retry safety", request_mode="research")

    assert "Freshness status: review_due" in result
    assert "Request mode: research" in result
    assert "continue the existing research workflow" in result
