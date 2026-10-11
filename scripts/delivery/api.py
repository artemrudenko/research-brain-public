"""
api.py — the typed contract of the deliver.py facade.

The delivery core modules (runtime, cli, dispatch, mcp, receipt_flow,
runtime_context, runtime_status) never import the facade directly: they receive
it as an `api` argument so tests can monkeypatch facade names and so the
back-compat surface stays in one module. `DeliveryApi` is that seam's type —
every attribute the core reads off the facade, no more. Both protocols are
runtime-checkable so the test suite can assert the real deliver.py module
satisfies them; signatures here describe what the CORE needs (the facade may
accept more optional parameters).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from scripts import run_lock
    from scripts.delivery import model


@runtime_checkable
class McpReceiptsApi(Protocol):
    """The mcp_receipts module surface the delivery core drives."""

    def mcp_status(
        self,
        digest_path: Path,
        config_path: Path,
        *,
        receipt_dir: Path,
        channel_names: tuple[str, ...],
        load_config: Callable[[Path], dict[str, object]],
        load_receipt: Callable[[Path], dict[str, dict[str, str]]],
        receipt_path: Callable[[Path, Path | None], Path],
        content_hash: Callable[[str], str],
        is_agent_channel: Callable[[str, dict[str, object]], bool],
        chunk_progress: Callable[[dict[str, str]], int],
        receipt_sent: str,
        receipt_sending: str,
        reservation_lease: float,
        receipt_content_hash: str,
    ) -> int: ...

    def reserve_mcp(
        self,
        digest_path: Path,
        channel: str,
        config_path: Path,
        *,
        receipt_dir: Path,
        channel_names: tuple[str, ...],
        load_config: Callable[[Path], dict[str, object]],
        receipt_path: Callable[[Path, Path | None], Path],
        load_receipt: Callable[[Path], dict[str, dict[str, str]]],
        write_receipt: Callable[[Path, dict[str, dict[str, str]]], None],
        content_hash: Callable[[str], str],
        is_agent_channel: Callable[[str, dict[str, object]], bool],
        record: Callable[..., None],
        receipt_sent: str,
        receipt_sending: str,
        reservation_lease: float,
        receipt_content_hash: str,
        delivery_lock_name: str,
        delivery_lock_lease: float,
        delivery_in_progress_message: str,
        in_flight_message: str,
        already_delivered_message: str,
        lock_acquire: Callable[..., run_lock.AcquireResult],
        lock_release: Callable[..., bool],
    ) -> int: ...

    def record_mcp(
        self,
        digest_path: Path,
        channel: str,
        config_path: Path,
        *,
        receipt_dir: Path,
        channel_names: tuple[str, ...],
        load_config: Callable[[Path], dict[str, object]],
        receipt_path: Callable[[Path, Path | None], Path],
        load_receipt: Callable[[Path], dict[str, dict[str, str]]],
        write_receipt: Callable[[Path, dict[str, dict[str, str]]], None],
        content_hash: Callable[[str], str],
        is_agent_channel: Callable[[str, dict[str, object]], bool],
        record: Callable[..., None],
        receipt_sent: str,
        delivery_lock_name: str,
        delivery_lock_lease: float,
        delivery_in_progress_message: str,
        lock_acquire: Callable[..., run_lock.AcquireResult],
        lock_release: Callable[..., bool],
        receipt_sending: str,
        chunks_sent: int | None = ...,
    ) -> int: ...


@runtime_checkable
class DeliveryApi(Protocol):
    """Everything the delivery core reads off the deliver.py facade module.

    Constants are read-only properties so the facade's narrower inferred types
    (e.g. a 3-tuple of channel names) still satisfy the protocol.
    """

    # --- status / message constants -------------------------------------- #
    @property
    def STATUS_SKIPPED(self) -> str: ...
    @property
    def STATUS_FAILED(self) -> str: ...
    @property
    def RECEIPT_SENT(self) -> str: ...
    @property
    def RECEIPT_SENDING(self) -> str: ...
    @property
    def RECEIPT_FAILED(self) -> str: ...
    @property
    def RECEIPT_CONTENT_HASH(self) -> str: ...
    def chunk_progress(self, entry: dict[str, str]) -> int: ...
    @property
    def RESERVATION_LEASE(self) -> float: ...
    @property
    def RESERVATION_IN_FLIGHT_MESSAGE(self) -> str: ...
    @property
    def RESERVATION_ALREADY_DELIVERED_MESSAGE(self) -> str: ...
    @property
    def NO_CHANNELS_MESSAGE(self) -> str: ...
    @property
    def ALL_MCP_ONLY_MESSAGE(self) -> str: ...
    @property
    def QUIET_SKIP_MESSAGE(self) -> str: ...
    @property
    def DELIVERY_IN_PROGRESS_MESSAGE(self) -> str: ...
    @property
    def SAMPLE_MESSAGE(self) -> str: ...

    # --- lock + channel constants ----------------------------------------- #
    @property
    def DELIVERY_LOCK_NAME(self) -> str: ...
    @property
    def DELIVERY_LOCK_LEASE(self) -> float: ...
    @property
    def _CHANNELS(self) -> tuple[str, ...]: ...

    # --- paths -------------------------------------------------------------- #
    @property
    def DEFAULT_CHANNELS_CONFIG(self) -> Path: ...

    # --- model types --------------------------------------------------------- #
    @property
    def DeliveryError(self) -> type[model.DeliveryError]: ...
    @property
    def SendOutcome(self) -> type[model.SendOutcome]: ...

    # --- nested module surface ---------------------------------------------- #
    @property
    def mcp_receipts(self) -> McpReceiptsApi: ...

    # --- config / env --------------------------------------------------------- #
    def load_dotenv(self, env_path: Path | None = ...) -> None: ...
    def load_config(self, path: Path) -> dict[str, object]: ...

    # --- receipts --------------------------------------------------------------- #
    def _default_receipt_dir(self) -> Path: ...
    def receipt_path(
        self, digest_path: Path, receipt_dir: Path | None = ...
    ) -> Path: ...
    def load_receipt(self, path: Path) -> dict[str, dict[str, str]]: ...
    def write_receipt(
        self, path: Path, receipt: dict[str, dict[str, str]]
    ) -> None: ...
    def content_hash(self, text: str) -> str: ...
    def _record(
        self,
        receipt: dict[str, dict[str, str]],
        channel: str,
        status: str,
        *,
        digest_hash: str,
        reason: str | None = ...,
        chunks_sent: int | None = ...,
    ) -> None: ...

    # --- delivery lock ------------------------------------------------------- #
    def _lock_acquire(
        self,
        path: Path,
        *,
        stale_after: float,
        steal_dead: bool,
        note: str,
    ) -> run_lock.AcquireResult: ...
    def _lock_release(self, path: Path, *, token: str | None = ...) -> bool: ...

    # --- digest classification ------------------------------------------------ #
    def is_quiet_digest(self, text: str) -> bool: ...
    def _is_mcp_channel(self, channel: str, cfg: dict[str, object]) -> bool: ...
    def _is_agent_delivered_channel(
        self, channel: str, cfg: dict[str, object]
    ) -> bool: ...

    # --- channel adapters ------------------------------------------------------ #
    def _deliver_email(
        self, cfg: dict[str, object], text: str, digest_path: Path
    ) -> model.SendResult: ...
    def _deliver_telegram(
        self, cfg: dict[str, object], text: str
    ) -> model.SendResult: ...
    def _deliver_rocketchat(
        self, cfg: dict[str, object], text: str
    ) -> model.SendResult: ...
    def _dry_run_channel(self, channel: str, cfg: dict[str, object]) -> None: ...

    # --- health hooks ------------------------------------------------------------ #
    def _record_delivery_health(
        self, digest_path: Path, *, channels: set[str] | None = ...
    ) -> None: ...
    def _record_all_mcp_only_health(self, channels: list[str]) -> None: ...

    # --- top-level flows ----------------------------------------------------------- #
    def deliver(
        self,
        digest_path: Path,
        config_path: Path = ...,
        *,
        dry_run: bool = ...,
        force: bool = ...,
        skip_quiet: bool = ...,
        receipt_dir: Path | None = ...,
        attempted: set[str] | None = ...,
    ) -> int: ...
    def mcp_status(
        self,
        digest_path: Path,
        config_path: Path = ...,
        *,
        receipt_dir: Path | None = ...,
    ) -> int: ...
    def reserve_mcp(
        self,
        digest_path: Path,
        channel: str,
        config_path: Path = ...,
        *,
        receipt_dir: Path | None = ...,
    ) -> int: ...
    def record_mcp(
        self,
        digest_path: Path,
        channel: str,
        config_path: Path = ...,
        *,
        receipt_dir: Path | None = ...,
        chunks_sent: int | None = ...,
    ) -> int: ...
    def _rehearse(
        self, config_path: Path, *, allow_unsanitized: bool = ...
    ) -> int: ...


__all__ = [
    "DeliveryApi",
    "McpReceiptsApi",
]
