"""
test_delivery.py — offline tests for the headless delivery module.

All network/SMTP I/O is monkeypatched; nothing here touches a real server.
Covers each adapter (payload/URL building, 2xx->True, error->False), Telegram
chunking, and the deliver.py dispatcher (skip disabled, missing secret, fixture
channels.yaml).
"""

import os
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# Make `scripts` importable as a package root (tests run from project root).
_PROJECT_ROOT = Path(__file__).resolve().parents[1]

from scripts.delivery import deliver, email_smtp, rocketchat_webhook, telegram_botapi
from scripts.delivery import receipts as receipts_mod

# Skip the whole module cleanly if PyYAML is unavailable in this interpreter.
pytest.importorskip("yaml", reason="PyYAML required for dispatcher config tests")


@pytest.fixture(autouse=True)
def _isolate_state_env(monkeypatch, tmp_path):
    """Relocate ALL durable runtime state (receipts + the health event log) onto a
    per-test tmp dir so this in-repo suite is hermetic.

    Both the receipts dir and the health log resolve via RESEARCH_BRAIN_STATE_DIR
    (scripts/state.py). Pointing it at a throwaway dir means a delivery run's
    best-effort health write (`record_delivery_health`, `project_root=_PROJECT_ROOT`)
    lands under tmp, never in the repo's real `pipeline/.health/events.jsonl` that
    doctor + delivery-status history read. (Deleting the var instead — the previous
    behaviour — left the health log resolving to that real in-repo path, so every
    delivering test forged rows into it: review 2026-07-22, P2.)

    A developer who has the var exported in their shell still sees this suite pass.
    The relocation-specific tests below re-set it explicitly: `delenv` for the
    unset-default case, or their own dir — overriding this default for their
    duration (monkeypatch undoes in LIFO order).
    """
    monkeypatch.setenv("RESEARCH_BRAIN_STATE_DIR", str(tmp_path / "state"))


def test_health_log_is_isolated_from_real_project(tmp_path):
    """Regression (review 2026-07-22, P2): a delivery run's best-effort health
    write (`record_delivery_health`, `project_root=_PROJECT_ROOT`) must NOT land
    in the repo's real `pipeline/.health/events.jsonl` — doctor + delivery-status
    history read that file, and a test suite must never forge its rows.

    The autouse `_isolate_state_env` fixture relocates ALL durable state onto a
    per-test tmp dir via RESEARCH_BRAIN_STATE_DIR; assert the health log resolves
    there and not under the real project root.
    """
    from scripts.health_checks.events import events_path

    resolved = events_path(deliver._PROJECT_ROOT)
    assert not resolved.is_relative_to(deliver._PROJECT_ROOT), (
        "the health event log must be relocated off the real project during "
        "delivery tests; got an in-repo path that a delivery run would pollute"
    )


# --------------------------------------------------------------------------- #
# Rocket.Chat webhook adapter
# --------------------------------------------------------------------------- #


def test_rocketchat_builds_payload_and_returns_true(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return 200

    monkeypatch.setattr(rocketchat_webhook, "_post_json", fake_post)
    assert rocketchat_webhook.send("hello", webhook_url="https://rc.example/hooks/x")
    assert captured["url"] == "https://rc.example/hooks/x"
    assert captured["payload"] == {"text": "hello"}


def test_rocketchat_returns_false_on_error(monkeypatch):
    def boom(url, payload):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(rocketchat_webhook, "_post_json", boom)
    assert rocketchat_webhook.send("hi", webhook_url="https://rc.example/hooks/x") is False


def test_rocketchat_false_on_non_2xx(monkeypatch):
    monkeypatch.setattr(rocketchat_webhook, "_post_json", lambda url, payload: 500)
    assert rocketchat_webhook.send("hi", webhook_url="https://rc.example/hooks/x") is False


def test_rocketchat_refuses_host_that_resolves_to_private_ip(monkeypatch):
    # A public-LOOKING DNS name that the resolver maps to a private address — the
    # DNS-rebinding / internal-name vector the literal-IP check alone missed. The
    # webhook must reuse the collector's resolve-then-check SSRF guard and refuse
    # BEFORE POSTing.
    from scripts.collection import fetch

    monkeypatch.setattr(
        fetch.socket, "getaddrinfo",
        lambda host, *a, **k: [(2, 1, 6, "", ("10.0.0.5", 0))],  # resolves private
    )
    posted: list[str] = []
    monkeypatch.setattr(rocketchat_webhook, "_open_post", lambda url, data: posted.append(url) or 200)
    assert rocketchat_webhook.send("hi", webhook_url="https://rebind.example/hooks/x") is False
    assert posted == [], "must refuse before POSTing"


def test_rocketchat_sends_when_host_resolves_public(monkeypatch):
    # The mirror case: a host resolving to a public address passes the resolve guard.
    from scripts.collection import fetch

    monkeypatch.setattr(
        fetch.socket, "getaddrinfo",
        lambda host, *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],  # public
    )
    monkeypatch.setattr(rocketchat_webhook, "_open_post", lambda url, data: 200)
    assert rocketchat_webhook.send("hi", webhook_url="https://rc.example/hooks/x") is True


def test_rocketchat_post_uses_safe_redirect_opener():
    # Redirects must be re-validated per hop (a public host 30x-ing to metadata /
    # localhost). Prove the POST opener carries the collector's SafeRedirectHandler
    # rather than the stdlib default that would follow such a hop.
    from scripts.collection.fetch import SafeRedirectHandler

    opener = rocketchat_webhook._safe_opener()
    assert any(isinstance(h, SafeRedirectHandler) for h in opener.handlers)


def test_rocketchat_false_on_empty_url():
    assert rocketchat_webhook.send("hi", webhook_url="") is False


def test_rocketchat_rejects_non_http_scheme(monkeypatch, capsys):
    # SSRF guard: a file:// (or any non-http(s)) URL must be refused before any POST.
    def must_not_post(url, payload):
        raise AssertionError("_post_json must not run for a rejected URL")

    monkeypatch.setattr(rocketchat_webhook, "_post_json", must_not_post)
    assert rocketchat_webhook.send("hi", webhook_url="file:///etc/passwd") is False
    assert "rocketchat" in capsys.readouterr().err.lower()


def test_rocketchat_refusal_redacts_secret_token_from_stderr(monkeypatch, capsys):
    # A self-hosted Rocket.Chat on a private IP fails the SSRF check; the refusal
    # message must NOT leak the token-bearing path/query into the cron log — only the
    # scheme+host are safe to print.
    def must_not_post(url, payload):
        raise AssertionError("_post_json must not run for a rejected URL")

    monkeypatch.setattr(rocketchat_webhook, "_post_json", must_not_post)
    secret_url = "https://10.0.4.7/hooks/abc123/SECRETTOKEN"
    assert rocketchat_webhook.send("hi", webhook_url=secret_url) is False
    err = capsys.readouterr().err
    assert "SECRETTOKEN" not in err
    assert "abc123" not in err
    assert "10.0.4.7" in err  # the host is fine to show for diagnosis


def test_rocketchat_rejects_private_ip_host(monkeypatch, capsys):
    # SSRF guard: an https URL whose host is a private/loopback/link-local/reserved
    # IP literal (here the cloud-metadata address) must be refused without posting.
    def must_not_post(url, payload):
        raise AssertionError("_post_json must not run for a rejected URL")

    monkeypatch.setattr(rocketchat_webhook, "_post_json", must_not_post)
    for bad in (
        "https://169.254.169.254/hooks/x",  # link-local cloud metadata
        "https://127.0.0.1/hooks/x",        # loopback
        "https://10.0.0.5/hooks/x",         # RFC1918 private
        "https://[::1]/hooks/x",            # IPv6 loopback
    ):
        assert rocketchat_webhook.send("hi", webhook_url=bad) is False
    assert "rocketchat" in capsys.readouterr().err.lower()


def test_rocketchat_rejects_numeric_ip_encodings(monkeypatch, capsys):
    # SSRF guard hardening: legacy numeric host encodings (decimal, octal, hex,
    # partial dotted) that resolvers still decode to a private IP must be refused —
    # they used to slip through as "hostnames" because ipaddress.ip_address rejects
    # the integer-string form.
    def must_not_post(url, payload):
        raise AssertionError("_post_json must not run for a rejected URL")

    monkeypatch.setattr(rocketchat_webhook, "_post_json", must_not_post)
    for bad in (
        "https://2130706433/hooks/x",   # decimal form of 127.0.0.1
        "https://0177.0.0.1/hooks/x",   # octal form of 127.0.0.1
        "https://0x7f000001/hooks/x",   # hex form of 127.0.0.1
        "https://127.1/hooks/x",        # partial dotted form of 127.0.0.1
    ):
        assert rocketchat_webhook.send("hi", webhook_url=bad) is False
    assert "rocketchat" in capsys.readouterr().err.lower()


def test_rocketchat_rejects_url_with_no_host(monkeypatch):
    def must_not_post(url, payload):
        raise AssertionError("_post_json must not run for a rejected URL")

    monkeypatch.setattr(rocketchat_webhook, "_post_json", must_not_post)
    assert rocketchat_webhook.send("hi", webhook_url="https:///hooks/x") is False


def test_rocketchat_allows_public_host(monkeypatch):
    # A normal public webhook host still posts (the guard must not over-reject).
    captured: dict[str, object] = {}

    def fake_post(url, payload):
        captured["url"] = url
        return 200

    monkeypatch.setattr(rocketchat_webhook, "_post_json", fake_post)
    assert rocketchat_webhook.send("hi", webhook_url="https://rc.example/hooks/x")
    assert captured["url"] == "https://rc.example/hooks/x"


# --------------------------------------------------------------------------- #
# Telegram Bot API adapter
# --------------------------------------------------------------------------- #


def test_telegram_builds_url_and_returns_true(monkeypatch):
    calls: list[tuple[str, str, str]] = []

    def fake_send(token, chat_id, text, *, parse_mode=None):
        calls.append((token, chat_id, text))
        return 200

    monkeypatch.setattr(telegram_botapi, "_post_send_message", fake_send)
    assert telegram_botapi.send("digest", token="T", chat_id="42")
    assert calls == [("T", "42", "digest")]


def test_telegram_returns_false_on_error(monkeypatch):
    def boom(token, chat_id, text, *, parse_mode=None):
        raise OSError("network")

    monkeypatch.setattr(telegram_botapi, "_post_send_message", boom)
    assert telegram_botapi.send("x", token="T", chat_id="42") is False


def test_telegram_false_on_missing_token_or_chat():
    assert telegram_botapi.send("x", token="", chat_id="42") is False
    assert telegram_botapi.send("x", token="T", chat_id="") is False


def test_telegram_chunking_for_long_text(monkeypatch):
    sent_chunks: list[str] = []

    def fake_send(token, chat_id, text, *, parse_mode=None):
        sent_chunks.append(text)
        return 200

    monkeypatch.setattr(telegram_botapi, "_post_send_message", fake_send)
    # 10 paragraphs of 1000 chars each -> well over the 4096 limit.
    long_text = "\n\n".join("A" * 1000 for _ in range(10))
    assert telegram_botapi.send(long_text, token="T", chat_id="42")
    assert len(sent_chunks) > 1
    assert all(len(c) <= telegram_botapi.TELEGRAM_MAX_CHARS for c in sent_chunks)


def test_telegram_chunk_text_short_is_single():
    assert telegram_botapi.chunk_text("short") == ["short"]


def test_telegram_chunk_text_hard_cut_no_boundaries():
    text = "B" * (telegram_botapi.TELEGRAM_MAX_CHARS + 100)
    chunks = telegram_botapi.chunk_text(text)
    assert len(chunks) == 2
    assert all(len(c) <= telegram_botapi.TELEGRAM_MAX_CHARS for c in chunks)


def test_telegram_chunk_text_does_not_orphan_markdown_header():
    # A section header whose body overflows the limit, and whose only blank line
    # sits right after the header, must keep the header WITH its first body lines
    # — never split into a header-only chunk (regression: the "Updated concepts"
    # heading was delivered as its own near-empty Telegram message).
    header = "## Updated concepts"
    body = "\n".join(f"- item {i}: " + "x" * 200 for i in range(60))
    chunks = telegram_botapi.chunk_text(header + "\n\n" + body)
    assert len(chunks) > 1
    assert chunks[0].startswith(header)
    assert "item 0" in chunks[0]  # body travels with the header


def test_telegram_chunk_text_does_not_orphan_rendered_header():
    # Same guard on the real (rendered-HTML) path: a `<b>` header line preceded
    # by the section divider, followed by an overflowing body, stays attached.
    header = f"{telegram_botapi._TG_DIVIDER}\n<b>UPDATED CONCEPTS</b>"
    body = "\n".join(f"• item {i}: " + "y" * 200 for i in range(60))
    chunks = telegram_botapi.chunk_text(header + "\n\n" + body)
    assert len(chunks) > 1
    assert "item 0" in chunks[0]


def test_telegram_payload_has_no_parse_mode_by_default(monkeypatch):
    # D3: plain text is the safe default — the payload must omit parse_mode so a
    # heading-heavy digest never trips legacy Markdown (V1) HTTP 400 parse errors.
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = request.data.decode("utf-8")

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp()

    monkeypatch.setattr(telegram_botapi.urllib.request, "urlopen", fake_urlopen)
    assert telegram_botapi.send("plain body", token="T", chat_id="42")
    assert "parse_mode" not in captured["body"]


def test_telegram_title_with_lone_asterisk_still_sends(monkeypatch):
    # D3: an unbalanced `*` in a title used to 400 under Markdown V1; with plain
    # text (no parse_mode) it sends fine.
    sent: list[str] = []
    monkeypatch.setattr(
        telegram_botapi, "_post_send_message",
        lambda token, chat_id, text, *, parse_mode=None: sent.append(text) or 200,
    )
    assert telegram_botapi.send("# Heading with a lone * here", token="T", chat_id="42")
    assert sent == ["# Heading with a lone * here"]


def test_telegram_opt_in_parse_mode_is_forwarded(monkeypatch):
    # A caller can still opt into MarkdownV2 once the body is escaped for it.
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        telegram_botapi, "_post_send_message",
        lambda token, chat_id, text, *, parse_mode=None: captured.update(pm=parse_mode) or 200,
    )
    assert telegram_botapi.send("x", token="T", chat_id="42", parse_mode="MarkdownV2")
    assert captured["pm"] == "MarkdownV2"


def test_telegram_protocol_relative_url_is_rejected():
    # A scheme-less `//host/...` URL (protocol-relative) must not become a clickable
    # href — only relative paths/fragments and explicit http(s)/mailto links are safe.
    assert telegram_botapi._is_safe_href("//evil.com/x") is False
    assert telegram_botapi._is_safe_href("/relative/path") is True
    assert telegram_botapi._is_safe_href("#fragment") is True
    assert telegram_botapi._is_safe_href("https://good.example/x") is True


def test_telegram_protocol_relative_link_renders_plain_text():
    html = telegram_botapi.markdown_to_telegram_html("[click me](//evil.com/x)")
    assert "//evil.com" not in html
    assert "<a " not in html
    assert "click me" in html


def test_telegram_chunk_honors_retry_after_on_429(monkeypatch):
    # A 429 rate-limit is the dominant cause of a mid-sequence chunk failure (which,
    # since the whole message restarts on the next run, double-sends earlier chunks).
    # Honoring the Retry-After header before the retry lets the burst clear so the
    # single call completes — no partial state, no cross-run duplicate.
    import email.message
    import urllib.error

    slept: list[float] = []
    monkeypatch.setattr(telegram_botapi, "_SLEEP", lambda s: slept.append(s), raising=False)

    calls = {"n": 0}

    def fake(token, chat_id, text, *, parse_mode=None):
        calls["n"] += 1
        if calls["n"] == 1:
            hdrs = email.message.Message()
            hdrs["Retry-After"] = "3"
            raise urllib.error.HTTPError(
                "https://api.telegram.org", 429, "Too Many Requests", hdrs, None
            )
        return 200

    monkeypatch.setattr(telegram_botapi, "_post_send_message", fake)
    assert telegram_botapi.send("short body", token="T", chat_id="42") is True
    assert slept == [3.0]


def test_telegram_retry_after_is_capped(monkeypatch):
    # A hostile/broken server could send an enormous Retry-After; the wait is capped
    # so it can never hold the delivery lock for an unbounded time.
    import email.message
    import urllib.error

    slept: list[float] = []
    monkeypatch.setattr(telegram_botapi, "_SLEEP", lambda s: slept.append(s), raising=False)

    calls = {"n": 0}

    def fake(token, chat_id, text, *, parse_mode=None):
        calls["n"] += 1
        if calls["n"] == 1:
            hdrs = email.message.Message()
            hdrs["Retry-After"] = "99999"
            raise urllib.error.HTTPError(
                "https://api.telegram.org", 429, "Too Many Requests", hdrs, None
            )
        return 200

    monkeypatch.setattr(telegram_botapi, "_post_send_message", fake)
    assert telegram_botapi.send("short body", token="T", chat_id="42") is True
    assert slept and slept[0] <= 30.0


def test_telegram_false_if_a_chunk_fails(monkeypatch):
    # First physical post succeeds, every subsequent attempt fails — so even after
    # the bounded per-chunk retry a later chunk cannot be delivered -> overall False.
    states = iter([200] + [500] * 10)
    monkeypatch.setattr(
        telegram_botapi, "_post_send_message",
        lambda t, c, x, *, parse_mode=None: next(states),
    )
    long_text = "\n\n".join("A" * 1000 for _ in range(10))
    assert telegram_botapi.send(long_text, token="T", chat_id="42") is False


def test_telegram_chunk_retry_resumes_not_restarts(monkeypatch):
    # CRITICAL: a transient failure on chunk 2 of 3 must retry ONLY chunk 2 — it
    # must never resend chunk 1 (the old code returned False on the first failure
    # and deliver.py restarted send() from chunk 1, re-delivering earlier chunks).
    # Three blocks each just under the limit -> exactly three chunks.
    block = telegram_botapi.TELEGRAM_MAX_CHARS - 200
    body = ("X" * block) + "\n\n" + ("Y" * block) + "\n\n" + ("Z" * block)
    assert len(telegram_botapi.chunk_text(body)) == 3

    posts: list[str] = []
    fail_once = {"done": False}

    def fake_send(token, chat_id, text, *, parse_mode=None):
        posts.append(text)
        # The 2nd distinct chunk fails transiently exactly once, then succeeds.
        if text.lstrip().startswith("Y") and not fail_once["done"]:
            fail_once["done"] = True
            return 500
        return 200

    monkeypatch.setattr(telegram_botapi, "_post_send_message", fake_send)
    assert telegram_botapi.send(body, token="T", chat_id="42") is True
    # Chunk 1 (the X chunk) posted exactly once; the Y chunk posted twice (retry).
    x_posts = [p for p in posts if p.lstrip().startswith("X")]
    y_posts = [p for p in posts if p.lstrip().startswith("Y")]
    z_posts = [p for p in posts if p.lstrip().startswith("Z")]
    assert len(x_posts) == 1, f"chunk 1 was resent: {posts}"
    assert len(y_posts) == 2, "failing chunk should retry exactly once more"
    assert len(z_posts) == 1


# --------------------------------------------------------------------------- #
# Email SMTP adapter
# --------------------------------------------------------------------------- #


def test_email_builds_message_and_returns_true(monkeypatch):
    captured: dict[str, object] = {}

    def fake_smtp_send(host, port, user, password, sender, to, message):
        captured.update(
            host=host, port=port, user=user, password=password,
            sender=sender, to=to, raw=message.as_string(), message=message,
        )
        return {}  # empty refused-map == all recipients accepted (matches _smtp_send contract)

    monkeypatch.setattr(email_smtp, "_smtp_send", fake_smtp_send)
    ok = email_smtp.send(
        "Subj", "body text",
        to=["a@example.com"], host="smtp.example.com", port=587,
        user="me@example.com", password="secret",
    )
    assert ok is True
    assert captured["host"] == "smtp.example.com"
    assert captured["port"] == 587
    assert captured["sender"] == "me@example.com"
    assert captured["to"] == ["a@example.com"]
    assert "Subj" in captured["raw"]
    # The plain-text part is the body; assert on the parsed message rather than
    # the serialized form (MIMEText base64-encodes the payload).
    msg = captured["message"]
    plain = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
    assert plain.get_payload(decode=True).decode("utf-8") == "body text"


def test_email_includes_html_alternative(monkeypatch):
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        email_smtp, "_smtp_send",
        lambda h, p, u, pw, s, to, msg: captured.update(raw=msg.as_string()) or {},
    )
    email_smtp.send(
        "S", "plain", to=["a@example.com"], host="h", port=587,
        user="u@example.com", password="x", html="<b>rich</b>",
    )
    assert "text/html" in captured["raw"]


def test_email_returns_false_on_error(monkeypatch):
    import smtplib

    def boom(*args, **kwargs):
        raise smtplib.SMTPException("rejected")

    monkeypatch.setattr(email_smtp, "_smtp_send", boom)
    ok = email_smtp.send(
        "S", "b", to=["a@example.com"], host="h", port=587,
        user="u", password="x",
    )
    assert ok is False


def test_email_total_refusal_still_returns_false(monkeypatch):
    # A TOTAL refusal raises SMTPRecipientsRefused (a subclass of SMTPException):
    # nobody received it, so this must still be False so the channel retries.
    import smtplib

    def total_refusal(*args, **kwargs):
        raise smtplib.SMTPRecipientsRefused({"a@example.com": (550, b"User unknown")})

    monkeypatch.setattr(email_smtp, "_smtp_send", total_refusal)
    ok = email_smtp.send(
        "S", "b", to=["a@example.com"], host="h", port=587, user="u", password="x",
    )
    assert ok is False


def test_email_starttls_uses_explicit_ssl_context(monkeypatch):
    # LOW: STARTTLS must be given an explicit verified SSLContext (not the implicit
    # unverified default) on the standard submission port.
    import ssl

    captured: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            captured["cls"] = "SMTP"
            captured["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, *, context=None):
            captured["context"] = context

        def login(self, user, password):
            pass

        def sendmail(self, sender, to, msg):
            captured["sent"] = True

    monkeypatch.setattr(email_smtp.smtplib, "SMTP", FakeSMTP)
    msg = email_smtp.build_message("S", "b", sender="u@x", to=["a@x"])
    email_smtp._smtp_send("h", 587, "u@x", "pw", "u@x", ["a@x"], msg)
    assert captured["cls"] == "SMTP"
    assert isinstance(captured["context"], ssl.SSLContext)
    assert captured["sent"] is True


def test_email_port_465_uses_smtp_ssl(monkeypatch):
    # LOW: port 465 is implicit TLS (SMTPS) — must use SMTP_SSL, not plain SMTP +
    # STARTTLS (which fails opaquely on 465).
    import ssl

    captured: dict[str, object] = {}

    class FakeSMTPSSL:
        def __init__(self, host, port, timeout=None, context=None):
            captured["cls"] = "SMTP_SSL"
            captured["port"] = port
            captured["context"] = context

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, password):
            pass

        def sendmail(self, sender, to, msg):
            captured["sent"] = True

    def fail_smtp(*a, **k):  # plain SMTP must NOT be used on 465
        raise AssertionError("port 465 must use SMTP_SSL, not plain SMTP")

    monkeypatch.setattr(email_smtp.smtplib, "SMTP_SSL", FakeSMTPSSL)
    monkeypatch.setattr(email_smtp.smtplib, "SMTP", fail_smtp)
    msg = email_smtp.build_message("S", "b", sender="u@x", to=["a@x"])
    email_smtp._smtp_send("h", 465, "u@x", "pw", "u@x", ["a@x"], msg)
    assert captured["cls"] == "SMTP_SSL"
    assert isinstance(captured["context"], ssl.SSLContext)
    assert captured["sent"] is True


def test_email_false_on_missing_params():
    assert email_smtp.send("S", "b", to=[], host="h", port=587, user="u", password="x") is False
    assert email_smtp.send("S", "b", to=["a@x"], host="", port=587, user="u", password="x") is False


# --------------------------------------------------------------------------- #
# Dispatcher (deliver.py)
# --------------------------------------------------------------------------- #


@pytest.fixture
def digest_file(tmp_path) -> Path:
    path = tmp_path / "2026-W24-digest.md"
    path.write_text("# Weekly digest\n\nSome content.\n", encoding="utf-8")
    return path


def _write_channels(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "channels.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_dispatcher_all_disabled_is_noop(tmp_path, digest_file, capsys):
    config = _write_channels(tmp_path, """
delivery:
  language: en
  email:
    enabled: false
    provider: smtp
  telegram:
    enabled: false
    transport: bot-api
  rocketchat:
    enabled: false
""")
    rc = deliver.deliver(digest_file, config)
    assert rc == 0
    out = capsys.readouterr().out
    assert "no enabled channels" in out


def test_dispatcher_enabled_rocketchat_sends(tmp_path, digest_file, monkeypatch, capsys):
    config = _write_channels(tmp_path, """
delivery:
  language: en
  rocketchat:
    enabled: true
    webhook_url_env: ROCKETCHAT_WEBHOOK_URL
""")
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    sent: dict[str, object] = {}
    monkeypatch.setattr(
        rocketchat_webhook, "send",
        lambda text, *, webhook_url: sent.update(text=text, url=webhook_url) or True,
    )
    rc = deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered")
    assert rc == 0
    assert sent["url"] == "https://rc.example/hooks/x"
    assert "Weekly digest" in sent["text"]
    assert "SENT" in capsys.readouterr().out


def test_dispatcher_missing_secret_is_clear_error(tmp_path, digest_file, monkeypatch, capsys):
    config = _write_channels(tmp_path, """
delivery:
  rocketchat:
    enabled: true
    webhook_url_env: ROCKETCHAT_WEBHOOK_URL
""")
    monkeypatch.delenv("ROCKETCHAT_WEBHOOK_URL", raising=False)
    rc = deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered")
    assert rc == 1
    out = capsys.readouterr().out
    assert "ROCKETCHAT_WEBHOOK_URL" in out
    assert "FAILED" in out


def test_dispatcher_skips_mcp_only_channels(tmp_path, digest_file, monkeypatch, capsys):
    # Email provider gmail-mcp and telegram transport mcp are handled by the
    # agent skill, not headless — dispatcher skips them without failing.
    config = _write_channels(tmp_path, """
delivery:
  email:
    enabled: true
    provider: gmail-mcp
    to: ["a@example.com"]
  telegram:
    enabled: true
    transport: mcp
    chat_id: "42"
""")
    rc = deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered")
    assert rc == 0
    out = capsys.readouterr().out
    assert "MCP-only" in out


def test_dispatcher_unknown_email_provider_is_error_not_silent_skip(tmp_path, digest_file, capsys):
    # MEDIUM: a typo like `provider: stmp` is neither smtp nor the known MCP value
    # gmail-mcp — it must surface as a config error (rc=1), not a silent MCP skip.
    config = _write_channels(tmp_path, """
delivery:
  email:
    enabled: true
    provider: stmp
    to: ["a@example.com"]
""")
    rc = deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered")
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "MCP-only" not in out  # the typo must NOT be reported as an MCP skip


def test_dispatcher_unknown_telegram_transport_is_error_not_silent_skip(tmp_path, digest_file, capsys):
    # MEDIUM: an unknown telegram transport (not bot-api, not the known mcp) is a
    # config error, not a silent skip.
    config = _write_channels(tmp_path, """
delivery:
  telegram:
    enabled: true
    transport: botapi
    chat_id: "42"
""")
    rc = deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered")
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "MCP-only" not in out


def test_dispatcher_enabled_telegram_botapi_sends(tmp_path, digest_file, monkeypatch):
    config = _write_channels(tmp_path, """
delivery:
  telegram:
    enabled: true
    transport: bot-api
    chat_id: "42"
    token_env: TELEGRAM_BOT_TOKEN
""")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    calls: dict[str, object] = {}
    monkeypatch.setattr(
        telegram_botapi, "send_detailed",
        lambda text, *, token, chat_id, parse_mode=None, render_markdown=False:
            calls.update(token=token, chat_id=chat_id)
            or telegram_botapi.TelegramSendResult(True, None),
    )
    assert deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered") == 0
    assert calls == {"token": "T", "chat_id": "42"}


def test_dispatcher_enabled_email_smtp_sends(tmp_path, digest_file, monkeypatch):
    config = _write_channels(tmp_path, """
delivery:
  email:
    enabled: true
    provider: smtp
    to: ["a@example.com"]
    smtp:
      host: smtp.example.com
      port: 587
      user: me@example.com
      password_env: SMTP_PASSWORD
""")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        email_smtp, "send_detailed",
        lambda subject, body, **kw: captured.update(subject=subject, **kw)
        or email_smtp.EmailSendResult(ok=True),
    )
    assert deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered") == 0
    assert captured["host"] == "smtp.example.com"
    assert captured["password"] == "secret"
    assert "a@example.com" in captured["to"]


def test_dispatcher_failed_send_returns_nonzero(tmp_path, digest_file, monkeypatch):
    config = _write_channels(tmp_path, """
delivery:
  rocketchat:
    enabled: true
    webhook_url_env: ROCKETCHAT_WEBHOOK_URL
""")
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    monkeypatch.setattr(rocketchat_webhook, "send", lambda text, *, webhook_url: False)
    assert deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered") == 1


def test_dispatcher_missing_config_file_raises(tmp_path, digest_file):
    with pytest.raises(deliver.DeliveryError):
        deliver.deliver(digest_file, tmp_path / "nope.yaml")


# --------------------------------------------------------------------------- #
# .env auto-loader (deliver.load_dotenv / parse_dotenv)
# --------------------------------------------------------------------------- #


def test_parse_dotenv_parses_and_skips_comments():
    body = (
        "# a comment\n"
        "\n"
        "FOO=bar\n"
        "  BAZ = qux  \n"           # surrounding whitespace stripped
        'QUOTED="has spaces"\n'     # quotes stripped
        "export EXPORTED=ev\n"      # `export ` prefix tolerated
        "no_equals_line\n"          # malformed -> skipped
    )
    parsed = deliver.parse_dotenv(body)
    assert parsed == {
        "FOO": "bar",
        "BAZ": "qux",
        "QUOTED": "has spaces",
        "EXPORTED": "ev",
    }
    assert "no_equals_line" not in parsed


def test_load_dotenv_sets_unset_vars(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("NEW_SECRET=fromfile\n", encoding="utf-8")
    monkeypatch.delenv("NEW_SECRET", raising=False)
    deliver.load_dotenv(env_file)
    assert os.environ["NEW_SECRET"] == "fromfile"


def test_load_dotenv_does_not_override_existing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("PRESET=fromfile\n", encoding="utf-8")
    monkeypatch.setenv("PRESET", "fromenv")
    deliver.load_dotenv(env_file)
    # Pre-existing environment value wins over the file value.
    assert os.environ["PRESET"] == "fromenv"


def test_load_dotenv_missing_file_is_noop(tmp_path):
    # Must not raise when config/.env does not exist (it is optional).
    deliver.load_dotenv(tmp_path / "does-not-exist.env")


# --------------------------------------------------------------------------- #
# --dry-run (no send; reports SET/MISSING; exits 0)
# --------------------------------------------------------------------------- #


def _telegram_botapi_config(tmp_path: Path) -> Path:
    return _write_channels(tmp_path, """
delivery:
  telegram:
    enabled: true
    transport: bot-api
    chat_id: "42"
    token_env: TELEGRAM_BOT_TOKEN
""")


def test_dry_run_sends_nothing_and_reports_missing(tmp_path, digest_file, monkeypatch, capsys):
    config = _telegram_botapi_config(tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    # Any real send attempt would explode the test.
    monkeypatch.setattr(
        telegram_botapi, "send",
        lambda *a, **k: pytest.fail("dry-run must not send"),
    )
    monkeypatch.setattr(
        telegram_botapi, "send_detailed",
        lambda *a, **k: pytest.fail("dry-run must not send"),
    )
    rc = deliver.deliver(digest_file, config, dry_run=True)
    assert rc == 0  # missing secret is not a failure in a check
    out = capsys.readouterr().out
    assert "WOULD SEND" in out
    assert "TELEGRAM_BOT_TOKEN=MISSING" in out
    assert "chat 42" in out


def test_dry_run_reports_set_when_secret_present(tmp_path, digest_file, monkeypatch, capsys):
    config = _telegram_botapi_config(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(
        telegram_botapi, "send",
        lambda *a, **k: pytest.fail("dry-run must not send"),
    )
    monkeypatch.setattr(
        telegram_botapi, "send_detailed",
        lambda *a, **k: pytest.fail("dry-run must not send"),
    )
    rc = deliver.deliver(digest_file, config, dry_run=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "TELEGRAM_BOT_TOKEN=SET" in out
    # The secret value itself must never be printed.
    assert "T\n" not in out and " T " not in out


def test_dry_run_never_prints_secret_value(tmp_path, digest_file, monkeypatch, capsys):
    config = _write_channels(tmp_path, """
delivery:
  rocketchat:
    enabled: true
    webhook_url_env: ROCKETCHAT_WEBHOOK_URL
""")
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://secret.example/hook/abc123")
    rc = deliver.deliver(digest_file, config, dry_run=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "ROCKETCHAT_WEBHOOK_URL=SET" in out
    assert "abc123" not in out  # the value is never echoed


def test_main_help_exits_clean(capsys):
    # `deliver.py --help` must print help and exit 0 — not fail with
    # "digest file not found: --help" (the old hand-rolled parser's bug).
    import pytest as _pytest

    with _pytest.raises(SystemExit) as exc:
        deliver.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "usage:" in out.lower()


def test_main_unknown_flag_is_rejected(capsys):
    # An unknown flag must be rejected by argparse (exit 2), not silently treated
    # as a digest path.
    import pytest as _pytest

    with _pytest.raises(SystemExit) as exc:
        deliver.main(["--frce"])  # typo of --force
    assert exc.value.code == 2
    err = capsys.readouterr().err.lower()
    assert "unrecognized" in err or "error" in err


def test_dry_run_main_with_no_digest_uses_sample(tmp_path, monkeypatch, capsys):
    config = _telegram_botapi_config(tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    # Avoid touching the real config/.env on the host; point the default config
    # at our fixture so `--dry-run` with no positional args has a config to read.
    monkeypatch.setattr(deliver, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(deliver, "DEFAULT_CHANNELS_CONFIG", config)
    rc = deliver.main(["--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "test message" in out  # the built-in sample note
    assert "WOULD SEND" in out


def test_no_channels_message_matches_skill_wording(tmp_path, digest_file, capsys):
    config = _write_channels(tmp_path, """
delivery:
  language: en
  email:
    enabled: false
  telegram:
    enabled: false
  rocketchat:
    enabled: false
""")
    deliver.deliver(digest_file, config)
    out = capsys.readouterr().out
    # Canonical wording shared with skills/digest-deliver (SKILL.md + acceptance).
    assert "no enabled channels — nothing to deliver" in out
    assert deliver.NO_CHANNELS_MESSAGE == "no enabled channels — nothing to deliver"


# --------------------------------------------------------------------------- #
# Delivery receipt + idempotency + retry + --force (CONVENTIONS §10)
# --------------------------------------------------------------------------- #


def _rocketchat_config(tmp_path: Path) -> Path:
    return _write_channels(tmp_path, """
delivery:
  rocketchat:
    enabled: true
    webhook_url_env: ROCKETCHAT_WEBHOOK_URL
""")


def test_receipt_written_on_success(tmp_path, digest_file, monkeypatch):
    config = _rocketchat_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    monkeypatch.setattr(rocketchat_webhook, "send", lambda text, *, webhook_url: True)
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 0
    rcpt = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))
    assert rcpt["rocketchat"]["status"] == "sent"
    assert rcpt["rocketchat"]["timestamp"]  # an ISO timestamp was stamped


def test_rerun_skips_already_delivered_channel(tmp_path, digest_file, monkeypatch, capsys):
    config = _rocketchat_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    calls = {"n": 0}

    def send(text, *, webhook_url):
        calls["n"] += 1
        return True

    monkeypatch.setattr(rocketchat_webhook, "send", send)
    # Run 1 sends.
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 0
    # Run 2 must NOT send again (idempotent skip).
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 0
    assert calls["n"] == 1
    out = capsys.readouterr().out
    assert "already delivered" in out


def test_headless_skip_marks_a_hash_less_receipt_as_unverified(
    tmp_path, digest_file, monkeypatch, capsys
):
    """A legacy receipt still skips — but the operator is told it is unverified.

    External review 2026-07-25 P2 called the skip a silent block. It is not:
    receipts are keyed per digest FILE, so a hash-less entry can only mean THIS
    digest went out, and refusing to match would re-deliver every legacy digest
    once, to real channels. What it genuinely cannot detect is a same-name
    rebuild — so that limit is printed instead of paid for with duplicates.
    """
    config = _rocketchat_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    deliver.write_receipt(
        deliver.receipt_path(digest_file, receipt_dir),
        {
            "rocketchat": {
                "status": deliver.RECEIPT_SENT,
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        },
    )
    calls = {"n": 0}
    monkeypatch.setattr(
        rocketchat_webhook, "send", lambda text, *, webhook_url: calls.__setitem__("n", 1) or True
    )

    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 0

    assert calls["n"] == 0, "a legacy receipt for THIS digest still means delivered"
    out = capsys.readouterr().out
    assert "already delivered" in out
    assert "content unverified" in out, "the legacy limit must be visible, not silent"


def test_force_resends_even_if_already_delivered(tmp_path, digest_file, monkeypatch):
    config = _rocketchat_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    calls = {"n": 0}

    def send(text, *, webhook_url):
        calls["n"] += 1
        return True

    monkeypatch.setattr(rocketchat_webhook, "send", send)
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 0
    # --force ignores the receipt and sends again.
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir, force=True) == 0
    assert calls["n"] == 2


def test_rerun_retries_only_failed_channel(tmp_path, digest_file, monkeypatch):
    config = _write_channels(tmp_path, """
delivery:
  rocketchat:
    enabled: true
    webhook_url_env: ROCKETCHAT_WEBHOOK_URL
""")
    receipt_dir = tmp_path / ".delivered"
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    # Run 1 fails (every attempt False).
    monkeypatch.setattr(rocketchat_webhook, "send", lambda text, *, webhook_url: False)
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 1
    rcpt = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))
    assert rcpt["rocketchat"]["status"] == "failed"
    # Run 2: a failed channel is retried (not skipped) and now succeeds.
    monkeypatch.setattr(rocketchat_webhook, "send", lambda text, *, webhook_url: True)
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 0
    rcpt = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))
    assert rcpt["rocketchat"]["status"] == "sent"


def test_bounded_retry_recovers_on_second_attempt(tmp_path, digest_file, monkeypatch):
    config = _rocketchat_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    states = iter([False, True])  # first attempt transient-fails, retry succeeds
    monkeypatch.setattr(
        rocketchat_webhook, "send", lambda text, *, webhook_url: next(states)
    )
    # The bounded retry inside the send path turns one transient failure into success.
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 0


def test_dry_run_neither_reads_nor_writes_receipt(tmp_path, digest_file, monkeypatch):
    config = _rocketchat_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    # Pre-seed a "sent" receipt: dry-run must ignore it (still reports WOULD SEND)
    # and must not create/modify the receipt file.
    rcpt_file = deliver.receipt_path(digest_file, receipt_dir)
    deliver.write_receipt(rcpt_file, {"rocketchat": {"status": "sent", "timestamp": "x"}})
    before = rcpt_file.read_text(encoding="utf-8")
    assert deliver.deliver(digest_file, config, dry_run=True, receipt_dir=receipt_dir) == 0
    # Unchanged on disk.
    assert rcpt_file.read_text(encoding="utf-8") == before


def test_load_receipt_corrupt_is_empty(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    assert deliver.load_receipt(bad) == {}


# --------------------------------------------------------------------------- #
# BUG A — an MCP-only skip must NOT be recorded as "sent" in the shared receipt
# --------------------------------------------------------------------------- #


def _mcp_only_config(tmp_path: Path) -> Path:
    # Email provider gmail-mcp and telegram transport mcp are agent-side only.
    return _write_channels(tmp_path, """
delivery:
  email:
    enabled: true
    provider: gmail-mcp
    to: ["a@example.com"]
  telegram:
    enabled: true
    transport: mcp
    chat_id: "42"
""")


def test_mcp_only_skip_not_recorded_as_sent(tmp_path, digest_file, capsys):
    # BUG A: a headless run skips MCP-only channels (handled by the agent skill).
    # The shared receipt is consulted by the agent-side MCP digest-deliver, so a
    # false "sent" would make the real MCP send get skipped. The skip must NOT be
    # written as sent (and must not be a failure either).
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    rc = deliver.deliver(digest_file, config, receipt_dir=receipt_dir)
    assert rc == 0  # an MCP-only skip is not a headless failure
    out = capsys.readouterr().out
    assert "MCP-only" in out
    rcpt = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))
    # Neither channel may be recorded as sent.
    assert rcpt.get("email", {}).get("status") != deliver.RECEIPT_SENT
    assert rcpt.get("telegram", {}).get("status") != deliver.RECEIPT_SENT


def test_all_mcp_only_headless_run_warns_nothing_delivered(tmp_path, digest_file, capsys):
    # A headless run whose ONLY enabled channels are MCP-only sends nothing and
    # returns 0 — which silently reads as success to cron. Surface a loud,
    # actionable note (without changing the exit code, since in agent/MCP mode an
    # all-MCP skip is expected and the skill does the real send).
    config = _mcp_only_config(tmp_path)
    rc = deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered")
    assert rc == 0
    out = capsys.readouterr().out
    assert deliver.ALL_MCP_ONLY_MESSAGE in out
    # The guidance must name the headless escape hatch.
    assert "smtp" in out and "bot-api" in out


def test_partial_mcp_only_does_not_warn(tmp_path, digest_file, monkeypatch, capsys):
    # Email is MCP-only but rocketchat is a real headless webhook that sends — so
    # the "delivered nothing" note must NOT fire (something did go out).
    config = _write_channels(tmp_path, """
delivery:
  email:
    enabled: true
    provider: gmail-mcp
    to: ["a@example.com"]
  rocketchat:
    enabled: true
    webhook_env: ROCKETCHAT_WEBHOOK_URL
""")
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://chat.example.com/hook/x")
    monkeypatch.setattr(deliver, "_deliver_rocketchat", lambda *a, **k: (deliver.SendOutcome.SENT, None))
    rc = deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered")
    assert rc == 0
    out = capsys.readouterr().out
    assert deliver.ALL_MCP_ONLY_MESSAGE not in out


def test_all_mcp_only_headless_run_records_degraded_delivery_health(
    tmp_path, digest_file, monkeypatch,
):
    # 2026-07-14 audit: an all-MCP config under cron builds, delivers to NOBODY,
    # exits 0 — and health stayed OK forever, the one failure mode with zero
    # signal. The skip must append a per-channel health event whose status
    # counts as a failure, so /status flips DEGRADED and the daily watchdog
    # pings. Self-healing: the MCP skill's own post-send
    # `health.py record --kind deliver --status sent` overwrites it per channel.
    import scripts.health as health

    monkeypatch.setattr(deliver, "_PROJECT_ROOT", tmp_path)
    config = _mcp_only_config(tmp_path)
    rc = deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered")
    assert rc == 0  # exit stays 0 so the cron && chain still stamps the heartbeat
    events = health.load_events(tmp_path)
    by_channel = {e["channel"]: e["status"] for e in events if e["kind"] == "deliver"}
    assert by_channel == {
        "email": "skipped-mcp-only",
        "telegram": "skipped-mcp-only",
    }
    assert all(s in health.FAILURE_STATUSES for s in by_channel.values())


def test_partial_mcp_only_records_no_skip_health(tmp_path, digest_file, monkeypatch):
    # Mixed setup: one channel really sent, one is MCP-only — the digest reached
    # someone, so the expected mixed-mode skip must NOT log a failure event.
    import scripts.health as health

    monkeypatch.setattr(deliver, "_PROJECT_ROOT", tmp_path)
    config = _write_channels(tmp_path, """
delivery:
  email:
    enabled: true
    provider: gmail-mcp
    to: ["a@example.com"]
  rocketchat:
    enabled: true
    webhook_env: ROCKETCHAT_WEBHOOK_URL
""")
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://chat.example.com/hook/x")
    monkeypatch.setattr(deliver, "_deliver_rocketchat", lambda *a, **k: (deliver.SendOutcome.SENT, None))
    rc = deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered")
    assert rc == 0
    events = health.load_events(tmp_path)
    assert not any(e.get("status") == "skipped-mcp-only" for e in events)


def test_mcp_only_channel_stays_eligible_on_rerun(tmp_path, digest_file, capsys):
    # BUG A: a second headless run must still treat an MCP-only channel as
    # not-yet-delivered (re-skip), never "already delivered" — so the channel
    # stays eligible for a real future send (agent MCP path or a switch to smtp).
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 0
    capsys.readouterr()  # discard run-1 output
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 0
    out = capsys.readouterr().out
    # Run 2 re-reports the MCP-only skip, not an idempotent "already delivered".
    assert "MCP-only" in out
    assert "already delivered" not in out


def test_mcp_only_skip_then_switch_to_smtp_sends(tmp_path, digest_file, monkeypatch):
    # BUG A: after a headless run skipped email as MCP-only, switching it to smtp
    # must still send (the prior skip must not have been recorded as "sent").
    receipt_dir = tmp_path / ".delivered"
    mcp_config = _write_channels(tmp_path, """
delivery:
  email:
    enabled: true
    provider: gmail-mcp
    to: ["a@example.com"]
""")
    assert deliver.deliver(digest_file, mcp_config, receipt_dir=receipt_dir) == 0

    smtp_config = _write_channels(tmp_path, """
delivery:
  email:
    enabled: true
    provider: smtp
    to: ["a@example.com"]
    smtp:
      host: smtp.example.com
      port: 587
      user: me@example.com
      password_env: SMTP_PASSWORD
""")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    sent = {"n": 0}
    monkeypatch.setattr(
        email_smtp, "send_detailed",
        lambda subject, body, **kw: sent.__setitem__("n", sent["n"] + 1)
        or email_smtp.EmailSendResult(ok=True),
    )
    assert deliver.deliver(digest_file, smtp_config, receipt_dir=receipt_dir) == 0
    assert sent["n"] == 1  # the real smtp send actually happened


def test_real_send_still_records_sent(tmp_path, digest_file, monkeypatch):
    # BUG A regression guard: a genuine send is still recorded as sent.
    config = _rocketchat_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    monkeypatch.setattr(rocketchat_webhook, "send", lambda text, *, webhook_url: True)
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 0
    rcpt = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))
    assert rcpt["rocketchat"]["status"] == deliver.RECEIPT_SENT


def test_final_receipt_write_failure_surfaces_nonzero(tmp_path, digest_file, monkeypatch, capsys):
    # SILENT-FAILURE DEFECT: a channel is delivered successfully, but the FINAL
    # receipt persistence fails (e.g. disk full). Without a recorded receipt the
    # next run re-sends the already-delivered channel — yet deliver() used to
    # return 0 (success), hiding the problem. A failed final write must surface as
    # a non-zero exit and a clear error line, never a silent success.
    config = _rocketchat_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    monkeypatch.setattr(rocketchat_webhook, "send", lambda text, *, webhook_url: True)
    # Every receipt write fails (covers both the per-channel flush and the final
    # persistence). The per-channel flush stays best-effort; the final write must
    # turn the all-sent run into a visible failure.
    def boom(path, receipt):
        raise OSError("disk full")

    monkeypatch.setattr(deliver, "write_receipt", boom)
    rc = deliver.deliver(digest_file, config, receipt_dir=receipt_dir)
    assert rc != 0  # the silent success is now a visible failure
    assert "receipt write failed" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# D7 — quiet-week skip (--skip-quiet)
# --------------------------------------------------------------------------- #


def _quiet_digest(tmp_path: Path) -> Path:
    path = tmp_path / "digest_quiet.md"
    path.write_text(
        "# Weekly digest — 2026-06-15\n\n"
        "Quiet week — no new sources and no concept updates in the last 7 days.\n",
        encoding="utf-8",
    )
    return path


def test_is_quiet_digest_detects_marker(tmp_path):
    assert deliver.is_quiet_digest(_quiet_digest(tmp_path).read_text("utf-8"))
    assert deliver.is_quiet_digest("# Weekly digest\n\n## New sources\n- x\n") is False


def test_is_quiet_digest_ignores_phrase_outside_quiet_marker():
    # BUG (LOW): the marker must be matched on the digest BODY, not the whole
    # text. A REAL digest whose body merely mentions the phrase "Quiet week —"
    # (e.g. an agent-authored narrative or a concept definition) must NOT be
    # misflagged as quiet, or --skip-quiet would wrongly suppress it.
    real_digest = (
        "---\n"
        "title: Weekly digest\n"
        "---\n"
        "# Weekly digest — 2026-06-19\n\n"
        "_3 new sources across 2 topics._\n\n"
        "## 🧪 Synthesis this week\n\n"
        'Last cycle was loud, unlike the "Quiet week —" lull we saw in May.\n'
    )
    assert deliver.is_quiet_digest(real_digest) is False
    # A genuine quiet-week digest (marker is the body line) still returns True.
    genuine_quiet = (
        "# Weekly digest — 2026-06-15\n\n"
        "Quiet week — no new sources and no concept updates in the last 7 days.\n"
    )
    assert deliver.is_quiet_digest(genuine_quiet) is True


def test_is_quiet_digest_detects_quiet_day(tmp_path):
    # The daily "inflow" digest (ADR 0016) marks a quiet build with "Quiet day —",
    # which --skip-quiet must recognize just like the weekly "Quiet week —".
    quiet_daily = (
        "# Daily digest — 2026-06-15\n\n"
        "Quiet day — nothing new arrived in the last 1 day. Everything's fine.\n"
    )
    assert deliver.is_quiet_digest(quiet_daily) is True


def test_skip_quiet_no_ops_on_quiet_week(tmp_path, monkeypatch, capsys):
    config = _rocketchat_config(tmp_path)
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    monkeypatch.setattr(
        rocketchat_webhook, "send",
        lambda *a, **k: pytest.fail("quiet week must not deliver"),
    )
    rc = deliver.deliver(
        _quiet_digest(tmp_path), config,
        skip_quiet=True, receipt_dir=tmp_path / ".delivered",
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "quiet week" in out
    # No receipt is written when nothing was delivered.
    assert not (tmp_path / ".delivered").exists()


def test_skip_quiet_still_delivers_non_quiet(tmp_path, digest_file, monkeypatch):
    config = _rocketchat_config(tmp_path)
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    sent = {"n": 0}
    monkeypatch.setattr(
        rocketchat_webhook, "send",
        lambda text, *, webhook_url: sent.__setitem__("n", sent["n"] + 1) or True,
    )
    # digest_file is a normal (non-quiet) digest -> --skip-quiet has no effect.
    rc = deliver.deliver(
        digest_file, config, skip_quiet=True, receipt_dir=tmp_path / ".delivered",
    )
    assert rc == 0
    assert sent["n"] == 1


def test_skip_quiet_dry_run_still_reports(tmp_path, monkeypatch, capsys):
    # Dry-run on a quiet week still reports (so channels can be verified) — the
    # skip only applies to a live send.
    config = _telegram_botapi_config(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    rc = deliver.deliver(
        _quiet_digest(tmp_path), config, dry_run=True, skip_quiet=True,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "WOULD SEND" in out
    assert "quiet week" not in out


# --------------------------------------------------------------------------- #
# Telegram chunk continuation markers + heading-boundary split
# --------------------------------------------------------------------------- #


def test_telegram_chunks_get_continuation_marker(monkeypatch):
    sent_chunks: list[str] = []
    monkeypatch.setattr(
        telegram_botapi, "_post_send_message",
        lambda token, chat_id, text, *, parse_mode=None: sent_chunks.append(text) or 200,
    )
    long_text = "\n\n".join("A" * 1000 for _ in range(10))
    assert telegram_botapi.send(long_text, token="T", chat_id="42")
    total = len(sent_chunks)
    assert total > 1
    # Every chunk carries an "(i/N)" marker and stays within the hard limit.
    for index, chunk in enumerate(sent_chunks, 1):
        assert f"({index}/{total})" in chunk
        assert len(chunk) <= telegram_botapi.TELEGRAM_MAX_CHARS


def test_telegram_single_chunk_has_no_marker(monkeypatch):
    sent_chunks: list[str] = []
    monkeypatch.setattr(
        telegram_botapi, "_post_send_message",
        lambda token, chat_id, text, *, parse_mode=None: sent_chunks.append(text) or 200,
    )
    assert telegram_botapi.send("short message", token="T", chat_id="42")
    assert sent_chunks == ["short message"]  # no marker noise on a single chunk


def test_telegram_prefers_heading_boundary():
    # A heading partway through a too-long body should be the split point, so the
    # heading travels with its section into the next chunk.
    limit = 200
    body = ("X" * 180) + "\n## Section Two\n" + ("Y" * 60) + "\n"
    chunks = telegram_botapi.chunk_text(body, limit=limit)
    assert len(chunks) == 2
    assert chunks[1].startswith("## Section Two")


def test_telegram_chunking_keeps_blockquotes_balanced():
    # CRITICAL: a rendered <blockquote expandable>…</blockquote> larger than the
    # limit must not be cut mid-tag (Telegram 400s on unbalanced HTML). Every
    # emitted chunk must carry balanced blockquote tags and stay within the limit.
    big_body = "\n".join(f"line {i} of a very long quote body" for i in range(400))
    html = f"<blockquote expandable>{big_body}</blockquote>"
    assert len(html) > telegram_botapi.TELEGRAM_MAX_CHARS
    chunks = telegram_botapi.chunk_text(html)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.count("<blockquote") == chunk.count("</blockquote>"), (
            f"unbalanced blockquote in chunk: {chunk[:80]!r}…{chunk[-80:]!r}"
        )
        assert len(chunk) <= telegram_botapi.TELEGRAM_MAX_CHARS
    # The reopened chunks must use the SAME variant (expandable).
    assert chunks[1].lstrip().startswith("<blockquote expandable>")


def test_telegram_chunking_keeps_plain_blockquote_balanced():
    # Same guard for the plain (non-expandable) TL;DR blockquote variant.
    big_body = "\n".join(f"summary point {i}" for i in range(500))
    html = f"<blockquote>{big_body}</blockquote>"
    assert len(html) > telegram_botapi.TELEGRAM_MAX_CHARS
    chunks = telegram_botapi.chunk_text(html)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.count("<blockquote") == chunk.count("</blockquote>")
        assert len(chunk) <= telegram_botapi.TELEGRAM_MAX_CHARS
    # Reopened with the plain variant, not the expandable one.
    assert chunks[1].lstrip().startswith("<blockquote>")


def test_telegram_expandable_blockquote_reserve_prevents_overflow():
    # Regression: the chunk budget must reserve room for the reopened tags for the
    # EXPANDABLE variant too (not only the plain "<blockquote>"). With a long
    # no-newline run packed near the budget, a missing reserve let close+reopen
    # tags push a chunk past the limit → Telegram 400. A small limit makes the
    # boundary deterministic regardless of line alignment.
    limit = 200
    body = "B" * 500 + "\n" + ("word " * 100) + "\n" + "C" * 400
    html = f"{telegram_botapi._BLOCKQUOTE_OPEN_EXPANDABLE}{body}{telegram_botapi._BLOCKQUOTE_CLOSE}"
    chunks = telegram_botapi.chunk_text(html, limit=limit)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= limit, f"chunk over limit: {len(chunk)}"
        assert chunk.count("<blockquote") == chunk.count("</blockquote>")


def test_telegram_hard_cut_never_splits_a_blockquote_tag():
    # Regression: a hard cut (long run with no newline) must not land inside a
    # "<blockquote …>" opening tag — a truncated tag can't be rebalanced and ships
    # unbalanced. The body before the tag has no newline, forcing a hard cut.
    limit = telegram_botapi.TELEGRAM_MAX_CHARS
    head = "A" * (limit - telegram_botapi._MARKER_RESERVE - telegram_botapi._BLOCKQUOTE_RESERVE - 4)
    html = f"{head}{telegram_botapi._BLOCKQUOTE_OPEN_EXPANDABLE}{'B' * 300}{telegram_botapi._BLOCKQUOTE_CLOSE}"
    chunks = telegram_botapi.chunk_text(html, limit=limit)
    for chunk in chunks:
        assert chunk.count("<blockquote") == chunk.count("</blockquote>")
        assert "<blockquote" not in chunk or "<blockquote expandable>" in chunk or "<blockquote>" in chunk
        assert len(chunk) <= limit


def test_telegram_prefers_divider_boundary():
    # In the rendered HTML path headings are <b>…</b>, not '## '; the section
    # divider line is the boundary, so a too-long body splits before it.
    limit = 200
    div = telegram_botapi._TG_DIVIDER
    body = ("X" * 180) + f"\n{div}\n<b>SECTION TWO</b>\n" + ("Y" * 40) + "\n"
    chunks = telegram_botapi.chunk_text(body, limit=limit)
    assert len(chunks) == 2
    assert chunks[1].startswith(div)


# --------------------------------------------------------------------------- #
# Telegram — section-aware message splitting (one message per major section)
# --------------------------------------------------------------------------- #


def _full_digest_md() -> str:
    """A small but structurally complete digest for split tests."""
    return (
        "# 🧠 Weekly digest — 2026-06-19\n\n"
        "_3 new sources across 2 topics, 4 updated concepts._\n\n"
        "## ⚡ TL;DR\n\n"
        "- 📰 Most active: **ai** (2 of 3 new sources)\n"
        "- 💡 4 concepts updated:\n"
        "  - Alpha\n  - Beta\n  - Gamma\n  - …and 1 more\n\n"
        "**🟢 Knowledge base:** 4 concepts · 0 orphans\n\n"
        "## 📰 New sources (last 7 days)\n\n"
        "### 🏷 ai (2)\n- **[t1](https://x/1)**\n  > k1\n- **[t2](https://x/2)**\n  > k2\n\n"
        "### 🏷 tech (1)\n- **[t3](https://x/3)**\n  > k3\n\n"
        "## 💡 Updated concepts (last 7 days)\n\n"
        "- **Concept A**\n  - 🟡 Single-source · 🔗 [ex.com](https://ex.com/a)\n  > a definition\n\n"
        "## 🧪 Synthesis this week\n\n"
        "Prose about the week and what it means.\n\n"
        "## 📌 Needs attention\n\nNothing pending.\n"
    )


def test_telegram_section_split_each_major_section_its_own_message():
    html = telegram_botapi.markdown_to_telegram_html(_full_digest_md())
    msgs = telegram_botapi.split_section_messages(html)
    # Four messages: [intro+TL;DR+New sources], [Updated concepts], [Synthesis],
    # [Needs attention].
    assert len(msgs) == 4
    assert "TL;DR" in msgs[0] and "NEW SOURCES" in msgs[0]
    assert "UPDATED CONCEPTS" in msgs[1] and "NEW SOURCES" not in msgs[1]
    assert "SYNTHESIS THIS WEEK" in msgs[2]
    assert "NEEDS ATTENTION" in msgs[3]


def test_telegram_section_split_header_starts_each_message_not_orphaned():
    html = telegram_botapi.markdown_to_telegram_html(_full_digest_md())
    msgs = telegram_botapi.split_section_messages(html)
    # No section header may sit on the LAST non-empty line of any message.
    for message in msgs:
        last = [line for line in message.split("\n") if line.strip()][-1]
        assert "UPDATED CONCEPTS" not in last
        assert "SYNTHESIS THIS WEEK" not in last
    # A standalone section message leads with its header, not a stray divider.
    assert not msgs[1].lstrip().startswith(telegram_botapi._TG_DIVIDER)
    assert msgs[1].lstrip().startswith("<b>")


def test_telegram_section_split_plaintext_falls_back_to_chunking():
    # No dividers (plain text / quiet week) -> single short message, unchanged.
    assert telegram_botapi.split_section_messages("just a short note") == [
        "just a short note"
    ]


def test_telegram_send_routes_through_section_split(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(
        telegram_botapi, "_post_send_message",
        lambda token, chat_id, text, *, parse_mode=None: sent.append(text) or 200,
    )
    assert telegram_botapi.send(
        _full_digest_md(), token="T", chat_id="42", render_markdown=True
    )
    # The digest goes out as several section messages, each carrying an (i/N) marker.
    assert len(sent) == 4
    assert all(f"({i}/4)" in chunk for i, chunk in enumerate(sent, 1))


# --------------------------------------------------------------------------- #
# Email — Markdown -> HTML alternative
# --------------------------------------------------------------------------- #


def test_email_channel_passes_html_alternative(tmp_path, monkeypatch):
    config = _write_channels(tmp_path, """
delivery:
  email:
    enabled: true
    provider: smtp
    to: ["a@example.com"]
    smtp:
      host: smtp.example.com
      port: 587
      user: me@example.com
      password_env: SMTP_PASSWORD
""")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        email_smtp, "send_detailed",
        lambda subject, body, **kw: captured.update(body=body, **kw)
        or email_smtp.EmailSendResult(ok=True),
    )
    digest = tmp_path / "digest_2026-06-15.md"
    digest.write_text("# Weekly digest\n\n## New sources\n\n- An item\n", encoding="utf-8")
    assert deliver.deliver(digest, config, receipt_dir=tmp_path / ".delivered") == 0
    # A premium HTML alternative is generated alongside the plain-text body: a
    # full styled document carrying the digest's title and content.
    html = captured["html"]
    assert isinstance(html, str)
    assert "<!doctype html" in html.lower()
    assert "Weekly digest" in html
    assert "<h1" in html and "An item" in html
    assert captured["body"].startswith("# Weekly digest")


# --------------------------------------------------------------------------- #
# D10 — rehearsal (--rehearse builds + dry-runs, sends nothing)
# --------------------------------------------------------------------------- #


def test_rehearse_builds_and_dry_runs(tmp_path, monkeypatch, capsys):
    config = _telegram_botapi_config(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    # A real send would fail the test — rehearsal must be dry only.
    monkeypatch.setattr(
        telegram_botapi, "send",
        lambda *a, **k: pytest.fail("rehearsal must not send"),
    )
    monkeypatch.setattr(
        telegram_botapi, "send_detailed",
        lambda *a, **k: pytest.fail("rehearsal must not send"),
    )
    rc = deliver.main(["--rehearse", str(config)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "rehearsal — would deliver a digest" in out
    assert "WOULD SEND" in out


def test_rehearse_unsanitized_incoming_fails_cleanly(tmp_path, monkeypatch, capsys):
    # The builder's sanitize gate (fail-closed by default) must surface from
    # --rehearse as a clean, actionable error — never a traceback.
    config = _telegram_botapi_config(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    from scripts import build_digest as bd

    def refuse(*a, **k):
        raise bd.IncomingNotSanitized(
            "refusing to build digest: 1 incoming article(s) lack a current "
            "sanitized companion — run `python3 scripts/sanitize_incoming.py "
            "sanitize` first"
        )

    monkeypatch.setattr(bd, "build_digest", refuse)
    rc = deliver.main(["--rehearse", str(config)])
    captured = capsys.readouterr()
    assert rc != 0
    assert "sanitize_incoming.py sanitize" in captured.err
    assert "Traceback" not in captured.err


def test_rehearse_allow_unsanitized_passes_optout_through(tmp_path, monkeypatch, capsys):
    # The build gate's explicit opt-out must be reachable from --rehearse too —
    # otherwise a controlled-feed install that opted out on the cron line can
    # never rehearse.
    config = _telegram_botapi_config(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    from scripts import build_digest as bd

    seen: dict[str, object] = {}
    real_build = bd.build_digest

    def spy(path, **kwargs):
        seen.update(kwargs)
        return real_build(path, **kwargs)

    monkeypatch.setattr(bd, "build_digest", spy)
    rc = deliver.main(["--rehearse", "--allow-unsanitized", str(config)])
    assert rc == 0
    assert seen["require_sanitized"] is False
    assert "rehearsal — would deliver a digest" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Regression: review cycle hardening (C5 / C6 / M1 / M2)
# --------------------------------------------------------------------------- #


def _two_channel_config(tmp_path: Path) -> Path:
    # rocketchat + telegram both enabled, so one can succeed and one can crash.
    return _write_channels(tmp_path, """
delivery:
  rocketchat:
    enabled: true
    webhook_url_env: ROCKETCHAT_WEBHOOK_URL
  telegram:
    enabled: true
    transport: bot-api
    token_env: TG_TOKEN
    chat_id: "42"
""")


def test_c5_unexpected_error_persists_already_sent_channels(tmp_path, digest_file, monkeypatch, capsys):
    # BUG C5: an unexpected (non-DeliveryError) exception in one channel must not
    # discard the receipt of channels already sent THIS run.
    config = _two_channel_config(tmp_path)
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/x")
    monkeypatch.setenv("TG_TOKEN", "tok")
    monkeypatch.setattr(rocketchat_webhook, "send", lambda text, *, webhook_url: True)

    def boom(*a, **k):
        raise RuntimeError("kaboom in transport")

    monkeypatch.setattr(telegram_botapi, "send_detailed", boom)
    receipt_dir = tmp_path / ".delivered"
    rc = deliver.deliver(digest_file, config, receipt_dir=receipt_dir)

    assert rc == 1  # one channel failed
    receipt = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))
    # rocketchat's success was persisted despite the telegram crash.
    assert receipt["rocketchat"]["status"] == deliver.RECEIPT_SENT
    assert receipt["telegram"]["status"] == deliver.RECEIPT_FAILED
    # A re-run skips the already-sent rocketchat (no double-send).
    calls = []
    monkeypatch.setattr(rocketchat_webhook, "send", lambda text, *, webhook_url: calls.append(1) or True)
    monkeypatch.setattr(
        telegram_botapi, "send_detailed",
        lambda *a, **k: telegram_botapi.TelegramSendResult(True, None),
    )
    deliver.deliver(digest_file, config, receipt_dir=receipt_dir)
    assert calls == [], "already-sent rocketchat was re-sent"


def test_c6_non_numeric_smtp_port_is_reported_not_crash(tmp_path, digest_file, monkeypatch, capsys):
    # BUG C6: a non-numeric port is a config typo; report it per-channel rather
    # than crashing the whole run with a raw ValueError.
    config = _write_channels(tmp_path, """
delivery:
  email:
    enabled: true
    provider: smtp
    to: [you@example.com]
    smtp:
      host: smtp.example.com
      port: "not-a-number"
      password_env: SMTP_PASSWORD
""")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    rc = deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered")
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "port" in out


def test_m1_whitespace_only_secret_is_rejected(monkeypatch):
    # BUG M1: a whitespace-only secret must not pass as a credential.
    monkeypatch.setenv("WS_SECRET", "   ")
    with pytest.raises(deliver.DeliveryError):
        deliver._env_or_fail("rocketchat", "WS_SECRET")
    assert deliver._secret_state("WS_SECRET") == "MISSING"


def test_m2_receipt_write_is_atomic(tmp_path):
    # BUG M2: write_receipt leaves no partial file behind (temp + replace).
    path = tmp_path / ".delivered" / "d.json"
    deliver.write_receipt(path, {"rocketchat": {"status": "sent"}})
    assert path.exists()
    # No stray temp artifact left in the directory.
    assert [p.name for p in path.parent.iterdir()] == ["d.json"]
    assert deliver.load_receipt(path)["rocketchat"]["status"] == "sent"


# --------------------------------------------------------------------------- #
# Regression: delivery -> health-log wiring (cycle-4)
# --------------------------------------------------------------------------- #


def test_delivery_health_hook_records_from_receipt(tmp_path, digest_file, monkeypatch):
    # The non-dry-run health hook must mirror each receipt channel into the health
    # log. Point the module roots at a tmp dir so nothing touches the real repo.
    import scripts.health as health

    # This test drives the health hook with explicit roots (_PROJECT_ROOT +
    # DEFAULT_RECEIPT_DIR); opt out of the autouse STATE_DIR relocation so the
    # receipt + health log resolve to those exact tmp paths, not the relocated
    # ones. (STATE_DIR relocation is covered by the relocation tests below.)
    monkeypatch.delenv("RESEARCH_BRAIN_STATE_DIR", raising=False)
    receipt_dir = tmp_path / "pipeline" / "3-synthesis" / ".delivered"
    monkeypatch.setattr(deliver, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(deliver, "DEFAULT_RECEIPT_DIR", receipt_dir)
    # Write a receipt as a real send would have.
    deliver.write_receipt(
        deliver.receipt_path(digest_file, receipt_dir),
        {"telegram": {"status": deliver.RECEIPT_SENT},
         "email": {"status": deliver.RECEIPT_FAILED}},
    )

    deliver._record_delivery_health(digest_file)

    events = health.load_events(tmp_path)
    by_channel = {e["channel"]: e["status"] for e in events if e["kind"] == "deliver"}
    assert by_channel == {"telegram": "sent", "email": "failed"}


def test_delivery_health_records_only_channels_attempted_this_run(tmp_path, monkeypatch):
    # LOW: on an idempotent re-run, a channel already delivered (and skipped this
    # run) must NOT log another health event — only channels actually attempted
    # this run are recorded. The receipt still carries the prior channel.
    import scripts.health as health

    # Explicit-roots test — opt out of the autouse STATE_DIR relocation (see the
    # from_receipt test above).
    monkeypatch.delenv("RESEARCH_BRAIN_STATE_DIR", raising=False)
    receipt_dir = tmp_path / "pipeline" / "3-synthesis" / ".delivered"
    monkeypatch.setattr(deliver, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(deliver, "DEFAULT_RECEIPT_DIR", receipt_dir)
    digest = tmp_path / "digest_x.md"
    digest.write_text("# d", encoding="utf-8")
    # Receipt already has telegram sent from a prior run; this run only attempted
    # email (e.g. telegram was idempotently skipped).
    deliver.write_receipt(
        deliver.receipt_path(digest, receipt_dir),
        {"telegram": {"status": deliver.RECEIPT_SENT},
         "email": {"status": deliver.RECEIPT_SENT}},
    )
    deliver._record_delivery_health(digest, channels={"email"})

    events = health.load_events(tmp_path)
    recorded = [e["channel"] for e in events if e["kind"] == "deliver"]
    assert recorded == ["email"]  # telegram (skipped this run) not re-logged


def test_delivery_health_hook_works_as_direct_script(tmp_path):
    # Regression: `python scripts/delivery/deliver.py` runs with only the script's
    # own dir on sys.path (NOT the project root), so the health hook's
    # `from scripts import health` import silently failed and recorded nothing.
    # Reproduce that exact path condition in a subprocess and assert it records.
    import subprocess
    import sys as _sys
    import textwrap

    root = Path(__file__).resolve().parents[1]
    code = textwrap.dedent(f"""
        import os, sys, pathlib
        # Explicit-roots test: opt out of any inherited STATE_DIR relocation so the
        # receipt + health log resolve to `sandbox/...` exactly (the autouse test
        # fixture exports this var; a direct-script run in the wild would not).
        os.environ.pop("RESEARCH_BRAIN_STATE_DIR", None)
        # Mimic a direct-script run: ONLY the delivery dir on the path.
        sys.path.insert(0, r"{root / 'scripts' / 'delivery'}")
        import deliver
        sandbox = pathlib.Path(r"{tmp_path}")
        deliver._PROJECT_ROOT = sandbox
        deliver.DEFAULT_RECEIPT_DIR = sandbox / "pipeline" / "3-synthesis" / ".delivered"
        d = sandbox / "digest_x.md"; d.write_text("# d", encoding="utf-8")
        deliver.write_receipt(
            deliver.receipt_path(d, deliver.DEFAULT_RECEIPT_DIR),
            {{"telegram": {{"status": "sent"}}}},
        )
        deliver._record_delivery_health(d)
        ev = sandbox / "pipeline" / ".health" / "events.jsonl"
        assert ev.exists(), "health hook recorded nothing (import silently failed)"
        print("OK")
    """)
    # cwd=tmp_path so the project root is NOT implicitly on sys.path via CWD.
    result = subprocess.run(
        [_sys.executable, "-c", code], cwd=tmp_path,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "OK" in result.stdout


# --------------------------------------------------------------------------- #
# Telegram markdown -> HTML rendering (polished digest)
# --------------------------------------------------------------------------- #


def test_telegram_markdown_html_headings_links_bullets():
    conv = telegram_botapi.markdown_to_telegram_html
    out = conv("# Weekly digest\n\n- [GLM 5.2](https://hf.co/blog/a_b_c) — note\n")
    assert "<b>WEEKLY DIGEST</b>" in out
    assert '<a href="https://hf.co/blog/a_b_c">GLM 5.2</a>' in out
    assert "• " in out
    # An underscore inside a URL must NOT be turned into italics.
    assert "a_b_c" in out
    assert "<i>" not in out


def test_telegram_link_disallowed_scheme_renders_plain_text():
    # HIGH: a javascript:/data: scheme from untrusted article content must NOT
    # become a clickable href — render the link as plain escaped text instead.
    conv = telegram_botapi.markdown_to_telegram_html
    out = conv("[click me](javascript:alert(1))")
    assert "<a " not in out  # no anchor emitted
    assert "javascript:" not in out  # the unsafe href is dropped entirely
    assert "click me" in out  # the label survives as plain text


def test_telegram_link_with_paren_in_url_survives():
    # HIGH: a URL containing a balanced ')' must not be truncated at the first ')'.
    conv = telegram_botapi.markdown_to_telegram_html
    out = conv("[wiki](https://en.wikipedia.org/wiki/Foo_(bar))")
    assert '<a href="https://en.wikipedia.org/wiki/Foo_(bar)">wiki</a>' in out


def test_telegram_link_allowed_schemes_still_render():
    conv = telegram_botapi.markdown_to_telegram_html
    assert '<a href="https://x.com/a">x</a>' in conv("[x](https://x.com/a)")
    assert '<a href="http://x.com/a">x</a>' in conv("[x](http://x.com/a)")
    assert '<a href="mailto:a@b.com">mail</a>' in conv("[mail](mailto:a@b.com)")


def test_telegram_link_label_backslash_escapes_are_unescaped():
    # A parenthesized/bracketed title is backslash-escaped by _md_link; the telegram
    # renderer must unescape the label (and still match a bracketed one as a link).
    from scripts.digest.model import _md_link

    conv = telegram_botapi.markdown_to_telegram_html
    out_paren = conv(_md_link("Attention (Is All You Need)", "https://x.example/a"))
    assert ">Attention (Is All You Need)</a>" in out_paren
    assert "\\(" not in out_paren

    out_bracket = conv(_md_link("Foo [2026] review", "https://x.example/a"))
    assert '<a href="https://x.example/a">Foo [2026] review</a>' in out_bracket


def test_telegram_markdown_html_escapes_special_chars():
    conv = telegram_botapi.markdown_to_telegram_html
    out = conv("R&D in C++ uses <vector> & >0 checks")
    assert "&amp;" in out and "&lt;vector&gt;" in out
    assert "<vector>" not in out  # raw angle brackets escaped


def test_telegram_tldr_wrapped_in_plain_blockquote():
    html = telegram_botapi.markdown_to_telegram_html(_full_digest_md())
    # The TL;DR is a PLAIN (non-expandable) quote so the summary always shows in
    # full; the header stays outside it.
    assert "<b>⚡ TL;DR</b>" in html
    quoted = html.split("<blockquote>", 1)[1].split("</blockquote>", 1)[0]
    assert "Most active" in quoted
    assert "TL;DR" not in quoted
    # The TL;DR quote must NOT be the expandable variant.
    assert "<blockquote expandable>• 📰 Most active" not in html


def test_telegram_synthesis_wrapped_in_expandable_blockquote():
    html = telegram_botapi.markdown_to_telegram_html(_full_digest_md())
    # The synthesis prose collapses into an expandable quote (the one carrying it).
    parts = html.split("<blockquote expandable>")
    assert any("Prose about the week" in p.split("</blockquote>")[0] for p in parts[1:])


def test_telegram_blockquote_absent_when_sections_absent():
    # A plain body with no TL;DR / synthesis section and no `>` quote lines gets
    # no blockquotes.
    html = telegram_botapi.markdown_to_telegram_html("# Title\n\njust some text\n")
    assert "<blockquote" not in html


def test_telegram_quote_line_renders_as_expandable_blockquote():
    # A `> body` line (concept definition / source takeaway) becomes an
    # expandable blockquote: short ones show fully, long ones collapse.
    html = telegram_botapi.markdown_to_telegram_html(
        "- **[t1](https://x/1)**\n  > the full takeaway text\n"
    )
    assert "<blockquote expandable>the full takeaway text</blockquote>" in html
    assert "&gt;" not in html  # the leading '>' is consumed, not escaped


def test_telegram_consecutive_concept_quotes_are_separate_blockquotes():
    # Two concepts -> two independent quote blocks (the blank line between them
    # closes the first), never one merged quote.
    md = (
        "- **Concept A**\n  > def A\n\n"
        "- **Concept B**\n  > def B\n"
    )
    html = telegram_botapi.markdown_to_telegram_html(md)
    assert "<blockquote expandable>def A</blockquote>" in html
    assert "<blockquote expandable>def B</blockquote>" in html


def test_telegram_send_render_markdown_sets_html_parse_mode(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        telegram_botapi, "_post_send_message",
        lambda token, chat_id, text, *, parse_mode=None: calls.update(
            text=text, parse_mode=parse_mode) or 200,
    )
    ok = telegram_botapi.send(
        "# Hi\n\n- [x](https://y.com) — z", token="t", chat_id="1",
        render_markdown=True,
    )
    assert ok is True
    assert calls["parse_mode"] == "HTML"
    assert "<b>HI</b>" in calls["text"]
    assert '<a href="https://y.com">x</a>' in calls["text"]


# --------------------------------------------------------------------------- #
# Concurrency / idempotency hardening (unique temp, per-channel persist,
# content-hash idempotency, malformed-YAML guard)
# --------------------------------------------------------------------------- #


def test_write_receipt_uses_unique_temp_name(tmp_path, monkeypatch):
    # DEFECT 1: two concurrent deliver.py processes on the same digest must not
    # collide on a single fixed ".tmp" name. The temp file must be unique per
    # write (process-specific), so capture every temp path os.replace sees and
    # assert they differ across writes.
    path = tmp_path / ".delivered" / "d.json"
    temps: list[Path] = []
    real_replace = os.replace

    def spy_replace(src, dst):
        temps.append(Path(src))
        real_replace(src, dst)

    monkeypatch.setattr(deliver.os, "replace", spy_replace)
    deliver.write_receipt(path, {"a": {"status": "sent"}})
    deliver.write_receipt(path, {"a": {"status": "sent"}})
    assert len(temps) == 2
    # The two temp paths must NOT be the same fixed name (concurrency-safe).
    assert temps[0] != temps[1]
    # Both temps live in the same dir as the final receipt (atomic os.replace).
    assert temps[0].parent == path.parent
    assert temps[1].parent == path.parent
    # And no stray temp artifact is left behind afterwards.
    assert [p.name for p in path.parent.iterdir()] == ["d.json"]


def test_write_receipt_cleans_temp_on_replace_failure(tmp_path, monkeypatch):
    # DEFECT 1: if the atomic replace fails, the unique temp file must be cleaned
    # up rather than left as garbage in the receipt dir.
    path = tmp_path / ".delivered" / "d.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    def boom_replace(src, dst):
        raise OSError("replace failed (disk full)")

    monkeypatch.setattr(deliver.os, "replace", boom_replace)
    with pytest.raises(OSError):
        deliver.write_receipt(path, {"a": {"status": "sent"}})
    # No temp file (or final file) left behind in the directory.
    assert list(path.parent.iterdir()) == []


def test_receipt_persisted_after_each_channel(tmp_path, digest_file, monkeypatch):
    # DEFECT 2: the receipt must be durably written after EACH channel's send, not
    # only once after the whole loop. _CHANNELS order is telegram-before-rocketchat,
    # so have the SECOND channel (rocketchat) read the on-disk receipt mid-loop and
    # assert the FIRST channel (telegram) is already recorded there. If persistence
    # only happened in the final finally, telegram would not yet be on disk.
    config = _two_channel_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/x")
    monkeypatch.setenv("TG_TOKEN", "tok")
    monkeypatch.setattr(
        telegram_botapi, "send_detailed",
        lambda *a, **k: telegram_botapi.TelegramSendResult(True, None),
    )

    seen: dict[str, object] = {}

    def rocketchat_reads_receipt(text, *, webhook_url):
        rcpt = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))
        seen["telegram_status"] = rcpt.get("telegram", {}).get("status")
        return True

    monkeypatch.setattr(rocketchat_webhook, "send", rocketchat_reads_receipt)
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 0
    # telegram was already durably persisted before rocketchat ran.
    assert seen["telegram_status"] == deliver.RECEIPT_SENT


def test_changed_content_same_day_resends(tmp_path, monkeypatch):
    # DEFECT 3: a same-day rebuild with DIFFERENT content must re-send — the
    # receipt key (digest stem) alone wrongly treated it as already-sent. With a
    # content hash, changed content invalidates the prior "sent" record.
    config = _rocketchat_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    calls = {"n": 0}
    monkeypatch.setattr(
        rocketchat_webhook, "send",
        lambda text, *, webhook_url: calls.__setitem__("n", calls["n"] + 1) or True,
    )
    digest = tmp_path / "2026-W24-digest.md"
    digest.write_text("# Weekly digest\n\nFirst content.\n", encoding="utf-8")
    assert deliver.deliver(digest, config, receipt_dir=receipt_dir) == 0
    assert calls["n"] == 1
    # Rewrite the SAME-named digest with DIFFERENT content (same-day rebuild).
    digest.write_text("# Weekly digest\n\nUPDATED content!\n", encoding="utf-8")
    assert deliver.deliver(digest, config, receipt_dir=receipt_dir) == 0
    assert calls["n"] == 2, "changed content must re-send, not falsely skip"


def test_same_content_rerun_still_skips(tmp_path, digest_file, monkeypatch, capsys):
    # DEFECT 3 (regression): identical content on a re-run must STILL be skipped
    # (the content hash matches the stored one).
    config = _rocketchat_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    calls = {"n": 0}
    monkeypatch.setattr(
        rocketchat_webhook, "send",
        lambda text, *, webhook_url: calls.__setitem__("n", calls["n"] + 1) or True,
    )
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 0
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 0
    assert calls["n"] == 1
    assert "already delivered" in capsys.readouterr().out


def test_old_receipt_without_hash_is_tolerated(tmp_path, digest_file, monkeypatch):
    # DEFECT 3 (back-compat): a pre-existing receipt that lacks the content hash
    # field must still be read (load_receipt must not choke). A legacy "sent"
    # record with no hash is treated as a skip (preserve prior idempotency) rather
    # than a forced re-send.
    config = _rocketchat_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    # Seed a legacy receipt (status+timestamp only — no content hash).
    deliver.write_receipt(
        deliver.receipt_path(digest_file, receipt_dir),
        {"rocketchat": {"status": "sent", "timestamp": "2026-06-15T00:00:00+00:00"}},
    )
    rcpt = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))
    assert rcpt["rocketchat"]["status"] == "sent"  # tolerated, readable
    calls = {"n": 0}
    monkeypatch.setattr(
        rocketchat_webhook, "send",
        lambda text, *, webhook_url: calls.__setitem__("n", calls["n"] + 1) or True,
    )
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 0
    assert calls["n"] == 0, "legacy hash-less 'sent' record should still skip"


def test_malformed_channels_yaml_is_reported_not_crash(tmp_path, digest_file):
    # DEFECT 4: a malformed channels.yaml must raise a clean DeliveryError, not an
    # unhandled yaml.YAMLError/ParserError traceback.
    bad = _write_channels(tmp_path, "delivery:\n  email:\n    enabled: true\n  : : :\n")
    with pytest.raises(deliver.DeliveryError):
        deliver.load_config(bad)
    # And the same surfaces cleanly through deliver() (no raw YAMLError).
    with pytest.raises(deliver.DeliveryError):
        deliver.deliver(digest_file, bad, receipt_dir=tmp_path / ".delivered")


_RC_ENABLED = """
delivery:
  language: en
  rocketchat:
    enabled: true
    webhook_url_env: ROCKETCHAT_WEBHOOK_URL
"""


def test_delivery_lock_lease_survives_a_slow_multichannel_send():
    # The delivery lock is acquired with steal_dead=True, so a CRASHED holder is
    # reclaimed instantly regardless of lease — the lease only governs when a LIVE
    # holder can be stolen. If it expires mid-send (a large digest on a slow network,
    # telegram chunks retrying), a second run steals the lock and re-sends the digest.
    # So the lease must comfortably exceed the worst-case single-run transport budget
    # (email + telegram chunks + rocketchat, each with a ~30s timeout and one retry).
    # Keep it at least an hour; lowering it back re-opens the mid-send double-send.
    assert deliver.DELIVERY_LOCK_LEASE >= 3600.0


def test_concurrent_delivery_is_refused_not_double_sent(
    tmp_path, digest_file, monkeypatch, capsys
):
    # DEFECT #4: a real delivery takes a lock. If another delivery already holds
    # it, the second refuses (exit 1) and sends nothing — no double-send — then
    # proceeds normally once the lock is released.
    from scripts import run_lock

    config = _write_channels(tmp_path, _RC_ENABLED)
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    sends: list[str] = []
    monkeypatch.setattr(
        rocketchat_webhook, "send",
        lambda text, *, webhook_url: sends.append(text) or True,
    )
    receipt_dir = tmp_path / ".delivered"
    lock_path = receipt_dir / deliver.DELIVERY_LOCK_NAME

    # Simulate a concurrent delivery already in progress (live pid, fresh lease).
    held = run_lock.acquire(lock_path, note="other-delivery")
    assert held.acquired

    rc = deliver.deliver(digest_file, config, receipt_dir=receipt_dir)
    assert rc == 1
    assert sends == [], "a held lock must prevent any send (no double-send)"
    assert "already in progress" in capsys.readouterr().out

    # Once the other delivery finishes, a fresh run proceeds and sends once.
    run_lock.release(lock_path, token=held.token)
    rc2 = deliver.deliver(digest_file, config, receipt_dir=receipt_dir)
    assert rc2 == 0
    assert len(sends) == 1
    # The lock is released after a normal run — no stale lockfile left behind.
    assert not lock_path.exists()


def test_dry_run_never_locks(tmp_path, digest_file, monkeypatch):
    # A dry-run is a pure check: it must not be blocked by a held delivery lock
    # and must not create one.
    from scripts import run_lock

    config = _write_channels(tmp_path, _RC_ENABLED)
    receipt_dir = tmp_path / ".delivered"
    lock_path = receipt_dir / deliver.DELIVERY_LOCK_NAME
    held = run_lock.acquire(lock_path, note="other-delivery")
    assert held.acquired

    # Even with the lock held, the dry-run check returns 0 (never blocked).
    assert deliver.deliver(digest_file, config, dry_run=True, receipt_dir=receipt_dir) == 0


def test_all_disabled_is_noop_even_with_held_lock(tmp_path, digest_file, capsys):
    # A run with NO enabled channels has nothing to send (and nothing to
    # double-send), so a held .delivery.lock must NOT turn the no-op into a
    # spurious "another delivery is already in progress" exit-1. The lock only
    # serializes real deliveries — it must be acquired AFTER the enabled-channel check.
    from scripts import run_lock

    config = _write_channels(tmp_path, """
delivery:
  language: en
  email:
    enabled: false
    provider: smtp
  telegram:
    enabled: false
    transport: bot-api
  rocketchat:
    enabled: false
""")
    receipt_dir = tmp_path / ".delivered"
    lock_path = receipt_dir / deliver.DELIVERY_LOCK_NAME
    held = run_lock.acquire(lock_path, note="other-delivery")
    assert held.acquired

    rc = deliver.deliver(digest_file, config, receipt_dir=receipt_dir)
    out = capsys.readouterr().out
    assert rc == 0
    assert "no enabled channels" in out
    assert "already in progress" not in out
    run_lock.release(lock_path, token=held.token)


# --------------------------------------------------------------------------- #
# Durable runtime state — RESEARCH_BRAIN_STATE_DIR relocates the receipts
# (idempotency memory survives a clone / redeploy / state-wipe)
# --------------------------------------------------------------------------- #

_STATE_ENV = "RESEARCH_BRAIN_STATE_DIR"


def test_default_receipt_dir_in_repo_when_state_env_unset(monkeypatch):
    # Default (env unset): the module's DEFAULT_RECEIPT_DIR is the exact in-repo
    # path, recomputed here from the SAME resolver so we assert byte-for-byte the
    # default behavior is unchanged.
    monkeypatch.delenv(_STATE_ENV, raising=False)
    from importlib import reload

    from scripts.delivery import deliver as fresh
    reload(fresh)
    expected = fresh._PROJECT_ROOT / "pipeline" / "3-synthesis" / ".delivered"
    assert fresh.DEFAULT_RECEIPT_DIR == expected
    reload(fresh)  # restore (defensive — leave the module in its default state)


def test_state_env_relocates_default_receipt_dir(monkeypatch, tmp_path):
    # env SET: the module-level DEFAULT_RECEIPT_DIR relocates under the state dir,
    # preserving the pipeline/3-synthesis/.delivered substructure.
    state_dir = tmp_path / "persistent"
    monkeypatch.setenv(_STATE_ENV, str(state_dir))
    from importlib import reload

    from scripts.delivery import deliver as fresh
    reload(fresh)
    try:
        assert fresh.DEFAULT_RECEIPT_DIR == (
            state_dir / "pipeline" / "3-synthesis" / ".delivered"
        )
    finally:
        monkeypatch.delenv(_STATE_ENV, raising=False)
        reload(fresh)  # restore the in-repo default for the rest of the suite


def test_receipt_under_state_dir_survives_wiped_repo(tmp_path, digest_file, monkeypatch):
    # The core durability guarantee: with the state dir set, a receipt written on
    # run 1 lives under the persistent volume, so even after the in-repo receipt
    # dir is wiped (a fresh clone / redeploy) run 2 still finds it and skips the
    # already-delivered channel — no double-send.
    state_dir = tmp_path / "volume"
    in_repo_receipts = tmp_path / "repo" / "pipeline" / "3-synthesis" / ".delivered"
    config = _rocketchat_config(tmp_path)
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    monkeypatch.setenv(_STATE_ENV, str(state_dir))

    # The in-repo default the caller would pass; with the env set it relocates.
    from scripts.state import state_root
    relocated = state_root(in_repo_receipts, project_root=tmp_path / "repo")
    assert relocated.is_relative_to(state_dir)

    calls = {"n": 0}
    monkeypatch.setattr(
        rocketchat_webhook, "send",
        lambda text, *, webhook_url: calls.__setitem__("n", calls["n"] + 1) or True,
    )
    # Run 1 sends and writes the receipt onto the volume.
    assert deliver.deliver(digest_file, config, receipt_dir=relocated) == 0
    assert calls["n"] == 1
    receipt_on_volume = deliver.receipt_path(digest_file, relocated)
    assert receipt_on_volume.exists()

    # Simulate a wiped repo: the in-repo receipt dir is empty / gone, but the
    # volume still holds the receipt. Run 2 (same relocated dir) must skip.
    assert not in_repo_receipts.exists()
    assert deliver.deliver(digest_file, config, receipt_dir=relocated) == 0
    assert calls["n"] == 1, "receipt on the persistent volume must prevent a re-send"


def test_state_env_set_after_import_relocates_receipt_lazily(tmp_path, monkeypatch):
    # The receipt-dir default must be resolved LAZILY (at call time), not frozen at
    # module-import time — matching health.py / synthesis_freshness.py. A deployment
    # that sets RESEARCH_BRAIN_STATE_DIR *after* this module was first imported (the
    # common case: env wired up by the runtime, not the interpreter) must still see
    # the receipt + .delivery.lock land under the state dir. With an import-time
    # constant this env is ignored and the receipt lands in-repo instead.
    state_dir = tmp_path / "late-volume"
    monkeypatch.setenv(_STATE_ENV, str(state_dir))  # set AFTER `deliver` was imported

    # A uniquely-named digest so the in-repo default path can't collide with any
    # real runtime receipt sitting in pipeline/3-synthesis/.delivered.
    digest = tmp_path / "digest_lazy-state-probe.md"
    digest.write_text("# probe digest\n", encoding="utf-8")
    in_repo_default = deliver._PROJECT_ROOT / "pipeline" / "3-synthesis" / ".delivered"
    assert not (in_repo_default / f"{digest.stem}.json").exists()  # clean precondition

    config = _rocketchat_config(tmp_path)
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    monkeypatch.setattr(rocketchat_webhook, "send", lambda text, *, webhook_url: True)

    # No explicit receipt_dir: deliver() must resolve the default lazily and honor
    # the env set above, relocating the receipt under the state volume.
    assert deliver.deliver(digest, config) == 0

    # The receipt now lives under the state dir (proving lazy resolution), not under
    # the in-repo pipeline/3-synthesis/.delivered default.
    relocated_dir = state_dir / "pipeline" / "3-synthesis" / ".delivered"
    assert deliver.receipt_path(digest, relocated_dir).exists()
    assert not (in_repo_default / f"{digest.stem}.json").exists()


# --------------------------------------------------------------------------- #
# BUG 1 — SMTP partial-recipient silent loss
# --------------------------------------------------------------------------- #


def test_email_partial_recipient_refusal_is_sent_not_resent(monkeypatch, capsys):
    # smtplib.SMTP.sendmail() only raises SMTPRecipientsRefused when ALL recipients
    # are rejected. With a multi-recipient list, a single refused address makes
    # sendmail() return a NON-EMPTY refused dict and NOT raise — the message WAS
    # delivered to the accepted recipients. Returning False here would mark the
    # channel FAILED and the idempotent retry would re-send to EVERYONE, duplicating
    # the digest for those who already received it. So a partial refusal is a
    # successful send (True), with the refused addresses logged to stderr.
    refused = {"bad@example.com": (550, b"User unknown")}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, *, context=None):
            pass

        def login(self, user, password):
            pass

        def sendmail(self, sender, to, msg):
            # Mirror stdlib: a per-recipient refusal is RETURNED, not raised.
            return refused

    monkeypatch.setattr(email_smtp.smtplib, "SMTP", FakeSMTP)
    ok = email_smtp.send(
        "Subj", "body",
        to=["good@example.com", "bad@example.com"],
        host="h", port=587, user="me@example.com", password="pw",
    )
    assert ok is True  # accepted recipients got it — must NOT trigger a full re-send
    err = capsys.readouterr().err
    # The refused recipient is surfaced (addresses are not secrets)…
    assert "bad@example.com" in err
    # …but the credential is never printed.
    assert "pw" not in err


def test_email_all_recipients_accepted_returns_true(monkeypatch):
    # Regression guard: an EMPTY refused dict (every recipient accepted) is success.
    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, *, context=None):
            pass

        def login(self, user, password):
            pass

        def sendmail(self, sender, to, msg):
            return {}  # no refusals -> all accepted

    monkeypatch.setattr(email_smtp.smtplib, "SMTP", FakeSMTP)
    assert email_smtp.send(
        "Subj", "body",
        to=["a@example.com", "b@example.com"],
        host="h", port=587, user="me@example.com", password="pw",
    ) is True


def test_email_send_detailed_surfaces_refused_recipients(monkeypatch):
    # send_detailed exposes the refused recipients (which bare send() only logs to
    # stderr) so the dispatcher can warn the operator in the delivery summary.
    refused = {"bad@example.com": (550, b"no such user")}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, *, context=None):
            pass

        def login(self, user, password):
            pass

        def sendmail(self, sender, to, msg):
            return refused

    monkeypatch.setattr(email_smtp.smtplib, "SMTP", FakeSMTP)
    result = email_smtp.send_detailed(
        "Subj", "body",
        to=["good@example.com", "bad@example.com"],
        host="h", port=587, user="me@example.com", password="pw",
    )
    assert result.ok is True
    assert result.refused == ["bad@example.com"]
    assert bool(result) is True  # __bool__ preserves the send() contract
    # The thin send() wrapper still returns a plain bool.
    monkeypatch.setattr(email_smtp.smtplib, "SMTP", FakeSMTP)
    assert email_smtp.send(
        "Subj", "body", to=["good@example.com", "bad@example.com"],
        host="h", port=587, user="me@example.com", password="pw",
    ) is True


def test_dispatcher_email_partial_refusal_warns_in_summary(
    tmp_path, digest_file, monkeypatch, capsys
):
    # A partial refusal is SENT (no re-send), but the operator summary must flag
    # the refused recipients — not bury them only in stderr.
    config = _write_channels(tmp_path, """
delivery:
  email:
    enabled: true
    provider: smtp
    to: ["good@example.com", "bad@example.com"]
    smtp:
      host: smtp.example.com
      port: 587
      user: me@example.com
      password_env: SMTP_PASSWORD
""")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setattr(
        email_smtp, "send_detailed",
        lambda subject, body, **kw: email_smtp.EmailSendResult(
            ok=True, refused=["bad@example.com"]
        ),
    )
    assert deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered") == 0
    out = capsys.readouterr().out
    assert "email" in out and "SENT" in out
    assert "bad@example.com" in out  # the refusal is visible in the stdout summary


def test_dispatcher_rocketchat_unsafe_url_is_distinct_from_post_failure(
    tmp_path, digest_file, monkeypatch, capsys
):
    # An unsafe webhook URL must be reported as a URL/config rejection, NOT as a
    # generic "webhook POST failed" — and send() must never be attempted.
    config = _write_channels(tmp_path, """
delivery:
  rocketchat:
    enabled: true
    webhook_url_env: ROCKETCHAT_WEBHOOK_URL
""")
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "http://127.0.0.1/hooks/x")

    def must_not_send(text, *, webhook_url):
        raise AssertionError("send must not be invoked when the guard refuses")

    monkeypatch.setattr(rocketchat_webhook, "send", must_not_send)
    assert deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered") == 1
    out = capsys.readouterr().out.lower()
    assert "rocketchat" in out and "failed" in out
    assert "url rejected" in out  # distinct, config-specific reason
    assert "post failed" not in out


# --------------------------------------------------------------------------- #
# BUG 2 — partial multi-channel delivery records only succeeded channels
# --------------------------------------------------------------------------- #


def test_partial_delivery_records_only_succeeded_channel(tmp_path, digest_file, monkeypatch):
    # BUG 2: when one channel succeeds and another fails in the same run, the
    # receipt must record the success as `sent` and the failure as `failed` — so a
    # re-run retries ONLY the failed channel and never re-sends the succeeded one.
    config = _write_channels(tmp_path, """
delivery:
  rocketchat:
    enabled: true
    webhook_url_env: ROCKETCHAT_WEBHOOK_URL
  telegram:
    enabled: true
    transport: bot-api
    chat_id: "42"
    token_env: TELEGRAM_BOT_TOKEN
""")
    receipt_dir = tmp_path / ".delivered"
    monkeypatch.setenv("ROCKETCHAT_WEBHOOK_URL", "https://rc.example/hooks/x")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")

    rc_calls = {"n": 0}
    tg_calls = {"n": 0}

    def rc_send(text, *, webhook_url):
        rc_calls["n"] += 1
        return True  # rocketchat succeeds

    def tg_send(text, *, token, chat_id, parse_mode=None, render_markdown=False):
        tg_calls["n"] += 1
        return telegram_botapi.TelegramSendResult(False, "HTTP 500")  # telegram fails

    monkeypatch.setattr(rocketchat_webhook, "send", rc_send)
    monkeypatch.setattr(telegram_botapi, "send_detailed", tg_send)

    # Run 1: telegram fails -> overall non-zero, but rocketchat succeeded.
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 1
    rcpt = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))
    assert rcpt["rocketchat"]["status"] == deliver.RECEIPT_SENT
    assert rcpt["telegram"]["status"] == deliver.RECEIPT_FAILED
    assert rc_calls["n"] == 1 and tg_calls["n"] == 1

    # Run 2: telegram now recovers. The succeeded rocketchat must NOT be re-sent
    # (idempotent skip), and only telegram is retried.
    monkeypatch.setattr(
        telegram_botapi, "send_detailed",
        lambda text, *, token, chat_id, parse_mode=None, render_markdown=False:
            tg_calls.__setitem__("n", tg_calls["n"] + 1)
            or telegram_botapi.TelegramSendResult(True, None),
    )
    assert deliver.deliver(digest_file, config, receipt_dir=receipt_dir) == 0
    assert rc_calls["n"] == 1, "succeeded channel must not be re-sent on a retry run"
    assert tg_calls["n"] == 2, "only the failed channel is retried"
    rcpt = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))
    assert rcpt["rocketchat"]["status"] == deliver.RECEIPT_SENT
    assert rcpt["telegram"]["status"] == deliver.RECEIPT_SENT


# --------------------------------------------------------------------------- #
# MCP-path idempotency — record-mcp / mcp-status share the headless receipt
# --------------------------------------------------------------------------- #


def test_record_mcp_stamps_receipt(tmp_path, digest_file):
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    rc = deliver.record_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir)
    assert rc == 0
    rcpt = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))
    assert rcpt["telegram"]["status"] == deliver.RECEIPT_SENT
    expected_hash = deliver.content_hash(digest_file.read_text(encoding="utf-8"))
    assert rcpt["telegram"][deliver.RECEIPT_CONTENT_HASH] == expected_hash


def test_record_mcp_rejects_non_mcp_channel(tmp_path, digest_file, capsys):
    # bot-api telegram is the HEADLESS transport — its receipt is owned by
    # deliver(); stamping it from the MCP path would fake a send.
    config = _telegram_botapi_config(tmp_path)
    rc = deliver.record_mcp(digest_file, "telegram", config, receipt_dir=tmp_path / ".d")
    assert rc == 2
    assert "not agent-delivered" in capsys.readouterr().err


def test_record_mcp_stamps_rocketchat(tmp_path, digest_file):
    # In MCP mode the agent skill POSTs the Rocket.Chat webhook itself (there is no
    # MCP transport for it), so it must be able to STAMP the shared receipt — else a
    # re-run has no idempotency signal and re-sends the digest. record-mcp must
    # accept rocketchat even though it is not an MCP transport.
    config = _rocketchat_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    rc = deliver.record_mcp(digest_file, "rocketchat", config, receipt_dir=receipt_dir)
    assert rc == 0
    rcpt = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))
    assert rcpt["rocketchat"]["status"] == deliver.RECEIPT_SENT
    expected_hash = deliver.content_hash(digest_file.read_text(encoding="utf-8"))
    assert rcpt["rocketchat"][deliver.RECEIPT_CONTENT_HASH] == expected_hash


def test_mcp_status_reports_enabled_rocketchat(tmp_path, digest_file, capsys):
    # The MCP-mode pre-send check must SEE rocketchat, so the skill can skip an
    # already-delivered one instead of re-POSTing the webhook every run.
    config = _rocketchat_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    assert deliver.mcp_status(digest_file, config, receipt_dir=receipt_dir) == 0
    assert "rocketchat" in capsys.readouterr().out  # reported, PENDING at first

    deliver.record_mcp(digest_file, "rocketchat", config, receipt_dir=receipt_dir)
    capsys.readouterr()
    deliver.mcp_status(digest_file, config, receipt_dir=receipt_dir)
    assert "DELIVERED" in capsys.readouterr().out


def test_record_mcp_rejects_unknown_channel(tmp_path, digest_file, capsys):
    config = _mcp_only_config(tmp_path)
    rc = deliver.record_mcp(digest_file, "smoke-signals", config, receipt_dir=tmp_path / ".d")
    assert rc == 2
    assert "unknown channel" in capsys.readouterr().err


def test_record_mcp_refuses_on_held_delivery_lock(tmp_path, digest_file, capsys):
    from scripts.run_lock import acquire

    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    receipt_dir.mkdir()
    lock = receipt_dir / deliver.DELIVERY_LOCK_NAME
    held = acquire(lock, note="other-delivery")
    assert held.acquired
    rc = deliver.record_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir)
    assert rc == 1
    assert deliver.DELIVERY_IN_PROGRESS_MESSAGE in capsys.readouterr().out


def test_mcp_status_pending_then_delivered_then_content_change(tmp_path, digest_file, capsys):
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"

    assert deliver.mcp_status(digest_file, config, receipt_dir=receipt_dir) == 0
    out = capsys.readouterr().out
    assert "telegram" in out and "email" in out
    assert out.count("PENDING") == 2

    deliver.record_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir)
    capsys.readouterr()
    deliver.mcp_status(digest_file, config, receipt_dir=receipt_dir)
    out = capsys.readouterr().out
    assert "DELIVERED" in out  # telegram
    assert "PENDING" in out    # email still pending

    # Rebuild with different content: the recorded hash no longer matches, so
    # telegram must read as needing a send again, not as delivered.
    digest_file.write_text(
        digest_file.read_text(encoding="utf-8") + "\nrebuilt\n", encoding="utf-8"
    )
    deliver.mcp_status(digest_file, config, receipt_dir=receipt_dir)
    out = capsys.readouterr().out
    assert "DELIVERED" not in out


def test_chunk_progress_keeps_the_reservation_and_records_the_resume_point(
    tmp_path, digest_file, capsys
):
    """A long chunked send must be resumable, and must not expire mid-flight.

    External review 2026-07-25 P2: a Telegram body over 4096 chars is split and
    sent as N messages, but the receipt is per CHANNEL — so a failure after
    chunk 3 of 5 left nothing recorded, and a later run re-sent chunks 1-3 that
    the user had already received. Recording progress also refreshes the
    reservation, so a slow multi-chunk send cannot outlive its own claim.
    """
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    assert deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir) == 0

    assert (
        deliver.record_mcp(
            digest_file, "telegram", config, receipt_dir=receipt_dir, chunks_sent=3
        )
        == 0
    )

    rcpt = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))
    entry = rcpt["telegram"]
    assert entry["status"] == deliver.RECEIPT_SENDING, "progress is not a completed send"
    # Stored as a string so receipt entries stay dict[str, str]; read it back
    # through the parser the delivery path uses.
    assert receipts_mod.chunk_progress(entry) == 3

    capsys.readouterr()
    deliver.mcp_status(digest_file, config, receipt_dir=receipt_dir)
    out = capsys.readouterr().out
    assert "IN-FLIGHT" in out
    assert "3 chunk" in out, "the resume point must be visible to the next sender"


def test_recording_the_final_send_clears_chunk_progress(tmp_path, digest_file):
    """Once the channel is delivered, stale progress must not linger."""
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir)
    deliver.record_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir, chunks_sent=3)

    assert deliver.record_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir) == 0

    entry = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))["telegram"]
    assert entry["status"] == deliver.RECEIPT_SENT
    assert "chunks_sent" not in entry


def test_cli_records_chunk_progress(tmp_path, digest_file, monkeypatch):
    config = _mcp_only_config(tmp_path)
    monkeypatch.setenv("RESEARCH_BRAIN_STATE_DIR", str(tmp_path / "state"))
    assert deliver.main([str(digest_file), str(config), "--reserve-mcp", "telegram"]) == 0

    rc = deliver.main(
        [str(digest_file), str(config), "--record-mcp", "telegram", "--chunks-sent", "2"]
    )
    assert rc == 0


def test_mcp_status_annotates_a_legacy_receipt_without_a_content_hash(
    tmp_path, digest_file, capsys
):
    """Reported DELIVERED (per-digest keying makes that right) but marked legacy.

    See `test_headless_skip_marks_a_hash_less_receipt_as_unverified` for why the
    verdict stands and only the wording changes.
    """
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    deliver.write_receipt(
        deliver.receipt_path(digest_file, receipt_dir),
        {"telegram": {"status": deliver.RECEIPT_SENT, "timestamp": "2026-01-01T00:00:00+00:00"}},
    )

    assert deliver.mcp_status(digest_file, config, receipt_dir=receipt_dir) == 0
    out = capsys.readouterr().out

    assert "DELIVERED" in out
    assert "legacy receipt" in out, "the unverifiable-content limit must be stated"


def test_reserve_mcp_agrees_with_status_on_a_hash_less_receipt(tmp_path, digest_file):
    """The three readers must apply ONE match rule.

    If `--mcp-status` said DELIVERED while `--reserve-mcp` handed out the
    channel, the skill would be told to skip and to send at the same time.
    """
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    deliver.write_receipt(
        deliver.receipt_path(digest_file, receipt_dir),
        {"telegram": {"status": deliver.RECEIPT_SENT, "timestamp": "2026-01-01T00:00:00+00:00"}},
    )

    rc = deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir)

    assert rc == 3, "already-delivered per status must also be refused by reserve"


def test_mcp_status_no_mcp_channels(tmp_path, digest_file, capsys):
    config = _telegram_botapi_config(tmp_path)
    assert deliver.mcp_status(digest_file, config, receipt_dir=tmp_path / ".d") == 0
    assert "no enabled MCP channels" in capsys.readouterr().out


def test_cli_record_mcp_and_status_roundtrip(tmp_path, digest_file, monkeypatch, capsys):
    config = _mcp_only_config(tmp_path)
    monkeypatch.setenv("RESEARCH_BRAIN_STATE_DIR", str(tmp_path / "state"))

    rc = deliver.main([str(digest_file), str(config), "--record-mcp", "telegram"])
    assert rc == 0
    assert "recorded" in capsys.readouterr().out

    rc = deliver.main([str(digest_file), str(config), "--mcp-status"])
    assert rc == 0
    assert "DELIVERED" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# MCP-path reservation — claim the channel BEFORE the external send
#
# External review 2026-07-25 P1: the MCP sequence was status -> send -> record.
# Nothing was written before the external side effect, so two agents that both
# read PENDING both sent the digest and only then serialised on the receipt
# write. `reserve_mcp` claims the channel first, under the same .delivery.lock,
# so the second agent is refused BEFORE it sends.
#
# Honest limit, pinned by the lease test below: an external send is not
# transactional, so this converts a silent double-send into a refusal — it
# cannot make one impossible if a reserving agent dies mid-send.
# --------------------------------------------------------------------------- #


def test_reserve_mcp_claims_the_channel(tmp_path, digest_file):
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"

    assert deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir) == 0

    rcpt = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))
    assert rcpt["telegram"]["status"] == deliver.RECEIPT_SENDING
    expected_hash = deliver.content_hash(digest_file.read_text(encoding="utf-8"))
    assert rcpt["telegram"][deliver.RECEIPT_CONTENT_HASH] == expected_hash


def test_second_reserve_of_the_same_channel_is_refused(tmp_path, digest_file, capsys):
    """The whole point: agent B must not reach its send at all."""
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"

    assert deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir) == 0
    capsys.readouterr()

    rc = deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir)

    assert rc != 0, "a channel already claimed by another sender must be refused"
    assert "in flight" in capsys.readouterr().out.lower()


def test_reserve_mcp_refuses_an_already_delivered_channel(tmp_path, digest_file, capsys):
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    deliver.record_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir)
    capsys.readouterr()

    rc = deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir)

    assert rc != 0
    assert "delivered" in capsys.readouterr().out.lower()


def test_record_mcp_promotes_a_reservation_to_sent(tmp_path, digest_file):
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir)

    assert deliver.record_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir) == 0

    rcpt = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))
    assert rcpt["telegram"]["status"] == deliver.RECEIPT_SENT


def test_reserve_mcp_reclaims_an_abandoned_reservation(tmp_path, digest_file, monkeypatch):
    """A reserving agent that dies mid-send must not block the channel forever.

    This is also the honest limit of the mechanism: past the lease the channel is
    re-sendable, so a *very* slow send can still be duplicated. The lease is sized
    (like the delivery lock's) to exceed a realistic multi-chunk send.
    """
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir)

    # Age the reservation past its lease by rewriting its timestamp.
    rcpt_path = deliver.receipt_path(digest_file, receipt_dir)
    rcpt = deliver.load_receipt(rcpt_path)
    stale = datetime.now(UTC) - timedelta(seconds=deliver.RESERVATION_LEASE + 60)
    rcpt["telegram"]["timestamp"] = stale.isoformat(timespec="seconds")
    deliver.write_receipt(rcpt_path, rcpt)

    assert deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir) == 0


def test_reserve_mcp_recovers_from_a_reservation_with_a_corrupt_timestamp(
    tmp_path, digest_file
):
    """A garbage timestamp must not make a channel permanently unsendable.

    Self-review of the reservation work: treating an unparseable timestamp as a
    LIVE claim looks like the fail-safe choice, but a `sending` entry is only
    ever cleared by a successful send — so if every sender is refused, nothing
    can ever clear it and the channel is silently dead forever. An expired
    reading is recoverable and still cannot resurrect a real delivery, because
    an actually-delivered channel is recorded as `sent`, not `sending`.
    """
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    assert deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir) == 0

    rcpt_path = deliver.receipt_path(digest_file, receipt_dir)
    rcpt = deliver.load_receipt(rcpt_path)
    rcpt["telegram"]["timestamp"] = "not-a-timestamp"
    deliver.write_receipt(rcpt_path, rcpt)

    assert deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir) == 0


def test_recorded_status_is_always_a_known_value(tmp_path, digest_file):
    """Guard against an invalid state being representable at all.

    `record_mcp` picks between `sending` and `sent`; a caller that omitted the
    `sending` token would have written an empty status that no reader matches,
    leaving the channel in limbo. Pinned across both branches.
    """
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    known = {deliver.RECEIPT_SENT, deliver.RECEIPT_SENDING, deliver.RECEIPT_FAILED}

    deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir)
    deliver.record_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir, chunks_sent=1)
    partial = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))["telegram"]

    deliver.record_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir)
    final = deliver.load_receipt(deliver.receipt_path(digest_file, receipt_dir))["telegram"]

    assert partial["status"] in known
    assert final["status"] in known


def test_reserve_mcp_refuses_on_held_delivery_lock(tmp_path, digest_file, capsys):
    from scripts.run_lock import acquire

    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    receipt_dir.mkdir()
    held = acquire(receipt_dir / deliver.DELIVERY_LOCK_NAME, note="other-delivery")
    assert held.acquired

    rc = deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir)

    assert rc == 1
    assert deliver.DELIVERY_IN_PROGRESS_MESSAGE in capsys.readouterr().out


def test_reserve_mcp_rejects_a_headless_owned_channel(tmp_path, digest_file, capsys):
    config = _telegram_botapi_config(tmp_path)
    rc = deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=tmp_path / ".d")
    assert rc == 2
    assert "not agent-delivered" in capsys.readouterr().err


def test_mcp_status_reports_an_in_flight_reservation(tmp_path, digest_file, capsys):
    """The skill's pre-send check must distinguish "nobody has this" from
    "someone is sending it right now" — otherwise it races anyway."""
    config = _mcp_only_config(tmp_path)
    receipt_dir = tmp_path / ".delivered"
    deliver.reserve_mcp(digest_file, "telegram", config, receipt_dir=receipt_dir)
    capsys.readouterr()

    assert deliver.mcp_status(digest_file, config, receipt_dir=receipt_dir) == 0
    out = capsys.readouterr().out
    assert "IN-FLIGHT" in out
    assert "PENDING" in out  # email is untouched and still sendable


def test_cli_reserve_mcp_roundtrip(tmp_path, digest_file, monkeypatch, capsys):
    config = _mcp_only_config(tmp_path)
    monkeypatch.setenv("RESEARCH_BRAIN_STATE_DIR", str(tmp_path / "state"))

    assert deliver.main([str(digest_file), str(config), "--reserve-mcp", "telegram"]) == 0
    capsys.readouterr()
    # A second reservation from the CLI is refused with a non-zero exit, which is
    # what stops the skill from sending.
    assert deliver.main([str(digest_file), str(config), "--reserve-mcp", "telegram"]) != 0


# --------------------------------------------------------------------------- #
# quiet-week detection — structural marker, not English wording
# --------------------------------------------------------------------------- #


def test_is_quiet_digest_detects_html_marker_regardless_of_language():
    # A localized (e.g. Russian) quiet digest has no "Quiet week —" line; the
    # structural marker must still be recognized.
    text = (
        "# Еженедельный дайджест — 2026-07-03\n\n"
        "Тихая неделя — ничего нового за последние 7 дней.\n\n"
        "<!-- research-brain: quiet-digest -->\n"
    )
    assert deliver.is_quiet_digest(text)


def test_is_quiet_digest_legacy_english_line_still_detected():
    text = "# Weekly digest — 2026-07-03\n\nQuiet week — nothing new surfaced.\n"
    assert deliver.is_quiet_digest(text)


def test_quiet_marker_constant_in_sync_with_digest_model():
    # deliver.py keeps an inline copy to avoid a cross-package import; this
    # drift-guard is what makes that duplication safe.
    from scripts.digest.model import QUIET_DIGEST_HTML_MARKER

    assert deliver.QUIET_DIGEST_HTML_MARKER == QUIET_DIGEST_HTML_MARKER


# --------------------------------------------------------------------------- #
# Failure REASONS survive the adapter boundary (2026-07-14 review P2.1):
# a 401 bad token, a 403 bot-block, and a transient 500 used to print the
# identical "FAILED" line and record the identical health event — the first
# cron failure on a handed-over box was undiagnosable without reproducing by
# hand. The adapters now report WHY; the line, the receipt, and the health
# event carry it. Secrets (token / URL) must never appear in the reason.
# --------------------------------------------------------------------------- #


def _http_error(code: int, description: str) -> urllib.error.HTTPError:
    import io

    body = f'{{"ok": false, "description": "{description}"}}'.encode()
    return urllib.error.HTTPError(
        "https://api.telegram.org/botSECRET/sendMessage",
        code,
        "err",
        {},  # type: ignore[arg-type]
        io.BytesIO(body),
    )


def test_telegram_send_detailed_carries_http_reason(monkeypatch):
    def boom(*_a, **_k):
        raise _http_error(401, "Unauthorized: invalid token")

    monkeypatch.setattr(telegram_botapi.urllib.request, "urlopen", boom)
    result = telegram_botapi.send_detailed("x", token="SECRET-TOKEN", chat_id="42")
    assert result.ok is False
    assert result.reason is not None
    assert "HTTP 401" in result.reason
    assert "Unauthorized" in result.reason
    assert "SECRET-TOKEN" not in result.reason
    assert "api.telegram.org" not in result.reason  # URL embeds the token


def test_telegram_send_detailed_carries_network_reason(monkeypatch):
    def boom(*_a, **_k):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(telegram_botapi.urllib.request, "urlopen", boom)
    result = telegram_botapi.send_detailed("x", token="T", chat_id="42")
    assert result.ok is False
    assert "timed out" in (result.reason or "")


def test_telegram_send_bool_contract_unchanged(monkeypatch):
    # The public bool `send()` stays a bool (monkeypatch-friendly contract).
    def boom(*_a, **_k):
        raise urllib.error.URLError("nope")

    monkeypatch.setattr(telegram_botapi.urllib.request, "urlopen", boom)
    assert telegram_botapi.send("x", token="T", chat_id="42") is False


def test_email_send_detailed_carries_smtp_reason(monkeypatch):
    import smtplib

    def boom(*_a, **_k):
        raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Bad credentials")

    monkeypatch.setattr(email_smtp, "_smtp_send", boom)
    result = email_smtp.send_detailed(
        "s", "b", to=["a@example.com"], host="smtp.example.com",
        port=587, user="u@example.com", password="pw",
    )
    assert result.ok is False
    assert "SMTPAuthenticationError" in (result.reason or "")
    assert "535" in (result.reason or "")
    assert "pw" not in (result.reason or "")


def test_failed_send_prints_reason_and_records_it_everywhere(
    tmp_path, digest_file, monkeypatch, capsys
):
    # End to end through the dispatcher: the FAILED line names the cause, the
    # receipt persists it, and the health event carries it for /status forensics.
    import json

    import scripts.health as health

    monkeypatch.setattr(deliver, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(deliver, "_default_receipt_dir", lambda: tmp_path / ".delivered")
    config = _write_channels(tmp_path, """
delivery:
  telegram:
    enabled: true
    transport: bot-api
    chat_id: "42"
""")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "SECRET-TOKEN")
    monkeypatch.setattr(
        telegram_botapi,
        "send_detailed",
        lambda *a, **k: telegram_botapi.TelegramSendResult(
            False, "HTTP 401 — Unauthorized: invalid token"
        ),
    )
    rc = deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered")
    assert rc != 0
    out = capsys.readouterr().out
    assert "HTTP 401" in out
    assert "SECRET-TOKEN" not in out

    receipt = json.loads(
        (tmp_path / ".delivered" / f"{digest_file.stem}.json").read_text(encoding="utf-8")
    )
    assert receipt["telegram"]["status"] == "failed"
    assert "HTTP 401" in receipt["telegram"]["reason"]

    # The CLI records health from the receipt right after the run — same hook.
    deliver._record_delivery_health(digest_file, channels=None)
    events = health.load_events(tmp_path)
    deliver_events = [e for e in events if e["kind"] == "deliver"]
    assert deliver_events
    assert any("HTTP 401" in e.get("reason", "") for e in deliver_events)


def test_successful_send_receipt_has_no_reason(tmp_path, digest_file, monkeypatch):
    import json

    config = _write_channels(tmp_path, """
delivery:
  telegram:
    enabled: true
    transport: bot-api
    chat_id: "42"
""")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(
        telegram_botapi,
        "send_detailed",
        lambda *a, **k: telegram_botapi.TelegramSendResult(True, None),
    )
    rc = deliver.deliver(digest_file, config, receipt_dir=tmp_path / ".delivered")
    assert rc == 0
    receipt = json.loads(
        (tmp_path / ".delivered" / f"{digest_file.stem}.json").read_text(encoding="utf-8")
    )
    assert receipt["telegram"]["status"] == "sent"
    assert "reason" not in receipt["telegram"]
