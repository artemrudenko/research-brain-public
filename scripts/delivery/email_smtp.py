"""
email_smtp.py — send a digest by email over SMTP.

Builds a multipart message (plain-text always, HTML optional) and submits it via
STARTTLS. Host/port/user come from config; the password comes from the env.
"""

import smtplib
import ssl
import sys
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Connection timeout (seconds) for the SMTP session.
_TIMEOUT = 30

# Implicit-TLS (SMTPS) submission port: a 465 connection is TLS from the first
# byte, so it needs SMTP_SSL rather than plain SMTP + STARTTLS (which 400s/hangs).
_SMTPS_PORT = 465


@dataclass(frozen=True)
class EmailSendResult:
    """Outcome of an SMTP send.

    `ok` is the send/no-send bool contract (also exposed via `__bool__` so the
    result drops into any truthiness check). `refused` lists the recipients SMTP
    refused on an otherwise-accepted send (a PARTIAL refusal — the message WAS
    delivered to the rest); it lets the caller surface them instead of marking the
    whole channel failed and re-sending to everyone. `reason` is a short,
    secret-free diagnosis on failure (auth error vs connection refused vs bad
    recipient read very differently to the operator) — None on success.
    """

    ok: bool
    refused: list[str] = field(default_factory=list)
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.ok


def build_message(
    subject: str,
    body: str,
    *,
    sender: str,
    to: list[str],
    html: str | None = None,
) -> MIMEMultipart:
    """Construct the MIME message (plain-text + optional HTML alternative)."""
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(to)
    message.attach(MIMEText(body, "plain", "utf-8"))
    if html:
        message.attach(MIMEText(html, "html", "utf-8"))
    return message


def _smtp_send(
    host: str,
    port: int,
    user: str,
    password: str,
    sender: str,
    to: list[str],
    message: MIMEMultipart,
) -> dict[str, tuple[int, bytes]]:
    """Open an SMTP session, authenticate, and send `message`.

    Uses an explicit verified TLS context (`ssl.create_default_context()` —
    certificate + hostname verification). Port 465 is implicit TLS (SMTP_SSL);
    every other port uses plain SMTP upgraded via STARTTLS with the same context.
    Isolated so tests can monkeypatch the transport without a real server.

    Returns smtplib's per-recipient refusal map: empty when every recipient was
    accepted, else `{address: (code, reason)}` for each refused recipient.
    smtplib only RAISES (SMTPRecipientsRefused) when *all* recipients are refused;
    a partial refusal is returned, not raised, so the caller must inspect this map.
    """
    context = ssl.create_default_context()
    if port == _SMTPS_PORT:
        with smtplib.SMTP_SSL(host, port, timeout=_TIMEOUT, context=context) as server:
            server.login(user, password)
            return server.sendmail(sender, to, message.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=_TIMEOUT) as server:
            server.starttls(context=context)
            server.login(user, password)
            return server.sendmail(sender, to, message.as_string())


def send_detailed(
    subject: str,
    body: str,
    *,
    to: list[str],
    host: str,
    port: int,
    user: str,
    password: str,
    html: str | None = None,
) -> EmailSendResult:
    """Send an email digest over SMTP and report the per-recipient outcome.

    The SMTP `user` is used as the sender address. Returns an `EmailSendResult`:
    `ok=False` on any SMTP/connection error or missing params; `ok=True` otherwise,
    with `refused` carrying any partially-refused recipients (see below).
    """
    if not to or not host or not user:
        return EmailSendResult(ok=False, reason="missing recipient/host/user config")
    message = build_message(subject, body, sender=user, to=to, html=html)
    try:
        refused = _smtp_send(host, port, user, password, user, to, message)
    except (smtplib.SMTPException, OSError) as error:
        # Diagnose without secrets: exception class + its own message (smtplib
        # never echoes the password; the message is the server's reply).
        return EmailSendResult(
            ok=False, reason=f"{type(error).__name__}: {str(error)[:160]}"
        )
    # A PARTIAL refusal does not raise (smtplib only raises SMTPRecipientsRefused when
    # ALL recipients are refused): sendmail returns a non-empty `{address: (code,
    # reason)}` map while the message WAS delivered to the accepted recipients. Marking
    # the channel FAILED here would make the idempotent retry re-send to EVERYONE,
    # duplicating the digest for those who already received it. So a partial refusal is
    # a successful send (receipt records SENT, no re-send); we log the refused addresses
    # (stderr, never the password) AND return them so the dispatcher can also flag them
    # in the operator summary — a cron log then shows who to fix by hand.
    addresses = sorted(refused)
    if addresses:
        print(
            f"email: SMTP accepted the message but refused {len(addresses)} "
            f"recipient(s) (delivered to the rest): {', '.join(addresses)}",
            file=sys.stderr,
        )
    return EmailSendResult(ok=True, refused=addresses)


def send(
    subject: str,
    body: str,
    *,
    to: list[str],
    host: str,
    port: int,
    user: str,
    password: str,
    html: str | None = None,
) -> bool:
    """Send an email digest over SMTP; thin bool wrapper over `send_detailed`.

    Returns True on success (including a partial refusal — the accepted recipients
    got it), False on any SMTP/connection error or if required params are missing.
    """
    return send_detailed(
        subject, body, to=to, host=host, port=port, user=user,
        password=password, html=html,
    ).ok
