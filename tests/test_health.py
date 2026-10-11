"""
test_health.py — offline tests for the operational health / run-history log.

Every test builds a self-contained fake vault under a tmp dir and drives
`scripts/health.py` against it, so the real vault is never touched. No network.
The event log is plain JSONL, so these tests need no PyYAML.
"""
from datetime import date
from pathlib import Path

import pytest

from scripts import health as h  # noqa: E402

TODAY = date(2026, 6, 19)


@pytest.fixture(autouse=True)
def _isolate_state_env(monkeypatch):
    """Clear RESEARCH_BRAIN_STATE_DIR so these in-repo tests are hermetic.

    The event log relocates onto a persistent volume when this var is set; a
    developer who has it exported in their shell must still see this suite pass.
    The relocation-specific tests below re-set it explicitly.
    """
    monkeypatch.delenv("RESEARCH_BRAIN_STATE_DIR", raising=False)


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "pipeline" / "3-synthesis").mkdir(parents=True)
    return tmp_path


# --------------------------------------------------------------------------- #
# record / load round-trip
# --------------------------------------------------------------------------- #


def test_record_then_load_roundtrips(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    h.record_event(vault, "collect", source="https://a.com/feed", items=3)
    h.record_event(vault, "deliver", status="sent", channel="telegram")
    events = h.load_events(vault)
    assert len(events) == 2
    assert events[0]["kind"] == "collect" and events[0]["items"] == 3
    assert events[1]["status"] == "sent" and events[1]["channel"] == "telegram"
    assert all("ts" in e for e in events)


def test_load_missing_log_is_empty(tmp_path: Path) -> None:
    assert h.load_events(_vault(tmp_path)) == []


def test_load_tolerates_corrupt_line(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    h.record_event(vault, "run", status="ok")
    # Simulate a half-written final line.
    with h.events_path(vault).open("a", encoding="utf-8") as fh:
        fh.write('{"kind": "deliver", "status":\n')
    events = h.load_events(vault)
    assert len(events) == 1 and events[0]["kind"] == "run"


def test_record_is_best_effort_never_raises(tmp_path: Path) -> None:
    # Point root at a path whose parent can't be created (a file, not a dir).
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    # Should swallow the OSError rather than propagate.
    h.record_event(blocker, "collect", source="x", items=0)


# --------------------------------------------------------------------------- #
# feed_health — dead-feed detection
# --------------------------------------------------------------------------- #


def test_feed_health_flags_dead_after_threshold_of_failures(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    # alive.com keeps fetching OK; dead.com errors on its last 2 fetches.
    h.record_event(vault, "collect", source="https://alive.com", items=2)
    h.record_event(vault, "collect", source="https://dead.com", items=1)
    h.record_event(vault, "collect", source="https://alive.com", items=4)
    h.record_event(vault, "collect", source="https://dead.com", items=0, status="error")
    h.record_event(vault, "collect", source="https://dead.com", items=0, status="failed")

    feeds = {f.source: f for f in h.feed_health(h.load_events(vault))}
    assert feeds["https://alive.com"].healthy is True
    assert feeds["https://dead.com"].healthy is False
    assert feeds["https://dead.com"].consecutive_failures == 2


def test_feed_health_zero_items_success_is_healthy(tmp_path: Path) -> None:
    # Liveness is reachability, not publish frequency: a feed that fetches OK but
    # returns 0 new items — even repeatedly — is ALIVE, never flagged dead.
    vault = _vault(tmp_path)
    for _ in range(5):
        h.record_event(vault, "collect", source="https://s.com", items=0)
    feeds = h.feed_health(h.load_events(vault))
    assert feeds[0].healthy is True
    assert feeds[0].consecutive_failures == 0


def test_feed_health_error_status_counts_as_failure(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    # Even with items recorded, an errored fetch is a failure (unreachable feed).
    h.record_event(vault, "collect", source="https://s.com", items=5, status="error")
    h.record_event(vault, "collect", source="https://s.com", items=5, status="error")
    feeds = h.feed_health(h.load_events(vault))
    assert feeds[0].healthy is False  # errored runs are not "alive"


# --------------------------------------------------------------------------- #
# delivery_health — latest status per channel
# --------------------------------------------------------------------------- #


def test_delivery_health_latest_wins(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    h.record_event(vault, "deliver", status="failed", channel="email")
    h.record_event(vault, "deliver", status="sent", channel="email")
    h.record_event(vault, "deliver", status="failed", channel="telegram")
    delivery = h.delivery_health(h.load_events(vault))
    assert delivery == {"email": "sent", "telegram": "failed"}


# --------------------------------------------------------------------------- #
# health_summary — roll-up verdict
# --------------------------------------------------------------------------- #


def test_summary_ok_when_all_green(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://s.com", items=3)
    h.record_event(vault, "deliver", status="sent", channel="telegram")
    summary = h.health_summary(vault, today=TODAY)
    assert summary.ok is True
    assert summary.last_digest_age_days == 1
    assert summary.dead_feeds == []


def test_summary_not_ok_on_stale_digest(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-01.md").write_text("# d\n")
    summary = h.health_summary(vault, today=TODAY)
    assert summary.digest_stale is True
    assert summary.ok is False


def test_summary_not_ok_on_dead_feed_or_failed_delivery(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "deliver", status="failed", channel="email")
    summary = h.health_summary(vault, today=TODAY)
    assert summary.ok is False
    assert "email" in summary.delivery


# --------------------------------------------------------------------------- #
# health_summary — 4-state status (UNCONFIGURED / UNKNOWN / DEGRADED / OK)
# --------------------------------------------------------------------------- #


def _write_sources(vault: Path, body: str) -> None:
    """Write a `config/sources.yaml` under the fake vault (parents created)."""
    sources = vault / "config" / "sources.yaml"
    sources.parent.mkdir(parents=True, exist_ok=True)
    sources.write_text(body, encoding="utf-8")


def _write_registry(vault: Path, rows: list[tuple[str, str, str]]) -> None:
    """Write `pipeline/registry.md` with `(collected, category, url)` rows.

    The real table is `collected | category | status | url | title`; status/title
    are filled with placeholders so the feed-liveness reader exercises the same
    column layout collection actually writes.
    """
    registry = vault / "pipeline" / "registry.md"
    registry.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "| collected  | category | status | url | title |",
        "|------------|----------|--------|-----|-------|",
    ]
    for collected, category, url in rows:
        lines.append(f"| {collected} | {category} |  | {url} | t |")
    registry.write_text("\n".join(lines) + "\n", encoding="utf-8")


# A minimal sources.yaml (schema 2) with ONE real active source.
_REAL_SOURCE_YAML = """\
schema_version: 2
categories:
  - name: ai
    sources:
      - url: "https://real.com/feed.xml"
        type: rss
        tier: high
        priority: high
        filter: all
        active: true
"""

# A sources.yaml carrying ONLY template furniture (a named category, zero real
# sources) — the YAML analog of the retired EXAMPLE-only .md template.
_TEMPLATE_ONLY_YAML = """\
schema_version: 2
categories:
  - name: example-topic
    sources: []
"""


def test_status_unconfigured_on_fresh_repo(tmp_path: Path) -> None:
    # A fresh vault: no sources (no collect events), no digest, no delivery/run.
    # UNCONFIGURED takes precedence — it is NOT "OK".
    vault = _vault(tmp_path)
    summary = h.health_summary(vault, today=TODAY)
    assert summary.status == h.Status.UNCONFIGURED
    assert summary.ok is False
    assert "⚙️" in h.render(summary)
    assert "UNCONFIGURED" in h.render(summary)


def test_status_configured_from_sources_yaml_without_events(tmp_path: Path) -> None:
    # A real source in config/sources.yaml proves configuration EVEN with no
    # collect events yet. The system must report configured (→ UNKNOWN, since it
    # has a source but has never produced a digest or any run/delivery activity)
    # — NOT UNCONFIGURED. This is the core defect: `configured` must derive from
    # the source registry, not from historical events.
    vault = _vault(tmp_path)
    _write_sources(vault, _REAL_SOURCE_YAML)
    summary = h.health_summary(vault, today=TODAY)
    assert summary.status == h.Status.UNKNOWN
    assert summary.ok is False


def test_status_unconfigured_with_only_template_sources(tmp_path: Path) -> None:
    # A sources.yaml holding ONLY template furniture (a category section with no
    # real source, like the shipped empty starter) is not really configured →
    # UNCONFIGURED. `monitored_sources` counts sources, not category sections.
    vault = _vault(tmp_path)
    _write_sources(vault, _TEMPLATE_ONLY_YAML)
    summary = h.health_summary(vault, today=TODAY)
    assert summary.status == h.Status.UNCONFIGURED
    assert summary.ok is False


def test_status_unknown_when_configured_but_never_ran(tmp_path: Path) -> None:
    # Has a source (a collect event proves configuration) but never produced a
    # digest and recorded no delivery/run activity → set up but never ran.
    vault = _vault(tmp_path)
    h.record_event(vault, "collect", source="https://s.com", items=2)
    summary = h.health_summary(vault, today=TODAY)
    assert summary.status == h.Status.UNKNOWN
    assert summary.ok is False
    assert "❓" in h.render(summary)
    assert "UNKNOWN" in h.render(summary)


def test_status_degraded_on_failed_run_event(tmp_path: Path) -> None:
    # Configured + has produced a digest, but a recorded `run` event failed →
    # DEGRADED (and a failed run is read from the event log, not ignored).
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://s.com", items=3)
    h.record_event(vault, "run", status="failed")
    summary = h.health_summary(vault, today=TODAY)
    assert summary.status == h.Status.DEGRADED
    assert summary.failed_run is True
    assert summary.ok is False
    assert "⚠️" in h.render(summary)
    assert "DEGRADED" in h.render(summary)


def test_status_ok_when_configured_and_functioned(tmp_path: Path) -> None:
    # Configured (a live source) AND functioned (a recent digest) AND no failure
    # signals → OK.
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://s.com", items=3)
    h.record_event(vault, "deliver", status="sent", channel="telegram")
    # An in-window run (deterministic ts) so the run-recency axis stays green
    # regardless of the wall clock relative to the fixture TODAY.
    h.record_event(vault, "run", status="ok", timestamp="2026-06-18T09:00:00+00:00")
    summary = h.health_summary(vault, today=TODAY)
    assert summary.status == h.Status.OK
    assert summary.ok is True
    assert "✅" in h.render(summary)


def test_render_contains_markers(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "deliver", status="sent", channel="telegram")
    text = h.render(h.health_summary(vault, today=TODAY))
    assert "System health" in text
    assert "Delivery [telegram]" in text


def test_health_degraded_findings_include_next_actions() -> None:
    summary = h.HealthSummary(
        status=h.Status.DEGRADED,
        last_digest_age_days=10,
        digest_stale=True,
        delivery={"email": "failed"},
        dead_feeds=[
            h.FeedStatus(
                source="https://dead.example/feed.xml",
                last_items=0,
                consecutive_failures=2,
                healthy=False,
            )
        ],
        live_feed_count=0,
        failed_run=True,
        run_overdue=True,
        gate_skipped=["ai-safety"],
    )

    text = h.render(summary)
    assert text.count("Next action:") >= 5
    assert "python3 scripts/doctor.py" in text
    assert "python3 scripts/delivery/deliver.py" in text
    assert "fix or pause the source with source-manage" in text
    assert "run the pipeline now" in text
    assert "python3 scripts/sanitize_incoming.py sanitize" in text


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_record_then_report(tmp_path: Path, capsys) -> None:
    vault = _vault(tmp_path)
    rc = h.main(["--root", str(vault), "record", "--kind", "collect",
                 "--source", "https://s.com", "--items", "2"])
    assert rc == 0
    assert h.load_events(vault)[0]["items"] == 2
    rc = h.main(["--root", str(vault), "report"])
    assert rc == 0
    assert "System health" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Regression: review-cycle-4 hardening
# --------------------------------------------------------------------------- #


def test_record_never_raises_on_nonserializable_detail(tmp_path: Path) -> None:
    # The "never raises" guarantee must hold for a non-JSON-serializable detail.
    vault = _vault(tmp_path)
    h.record_event(vault, "collect", source="x", items=0, weird={1, 2, 3})
    # Nothing was written (json.dumps failed), but no exception escaped.
    assert h.load_events(vault) == []


def test_record_never_raises_on_bad_root() -> None:
    # A non-Path/str root must not raise (guarantee is absolute).
    h.record_event(None, "collect", items=0)  # type: ignore[arg-type]


def test_summary_tolerates_event_without_ts(tmp_path: Path) -> None:
    # A valid-JSON but ts-less line (manual edit / older shape) must not crash
    # the user-facing health report.
    vault = _vault(tmp_path)
    path = h.events_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write('{"kind": "collect"}\n')
    summary = h.health_summary(vault, today=TODAY)  # must not raise
    assert summary.last_event_kind == "collect"
    assert h.render(summary)  # renders without error


def test_future_dated_digest_is_ignored(tmp_path: Path) -> None:
    # A future-dated digest must not mask a real stale one, nor render a negative age.
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-12-31.md").write_text("# d\n")
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-01.md").write_text("# d\n")
    summary = h.health_summary(vault, today=TODAY)
    assert summary.last_digest_age_days == 18  # 2026-06-19 - 2026-06-01
    assert summary.digest_stale is True


def test_delivery_error_status_flips_verdict(tmp_path: Path) -> None:
    # `error` (not just `failed`) must count as a delivery failure.
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "deliver", status="error", channel="email")
    summary = h.health_summary(vault, today=TODAY)
    assert summary.ok is False
    assert "❌ Delivery [email]: error" in h.render(summary)


# --------------------------------------------------------------------------- #
# Silently-degraded signal #1: gate-skip / degraded-topic hygiene event
# --------------------------------------------------------------------------- #


def test_gate_skip_event_makes_degraded_and_names_topic(tmp_path: Path) -> None:
    # A `hygiene` event with status `degraded` means the sanitize/synthesis gate
    # skipped a topic. The verdict must flip to DEGRADED and the report must NAME
    # the skipped topic (so /status surfaces "topic X was gate-skipped").
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://s.com", items=3)
    # Pin the ts to TODAY so the assertion is deterministic vs. the wall clock
    # (the non-future recency band excludes a ts dated after `today`).
    h.record_event(
        vault, "hygiene", status="degraded", note="ai-safety",
        timestamp="2026-06-19T09:00:00+00:00",
    )
    summary = h.health_summary(vault, today=TODAY)
    assert summary.status == h.Status.DEGRADED
    assert summary.gate_skipped == ["ai-safety"]
    assert summary.ok is False
    text = h.render(summary)
    assert "ai-safety" in text
    assert "gate-skipped" in text


def test_gate_skip_via_cli_record(tmp_path: Path) -> None:
    # The gate-skip event is emitted through the SAME `record` CLI path.
    vault = _vault(tmp_path)
    rc = h.main(["--root", str(vault), "record", "--kind", "hygiene",
                 "--status", "degraded", "--note", "robotics"])
    assert rc == 0
    # The CLI stamps the event with the wall clock; classify against the real
    # current date so the event lands inside the non-future recency band.
    summary = h.health_summary(vault, today=date.today())
    assert summary.gate_skipped == ["robotics"]


def test_gate_skip_today_degrades(tmp_path: Path) -> None:
    # A gate-skip dated TODAY is within the recency window → DEGRADED + named.
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://s.com", items=3)
    h.record_event(
        vault, "hygiene", status="degraded", note="ai-safety",
        timestamp="2026-06-19T09:00:00+00:00",
    )
    summary = h.health_summary(vault, today=TODAY)
    assert summary.gate_skipped == ["ai-safety"]
    assert summary.status == h.Status.DEGRADED


def test_old_gate_skip_ages_out(tmp_path: Path) -> None:
    # The SAME gate-skip event dated >8 days ago has been fixed/re-synthesized
    # since — it must age out: no longer DEGRADED on the gate-skip axis, so the
    # push-alert stops crying wolf every run.
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://s.com", items=3)
    h.record_event(vault, "deliver", status="sent", channel="telegram")
    h.record_event(vault, "run", status="ok", timestamp="2026-06-18T09:00:00+00:00")
    h.record_event(
        vault, "hygiene", status="degraded", note="ai-safety",
        timestamp="2026-06-01T09:00:00+00:00",  # >8 days before TODAY
    )
    summary = h.health_summary(vault, today=TODAY)
    assert summary.gate_skipped == []
    assert summary.status == h.Status.OK


# --------------------------------------------------------------------------- #
# built-but-undelivered digest — the last-mile gap the health view used to miss
# (live-proven: digest_2026-07-08/09 existed with no receipts while health
# stayed OK for 13 days; the on-disk builds masked the stale-digest trigger).
# --------------------------------------------------------------------------- #


def _enable_telegram_channel(vault: Path) -> None:
    """Minimal channels.yaml with one ENABLED delivery channel."""
    channels = vault / "config" / "channels.yaml"
    channels.parent.mkdir(parents=True, exist_ok=True)
    channels.write_text(
        "delivery:\n"
        "  language: en\n"
        "  telegram:\n"
        "    enabled: true\n"
        "    transport: bot-api\n"
        '    chat_id: "1"\n',
        encoding="utf-8",
    )


def _configured_vault_with_digest(tmp_path: Path, *, digest_stamp: str) -> Path:
    """Configured vault (collect event) + one real-looking digest file."""
    vault = _vault(tmp_path)
    _enable_telegram_channel(vault)
    (vault / "pipeline" / "3-synthesis" / f"digest_{digest_stamp}.md").write_text(
        f"# 🧠 Weekly digest — {digest_stamp}\n\n- something new\n", encoding="utf-8"
    )
    h.record_event(vault, "collect", source="https://s.com", items=3)
    return vault


def test_undelivered_digest_degrades_after_window(tmp_path: Path) -> None:
    # A non-quiet digest built 3 days ago, delivery enabled, NO receipt with a
    # `sent` entry -> the summary must say so and go DEGRADED.
    vault = _configured_vault_with_digest(tmp_path, digest_stamp="2026-06-16")
    summary = h.health_summary(vault, today=TODAY)
    assert summary.undelivered_digest == "digest_2026-06-16"
    assert summary.status == h.Status.DEGRADED
    report = h.render(summary)
    assert "never delivered" in report
    assert "digest_2026-06-16" in report
    assert "Next action" in report


def test_undelivered_digest_ok_once_receipt_says_sent(tmp_path: Path) -> None:
    vault = _configured_vault_with_digest(tmp_path, digest_stamp="2026-06-16")
    receipt_dir = vault / "pipeline" / "3-synthesis" / ".delivered"
    receipt_dir.mkdir()
    (receipt_dir / "digest_2026-06-16.json").write_text(
        '{"telegram": {"status": "sent", "timestamp": "2026-06-16T09:05:00+00:00"}}\n',
        encoding="utf-8",
    )
    summary = h.health_summary(vault, today=TODAY)
    assert summary.undelivered_digest is None
    assert summary.status == h.Status.OK


def test_undelivered_digest_receipt_without_sent_still_flags(tmp_path: Path) -> None:
    # A receipt whose every entry failed means NOBODY got the digest — flagged.
    vault = _configured_vault_with_digest(tmp_path, digest_stamp="2026-06-16")
    receipt_dir = vault / "pipeline" / "3-synthesis" / ".delivered"
    receipt_dir.mkdir()
    (receipt_dir / "digest_2026-06-16.json").write_text(
        '{"telegram": {"status": "failed"}}\n', encoding="utf-8"
    )
    summary = h.health_summary(vault, today=TODAY)
    assert summary.undelivered_digest == "digest_2026-06-16"


def test_undelivered_digest_quiet_week_is_not_flagged(tmp_path: Path) -> None:
    # A quiet-week digest is deliberately NOT sent — never an undelivered alarm.
    vault = _configured_vault_with_digest(tmp_path, digest_stamp="2026-06-16")
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-16.md").write_text(
        "# 🧠 Weekly digest — 2026-06-16\n\n"
        "<!-- research-brain: quiet-digest -->\n"
        "Quiet week — nothing new surfaced.\n",
        encoding="utf-8",
    )
    summary = h.health_summary(vault, today=TODAY)
    assert summary.undelivered_digest is None


def test_undelivered_digest_needs_an_enabled_channel(tmp_path: Path) -> None:
    # Building locally with every channel off is a legitimate workflow.
    vault = _configured_vault_with_digest(tmp_path, digest_stamp="2026-06-16")
    (vault / "config" / "channels.yaml").write_text(
        "delivery:\n  telegram:\n    enabled: false\n", encoding="utf-8"
    )
    summary = h.health_summary(vault, today=TODAY)
    assert summary.undelivered_digest is None


def test_undelivered_digest_grace_window(tmp_path: Path) -> None:
    # Built yesterday: still inside the delivery grace window — no alarm yet.
    vault = _configured_vault_with_digest(tmp_path, digest_stamp="2026-06-18")
    summary = h.health_summary(vault, today=TODAY)
    assert summary.undelivered_digest is None


def test_undelivered_digest_reads_relocated_receipts(tmp_path: Path, monkeypatch) -> None:
    # With RESEARCH_BRAIN_STATE_DIR set, receipts live on the persistent volume —
    # the detector must look THERE, not at the in-repo default, or a healthy
    # relocated deployment would false-alarm forever.
    vault = _configured_vault_with_digest(tmp_path, digest_stamp="2026-06-16")
    state_dir = tmp_path / "state"
    monkeypatch.setenv("RESEARCH_BRAIN_STATE_DIR", str(state_dir))
    relocated = state_dir / "pipeline" / "3-synthesis" / ".delivered"
    relocated.mkdir(parents=True)
    (relocated / "digest_2026-06-16.json").write_text(
        '{"telegram": {"status": "sent"}}\n', encoding="utf-8"
    )
    summary = h.health_summary(vault, today=TODAY)
    assert summary.undelivered_digest is None


def test_future_dated_gate_skip_is_excluded(tmp_path: Path) -> None:
    # A clock-skewed FUTURE-dated gate-skip (today+3) must NOT pin DEGRADED: the
    # recency band is one-sided (today-or-past only), matching the future-date
    # guards on the run/digest axes. Otherwise abs(...) would keep a future event
    # inside the window forever and the verdict would stay DEGRADED.
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://s.com", items=3)
    h.record_event(vault, "deliver", status="sent", channel="telegram")
    h.record_event(vault, "run", status="ok", timestamp="2026-06-18T09:00:00+00:00")
    h.record_event(
        vault, "hygiene", status="degraded", note="ai-safety",
        timestamp="2026-06-22T09:00:00+00:00",  # TODAY + 3 days (clock skew)
    )
    summary = h.health_summary(vault, today=TODAY)
    assert summary.gate_skipped == []
    assert summary.status == h.Status.OK


def test_window_plus_one_old_gate_skip_still_ages_out(tmp_path: Path) -> None:
    # The past-side window behavior is unchanged: a skip dated exactly window+1
    # days old still ages out (window = STALE_DIGEST_DAYS = 8 → 9 days before TODAY).
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://s.com", items=3)
    h.record_event(vault, "deliver", status="sent", channel="telegram")
    h.record_event(vault, "run", status="ok", timestamp="2026-06-18T09:00:00+00:00")
    h.record_event(
        vault, "hygiene", status="degraded", note="ai-safety",
        timestamp="2026-06-10T09:00:00+00:00",  # 9 days before TODAY (window+1)
    )
    summary = h.health_summary(vault, today=TODAY)
    assert summary.gate_skipped == []
    assert summary.status == h.Status.OK


def test_gate_skip_without_ts_ages_out(tmp_path: Path) -> None:
    # A gate-skip with a missing/unparseable ts is treated as NOT recent (excluded)
    # — an ancient or ts-less skip must not pin the verdict to DEGRADED forever.
    vault = _vault(tmp_path)
    path = h.events_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write('{"kind": "hygiene", "status": "degraded", "note": "ai-safety"}\n')
    summary = h.health_summary(vault, today=TODAY)
    assert summary.gate_skipped == []


def test_healthy_hygiene_event_does_not_degrade(tmp_path: Path) -> None:
    # An `ok` hygiene event is not a gate-skip and must not flip the verdict.
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://s.com", items=3)
    h.record_event(vault, "deliver", status="sent", channel="telegram")
    h.record_event(vault, "run", status="ok", timestamp="2026-06-18T09:00:00+00:00")
    h.record_event(vault, "hygiene", status="ok", note="all-clean")
    summary = h.health_summary(vault, today=TODAY)
    assert summary.gate_skipped == []
    assert summary.status == h.Status.OK


# --------------------------------------------------------------------------- #
# Silently-degraded signal #2: expected weekly run didn't happen
# --------------------------------------------------------------------------- #


def test_missing_run_degrades_when_latest_run_too_old(tmp_path: Path) -> None:
    # A configured system whose newest `run` event is older than the expected
    # weekly window → DEGRADED with a "no recent run" signal — caught directly,
    # not only via the 8-day digest-staleness proxy.
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://s.com", items=3)
    # A run that succeeded, but long ago (older than EXPECTED_RUN_DAYS).
    h.record_event(vault, "run", status="ok", timestamp="2026-06-01T09:00:00+00:00")
    summary = h.health_summary(vault, today=TODAY)
    assert summary.run_overdue is True
    assert summary.status == h.Status.DEGRADED
    assert summary.ok is False
    assert "no recent run" in h.render(summary).lower()


def test_future_dated_run_event_is_ignored_for_overdue(tmp_path: Path) -> None:
    # A future-skewed `run` ts (clock skew / CI) must NOT become `latest` and
    # silently suppress run_overdue — that would mask a real DEGRADED. The future
    # event is ignored, so a vault whose ONLY runs are an old real one plus a
    # future-dated one still reads run_overdue=True off the old real run.
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://s.com", items=3)
    # A real run, long ago (older than EXPECTED_RUN_DAYS), plus a future-dated one.
    h.record_event(vault, "run", status="ok", timestamp="2026-06-01T09:00:00+00:00")
    h.record_event(vault, "run", status="ok", timestamp="2026-12-31T09:00:00+00:00")
    summary = h.health_summary(vault, today=TODAY)
    assert summary.run_overdue is True
    assert summary.status == h.Status.DEGRADED


def test_only_future_dated_run_event_still_overdue(tmp_path: Path) -> None:
    # If the ONLY run event is future-dated, it has no valid recent run at all:
    # the future event is ignored, so the system reads run_overdue=True (a
    # configured system with no real run inside the window).
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://s.com", items=3)
    h.record_event(vault, "run", status="ok", timestamp="2026-12-31T09:00:00+00:00")
    summary = h.health_summary(vault, today=TODAY)
    assert summary.run_overdue is True
    assert summary.status == h.Status.DEGRADED


def test_recent_run_is_not_overdue(tmp_path: Path) -> None:
    # A run inside the expected window must NOT trip the overdue axis.
    vault = _vault(tmp_path)
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "collect", source="https://s.com", items=3)
    h.record_event(vault, "deliver", status="sent", channel="telegram")
    h.record_event(vault, "run", status="ok", timestamp="2026-06-18T09:00:00+00:00")
    summary = h.health_summary(vault, today=TODAY)
    assert summary.run_overdue is False
    assert summary.status == h.Status.OK


def test_fresh_vault_with_no_run_events_stays_unknown(tmp_path: Path) -> None:
    # A configured-but-never-run system has NO run events at all. "Missing run"
    # must NOT false-alarm here: absence of any run history stays UNKNOWN, never
    # DEGRADED (the system has not yet established a run cadence to be late on).
    vault = _vault(tmp_path)
    h.record_event(vault, "collect", source="https://s.com", items=2)
    summary = h.health_summary(vault, today=TODAY)
    assert summary.run_overdue is False
    assert summary.status == h.Status.UNKNOWN
    assert summary.ok is False


def test_unconfigured_vault_with_no_runs_does_not_alarm(tmp_path: Path) -> None:
    # A brand-new/unconfigured vault must stay UNCONFIGURED — never DEGRADED — on
    # the missing-run axis.
    vault = _vault(tmp_path)
    summary = h.health_summary(vault, today=TODAY)
    assert summary.run_overdue is False
    assert summary.status == h.Status.UNCONFIGURED


# --------------------------------------------------------------------------- #
# Silently-degraded signal #3: feed-liveness from the registry (headless path)
# --------------------------------------------------------------------------- #
#
# build_digest.py never collects, and `collect` events are only written by the
# agent path, so on the pure-headless cron path a DEAD FEED is invisible until
# topics quietly go dry. The robust, mode-independent signal is the registry's
# per-category last-collected date — collection updates it regardless of agent
# vs headless. A monitored category whose newest registry row is older than the
# staleness window is a dead feed; one never collected stays "unknown, not dead".


def test_quiet_registry_is_informational_not_degraded(tmp_path: Path) -> None:
    # A configured feed (category `ai`) whose newest registry collection is older
    # than the window is NOT a failure: a quiet registry measures publish frequency,
    # not reachability, so it must be reported informationally and stay OK (no false
    # DEGRADED / push alert on a slow-but-healthy feed).
    vault = _vault(tmp_path)
    _write_sources(vault, _REAL_SOURCE_YAML)  # category: ai
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "deliver", status="sent", channel="telegram")
    _write_registry(vault, [("2026-06-01", "ai", "https://real.com/post")])

    summary = h.health_summary(vault, today=TODAY)  # 2026-06-19, window = 8d
    assert summary.stale_feeds == ["ai"]  # still surfaced …
    assert summary.status == h.Status.OK  # … but does NOT degrade the verdict
    assert summary.ok is True
    text = h.render(summary)
    assert "ai" in text
    assert "quiet" in text.lower()  # reported as quiet, not "dead feed"


def test_recently_collected_feed_not_flagged(tmp_path: Path) -> None:
    # A feed collected inside the window must NOT be flagged.
    vault = _vault(tmp_path)
    _write_sources(vault, _REAL_SOURCE_YAML)  # category: ai
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "deliver", status="sent", channel="telegram")
    _write_registry(vault, [("2026-06-18", "ai", "https://real.com/post")])

    summary = h.health_summary(vault, today=TODAY)
    assert summary.stale_feeds == []
    assert summary.status == h.Status.OK


def test_fresh_vault_empty_registry_not_flagged(tmp_path: Path) -> None:
    # A configured-but-never-collected feed (no registry row for the category)
    # must NOT false-alarm: stays UNKNOWN, never DEGRADED on the feed-liveness axis.
    vault = _vault(tmp_path)
    _write_sources(vault, _REAL_SOURCE_YAML)  # category: ai
    _write_registry(vault, [])  # ships empty — nothing collected yet

    summary = h.health_summary(vault, today=TODAY)
    assert summary.stale_feeds == []
    assert summary.status == h.Status.UNKNOWN


def test_unconfigured_vault_no_registry_not_flagged(tmp_path: Path) -> None:
    # No sources, no registry → UNCONFIGURED, never DEGRADED on the feed axis.
    vault = _vault(tmp_path)
    summary = h.health_summary(vault, today=TODAY)
    assert summary.stale_feeds == []
    assert summary.status == h.Status.UNCONFIGURED


def test_malformed_registry_without_dates_no_crash_no_alarm(tmp_path: Path) -> None:
    # An older-format registry whose rows carry no usable last-collected date must
    # degrade gracefully: treat as "unknown, not dead" — no crash, no false alarm.
    vault = _vault(tmp_path)
    _write_sources(vault, _REAL_SOURCE_YAML)  # category: ai
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "deliver", status="sent", channel="telegram")
    registry = vault / "pipeline" / "registry.md"
    registry.parent.mkdir(parents=True, exist_ok=True)
    # Rows with an unparseable `collected` cell (old shape) — must not crash.
    registry.write_text(
        "| collected | category | status | url | title |\n"
        "|-----------|----------|--------|-----|-------|\n"
        "| n/a | ai |  | https://real.com/post | t |\n",
        encoding="utf-8",
    )
    summary = h.health_summary(vault, today=TODAY)  # must not raise
    assert summary.stale_feeds == []
    assert summary.status == h.Status.OK


def test_malformed_registry_row_does_not_mask_stale_feed(tmp_path: Path) -> None:
    # A monitored topic with TWO registry rows — one parseable-but-stale, one with
    # an unparseable date — must STILL be reported quiet: a single bad row must not
    # throw away the whole category and mask the real signal. (Quiet is now an
    # informational note, not a DEGRADED verdict — see the test above.)
    vault = _vault(tmp_path)
    _write_sources(vault, _REAL_SOURCE_YAML)  # category: ai
    (vault / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text("# d\n")
    h.record_event(vault, "deliver", status="sent", channel="telegram")
    registry = vault / "pipeline" / "registry.md"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        "| collected | category | status | url | title |\n"
        "|-----------|----------|--------|-----|-------|\n"
        "| 2026-06-01 | ai |  | https://real.com/post | t |\n"  # parseable, stale
        "| n/a | ai |  | https://real.com/other | t |\n",  # bad date — must not mask
        encoding="utf-8",
    )
    summary = h.health_summary(vault, today=TODAY)  # 2026-06-19, window = 8d
    assert summary.stale_feeds == ["ai"]  # bad row did not mask the quiet signal
    assert summary.status == h.Status.OK  # quiet registry is informational, not a failure


# --------------------------------------------------------------------------- #
# Durable runtime state — RESEARCH_BRAIN_STATE_DIR relocates the event log
# --------------------------------------------------------------------------- #

_STATE_ENV = "RESEARCH_BRAIN_STATE_DIR"


def test_events_path_in_repo_when_state_env_unset(tmp_path: Path, monkeypatch) -> None:
    # Default (env unset): the event log resolves to the exact in-repo path.
    monkeypatch.delenv(_STATE_ENV, raising=False)
    vault = _vault(tmp_path)
    assert h.events_path(vault) == vault / "pipeline" / ".health" / "events.jsonl"


def test_events_path_relocates_under_state_dir(tmp_path: Path, monkeypatch) -> None:
    # env SET: the log relocates under the state dir, preserving the
    # pipeline/.health/events.jsonl substructure relative to the project root.
    state_dir = tmp_path / "volume"
    vault = tmp_path / "repo"
    monkeypatch.setenv(_STATE_ENV, str(state_dir))
    assert h.events_path(vault) == (
        state_dir / "pipeline" / ".health" / "events.jsonl"
    )


def test_event_log_under_state_dir_survives_wiped_repo(tmp_path: Path, monkeypatch) -> None:
    # The durability guarantee: with the state dir set, events recorded on run 1
    # live on the persistent volume, so a wiped repo (fresh clone / redeploy)
    # still reads the prior run history rather than losing it.
    state_dir = tmp_path / "volume"
    vault = tmp_path / "repo"
    vault.mkdir()
    monkeypatch.setenv(_STATE_ENV, str(state_dir))

    h.record_event(vault, "deliver", status="sent", channel="telegram")
    # The log was written under the volume, NOT inside the (empty) repo.
    assert (state_dir / "pipeline" / ".health" / "events.jsonl").exists()
    assert not (vault / "pipeline").exists()

    # Simulate a wiped repo: the load still finds the events via the volume.
    events = h.load_events(vault)
    assert len(events) == 1 and events[0]["channel"] == "telegram"


# ── ops_headline: the one-line ops summary the digest embeds ─────────────────


def test_ops_headline_none_when_ok():
    summary = h.HealthSummary(status=h.Status.OK)
    assert h.ops_headline(summary) is None


def test_ops_headline_none_when_unconfigured():
    summary = h.HealthSummary(status=h.Status.UNCONFIGURED)
    assert h.ops_headline(summary) is None


def test_ops_headline_lists_degradation_reasons():
    summary = h.HealthSummary(
        status=h.Status.DEGRADED,
        dead_feeds=[h.FeedStatus(source="https://dead.example/rss", last_items=0, consecutive_failures=3, healthy=False)],
        delivery={"telegram": "failed"},
        run_overdue=True,
        digest_stale=True,
    )
    line = h.ops_headline(summary)
    assert line is not None
    assert "1 unreachable source" in line
    assert "telegram" in line
    assert "overdue" in line
    assert "stale" in line
    # One line, plain language, no newlines — it embeds into the digest.
    assert "\n" not in line
