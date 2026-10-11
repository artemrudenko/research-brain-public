"""Tests for scripts/setup_check.py — truthful first-run activation receipt.

The setup checker is deliberately read-only: it composes config validation,
source productivity probing, delivery dry-run reporting, and scheduler state into
one activation receipt. It must not send, write receipts, or mutate the vault.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

from scripts import setup_check  # noqa: E402


def _tmp_install(tmp_path: Path) -> Path:
    root = tmp_path / "install"
    shutil.copytree(
        _PROJECT_ROOT / "config",
        root / "config",
        ignore=shutil.ignore_patterns(".env", "*.local*"),
    )
    (root / "pipeline" / "1-incoming").mkdir(parents=True)
    (root / "pipeline" / "registry.md").write_text(
        "| collected | category | url | title | processed |\n"
        "|-----------|----------|-----|-------|-----------|\n",
        encoding="utf-8",
    )
    (root / "brain").mkdir()
    return root


def _write_sources(root: Path, *, source_type: str = "rss", active: bool = True) -> None:
    """Overwrite the copied empty YAML twins with one real monitored source."""
    (root / "config" / "sources.yaml").write_text(
        f"""schema_version: 2
categories:
  - name: ai-agents
    sources:
      - url: "https://example.com/feed.xml"
        type: {source_type}
        tier: high
        priority: medium
        filter: all
        active: {"true" if active else "false"}
""",
        encoding="utf-8",
    )
    (root / "config" / "topics.yaml").write_text(
        """schema_version: 2
topics:
  - name: ai-agents
    tags: [ai-agents]
    include: agent content
    exclude: off topic
""",
        encoding="utf-8",
    )


def _long_rss_body() -> str:
    return " ".join(["substantive"] * 80)


def _rss_with_body(body: str) -> str:
    return f"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Feed</title>
    <item>
      <title>Useful article</title>
      <link>https://example.com/article-1</link>
      <description>{body}</description>
      <pubDate>Mon, 06 Jul 2026 09:00:00 GMT</pubDate>
      <guid>article-1</guid>
    </item>
  </channel>
</rss>
"""


def _verified_source(_root: Path, _runtime: str) -> setup_check.CheckItem:
    return setup_check.CheckItem("source", "verified", "source probe ok", [])


def _rehearsed_delivery(_root: Path, _runtime: str) -> setup_check.CheckItem:
    return setup_check.CheckItem("delivery", "rehearsed", "delivery dry-run ok", [])


def _item_status(result: setup_check.SetupCheck, name: str) -> str:
    return result.items[name].status


def test_complete_requires_all_activation_gates(tmp_path: Path) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)
    result = setup_check.run_setup_check(
        root,
        runtime="agentic",
        scheduler_state="registered",
        source_probe=_verified_source,
        delivery_probe=_rehearsed_delivery,
    )
    assert set(result.items) == {
        "source",
        "config",
        "delivery",
        "scheduler",
        "first_value",
        "next_action",
    }
    assert result.final_status == "complete"

    not_complete = setup_check.run_setup_check(
        root,
        runtime="agentic",
        scheduler_state="ready_not_registered",
        source_probe=_verified_source,
        delivery_probe=_rehearsed_delivery,
    )
    assert not_complete.final_status != "complete"


def test_ready_schedule_not_registered_is_not_complete(tmp_path: Path) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)
    result = setup_check.run_setup_check(
        root,
        runtime="agentic",
        scheduler_state="ready_not_registered",
        source_probe=_verified_source,
        delivery_probe=_rehearsed_delivery,
    )
    assert result.final_status == "ready_schedule_not_registered"
    rendered = setup_check.render_human(result)
    assert "register one recurring run for schedule/weekly-run.md" in rendered


def test_unknown_scheduler_is_needs_attention(tmp_path: Path) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)
    result = setup_check.run_setup_check(
        root,
        runtime="agentic",
        scheduler_state="unknown",
        source_probe=_verified_source,
        delivery_probe=_rehearsed_delivery,
    )
    assert result.final_status == "needs_attention"
    assert _item_status(result, "scheduler") == "unknown"


def test_active_source_row_alone_is_not_verified(tmp_path: Path) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root, source_type="blog")
    result = setup_check.run_setup_check(
        root,
        runtime="agentic",
        scheduler_state="registered",
        delivery_probe=_rehearsed_delivery,
    )
    assert _item_status(result, "source") == "unsupported"
    assert result.final_status == "needs_attention"


def test_probe_rss_sources_reports_verified_empty_failed_and_missing(tmp_path: Path) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)

    verified = setup_check.probe_rss_sources(root, fetch_fn=lambda _url: _rss_with_body(_long_rss_body()))
    assert verified.status == "verified"

    empty = setup_check.probe_rss_sources(root, fetch_fn=lambda _url: _rss_with_body("short"))
    assert empty.status == "empty"

    def boom(_url: str) -> str:
        raise OSError("network down")

    failed = setup_check.probe_rss_sources(root, fetch_fn=boom)
    assert failed.status == "failed"

    _write_sources(root, source_type="blog")
    missing = setup_check.probe_rss_sources(root, fetch_fn=lambda _url: "")
    assert missing.status == "missing"


def test_headless_runtime_uses_rss_probe(tmp_path: Path) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)
    result = setup_check.run_setup_check(
        root,
        runtime="headless",
        scheduler_state="registered",
        delivery_probe=_rehearsed_delivery,
    )
    # The default fetcher cannot reach example.com in tests; the important
    # contract is that headless does not count the row as verified.
    assert _item_status(result, "source") in {"empty", "failed"}
    assert result.final_status == "needs_attention"


def test_config_validation_failure_is_classified(tmp_path: Path) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)
    (root / "config" / "channels.yaml").write_text("delivery: [broken\n", encoding="utf-8")
    result = setup_check.run_setup_check(
        root,
        source_probe=_verified_source,
        delivery_probe=_rehearsed_delivery,
    )
    assert _item_status(result, "config") == "invalid"
    assert any("channels.yaml" in line for line in result.items["config"].detail)
    assert "Traceback" not in setup_check.render_human(result)


def _enable_smtp_email(root: Path) -> None:
    channels = (root / "config" / "channels.yaml").read_text(encoding="utf-8")
    channels = channels.replace("  email:\n    enabled: false\n", "  email:\n    enabled: true\n")
    channels = channels.replace("provider: gmail-mcp", "provider: smtp")
    channels = channels.replace("to: []", 'to: ["user@example.com"]')
    channels = channels.replace('host: ""', "host: smtp.example.com")
    channels = channels.replace('user: ""', "user: user@example.com")
    (root / "config" / "channels.yaml").write_text(channels, encoding="utf-8")


def test_delivery_missing_secret_is_classified_without_secret_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)
    _enable_smtp_email(root)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)

    result = setup_check.run_setup_check(
        root,
        source_probe=_verified_source,
        scheduler_state="registered",
    )
    assert _item_status(result, "delivery") == "missing_secret"
    rendered = setup_check.render_human(result)
    assert "SMTP_PASSWORD" in rendered
    for leaked in ("123456:AA_SECRET", "smtp-password-value", "https://hooks.example/secret"):
        assert leaked not in rendered


def test_delivery_reads_dotenv_temporarily_without_secret_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)
    _enable_smtp_email(root)
    secret = "smtp-password-value"
    (root / "config" / ".env").write_text(f"SMTP_PASSWORD={secret}\n", encoding="utf-8")
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)

    result = setup_check.run_setup_check(
        root,
        source_probe=_verified_source,
        scheduler_state="registered",
    )

    assert _item_status(result, "delivery") == "rehearsed"
    assert result.final_status == "complete"
    rendered = setup_check.render_human(result)
    assert "SMTP_PASSWORD=SET" in rendered
    assert secret not in rendered
    assert os.environ.get("SMTP_PASSWORD") is None


def test_mcp_only_headless_delivery_is_unsupported_runtime(tmp_path: Path) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)
    channels = (root / "config" / "channels.yaml").read_text(encoding="utf-8")
    channels = channels.replace("  email:\n    enabled: false\n", "  email:\n    enabled: true\n")
    channels = channels.replace("to: []", 'to: ["user@example.com"]')
    (root / "config" / "channels.yaml").write_text(channels, encoding="utf-8")

    result = setup_check.run_setup_check(
        root,
        runtime="headless",
        scheduler_state="registered",
        source_probe=_verified_source,
    )
    assert _item_status(result, "delivery") == "unsupported_runtime"


def test_mcp_only_agentic_delivery_requires_runtime_connector_probe(tmp_path: Path) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)
    channels = (root / "config" / "channels.yaml").read_text(encoding="utf-8")
    channels = channels.replace("  email:\n    enabled: false\n", "  email:\n    enabled: true\n")
    channels = channels.replace("to: []", 'to: ["user@example.com"]')
    (root / "config" / "channels.yaml").write_text(channels, encoding="utf-8")

    result = setup_check.run_setup_check(
        root,
        runtime="agentic",
        scheduler_state="registered",
        source_probe=_verified_source,
    )

    assert _item_status(result, "delivery") == "unsupported_runtime"
    assert result.final_status == "needs_attention"
    assert "connector verification" in result.items["delivery"].summary


def test_mixed_mcp_and_headless_delivery_does_not_hide_skipped_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)
    _enable_smtp_email(root)
    channels = (root / "config" / "channels.yaml").read_text(encoding="utf-8")
    channels = channels.replace(
        "  telegram:\n    enabled: false\n",
        '  telegram:\n    enabled: true\n',
    )
    channels = channels.replace('chat_id: ""', 'chat_id: "123456"')
    (root / "config" / "channels.yaml").write_text(channels, encoding="utf-8")
    (root / "config" / ".env").write_text("SMTP_PASSWORD=set\n", encoding="utf-8")
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)

    result = setup_check.run_setup_check(
        root,
        runtime="headless",
        scheduler_state="registered",
        source_probe=_verified_source,
    )

    assert _item_status(result, "delivery") == "unsupported_runtime"
    assert any("email" in line and "SET" in line for line in result.items["delivery"].detail)
    assert any("telegram" in line and "SKIPPED" in line for line in result.items["delivery"].detail)
    assert os.environ.get("SMTP_PASSWORD") is None


def test_delivery_config_error_is_distinct_from_transient_failure(tmp_path: Path) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)
    channels = (root / "config" / "channels.yaml").read_text(encoding="utf-8")
    channels = channels.replace("  email:\n    enabled: false\n", "  email:\n    enabled: true\n")
    channels = channels.replace("provider: gmail-mcp", "provider: stmp")
    (root / "config" / "channels.yaml").write_text(channels, encoding="utf-8")

    config_error = setup_check.run_setup_check(
        root,
        source_probe=_verified_source,
        scheduler_state="registered",
    )
    assert _item_status(config_error, "delivery") == "config_error"

    transient = setup_check.run_setup_check(
        root,
        source_probe=_verified_source,
        scheduler_state="registered",
        delivery_probe=lambda _root, _runtime: setup_check.CheckItem(
            "delivery", "transient_failure", "provider timeout", ["retry later"]
        ),
    )
    assert _item_status(transient, "delivery") == "transient_failure"


def test_setup_check_is_read_only(tmp_path: Path) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)

    def snapshot() -> dict[Path, tuple[int, int]]:
        out: dict[Path, tuple[int, int]] = {}
        for base in ("config", "pipeline", "brain"):
            for path in (root / base).rglob("*"):
                if path.is_file():
                    st = path.stat()
                    out[path.relative_to(root)] = (st.st_size, st.st_mtime_ns)
        return out

    before = snapshot()
    setup_check.run_setup_check(
        root,
        runtime="agentic",
        scheduler_state="registered",
        source_probe=_verified_source,
        delivery_probe=_rehearsed_delivery,
    )
    assert snapshot() == before


def test_cli_help_json_and_invalid_args(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)
    assert setup_check.main(["--help"]) == 0
    help_out = capsys.readouterr().out
    for flag in ("--json", "--runtime", "--scheduler-state", "--root"):
        assert flag in help_out

    rc = setup_check.main([
        "--root",
        str(root),
        "--json",
        "--runtime",
        "agentic",
        "--scheduler-state",
        "ready-not-registered",
    ])
    assert rc in (0, 1)
    data = json.loads(capsys.readouterr().out)
    assert {"final_status", "runtime", "items"} <= set(data)

    assert setup_check.main(["--root", str(root), "--runtime", "bogus"]) == 2


def test_status_enums_are_pinned() -> None:
    assert setup_check.SOURCE_STATUSES == {
        "verified",
        "missing",
        "empty",
        "unsupported",
        "failed",
    }
    assert setup_check.FINAL_STATUSES == {
        "complete",
        "ready_schedule_not_registered",
        "needs_attention",
    }


# --------------------------------------------------------------------------- #
# Scheduler registration probe — detection instead of assertion
# --------------------------------------------------------------------------- #


def _fake_run(stdout: str = "", returncode: int = 0):
    def run(cmd, **kwargs):  # noqa: ANN001, ANN003
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    return run


def test_probe_detects_registered_crontab_entry(tmp_path: Path) -> None:
    # A non-comment crontab line referencing THIS install by absolute path is
    # the registration signal (a sibling install's entry must not count).
    line = f"0 9 * * 1 cd {tmp_path} && .venv/bin/python3 scripts/build_digest.py"
    state, evidence = setup_check.probe_scheduler_registration(
        tmp_path, run=_fake_run(stdout=f"# a comment\n{line}\n"), platform="posix"
    )
    assert state == "registered"
    assert any(str(tmp_path) in item for item in evidence)


def test_probe_ignores_commented_crontab_entry(tmp_path: Path) -> None:
    line = f"# 0 9 * * 1 cd {tmp_path} && .venv/bin/python3 scripts/build_digest.py"
    state, _ = setup_check.probe_scheduler_registration(
        tmp_path, run=_fake_run(stdout=f"{line}\n"), platform="posix"
    )
    assert state == "ready_not_registered"


def test_probe_other_install_entry_does_not_count(tmp_path: Path) -> None:
    state, _ = setup_check.probe_scheduler_registration(
        tmp_path,
        run=_fake_run(stdout="0 9 * * 1 cd /some/other/research-brain && x\n"),
        platform="posix",
    )
    assert state == "ready_not_registered"


def test_probe_empty_crontab_is_ready_not_registered(tmp_path: Path) -> None:
    # `crontab -l` exits 1 with "no crontab for user" — that is a clean miss.
    state, evidence = setup_check.probe_scheduler_registration(
        tmp_path, run=_fake_run(stdout="", returncode=1), platform="posix"
    )
    assert state == "ready_not_registered"
    assert evidence


def test_probe_missing_binary_degrades_to_ready_not_registered(tmp_path: Path) -> None:
    # A box without crontab must be NO WORSE than before the probe existed
    # (unknown would flip the final status to needs_attention).
    def run(cmd, **kwargs):  # noqa: ANN001, ANN003
        raise FileNotFoundError("crontab")

    state, evidence = setup_check.probe_scheduler_registration(
        tmp_path, run=run, platform="posix"
    )
    assert state == "ready_not_registered"
    assert any("cannot verify" in item for item in evidence)


def test_probe_windows_uses_schtasks(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(cmd, **kwargs):  # noqa: ANN001, ANN003
        calls.append(list(cmd))
        return subprocess.CompletedProcess(
            cmd, 0, stdout=f"Task To Run: {tmp_path} scripts/build_digest.py", stderr=""
        )

    state, _ = setup_check.probe_scheduler_registration(tmp_path, run=run, platform="nt")
    assert state == "registered"
    assert calls and calls[0][0] == "schtasks"


def test_run_setup_check_uses_probe_when_no_explicit_state(tmp_path: Path) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)
    result = setup_check.run_setup_check(
        root,
        runtime="agentic",
        source_probe=_verified_source,
        delivery_probe=_rehearsed_delivery,
        scheduler_probe=lambda _root: ("registered", ["detected: 0 9 * * 1 …"]),
    )
    assert _item_status(result, "scheduler") == "registered"
    assert result.final_status == "complete"
    assert any("detected" in line for line in result.items["scheduler"].detail)


def test_explicit_scheduler_state_wins_over_probe(tmp_path: Path) -> None:
    root = _tmp_install(tmp_path)
    _write_sources(root)

    def probe(_root: Path) -> tuple[str, list[str]]:
        raise AssertionError("probe must not run when --scheduler-state is explicit")

    result = setup_check.run_setup_check(
        root,
        runtime="agentic",
        scheduler_state="registered",
        source_probe=_verified_source,
        delivery_probe=_rehearsed_delivery,
        scheduler_probe=probe,
    )
    assert _item_status(result, "scheduler") == "registered"


def test_config_item_accepts_yaml_format_vault(tmp_path: Path) -> None:
    # A YAML-only install (0.8.0: sources.yaml + topics.yaml, no .md config at
    # all) — the config item must validate the ACTIVE format and never demand
    # the retired sources.md/topics.md.
    root = _tmp_install(tmp_path)
    (root / "config" / "sources.yaml").write_text(
        "schema_version: 2\n"
        "categories:\n"
        "  - name: ai-agents\n"
        "    sources:\n"
        "      - url: \"https://example.com/feed.xml\"\n"
        "        type: rss\n"
        "        tier: high\n"
        "        priority: medium\n"
        "        filter: all\n"
        "        active: true\n",
        encoding="utf-8",
    )
    (root / "config" / "topics.yaml").write_text(
        "schema_version: 2\ntopics:\n  - name: ai-agents\n    tags: [ai-agents]\n",
        encoding="utf-8",
    )
    item = setup_check._config_item(root)
    assert item.status == "valid", item.to_dict()


def test_probe_rss_reads_yaml_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _tmp_install(tmp_path)
    (root / "config" / "sources.yaml").write_text(
        "categories:\n"
        "  - name: ai-agents\n"
        "    sources:\n"
        "      - url: \"https://example.com/feed.xml\"\n"
        "        type: rss\n"
        "        active: true\n",
        encoding="utf-8",
    )
    item = setup_check.probe_rss_sources(
        root, fetch_fn=lambda url: _rss_with_body(_long_rss_body())
    )
    assert item.status == "verified", item.to_dict()
    assert any("would_save=1" in line for line in item.detail)
