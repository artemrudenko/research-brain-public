"""
api.py — the typed contract of the sanitize_incoming.py facade.

The sanitizer CLI receives the stable facade module as `api`, so its calls go
through the facade's compatibility wrappers (which honor monkeypatched module
globals like SANITIZER_VERSION at call time). `SanitizerApi` types that seam —
exactly the attributes the CLI reads, no more. Runtime-checkable so the test
suite can assert the real facade satisfies it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import argparse
    from datetime import datetime
    from pathlib import Path

    from scripts.sanitizer import model


@runtime_checkable
class SanitizerApi(Protocol):
    """Everything the sanitizer CLI reads off the sanitize_incoming facade."""

    def _build_parser(self) -> argparse.ArgumentParser: ...
    def _articles(
        self, incoming_root: Path, topics: list[str] | None = ...
    ) -> list[Path]: ...
    def sanitize_file(
        self, src: Path, *, now: datetime | None = ...
    ) -> model.FileOutcome: ...
    def gate_tree(
        self, incoming_root: Path = ..., topics: list[str] | None = ...
    ) -> model.GateResult: ...


__all__ = ["SanitizerApi"]
