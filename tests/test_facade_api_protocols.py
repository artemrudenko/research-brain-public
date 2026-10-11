"""
test_facade_api_protocols.py — the sanitizer and config-validation `api` seams
are typed Protocols, matching the delivery core's DeliveryApi pattern.

Each stable facade module (sanitize_incoming.py, validate_config.py) passes
itself into its package CLI as `api`. These tests pin the contract: the facade
satisfies its protocol at runtime, and the CLI entrypoints stay annotated with
the protocol instead of drifting back to `Any`.
"""

import inspect

import pytest

from scripts import sanitize_incoming, validate_config
from scripts.config_validation import cli as config_validation_cli
from scripts.config_validation.api import ConfigValidationApi
from scripts.sanitizer import cli as sanitizer_cli
from scripts.sanitizer.api import SanitizerApi

# ---------------------------------------------------------------------------
# The facades satisfy their protocols (runtime structural check).
# ---------------------------------------------------------------------------


def test_sanitize_incoming_facade_satisfies_sanitizer_api():
    assert isinstance(sanitize_incoming, SanitizerApi)


def test_validate_config_facade_satisfies_config_validation_api():
    assert isinstance(validate_config, ConfigValidationApi)


def test_incomplete_object_fails_both_runtime_checks():
    class NotAnApi:
        pass

    assert not isinstance(NotAnApi(), SanitizerApi)
    assert not isinstance(NotAnApi(), ConfigValidationApi)


# ---------------------------------------------------------------------------
# The CLI entrypoints keep the typed seam (no drift back to Any).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("func", "expected"),
    [
        (sanitizer_cli.main, "SanitizerApi"),
        (config_validation_cli.run, "ConfigValidationApi"),
    ],
    ids=["sanitizer.cli.main", "config_validation.cli.run"],
)
def test_cli_api_parameter_is_the_protocol(func, expected):
    annotation = inspect.signature(func).parameters["api"].annotation
    assert annotation == expected, (
        f"{func.__module__}.{func.__qualname__} takes api: {annotation!r} "
        f"— the seam must stay typed as {expected}, not Any"
    )
