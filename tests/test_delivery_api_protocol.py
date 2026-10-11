"""
test_delivery_api_protocol.py — the delivery core's `api` seam is typed.

The core modules (runtime, cli, dispatch, mcp, receipt_flow, runtime_context,
runtime_status) receive the deliver.py facade module as `api`. That seam used to
be `api: Any`; it is now the `DeliveryApi` Protocol, so mypy verifies every
attribute the core reads off the facade, and this suite guards the contract at
runtime: the facade must satisfy the protocol, and no core entrypoint may drift
back to `Any`.
"""

import inspect

import pytest

from scripts.delivery import (
    cli,
    deliver,
    dispatch,
    mcp,
    receipt_flow,
    runtime,
    runtime_context,
    runtime_status,
)
from scripts.delivery.api import DeliveryApi, McpReceiptsApi

# ---------------------------------------------------------------------------
# The facade satisfies the protocol (runtime structural check).
# ---------------------------------------------------------------------------


def test_deliver_facade_satisfies_delivery_api():
    """deliver.py (the module passed as `api`) carries every protocol member."""
    assert isinstance(deliver, DeliveryApi)


def test_mcp_receipts_module_satisfies_mcp_receipts_api():
    """The facade's mcp_receipts attribute carries the nested surface."""
    assert isinstance(deliver.mcp_receipts, McpReceiptsApi)


def test_incomplete_object_fails_the_runtime_check():
    """The protocol check is not vacuous — a bare object must fail it."""

    class NotAnApi:
        pass

    assert not isinstance(NotAnApi(), DeliveryApi)


# ---------------------------------------------------------------------------
# No core entrypoint drifts back to `api: Any`.
# ---------------------------------------------------------------------------

_CORE_API_FUNCTIONS = [
    cli.main,
    dispatch.dispatch_channel,
    mcp.mcp_status,
    mcp.record_mcp,
    receipt_flow.ReceiptFlow.already_delivered,
    receipt_flow.ReceiptFlow.record_status,
    receipt_flow.ReceiptFlow.record_outcome,
    receipt_flow.ReceiptFlow.flush_best_effort,
    receipt_flow.ReceiptFlow.finalize,
    receipt_flow.start_receipt_flow,
    runtime.deliver,
    runtime_context.acquire_delivery_lock,
    runtime_context.release_delivery_lock,
    runtime_status.report_final_status,
]


@pytest.mark.parametrize(
    "func", _CORE_API_FUNCTIONS, ids=lambda f: f"{f.__module__}.{f.__qualname__}"
)
def test_core_api_parameter_is_the_protocol(func):
    """Every `api` parameter in the delivery core is annotated DeliveryApi."""
    annotation = inspect.signature(func).parameters["api"].annotation
    assert annotation == "DeliveryApi", (
        f"{func.__module__}.{func.__qualname__} takes api: {annotation!r} "
        "— the seam must stay typed as DeliveryApi, not Any"
    )
