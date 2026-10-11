"""
test_validate_config.py — offline tests for the glossary.yaml section of the
config validator.

config/glossary.yaml is OPTIONAL (deleting it turns the glossary off), but when
present it must be parseable YAML whose root is a mapping carrying a `terms:`
map of string → string — a typo must not silently disable the digest glossary.
Skips cleanly if PyYAML is missing.
"""
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# The validator imports PyYAML lazily; the assertions here need it directly.
yaml = pytest.importorskip("yaml", reason="PyYAML required for config schema tests")

from scripts import validate_config  # noqa: E402

SHIPPED_CONFIG = _PROJECT_ROOT / "config"


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "glossary.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_shipped_glossary_valid() -> None:
    errors = validate_config.validate_glossary(SHIPPED_CONFIG / "glossary.yaml", yaml)
    assert errors == [], errors


def test_glossary_missing_file_is_ok(tmp_path: Path) -> None:
    # The glossary is optional — an absent file is a valid configuration.
    errors = validate_config.validate_glossary(tmp_path / "glossary.yaml", yaml)
    assert errors == []


def test_glossary_broken_yaml_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, "terms: [unclosed\n")
    errors = validate_config.validate_glossary(path, yaml)
    assert any("parse error" in e for e in errors), errors


def test_glossary_root_not_mapping_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, "- just\n- a\n- list\n")
    errors = validate_config.validate_glossary(path, yaml)
    assert any("mapping" in e for e in errors), errors


def test_glossary_terms_not_mapping_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, "terms:\n  - LLM\n  - RAG\n")
    errors = validate_config.validate_glossary(path, yaml)
    assert any("terms" in e for e in errors), errors


def test_glossary_missing_terms_key_fails(tmp_path: Path) -> None:
    # A root mapping without `terms:` is a mis-keyed glossary, not an empty one.
    path = _write(tmp_path, "definitions:\n  LLM: ok\n")
    errors = validate_config.validate_glossary(path, yaml)
    assert any("terms" in e for e in errors), errors


def test_glossary_non_string_entry_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, 'terms:\n  LLM: "ok"\n  BAD:\n    nested: value\n')
    errors = validate_config.validate_glossary(path, yaml)
    assert any("BAD" in e for e in errors), errors


def test_glossary_valid_passes(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        'terms:\n  LLM: "Large Language Model"\n  RAG: "Retrieval-Augmented Generation"\n',
    )
    assert validate_config.validate_glossary(path, yaml) == []
