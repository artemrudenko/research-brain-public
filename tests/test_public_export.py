"""The GitHub export must require an explicit decision for every tracked path."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import export_public

ROOT = Path(__file__).resolve().parents[1]


def _minimal_blobs() -> dict[str, tuple[bytes, int]]:
    paths = export_public.REQUIRED_FILES | export_public.SEED_SHA256.keys()
    return {path: ((ROOT / path).read_bytes(), 0o644) for path in paths}


def test_export_keeps_source_and_examples_but_omits_private_and_runtime_files() -> None:
    assert export_public.classify("scripts/collect.py") == "include"
    assert export_public.classify("integrations/mcp_server/README.md") == "include"
    assert export_public.classify("integrations/mcp_server/uv.lock") == "include"
    assert export_public.classify("tests/test_dist.py") == "include"
    assert export_public.classify("brain/concepts/example-concept-a.md") == "include"
    assert export_public.classify("brain/concepts/customer-note.md") == "review"
    assert export_public.classify("docs/private-history/CHANGELOG.md") == "exclude"
    assert export_public.classify("docs/PUBLIC_RELEASE_PREP.md") == "exclude"
    assert export_public.classify("docs/BACKLOG.md") == "exclude"
    assert export_public.classify("docs/adr/0024-scholarly-author-ingestion.md") == "exclude"
    assert export_public.classify("pipeline/registry.md") == "review"
    assert export_public.classify("config/authors.yaml") == "review"


def test_export_refuses_unclassified_files_and_modified_seed() -> None:
    blobs = _minimal_blobs()
    export_public.select_public(blobs)
    with pytest.raises(ValueError, match="classify these tracked paths"):
        export_public.select_public({**blobs, "new-private-folder/data.md": (b"private", 0o644)})
    with pytest.raises(ValueError, match="review changed public seed"):
        export_public.select_public({**blobs, "config/sources.yaml": (b"a personal source", 0o644)})


def test_in_place_check_refuses_even_known_excluded_paths() -> None:
    blobs = _minimal_blobs()
    export_public.require_public_repository(blobs)
    with pytest.raises(ValueError, match="private paths are tracked"):
        export_public.require_public_repository(
            {**blobs, "docs/private-history/CHANGELOG.md": (b"internal notes", 0o644)}
        )


def test_export_refuses_internal_names_personal_paths_and_real_addresses() -> None:
    assert "internal name" in export_public.content_issues("README.md", b"Ari" + b"stek")
    assert "internal name" in export_public.content_issues(
        "README.md", "Арис".encode() + "тек".encode()
    )
    assert "internal name" in export_public.content_issues("README.md", b"ar" + b"stk")
    assert "absolute personal path" in export_public.content_issues(
        "README.md", b"/Users/" + b"person/project"
    )
    assert "non-example email address" in export_public.content_issues(
        "README.md", b"someone@" + b"company.test"
    )
    assert not export_public.content_issues("README.md", b"you@example.com")


@pytest.mark.parametrize("credential", [
    "ghp_" + "a" * 36,
    "github_pat_" + "a" * 50,
    "sk-proj-" + "a" * 40,
    "AKIA" + "A" * 16,
])
def test_export_refuses_credential_shaped_values(credential: str) -> None:
    assert "credential-shaped value" in export_public.content_issues(
        "README.md", credential.encode()
    )
