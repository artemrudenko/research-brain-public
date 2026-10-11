"""
rocketchat_webhook.py — post a digest to a Rocket.Chat incoming webhook.

Incoming webhooks accept an unauthenticated JSON POST with a `text` field
(Rocket.Chat renders the text as Markdown). No OAuth, no SDK — plain urllib.

SSRF hardening reuses the collector's outbound-HTTP guards
(`scripts.collection.fetch`): `is_safe_webhook_url` is a cheap OFFLINE literal
pre-check (used by the dry-run), and the real POST additionally RESOLVES the host
and refuses a non-public address (`assert_public_host`), following any redirect
through `SafeRedirectHandler` so each hop is re-validated. One hardened
implementation, shared with the feed fetcher.

Two callers, one guarded transport:
  - headless — `deliver.py` -> `channels.deliver_rocketchat` -> `send()`;
  - agentic  — the `digest-deliver` skill runs the CLI below.

CLI (called by the skill in MCP mode):
    python3 scripts/delivery/rocketchat_webhook.py --text-file <digest.md>
    <renderer> | python3 scripts/delivery/rocketchat_webhook.py --stdin

The webhook URL is read from the environment (`config/.env`), NEVER from an
argument — argv is visible in `ps`, in shell history, and in the agent's
persisted tool transcript, and the URL carries the channel's secret token. There
is deliberately no flag to pass it.
"""

import argparse
import ipaddress
import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if not __package__:  # direct script run (zip-run, no install)
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.collection.fetch import SafeRedirectHandler, assert_public_host  # noqa: E402
from scripts.delivery import config as delivery_config  # noqa: E402
from scripts.delivery import paths as delivery_paths  # noqa: E402

# Network timeout (seconds) for the webhook POST.
_TIMEOUT = 30

# Default secret name; channels.yaml may rename it via `webhook_url_env`, and the
# CLI honours that exactly as the headless dispatcher does (channels.py).
_DEFAULT_WEBHOOK_ENV = "ROCKETCHAT_WEBHOOK_URL"


def is_safe_webhook_url(webhook_url: str) -> bool:
    """True when `webhook_url` is an http(s) URL to a non-private host (SSRF guard).

    The webhook URL is operator-configured, but a typo or a tampered config could
    point the POST at the cloud-metadata endpoint (169.254.169.254), localhost, or
    an RFC1918 host — exfiltrating the digest internally. We require an http/https
    scheme with a non-empty hostname and reject any host that is an IP literal in a
    private / loopback / link-local / reserved / multicast / unspecified range. A
    plain hostname is allowed (resolving it here would need the network and would
    break the offline send path; the literal-IP check covers the metadata vector).
    Legacy numeric host encodings (decimal `2130706433`, octal `0177.0.0.1`, hex
    `0x7f000001`, partial `127.1`) are decoded via inet_aton so they can't smuggle a
    private IP past the dotted-quad check by masquerading as a hostname.
    """
    parts = urlsplit(webhook_url)
    if parts.scheme not in ("http", "https"):
        return False
    host = (parts.hostname or "").strip()
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            # inet_aton decodes the legacy numeric forms a resolver still accepts;
            # it raises OSError for a genuine DNS name, which is the allowed case.
            address = ipaddress.ip_address(socket.inet_aton(host))
        except OSError:
            return True  # a real hostname (not any IP encoding) — allowed
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _safe_opener() -> urllib.request.OpenerDirector:
    """An opener that re-validates every redirect hop (http(s)-only + public host).

    Reuses the collector's `SafeRedirectHandler`, so a webhook host that 30x-es to
    cloud metadata / localhost / an RFC1918 host is refused mid-redirect instead of
    followed by the stdlib default handler.
    """
    return urllib.request.build_opener(SafeRedirectHandler())


def _open_post(url: str, data: bytes) -> int:
    """POST `data` to `url` through the safe-redirect opener; return the status.

    Isolated so tests can monkeypatch the transport without touching the SSRF guard.
    """
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # B310: the scheme is validated by is_safe_webhook_url (send) and re-validated on
    # every redirect hop by SafeRedirectHandler, so this can't be steered off http(s).
    with _safe_opener().open(request, timeout=_TIMEOUT) as response:  # nosec B310
        return int(response.status)


def _post_json(url: str, payload: dict[str, object]) -> int:
    """POST `payload` as JSON to `url`; return the HTTP status code.

    Resolves the host and refuses a non-public address BEFORE connecting (reusing
    the collector's `assert_public_host`), closing the DNS-name / rebinding vector
    the offline literal check in `is_safe_webhook_url` cannot see. Isolated so tests
    can monkeypatch the transport.
    """
    assert_public_host(url)  # raises ValueError if the host resolves non-public
    return _open_post(url, json.dumps(payload).encode("utf-8"))


def send(text: str, *, webhook_url: str) -> bool:
    """Send `text` to a Rocket.Chat incoming webhook.

    Returns True on a 2xx response. Returns False — without sending — when the URL
    is empty or fails the SSRF safety check (`is_safe_webhook_url`), and on any
    HTTP/URL error from the POST.
    """
    if not webhook_url:
        return False
    # SSRF guard: refuse a non-http(s) URL, an empty host, or a private/loopback/
    # link-local/reserved IP host before posting (don't raise — soft-skip like the
    # rest of the delivery adapters).
    if not is_safe_webhook_url(webhook_url):
        # Redact the path/query — the webhook URL carries a secret token, and this
        # message lands in cron logs / mail spools. Show only scheme+host to diagnose.
        parts = urlsplit(webhook_url)
        safe_ref = f"{parts.scheme or '?'}://{parts.hostname or '?'}"
        print(
            f"rocketchat: refusing unsafe webhook URL {safe_ref} "
            "(must be http(s) to a public host) — skipping",
            file=sys.stderr,
        )
        return False
    try:
        status = _post_json(webhook_url, {"text": text})
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return False
    return 200 <= status < 300


def _webhook_env_name(config_path: Path) -> str:
    """The env var holding the webhook URL, honouring `webhook_url_env` overrides.

    Falls back to the default name when the config is absent or unreadable: the
    CLI's job is to send, and a missing channels.yaml should surface as the
    (actionable) missing-secret error rather than a config traceback.
    """
    try:
        cfg = delivery_config.load_config(config_path).get("rocketchat")
    except delivery_config.ConfigError:
        return _DEFAULT_WEBHOOK_ENV
    if not isinstance(cfg, dict):
        return _DEFAULT_WEBHOOK_ENV
    return str(cfg.get("webhook_url_env", _DEFAULT_WEBHOOK_ENV))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "POST a message to the configured Rocket.Chat incoming webhook, "
            "through the project's SSRF guards."
        ),
        epilog=(
            "The webhook URL comes from the environment (config/.env) — there is "
            "no flag for it, so the secret never reaches argv."
        ),
    )
    body = parser.add_mutually_exclusive_group(required=True)
    body.add_argument("--text-file", type=Path, help="file whose contents are the message body")
    body.add_argument("--stdin", action="store_true", help="read the message body from stdin")
    parser.add_argument(
        "--config",
        type=Path,
        default=delivery_paths.channels_config(_PROJECT_ROOT),
        help="channels.yaml to read `webhook_url_env` from",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=delivery_paths.env_file(_PROJECT_ROOT),
        help="dotenv file to load the secret from (default: config/.env)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Send a message body to the configured Rocket.Chat webhook. 0 on success.

    A non-zero exit means NOTHING was delivered — the caller (the digest-deliver
    skill) must not stamp the receipt for a failed send, or the digest is lost.
    """
    args = _build_parser().parse_args(argv)

    text = sys.stdin.read() if args.stdin else args.text_file.read_text(encoding="utf-8")
    if not text.strip():
        print("rocketchat: refusing to send an empty message body", file=sys.stderr)
        return 2

    delivery_config.load_dotenv(args.env_file)
    try:
        webhook_url = delivery_config.env_or_fail(
            "rocketchat", _webhook_env_name(args.config)
        )
    except delivery_config.ConfigError as error:
        print(str(error), file=sys.stderr)
        return 2

    # `send` owns the guards (scheme + literal-IP check, host resolution, redirect
    # re-validation) and prints its own redacted refusal — never re-implement them here.
    if not send(text, webhook_url=webhook_url):
        print("rocketchat: send failed — receipt NOT stamped", file=sys.stderr)
        return 1
    print("rocketchat sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
