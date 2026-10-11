"""
test_purge_rejected.py — rejected articles + companions must leave 1-incoming.

A curation `rejected` decision has to be enforced at the filesystem level so the
rejected content can't be re-sanitized, re-synthesized into brain/, folded into the
freshness hash, or surfaced by the digest.
"""
from pathlib import Path

from scripts import purge_rejected as pr  # noqa: E402
from scripts.registry import append_registry_row  # noqa: E402


def _article(incoming: Path, topic: str, name: str, url: str) -> Path:
    """Write a raw article + its sanitized companion; return the raw article path."""
    art = incoming / topic / f"{name}.md"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(
        f"---\ntitle: {name}\nurl: {url}\ncollected: 2026-06-01\n"
        f"category: {topic}\ntags: [{topic}]\n---\n\nbody\n",
        encoding="utf-8",
    )
    companion = incoming / topic / "sanitized" / f"{name}.md"
    companion.parent.mkdir(parents=True, exist_ok=True)
    companion.write_text("sanitized companion\n", encoding="utf-8")
    return art


def test_purge_removes_rejected_article_and_companion(tmp_path: Path) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    bad = _article(incoming, "ai", "hype", "https://hype.example.com/x")
    good = _article(incoming, "ai", "solid", "https://solid.example.com/y")
    append_registry_row(registry, collected="2026-06-01", category="ai",
                        url="https://hype.example.com/x", title="hype", status="rejected")
    append_registry_row(registry, collected="2026-06-01", category="ai",
                        url="https://solid.example.com/y", title="solid", status="processed")

    removed = pr.purge_rejected(incoming, registry)

    assert not bad.exists()  # rejected article gone
    assert not (incoming / "ai" / "sanitized" / "hype.md").exists()  # its companion gone
    assert good.exists()  # processed article kept
    assert (incoming / "ai" / "sanitized" / "solid.md").exists()
    assert set(removed) == {bad, incoming / "ai" / "sanitized" / "hype.md"}


def test_purge_matches_on_normalized_url(tmp_path: Path) -> None:
    # Article url and registry url differing only in shape (www/scheme/slash) still match.
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    bad = _article(incoming, "ai", "hype", "https://www.hype.example.com/x/")
    append_registry_row(registry, collected="2026-06-01", category="ai",
                        url="http://hype.example.com/x", title="hype", status="rejected")
    pr.purge_rejected(incoming, registry)
    assert not bad.exists()


def test_purge_tolerates_malformed_url_in_registry_and_article(tmp_path: Path) -> None:
    # One rejected row with an out-of-range port (normalize() would raise) must not
    # abort the batch: the other rejected article is still purged. Covers both the
    # rejected-keys scan and the per-article url match (both untrusted, stored).
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    bad = _article(incoming, "ai", "broken", "https://h:99999/p")
    good = _article(incoming, "ai", "hype", "https://hype.example.com/x")
    append_registry_row(registry, collected="2026-06-01", category="ai",
                        url="https://h:99999/p", title="broken", status="rejected")
    append_registry_row(registry, collected="2026-06-01", category="ai",
                        url="https://hype.example.com/x", title="hype", status="rejected")

    pr.purge_rejected(incoming, registry)  # must not raise

    assert not good.exists()  # the well-formed rejected article was still purged
    # The malformed row degrades to its raw key, so its article matches too.
    assert not bad.exists()


def test_purge_dry_run_removes_nothing(tmp_path: Path) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    bad = _article(incoming, "ai", "hype", "https://hype.example.com/x")
    append_registry_row(registry, collected="2026-06-01", category="ai",
                        url="https://hype.example.com/x", title="hype", status="rejected")
    removed = pr.purge_rejected(incoming, registry, dry_run=True)
    assert bad.exists()  # nothing actually deleted
    assert bad in removed  # ...but reported


def test_purge_is_idempotent_and_noop_without_rejections(tmp_path: Path) -> None:
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    _article(incoming, "ai", "solid", "https://solid.example.com/y")
    append_registry_row(registry, collected="2026-06-01", category="ai",
                        url="https://solid.example.com/y", title="solid", status="processed")
    assert pr.purge_rejected(incoming, registry) == []
    assert pr.purge_rejected(incoming, registry) == []  # second run still clean


# --------------------------------------------------------------------------- #
# Frontmatter edge cases: quoted URLs and missing url: field
# --------------------------------------------------------------------------- #


def test_purge_handles_quoted_url_value(tmp_path: Path) -> None:
    # Article's url: is quoted ("url: \"https://...\""), registry has unquoted url.
    # The URL stripping and normalization should still match and purge correctly.
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    bad = incoming / "ai" / "quoted.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    # Write with double-quoted url value (common YAML style).
    bad.write_text(
        '---\ntitle: quoted\nurl: "https://quoted.example.com/x"\ncollected: 2026-06-01\n'
        'category: ai\ntags: [ai]\n---\n\nbody\n',
        encoding="utf-8",
    )
    companion = incoming / "ai" / "sanitized" / "quoted.md"
    companion.parent.mkdir(parents=True, exist_ok=True)
    companion.write_text("sanitized\n", encoding="utf-8")

    append_registry_row(
        registry,
        collected="2026-06-01",
        category="ai",
        url="https://quoted.example.com/x",
        title="quoted",
        status="rejected",
    )

    removed = pr.purge_rejected(incoming, registry)

    # Both the article and companion should be removed.
    assert not bad.exists()
    assert not companion.exists()
    assert bad in removed
    assert companion in removed


def test_purge_handles_single_quoted_url_value(tmp_path: Path) -> None:
    # Article's url: uses single quotes instead of double.
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    bad = incoming / "ai" / "single.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text(
        "---\ntitle: single\nurl: 'https://single.example.com/x'\ncollected: 2026-06-01\n"
        "category: ai\ntags: [ai]\n---\n\nbody\n",
        encoding="utf-8",
    )

    append_registry_row(
        registry,
        collected="2026-06-01",
        category="ai",
        url="https://single.example.com/x",
        title="single",
        status="rejected",
    )

    removed = pr.purge_rejected(incoming, registry)

    assert not bad.exists()
    assert bad in removed


def test_purge_skips_article_with_missing_url_field(tmp_path: Path) -> None:
    # Article is missing the url: field entirely — should be skipped (no crash).
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    no_url = incoming / "ai" / "no_url.md"
    no_url.parent.mkdir(parents=True, exist_ok=True)
    no_url.write_text(
        "---\ntitle: no_url\ncollected: 2026-06-01\ncategory: ai\ntags: [ai]\n---\n\nbody\n",
        encoding="utf-8",
    )
    companion = incoming / "ai" / "sanitized" / "no_url.md"
    companion.parent.mkdir(parents=True, exist_ok=True)
    companion.write_text("sanitized\n", encoding="utf-8")

    # Register a url that is NOT in the article.
    append_registry_row(
        registry,
        collected="2026-06-01",
        category="ai",
        url="https://some.example.com/x",
        title="no_url",
        status="rejected",
    )

    removed = pr.purge_rejected(incoming, registry)

    # The article with no url: should NOT be removed (no match).
    assert no_url.exists()
    assert companion.exists()
    assert removed == []


def test_purge_handles_empty_url_field(tmp_path: Path) -> None:
    # Article has url: field but it's empty (url: "").
    # Should be skipped since an empty URL won't match anything.
    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    empty_url = incoming / "ai" / "empty.md"
    empty_url.parent.mkdir(parents=True, exist_ok=True)
    empty_url.write_text(
        '---\ntitle: empty\nurl: ""\ncollected: 2026-06-01\ncategory: ai\ntags: [ai]\n---\n\nbody\n',
        encoding="utf-8",
    )

    append_registry_row(
        registry,
        collected="2026-06-01",
        category="ai",
        url="https://some.example.com/x",
        title="empty",
        status="rejected",
    )

    removed = pr.purge_rejected(incoming, registry)

    # Empty URL article should not be removed.
    assert empty_url.exists()
    assert removed == []


def test_purge_skips_malformed_article_file(tmp_path: Path) -> None:
    # Article file is unreadable or corrupted (causes OSError).
    # _article_url catches OSError and returns "", so it should be skipped.
    import os

    incoming = tmp_path / "1-incoming"
    registry = tmp_path / "registry.md"
    bad_file = incoming / "ai" / "unreadable.md"
    bad_file.parent.mkdir(parents=True, exist_ok=True)
    bad_file.write_text("---\ntitle: unreadable\nurl: https://x.example\n---\n", encoding="utf-8")

    # Make the file unreadable.
    os.chmod(bad_file, 0o000)

    append_registry_row(
        registry,
        collected="2026-06-01",
        category="ai",
        url="https://x.example",
        title="unreadable",
        status="rejected",
    )

    try:
        # purge_rejected catches the error when trying to read and returns "".
        removed = pr.purge_rejected(incoming, registry)
        # The unreadable file should NOT be removed (read failure treated as no URL match).
        assert removed == []
    finally:
        # Restore permissions so cleanup works.
        os.chmod(bad_file, 0o644)
