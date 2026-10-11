"""Tests for scripts/_yaml.py — the one lazy-PyYAML import seam.

Sixteen runtime modules degrade differently when PyYAML is missing (fallback
parsers, advisory skips, clean CLI errors); they all share this single import
seam so the import behavior itself can never fork again.
"""

from __future__ import annotations

import sys

import pytest

from scripts._yaml import optional_yaml  # noqa: E402


def test_returns_the_yaml_module_when_installed() -> None:
    yaml = optional_yaml()
    assert yaml is not None
    assert callable(yaml.safe_load)


def test_returns_none_when_pyyaml_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    # Poisoning sys.modules with None makes `import yaml` raise ImportError —
    # the standard stdlib trick to simulate a missing distribution.
    monkeypatch.setitem(sys.modules, "yaml", None)
    assert optional_yaml() is None
