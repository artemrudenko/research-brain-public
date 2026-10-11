"""tests for scripts/doctor.py — the one-command "is everything OK?" check.

Doctor is read-only: it composes the existing validators/health/status pieces
into one plain-language report. It must never write, never send, and never
crash on a half-configured install — that is exactly when a user runs it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

from scripts import doctor

pytest.importorskip("yaml", reason="the config-section tests need PyYAML")


def _tmp_install(tmp_path: Path) -> Path:
    """A fresh install: the repo's shipped config templates, empty pipeline."""
    root = tmp_path / "install"
    shutil.copytree(
        _PROJECT_ROOT / "config", root / "config",
        ignore=shutil.ignore_patterns(".env", "*.local*"),
    )
    (root / "pipeline").mkdir()
    return root


def _section_block(output: str, section: str, level: str) -> str:
    header = f"[{level}] {section}"
    start = output.find(header)
    assert start != -1, f"missing section {header!r}:\n{output}"
    next_header = output.find("\n[", start + 1)
    end = next_header if next_header != -1 else len(output)
    return output[start:end]


def _write_ai_topic(root: Path) -> None:
    (root / "config" / "topics.yaml").write_text(
        """\
schema_version: 2
topics:
  - name: ai
    tags: [ai]
    include: AI news and analysis.
    exclude: Off-topic posts.
""",
        encoding="utf-8",
    )


def _write_non_rss_source(root: Path) -> None:
    _write_ai_topic(root)
    (root / "config" / "sources.yaml").write_text(
        """\
schema_version: 2
categories:
  - name: ai
    sources:
      - url: "https://example.com/news"
        type: blog
        tier: high
        priority: high
        filter: all
        active: true
""",
        encoding="utf-8",
    )


def _write_rss_source(root: Path) -> None:
    _write_ai_topic(root)
    (root / "config" / "sources.yaml").write_text(
        """\
schema_version: 2
categories:
  - name: ai
    sources:
      - url: "https://example.com/feed.xml"
        type: rss
        tier: high
        priority: high
        filter: all
        active: true
""",
        encoding="utf-8",
    )


def _write_smtp_delivery(root: Path) -> None:
    (root / "config" / "channels.yaml").write_text(
        """\
delivery:
  language: en
  email:
    enabled: true
    provider: smtp
    to: ["reader@example.com"]
    smtp:
      host: smtp.example.com
      port: 587
      user: bot@example.com
      password_env: SMTP_PASSWORD
  telegram:
    enabled: false
    transport: bot-api
    chat_id: ""
    token_env: TELEGRAM_BOT_TOKEN
  rocketchat:
    enabled: false
    webhook_url_env: ROCKETCHAT_WEBHOOK_URL
""",
        encoding="utf-8",
    )


def test_doctor_reports_all_sections_and_exits_zero_on_fresh_install(tmp_path, capsys):
    root = _tmp_install(tmp_path)
    rc = doctor.main(["--root", str(root)])
    out = capsys.readouterr().out
    for header in (
        "Environment", "Config", "Sources", "Delivery", "Schedule", "Health", "Run lock",
    ):
        assert header in out, f"missing section {header!r}:\n{out}"
    # A fresh, unconfigured install is not broken — warnings, not failures.
    assert rc == 0
    assert "FAIL" not in out


def test_doctor_schedule_section_detects_not_asserts(tmp_path, capsys):
    # A tmp install can never be referenced by the box's real crontab, so the
    # probe must report the miss (with the cloud-routine caveat) — and never FAIL.
    root = _tmp_install(tmp_path)
    rc = doctor.main(["--root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Schedule" in out
    assert "cloud-agent routine" in out


def test_doctor_fails_on_malformed_channels_yaml(tmp_path, capsys):
    root = _tmp_install(tmp_path)
    (root / "config" / "channels.yaml").write_text("delivery: [broken\n", encoding="utf-8")
    rc = doctor.main(["--root", str(root)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out
    assert "channels.yaml" in out


def test_doctor_fails_when_required_config_missing(tmp_path, capsys):
    root = _tmp_install(tmp_path)
    (root / "config" / "schedule.yaml").unlink()
    rc = doctor.main(["--root", str(root)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "schedule.yaml" in out


def test_doctor_fail_sections_include_next_action(tmp_path, capsys):
    malformed = _tmp_install(tmp_path / "malformed")
    (malformed / "config" / "channels.yaml").write_text(
        "delivery: [broken\n", encoding="utf-8"
    )
    rc = doctor.main(["--root", str(malformed)])
    out = capsys.readouterr().out
    assert rc == 1
    config_block = _section_block(out, "Config", doctor._FAIL)
    assert "Next action:" in config_block
    assert "fix config/channels.yaml" in config_block
    assert "python3 scripts/validate_config.py" in config_block

    missing = _tmp_install(tmp_path / "missing")
    (missing / "config" / "schedule.yaml").unlink()
    rc = doctor.main(["--root", str(missing)])
    out = capsys.readouterr().out
    assert rc == 1
    config_block = _section_block(out, "Config", doctor._FAIL)
    assert "Next action:" in config_block
    assert "restore config/schedule.yaml" in config_block
    assert "python3 scripts/validate_config.py" in config_block


def test_doctor_high_impact_warn_sections_include_next_action(
    tmp_path, capsys, monkeypatch
):
    no_sources = _tmp_install(tmp_path / "no_sources")
    rc = doctor.main(["--root", str(no_sources)])
    out = capsys.readouterr().out
    assert rc == 0
    sources_block = _section_block(out, "Sources", doctor._WARN)
    assert "Next action:" in sources_block
    assert 'say "let\'s set up sources"' in sources_block

    no_rss = _tmp_install(tmp_path / "no_rss")
    _write_non_rss_source(no_rss)
    rc = doctor.main(["--root", str(no_rss)])
    out = capsys.readouterr().out
    assert rc == 0
    sources_block = _section_block(out, "Sources", doctor._WARN)
    assert "Next action:" in sources_block
    assert "add at least one active rss source" in sources_block

    missing_secret = _tmp_install(tmp_path / "missing_secret")
    _write_rss_source(missing_secret)
    _write_smtp_delivery(missing_secret)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    rc = doctor.main(["--root", str(missing_secret)])
    out = capsys.readouterr().out
    assert rc == 0
    delivery_block = _section_block(out, "Delivery", doctor._WARN)
    assert "Next action:" in delivery_block
    assert "set SMTP_PASSWORD in config/.env" in delivery_block

    held_lock = _tmp_install(tmp_path / "held_lock")
    (held_lock / "pipeline").mkdir(exist_ok=True)
    (held_lock / "pipeline" / ".run.lock").write_text("{}", encoding="utf-8")
    rc = doctor.main(["--root", str(held_lock)])
    out = capsys.readouterr().out
    assert rc == 0
    lock_block = _section_block(out, "Run lock", doctor._WARN)
    assert "Next action:" in lock_block
    assert "python3 scripts/run_lock.py status" in lock_block

    degraded = _tmp_install(tmp_path / "degraded")
    _write_rss_source(degraded)
    (degraded / "pipeline" / "3-synthesis").mkdir(parents=True)
    (degraded / "pipeline" / "3-synthesis" / "digest_2026-06-18.md").write_text(
        "# d\n", encoding="utf-8"
    )
    from scripts import health as h

    h.record_event(degraded, "collect", source="https://example.com/feed.xml", items=1)
    h.record_event(degraded, "deliver", status="failed", channel="email")
    rc = doctor.main(["--root", str(degraded)])
    out = capsys.readouterr().out
    assert rc == 0
    health_block = _section_block(out, "Health", doctor._WARN)
    assert "Next action:" in health_block
    assert "retry delivery after fixing the channel" in health_block


def test_doctor_warns_about_placeholder_sources(tmp_path, capsys):
    # The shipped sources.yaml is an empty template (categories: []) — doctor
    # must say setup is unfinished in plain language, not report a healthy
    # system silently.
    root = _tmp_install(tmp_path)
    rc = doctor.main(["--root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "WARN" in out
    assert "source" in out.lower()
    assert "verdict: needs attention" in out
    assert "nothing broken" not in out


def test_doctor_without_yaml_does_not_invent_an_empty_source_roster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _tmp_install(tmp_path)
    _write_rss_source(root)
    monkeypatch.setattr(doctor, "yaml", None)
    assert doctor.main(["--root", str(root)]) == 0
    output = capsys.readouterr().out
    assert "source count unknown" in output
    assert "config schema status unknown" in output
    assert "no real monitored sources yet" not in output
    assert "every present config file passes its schema check" not in output


def test_doctor_reports_collection_capability_mode(tmp_path, capsys):
    root = _tmp_install(tmp_path)
    _write_rss_source(root)
    rc = doctor.main(["--root", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    block = _section_block(out, "Collection mode", doctor._OK)
    assert "Full agentic weekly-run" in block
    assert "Headless collect.py: RSS/Atom plus static article top-up" in block

    mixed = _tmp_install(tmp_path / "mixed")
    _write_ai_topic(mixed)
    (mixed / "config" / "sources.yaml").write_text(
        """\
schema_version: 2
categories:
  - name: ai
    sources:
      - url: "https://example.com/feed.xml"
        type: rss
        tier: high
        priority: high
        filter: all
        active: true
      - url: "https://example.com/blog"
        type: blog
        tier: medium
        priority: medium
        filter: all
        active: true
""",
        encoding="utf-8",
    )
    rc = doctor.main(["--root", str(mixed)])
    out = capsys.readouterr().out
    assert rc == 0
    block = _section_block(out, "Collection mode", doctor._OK)
    assert "1 active non-RSS source" in block
    assert "need the agentic collector" in block


def test_environment_hints_to_use_venv_when_system_python_lacks_pyyaml(tmp_path, monkeypatch):
    # Simulate running doctor with a Python that lacks PyYAML (system python3) while
    # the install HAS a virtualenv that has it — doctor must point at the venv, not
    # just say "PyYAML not installed".
    root = _tmp_install(tmp_path)
    monkeypatch.setattr(doctor, "yaml", None)
    (root / ".venv" / "lib" / "python3.11" / "site-packages" / "yaml").mkdir(parents=True)
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python3").write_text("")  # placeholder interpreter
    level, lines = doctor._section_environment(root)
    text = "\n".join(lines)
    assert level == doctor._WARN
    assert ".venv" in text  # actionable: names the venv interpreter
    assert "uv run" in text or "scripts/doctor.py" in text


def test_environment_generic_pyyaml_message_when_no_venv(tmp_path, monkeypatch):
    # No venv beside the install → keep the plain "install the toolchain" message
    # (never claim a venv exists that doesn't).
    root = _tmp_install(tmp_path)
    monkeypatch.setattr(doctor, "yaml", None)
    level, lines = doctor._section_environment(root)
    text = "\n".join(lines)
    assert level == doctor._WARN
    assert "PyYAML not installed" in text


def test_doctor_is_read_only(tmp_path):
    root = _tmp_install(tmp_path)
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    doctor.main(["--root", str(root)])
    after = sorted(p.relative_to(root) for p in root.rglob("*"))
    assert before == after


def test_doctor_runs_against_this_repo_read_only(capsys):
    # The real invocation path: no --root. Read-only by construction, so it is
    # safe against the dev checkout; must not crash and must print a verdict.
    rc = doctor.main([])
    out = capsys.readouterr().out
    assert rc in (0, 1)
    assert "verdict" in out.lower()


def test_doctor_config_section_accepts_yaml_format(tmp_path):
    # A YAML-only vault (sources.yaml/topics.yaml — 0.8.0 ships no .md config)
    # must not be reported as "sources.md: missing (required)" — the active
    # format is what counts.
    root = _tmp_install(tmp_path)
    config = root / "config"
    (config / "sources.yaml").write_text(
        "categories:\n"
        "  - name: ai\n"
        "    sources:\n"
        "      - url: \"https://example.com/feed.xml\"\n"
        "        type: rss\n"
        "        active: true\n",
        encoding="utf-8",
    )
    (config / "topics.yaml").write_text("topics:\n  - name: ai\n", encoding="utf-8")
    level, lines = doctor._section_config(root)
    joined = "\n".join(lines)
    assert "sources.md: missing" not in joined
    assert "topics.md: missing" not in joined
    assert level in ("OK", "WARN"), (level, lines)
