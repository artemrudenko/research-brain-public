#!/usr/bin/env python3
"""
deliver.py — headless digest dispatcher.

Reads `config/channels.yaml`, and for each channel with `enabled: true`
resolves its params + secrets (from env) and calls the matching adapter:

    email      -> email_smtp.send       (provider: smtp)
    telegram   -> telegram_botapi.send   (transport: bot-api)
    rocketchat -> rocketchat_webhook.send

Disabled channels are skipped. MCP-only channels (email provider gmail-mcp,
telegram transport mcp) are skipped here — those run through the agent skill,
not headless. Prints a per-channel status line; exits nonzero if any *enabled,
headless-capable* channel fails.

Before resolving secrets it auto-loads `config/.env` (if present) into the
environment, so a cron run does not need the secrets pre-exported.

Idempotency (CONVENTIONS §10): each run records a per-digest receipt at
`pipeline/3-synthesis/.delivered/{digest-stem}.json` mapping channel -> {status,
timestamp}. A channel already `sent` for this digest is skipped on re-run (unless
`--force`); a `failed` channel is retried. `--dry-run` neither reads nor writes a
receipt. A bounded retry covers transient transport errors inside the send path.
The agent-side MCP path shares the SAME receipt via `--mcp-status` (pre-send
check) and `--record-mcp CHANNEL` (post-send stamp), so both delivery modes are
idempotent against each other.

CLI:
    python3 scripts/delivery/deliver.py <digest_file.md> [channels.yaml]
                                        [--dry-run] [--force] [--skip-quiet]
                                        [--rehearse]

`--dry-run` resolves config + secrets and prints, per enabled channel, what
*would* be sent (transport, recipient/chat target, secret env-var name and
whether it is SET or MISSING — never the secret value) without sending
anything, exiting 0 even when secrets are missing (it is a pre-send check).
With no digest file given alongside `--dry-run`, a tiny built-in sample message
is used so a channel can be verified before the first real digest exists.

`--force` ignores the receipt and re-sends every enabled channel.

`--skip-quiet` (D7) makes a live run a no-op when the digest is a "quiet week"
one (build_digest emits these with no new sources/concepts) — so users are not
pinged weekly with "nothing new". Dry-run still reports normally.

`--rehearse` (D10) is an end-to-end pre-flight: it builds today's digest from
the configured lookback window into a temp file and dry-run-delivers it, printing
"would deliver a digest with N source(s) / M concept(s) to <channels>". Sends
nothing. Equivalent one-liner (the builder's sanitize gate is fail-closed by
default — sanitize first, or add --allow-unsanitized for controlled feeds):
    python3 scripts/sanitize_incoming.py sanitize && \
        python3 scripts/build_digest.py /tmp/d.md && \
        python3 scripts/delivery/deliver.py /tmp/d.md --dry-run
"""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from scripts.delivery.api import DeliveryApi

if not __package__:  # direct `python3 scripts/delivery/deliver.py` (zip-run, no install)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.delivery import email_html, email_smtp, rocketchat_webhook, telegram_botapi

# Back-compat: historical callers could reach adapter modules as attributes on
# `deliver`. The dispatch implementation now lives in channels.py, but keep these
# names present here.
_ADAPTER_MODULES = (email_html, email_smtp, rocketchat_webhook, telegram_botapi)

# Reuse the single-process run lock to serialize real deliveries (DEFECT #4):
# whether run as a package or as a standalone script.
# Import delivery submodules whether this file is imported as a package module or
# executed directly as `python3 scripts/delivery/deliver.py`.
from scripts.delivery import (  # noqa: E402 — after the direct-run prelude
    channels,
    constants,
    dry_run,
    health_log,
    mcp,
    mcp_receipts,
    model,
    paths,
    quiet,
    receipts,
    rehearsal,
    runtime,
)
from scripts.delivery import config as delivery_config  # noqa: E402 — after the direct-run prelude
from scripts.run_lock import acquire as _lock_acquire  # noqa: E402 — after the direct-run prelude
from scripts.run_lock import release as _lock_release  # noqa: E402 — after the direct-run prelude

# The durable-state resolver: routes the receipts dir (and its sibling
# .delivery.lock) onto a persistent volume when RESEARCH_BRAIN_STATE_DIR is set,
# else leaves it at the in-repo default. Same package/standalone import dance.
from scripts.state import state_root as _state_root  # noqa: E402 — after the direct-run prelude

# Back-compat: tests and historical callers monkeypatch `deliver.os.replace` to
# exercise receipt atomic-write failures. Receipt persistence now lives in
# receipts.py, so expose the same module object here.
os = receipts.os

# Compatibility anchors for facade-backed modules that access these names through
# `api` rather than direct references in this file.
_RUN_LOCK_FUNCS = (_lock_acquire, _lock_release)
_MCP_RECEIPTS_MODULE = mcp_receipts


def _api() -> "DeliveryApi":
    """This module, as the typed `DeliveryApi` seam the delivery core drives.

    Attribute reads through the seam happen at call time, so names tests
    monkeypatch on this module are honored. The cast is safe: the
    TYPE_CHECKING conformance assignment at the bottom of this file makes
    mypy verify the module really satisfies the protocol.
    """
    return cast("DeliveryApi", sys.modules[__name__])


# Resolve config relative to the project root (scripts/delivery/ -> root).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHANNELS_CONFIG = paths.channels_config(_PROJECT_ROOT)
# `.env` is resolved against the project root regardless of cwd (CONVENTIONS §8).
DEFAULT_ENV_FILE = paths.env_file(_PROJECT_ROOT)
# Delivery receipts live alongside the synthesis stage (CONVENTIONS §10).
# Routed through the durable-state resolver: with RESEARCH_BRAIN_STATE_DIR unset
# this is the exact in-repo path (zero change); with it set the receipts (and the
# .delivery.lock kept beside them) relocate onto a persistent volume so a redeploy
# can't lose the "already sent this digest" memory and double-send.
#
# Resolved LAZILY via `_default_receipt_dir()` below — never frozen at import.
# Sibling modules (health.py, synthesis_freshness.py) resolve their durable-state
# paths at call time, so an env set AFTER import is honored; freezing this as a
# module constant would silently ignore a runtime-wired RESEARCH_BRAIN_STATE_DIR
# and write receipts in-repo instead.


def _default_receipt_dir() -> Path:
    """The default receipts dir, resolved at CALL time (honors the env lazily).

    Routes the in-repo `pipeline/3-synthesis/.delivered` path through the
    durable-state resolver every call, so `RESEARCH_BRAIN_STATE_DIR` is read when
    a delivery actually runs — not once at import. With the env unset this is the
    exact in-repo default, byte-for-byte (pure identity); with it set the receipts
    (and the sibling `.delivery.lock`) relocate onto the persistent volume.
    """
    return paths.receipt_dir(
        _PROJECT_ROOT,
        state_root=lambda default: _state_root(default, project_root=_PROJECT_ROOT),
    )


# Back-compat module constant: the env-unset default, kept so existing callers /
# tests that reference `deliver.DEFAULT_RECEIPT_DIR` still resolve. Live paths go
# through `_default_receipt_dir()` so a late-set env is still honored.
DEFAULT_RECEIPT_DIR = _default_receipt_dir()

# Status tokens for the per-channel report line.
STATUS_SENT = constants.STATUS_SENT
STATUS_SKIPPED = constants.STATUS_SKIPPED
STATUS_FAILED = constants.STATUS_FAILED

# Receipt status values (lower-case, persisted in JSON).
RECEIPT_SENT = constants.RECEIPT_SENT
RECEIPT_FAILED = constants.RECEIPT_FAILED
# `sending` is a RESERVATION written before the agent's external send, so a
# concurrent sender is refused instead of duplicating the delivery.
RECEIPT_SENDING = constants.RECEIPT_SENDING
RESERVATION_LEASE = constants.RESERVATION_LEASE
RESERVATION_IN_FLIGHT_MESSAGE = constants.RESERVATION_IN_FLIGHT_MESSAGE
RESERVATION_ALREADY_DELIVERED_MESSAGE = constants.RESERVATION_ALREADY_DELIVERED_MESSAGE

# Per-channel receipt field carrying the digest content hash that was delivered.
# Lets a same-day rebuild with CHANGED content re-send (the stored hash no longer
# matches) while an unchanged re-run still skips (BUG: content-blind idempotency).
# Optional in older receipts — load_receipt tolerates its absence.
RECEIPT_CONTENT_HASH = receipts.RECEIPT_CONTENT_HASH
# Resume point for an interrupted chunked send (see receipts.record).
chunk_progress = receipts.chunk_progress

# Delivery concurrency guard (DEFECT #4). The content-hash + per-channel receipt
# stop a *sequential* re-run from re-sending, but two *concurrent* deliveries can
# both read an empty receipt and send the same digest twice. A short-lived lock
# (sibling of the receipts) serializes real deliveries: `steal_dead` reclaims a
# crashed delivery's lock immediately, while the lease only bounds one that is
# genuinely still running. Dry-run never locks.
DELIVERY_LOCK_NAME = constants.DELIVERY_LOCK_NAME
DELIVERY_LOCK_LEASE = constants.DELIVERY_LOCK_LEASE
DELIVERY_IN_PROGRESS_MESSAGE = constants.DELIVERY_IN_PROGRESS_MESSAGE

# The KNOWN agent-side (MCP) values per channel. These SKIP in a headless run
# (handled by the agent skill). Any OTHER non-headless value is a config typo and
# must be reported as an error, not silently dropped as MCP-only (BUG M4).
_EMAIL_HEADLESS_PROVIDER = constants.EMAIL_HEADLESS_PROVIDER
_EMAIL_MCP_PROVIDER = constants.EMAIL_MCP_PROVIDER
_TELEGRAM_HEADLESS_TRANSPORT = constants.TELEGRAM_HEADLESS_TRANSPORT
_TELEGRAM_MCP_TRANSPORT = constants.TELEGRAM_MCP_TRANSPORT


SendOutcome = model.SendOutcome

# Bounded retry on transient transport errors (one extra attempt — no new deps).
_MAX_SEND_ATTEMPTS = constants.MAX_SEND_ATTEMPTS

# No-op message — kept identical to the digest-deliver skill/acceptance wording.
NO_CHANNELS_MESSAGE = constants.NO_CHANNELS_MESSAGE

# Printed when a live (non-dry-run) headless run had enabled channels but EVERY one
# resolved to an MCP-only transport, so the deterministic adapters sent nothing and
# the run would otherwise exit 0 — reading as success to cron. In agent/MCP mode an
# all-MCP skip is expected (the digest-deliver skill performs the real send via MCP),
# so this is informational only and does NOT change the exit code.
ALL_MCP_ONLY_MESSAGE = constants.ALL_MCP_ONLY_MESSAGE

# Printed (and the run no-ops) when --skip-quiet sees a quiet-week digest, so a
# cron log shows why nothing was delivered. Mirrors build_digest's quiet output.
QUIET_SKIP_MESSAGE = constants.QUIET_SKIP_MESSAGE

# Quiet-digest constants are re-exported for the existing delivery module API.
_QUIET_DIGEST_MARKERS = quiet.QUIET_DIGEST_MARKERS
QUIET_DIGEST_HTML_MARKER = quiet.QUIET_DIGEST_HTML_MARKER

# Built-in sample used by --dry-run when no real digest file is supplied, so a
# user can verify a channel is wired up before the first digest exists.
SAMPLE_MESSAGE = constants.SAMPLE_MESSAGE


DeliveryError = model.DeliveryError

_strip_frontmatter = quiet.strip_frontmatter
is_quiet_digest = quiet.is_quiet_digest
parse_dotenv = delivery_config.parse_dotenv


def load_dotenv(env_path: Path | None = None) -> None:
    """Load `env_path` into os.environ without overriding already-set vars.

    A no-op if the file does not exist (the `.env` is optional). Existing
    environment values always take precedence over file values.
    """
    delivery_config.load_dotenv(DEFAULT_ENV_FILE if env_path is None else env_path)


def receipt_path(digest_path: Path, receipt_dir: Path | None = None) -> Path:
    """Return the receipt JSON path for a digest (stem == filename sans extension).

    `receipt_dir` defaults to the lazily-resolved durable-state dir so a late-set
    `RESEARCH_BRAIN_STATE_DIR` is honored (not the import-time path).
    """
    return receipts.receipt_path(digest_path, receipt_dir or _default_receipt_dir())


load_receipt = receipts.load_receipt
write_receipt = receipts.write_receipt
content_hash = receipts.content_hash
_record = receipts.record


def _send_with_retry(send_fn: Callable[[], bool]) -> bool:
    """Call a zero-arg send closure with one bounded retry on a transient failure.

    The adapters return False (rather than raising) on any transport error, so a
    transient timeout / 5xx looks identical to a hard failure here; we simply give
    one extra attempt. A success short-circuits; no sleep keeps it dependency-free
    and fast under test.
    """
    return channels.send_with_retry(send_fn, attempts=_MAX_SEND_ATTEMPTS)


def _require_yaml() -> Any:  # Any: optional-dependency boundary (PyYAML)
    """Import PyYAML lazily; raise a clear, actionable error if it is missing."""
    try:
        return delivery_config.require_yaml()
    except delivery_config.ConfigError as error:
        raise DeliveryError(str(error)) from error


def load_config(path: Path) -> dict[str, object]:
    """Load and return the `delivery` mapping from a channels.yaml file."""
    try:
        return delivery_config.load_config(path)
    except delivery_config.ConfigError as error:
        raise DeliveryError(str(error)) from error


def _env_or_fail(channel: str, env_var: str) -> str:
    """Read a required env var; raise an actionable error when it is absent/empty."""
    try:
        return delivery_config.env_or_fail(channel, env_var)
    except delivery_config.ConfigError as error:
        raise DeliveryError(str(error)) from error


_email_subject = channels.email_subject


def _deliver_email(
    cfg: dict[str, object], text: str, digest_path: Path
) -> model.SendResult:
    """Dispatch the email channel; (SENT/FAILED/SKIPPED, failure reason)."""
    try:
        status, reason = channels.deliver_email(
            cfg,
            text,
            digest_path,
            env_or_fail=_env_or_fail,
            retry=_send_with_retry,
        )
        return SendOutcome(status), reason
    except channels.ChannelError as error:
        raise DeliveryError(str(error)) from error


def _deliver_telegram(
    cfg: dict[str, object], text: str
) -> model.SendResult:
    """Dispatch the telegram channel; (SENT/FAILED/SKIPPED, failure reason)."""
    try:
        status, reason = channels.deliver_telegram(cfg, text, env_or_fail=_env_or_fail)
        return SendOutcome(status), reason
    except channels.ChannelError as error:
        raise DeliveryError(str(error)) from error


def _deliver_rocketchat(
    cfg: dict[str, object], text: str
) -> model.SendResult:
    """Dispatch the Rocket.Chat webhook channel; (SENT/FAILED, failure reason)."""
    try:
        status, reason = channels.deliver_rocketchat(
            cfg, text, env_or_fail=_env_or_fail, retry=_send_with_retry
        )
        return SendOutcome(status), reason
    except channels.ChannelError as error:
        raise DeliveryError(str(error)) from error


# The channel names, in delivery order. Dispatch itself is per-channel in
# dispatch.py (email needs the digest path for the subject, so the adapters
# keep distinct signatures).
_CHANNELS = constants.CHANNELS


_secret_state = delivery_config.secret_state


def _dry_run_channel(channel: str, cfg: dict[str, object]) -> None:
    """Print what an enabled channel *would* send, resolving no secrets to send.

    Skips MCP-only transports with a note (matching the live path), and for
    headless transports prints the target plus the secret env-var name and its
    SET/MISSING state — but never the secret value.
    """
    dry_run.dry_run_channel(channel, cfg, secret_state=_secret_state)


def deliver(
    digest_path: Path,
    config_path: Path = DEFAULT_CHANNELS_CONFIG,
    *,
    dry_run: bool = False,
    force: bool = False,
    skip_quiet: bool = False,
    receipt_dir: Path | None = None,
    attempted: set[str] | None = None,
) -> int:
    """Deliver `digest_path` to every enabled, headless-capable channel.

    Returns an exit code: 0 if all enabled channels succeeded (or were skipped),
    1 if any enabled channel failed or hit a config/secret error.

    Idempotent (CONVENTIONS §10): a per-digest receipt records each channel's
    status. A channel already `sent` for this digest is skipped (unless `force`);
    a `failed` channel is retried. The receipt is updated after each live send.

    With `dry_run=True` nothing is sent and no receipt is read or written: each
    enabled channel is reported with the target and its secret's SET/MISSING
    state, and the call always exits 0 (a pre-send check never fails on a missing
    secret). With `force=True` the receipt is ignored and every enabled channel
    is (re-)sent.
    """
    return runtime.deliver(
        digest_path,
        config_path,
        dry_run=dry_run,
        force=force,
        skip_quiet=skip_quiet,
        receipt_dir=receipt_dir,
        attempted=attempted,
        api=_api(),
    )


def _is_mcp_channel(channel: str, cfg: dict[str, Any]) -> bool:
    """True when this enabled channel is configured for the agent-side MCP
    transport (the headless adapters SKIP it; the digest-deliver skill sends)."""
    return channels.is_mcp_channel(channel, cfg)


def _is_agent_delivered_channel(channel: str, cfg: dict[str, Any]) -> bool:
    """True when the agent skill sends this channel in MCP mode — the MCP
    transports PLUS Rocket.Chat's webhook. Drives who owns the receipt (record-mcp
    / mcp-status); the headless send-skip still uses `_is_mcp_channel`."""
    return channels.is_agent_delivered_channel(channel, cfg)


def mcp_status(
    digest_path: Path,
    config_path: Path = DEFAULT_CHANNELS_CONFIG,
    *,
    receipt_dir: Path | None = None,
) -> int:
    """Report each enabled MCP channel's receipt state for `digest_path`.

    The MCP send is performed by the digest-deliver skill, but idempotency must
    live in ONE place — the same `.delivered/{stem}.json` the headless path
    uses. The skill calls this before sending: a channel already recorded for
    this exact content prints DELIVERED (skip it); anything else prints PENDING
    (send it, then stamp with `record_mcp`). A recorded hash that no longer
    matches the digest (same-name rebuild) reads PENDING again.
    """
    return mcp.mcp_status(
        digest_path,
        config_path,
        receipt_dir=receipt_dir or _default_receipt_dir(),
        api=_api(),
    )


def reserve_mcp(
    digest_path: Path,
    channel: str,
    config_path: Path = DEFAULT_CHANNELS_CONFIG,
    *,
    receipt_dir: Path | None = None,
) -> int:
    """Claim `channel` for `digest_path` BEFORE the agent performs the send.

    Exit 0 means the caller owns the channel and may send. Any non-zero exit
    means it must not: another sender holds it (4), it is already delivered (3),
    the delivery lock is busy (1), or the channel is not the agent's to send (2).
    The check and the claim share one `.delivery.lock` critical section, so two
    agents that both see PENDING cannot both proceed to send.
    """
    return mcp.reserve_mcp(
        digest_path,
        channel,
        config_path,
        receipt_dir=receipt_dir or _default_receipt_dir(),
        api=_api(),
    )


def record_mcp(
    digest_path: Path,
    channel: str,
    config_path: Path = DEFAULT_CHANNELS_CONFIG,
    *,
    receipt_dir: Path | None = None,
    chunks_sent: int | None = None,
) -> int:
    """Stamp `channel` as delivered for `digest_path` in the shared receipt.

    Called by the digest-deliver skill immediately after a successful MCP send,
    so a re-run of the skill (or a later headless pass) sees the channel as
    already delivered instead of re-sending. Refuses (exit 2) for a channel the
    headless adapters own — its receipt must only ever be stamped by a real
    send. Takes the same `.delivery.lock` as live deliveries so a concurrent
    headless run can't interleave with the receipt write.
    """
    return mcp.record_mcp(
        digest_path,
        channel,
        config_path,
        receipt_dir=receipt_dir or _default_receipt_dir(),
        api=_api(),
        chunks_sent=chunks_sent,
    )


def _rehearse(config_path: Path, *, allow_unsanitized: bool = False) -> int:
    """D10: build today's digest into a temp file, then dry-run-deliver it.

    A one-command end-to-end smoke test the user can run before the first real
    send: it builds the deterministic digest from the configured lookback window
    and prints what *would* be delivered (channels + secret state) without
    sending anything. Returns the dry-run exit code (0 on a check).
    """
    return rehearsal.rehearse(
        config_path,
        allow_unsanitized=allow_unsanitized,
        project_root=_PROJECT_ROOT,
        deliver_func=deliver,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry: `deliver.py <digest_file.md> [channels.yaml] [flags]`.

    Flags: `--dry-run`, `--force`, `--skip-quiet` (no-op on a quiet-week digest),
    `--rehearse` (build today's digest + dry-run-deliver it, end-to-end).
    """
    from scripts.delivery import cli as delivery_cli  # noqa: PLC0415 — lazy: CLI-only seam

    return delivery_cli.main(argv, api=_api())


def _record_delivery_health(
    digest_path: Path, *, channels: set[str] | None = None
) -> None:
    """Append one health event per channel ATTEMPTED this run, from the receipt.

    Reads the just-written receipt and mirrors each channel's status into the
    append-only health log. `channels` limits recording to the channels actually
    attempted/sent this run, so an idempotent re-run (which skips already-delivered
    channels) does not re-log a health event for them (BUG L5). When `channels`
    is None, every channel in the receipt is recorded (the legacy behaviour).
    Best-effort: any failure (missing module, bad path) is swallowed so it can
    never affect the exit code of a real delivery.
    """
    health_log.record_delivery_health(
        digest_path,
        channels=channels,
        project_root=_PROJECT_ROOT,
        receipt_dir=_default_receipt_dir(),
        load_receipt=load_receipt,
        receipt_path=receipt_path,
    )


def _record_all_mcp_only_health(channels: list[str]) -> None:
    """Log the delivered-to-nobody run: every enabled channel was MCP-only.

    Status "skipped-mcp-only" counts as a FAILURE_STATUSES member, so health
    turns DEGRADED and the watchdog pings instead of a forever-green silence.
    The agent-mode skill overwrites it with `sent` after the real MCP send.
    Best-effort, like every health hook here."""
    health_log.record_channel_statuses(
        channels, status="skipped-mcp-only", project_root=_PROJECT_ROOT
    )


if TYPE_CHECKING:
    # Static conformance check: mypy verifies this module satisfies DeliveryApi,
    # so the cast inside `_api()` can never hide facade drift. Zero runtime cost.
    import scripts.delivery.deliver as _facade_for_typecheck

    _API_CONFORMANCE: DeliveryApi = _facade_for_typecheck


if __name__ == "__main__":
    sys.exit(main())
