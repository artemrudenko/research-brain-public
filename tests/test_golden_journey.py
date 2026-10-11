"""
test_golden_journey.py — the hermetic golden e2e journey (release gate).

Chains the REAL stage CLIs — collect → sanitize → build_digest → deliver
(dry-run) — over one tmp vault, with ONLY the network edge faked. The unit
suites prove each stage in isolation; this file proves the SEAMS: what collect
writes is what sanitize stamps, what the digest scan reads, and what delivery
resolves. It runs in plain pytest, so `make gate` and CI gate every release on
the full headless value loop. The live/agentic half of the release protocol
(agent-authored digest quality, real sends) remains `docs/PILOT.md` — this
file is the deterministic half the audit asked to make a gate.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts import build_digest as bd  # noqa: E402
from scripts import collect  # noqa: E402
from scripts import sanitize_incoming as si  # noqa: E402
from scripts.delivery import deliver  # noqa: E402

TODAY = date(2026, 6, 15)

_BODY = "Body prose about agent sandboxing patterns. " * 20  # > min_text_chars

_RSS = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Alpha Article One</title>
      <link>https://feed.example.com/alpha</link>
      <description>{_BODY}</description>
    </item>
    <item>
      <title>Beta Article Two</title>
      <link>https://feed.example.com/beta</link>
      <description>{_BODY}</description>
    </item>
  </channel>
</rss>
"""

# The schema-2 YAML config (CONVENTIONS §2.3) — since 0.8.0 the ONLY format the
# runtime reads.
_SOURCES_YAML = """schema_version: 2
categories:
  - name: ai
    sources:
      - url: "https://feed.example.com/rss.xml"
        type: rss
        tier: high
        priority: medium
        filter: all
        active: true
"""

# A stale legacy table left behind after migration: if collect ever read it,
# articles would land under `stale-md-topic` and the journey would fail below.
_STALE_SOURCES_MD = """## Category: stale-md-topic

### Active sources

| URL | Type | Tier | Priority | Filter | Active |
|-----|------|------|----------|--------|--------|
| https://feed.example.com/rss.xml | rss | low | low | all | yes |
"""

_CHANNELS = """delivery:
  telegram:
    enabled: true
    transport: bot-api
    chat_id: "42"
    token_env: TELEGRAM_BOT_TOKEN
"""


def _vault(tmp_path: Path, config_format: str = "yaml") -> Path:
    """A product-shaped tree: config/ + pipeline/ + brain/, nothing pre-collected.

    `config_format="yaml"` is a fresh 0.8.0 vault (sources.yaml only);
    `config_format="yaml-stale-md"` is a migrated vault — sources.yaml is the
    active config and a STALE sources.md leftover sits next to it (it must be
    ignored).
    """
    (tmp_path / "config").mkdir()
    (tmp_path / "pipeline" / "1-incoming").mkdir(parents=True)
    (tmp_path / "pipeline" / "3-synthesis").mkdir(parents=True)
    (tmp_path / "brain" / "concepts").mkdir(parents=True)
    (tmp_path / "config" / "schedule.yaml").write_text(
        'digest:\n  cron: "0 9 * * 1"\n  lookback_days: 7\n', encoding="utf-8"
    )
    (tmp_path / "config" / "sources.yaml").write_text(_SOURCES_YAML, encoding="utf-8")
    if config_format == "yaml-stale-md":
        (tmp_path / "config" / "sources.md").write_text(_STALE_SOURCES_MD, encoding="utf-8")
    (tmp_path / "config" / "channels.yaml").write_text(_CHANNELS, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("config_format", ["yaml", "yaml-stale-md"])
def test_golden_headless_journey(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    config_format: str,
) -> None:
    vault = _vault(tmp_path, config_format)
    incoming = vault / "pipeline" / "1-incoming"
    registry = vault / "pipeline" / "registry.md"
    monkeypatch.setattr(collect, "fetch", lambda url, **_: _RSS)

    # 1) COLLECT — the real CLI writes articles + registry rows. On the migrated
    # vault we pass the legacy `sources.md` SPELLING: collect must resolve it to
    # the sources.yaml twin (the only file the runtime reads since 0.8.0).
    sources_arg = (
        vault / "config" / ("sources.md" if config_format == "yaml-stale-md" else "sources.yaml")
    )
    rc = collect.main([
        "--sources", str(sources_arg),
        "--incoming", str(incoming),
        "--registry", str(registry),
        "--today", TODAY.isoformat(),
    ])
    assert rc == 0
    reg_text = registry.read_text(encoding="utf-8")
    assert "Alpha Article One" in reg_text
    assert "Beta Article Two" in reg_text
    articles = sorted(p for p in (incoming / "ai").glob("*.md"))
    assert len(articles) == 2
    # On the migrated vault the stale legacy table must be IGNORED: everything
    # lands under the YAML config's category, nothing under the .md's.
    assert not (incoming / "stale-md-topic").exists()
    front = articles[0].read_text(encoding="utf-8")
    assert f"collected: {TODAY.isoformat()}" in front  # the axis the digest scans

    # 2) SANITIZE — companions appear; the fail-closed gate then passes.
    assert si.main(["sanitize", "--incoming", str(incoming)]) == 0
    assert (incoming / "ai" / "sanitized").is_dir()
    assert si.main(["gate", "--incoming", str(incoming)]) == 0

    # 3) BUILD — the real weekly invocation (trends default-on, report opted in).
    monkeypatch.setattr(bd, "PROJECT_ROOT", vault)
    out = vault / "pipeline" / "3-synthesis" / f"digest_{TODAY.isoformat()}.md"
    rc = bd.main([str(out), "--report"], today=TODAY)
    build_out = capsys.readouterr().out
    assert rc == 0
    assert "QUIET_WEEK" not in build_out  # two fresh sources — not a quiet week
    md = out.read_text(encoding="utf-8")
    assert "Alpha Article One" in md          # collect → digest seam
    assert "## 📈 Trends" in md               # wave-1 default-on trends embed
    assert "💬" in md                         # wave-3 feedback invite footer
    assert "📊" in md                         # wave-3 report link footer
    assert bd.report_out_path(out).exists()   # the browser-grade report sidecar

    # 4) DELIVER (dry-run) — channel + secret resolve; nothing sent, no receipts.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(deliver, "load_dotenv", lambda *a, **k: None)
    rc = deliver.main([str(out), str(vault / "config" / "channels.yaml"), "--dry-run"])
    dry_out = capsys.readouterr().out
    assert rc == 0
    assert "WOULD SEND" in dry_out
    assert "telegram" in dry_out
    assert "TELEGRAM_BOT_TOKEN=SET" in dry_out  # secret resolved, value never shown
    assert "test-token" not in dry_out
    assert not (vault / "pipeline" / "3-synthesis" / ".delivered").exists()


def test_golden_quiet_week_short_circuits_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other product-critical journey: an EMPTY week builds the one-line
    quiet digest (marker on stdout, structural comment inside) and
    `deliver --skip-quiet` then declines to ping anyone."""
    vault = _vault(tmp_path)
    monkeypatch.setattr(bd, "PROJECT_ROOT", vault)
    out = vault / "pipeline" / "3-synthesis" / f"digest_{TODAY.isoformat()}.md"
    rc = bd.main([str(out)], today=TODAY)
    build_out = capsys.readouterr().out
    assert rc == 0
    assert "QUIET_WEEK" in build_out
    md = out.read_text(encoding="utf-8")
    assert "quiet-digest" in md      # the structural marker --skip-quiet keys on
    assert "📈 Trends" not in md     # quiet weeks never carry a zero-noise section
    assert "💬" not in md            # nor the feedback invite

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(deliver, "load_dotenv", lambda *a, **k: None)
    rc = deliver.main([
        str(out), str(vault / "config" / "channels.yaml"), "--dry-run", "--skip-quiet",
    ])
    dry_out = capsys.readouterr().out
    assert rc == 0
    # Documented seam (weekly-digest.md): a DRY-RUN still reports normally even
    # on a quiet week — so a channel can be verified — while a real send with
    # --skip-quiet is suppressed (covered by the delivery unit suite).
    assert "WOULD SEND" in dry_out
    assert not (vault / "pipeline" / "3-synthesis" / ".delivered").exists()
