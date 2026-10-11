"""
test_trends.py — offline tests for the deterministic weekly trends builder (ADR 0017).

All tests build tmp registry / concept fixtures and drive `trends` with a fixed
`today`, so windows are reproducible. No network, no real vault.
"""
import sys
from datetime import date
from pathlib import Path

from scripts import registry as reg  # noqa: E402
from scripts import trends as tr  # noqa: E402

TODAY = date(2026, 6, 15)  # a Monday


def _row(collected: str, category: str, status: str = "", url: str = "") -> reg.RegistryRow:
    return reg.RegistryRow(
        collected=collected, category=category, status=status,
        url=url or f"https://x.com/{collected}/{category}", title="t",
    )


def _append(registry_path: Path, row: reg.RegistryRow) -> None:
    reg.append_registry_row(
        registry_path, collected=row.collected, category=row.category,
        url=row.url, title=row.title, status=row.status,
    )


# --------------------------------------------------------------------------- #
# period_index — rolling 7-day windows anchored on today
# --------------------------------------------------------------------------- #


def test_period_index_buckets_by_seven_day_window() -> None:
    assert tr.period_index(TODAY, TODAY) == 0            # today -> current week
    assert tr.period_index(date(2026, 6, 9), TODAY) == 0  # today-6 -> current
    assert tr.period_index(date(2026, 6, 8), TODAY) == 1  # today-7 -> prior
    assert tr.period_index(date(2026, 6, 2), TODAY) == 1  # today-13 -> prior
    assert tr.period_index(date(2026, 6, 1), TODAY) == 2  # today-14 -> two back


def test_period_index_future_is_none() -> None:
    assert tr.period_index(date(2026, 6, 16), TODAY) is None


# --------------------------------------------------------------------------- #
# (a) volume by topic — this week vs prior
# --------------------------------------------------------------------------- #


def test_topic_trends_counts_current_vs_prior() -> None:
    rows = [
        _row("2026-06-15", "ai"), _row("2026-06-14", "ai"),   # 2 this week
        _row("2026-06-10", "ai"),                              # ai prior? 06-10 -> current (today-5)
        _row("2026-06-05", "ai"),                              # prior week (today-10)
        _row("2026-06-12", "security"),                        # security current
    ]
    trends = {t.topic: t for t in tr.topic_trends(rows, TODAY)}
    assert trends["ai"].current == 3  # 06-15, 06-14, 06-10
    assert trends["ai"].prior == 1    # 06-05
    assert trends["ai"].delta == 2
    assert trends["security"].current == 1
    assert trends["security"].prior == 0


def test_topic_trends_sorted_by_current_desc() -> None:
    rows = [_row("2026-06-15", "b"), _row("2026-06-15", "a"), _row("2026-06-14", "a")]
    ordered = [t.topic for t in tr.topic_trends(rows, TODAY)]
    assert ordered[0] == "a"  # a has 2 current, b has 1


def test_new_and_fading_topics() -> None:
    rows = [
        _row("2026-06-15", "fresh"),   # current only -> new
        _row("2026-06-05", "old"),     # prior only -> fading
        _row("2026-06-15", "steady"), _row("2026-06-05", "steady"),  # both
    ]
    trends = tr.topic_trends(rows, TODAY)
    assert tr.new_topics(trends) == ["fresh"]
    assert tr.fading_topics(trends) == ["old"]


def test_topic_trends_ignores_out_of_window_rows() -> None:
    rows = [_row("2026-06-15", "ai"), _row("2026-01-01", "ai")]  # second far outside
    trends = {t.topic: t for t in tr.topic_trends(rows, TODAY)}
    assert trends["ai"].current == 1
    assert trends["ai"].prior == 0


# --------------------------------------------------------------------------- #
# (c) activity — inflow this vs prior, backlog proxy
# --------------------------------------------------------------------------- #


def test_activity_summary_inflow_and_backlog() -> None:
    rows = [
        _row("2026-06-15", "ai", status=""),           # current, unprocessed (backlog)
        _row("2026-06-14", "ai", status="processed"),  # current, processed
        _row("2026-06-05", "ai", status=""),           # prior, unprocessed (backlog)
        _row("2026-06-05", "ai", status="rejected"),   # prior, rejected
    ]
    act = tr.activity_summary(rows, TODAY)
    assert act.inflow_current == 2
    assert act.inflow_prior == 2
    assert act.inflow_delta == 0
    assert act.backlog == 2  # two blank-status rows all-time


# --------------------------------------------------------------------------- #
# concepts — growth, linking, tag trends
# --------------------------------------------------------------------------- #


def _concept(
    tmp: Path, stem: str, *, created: str, last_updated: str,
    tags: list[str] | None = None, related: list[str] | None = None, seed: bool = False,
) -> None:
    tags = tags or ["ai/agents"]
    related = related or []
    seed_marker = "> ⚠️ **SEED / EXAMPLE NOTE.**\n\n" if seed else ""
    rel_block = ""
    if related:
        rel_block = "related_concept:\n" + "".join(f'  - "[[concepts/{r}]]"\n' for r in related)
    (tmp / f"{stem}.md").write_text(
        "---\n"
        f"title: {stem}\n"
        "type: concept\n"
        f"tags: [{', '.join(tags)}]\n"
        f"created: {created}\n"
        f"last_updated: {last_updated}\n"
        f"{rel_block}"
        "---\n\n"
        f"# {stem}\n\n{seed_marker}## What it is\n\nA thing.\n",
        encoding="utf-8",
    )


def test_load_concept_records_excludes_seed(tmp_path: Path) -> None:
    _concept(tmp_path, "real", created="2026-06-15", last_updated="2026-06-15")
    _concept(tmp_path, "sample", created="2026-06-15", last_updated="2026-06-15",
             tags=["seed", "example"], seed=True)
    names = {r.name for r in tr.load_concept_records(tmp_path)}
    assert "real" in names
    assert "sample" not in names


def test_load_concept_records_works_without_pyyaml(tmp_path: Path, monkeypatch) -> None:
    # The headless (no-PyYAML) runtime is documented + supported (CONVENTIONS §5), and
    # trends.py is invoked as bare `python3`. The concept reader must fall back to the
    # stdlib frontmatter parser instead of silently returning [] (which would falsely
    # report zero concept growth / no rising tags in the digest).
    _concept(tmp_path, "real", created="2026-06-15", last_updated="2026-06-15",
             tags=["ai/agents"], related=["runtime-governance"])
    monkeypatch.setitem(sys.modules, "yaml", None)  # make `import yaml` raise ImportError
    records = tr.load_concept_records(tmp_path)
    assert len(records) == 1
    rec = records[0]
    assert rec.created == date(2026, 6, 15)
    assert "ai/agents" in rec.tags
    assert "runtime-governance" in rec.out_targets


def test_concept_growth_created_current_vs_prior(tmp_path: Path) -> None:
    _concept(tmp_path, "new1", created="2026-06-15", last_updated="2026-06-15")
    _concept(tmp_path, "new2", created="2026-06-14", last_updated="2026-06-14")
    _concept(tmp_path, "old1", created="2026-06-05", last_updated="2026-06-05")
    records = tr.load_concept_records(tmp_path)
    growth = tr.concept_growth(records, TODAY)
    assert growth.created_current == 2
    assert growth.created_prior == 1


def test_growth_series_buckets_by_week_oldest_first(tmp_path: Path) -> None:
    # The longitudinal series behind the sparkline: fixed width, oldest → newest,
    # dates outside the window (or future) simply don't count.
    _concept(tmp_path, "now", created="2026-06-15", last_updated="2026-06-15")
    _concept(tmp_path, "lastweek", created="2026-06-07", last_updated="2026-06-07")
    _concept(tmp_path, "old", created="2026-05-30", last_updated="2026-05-30")
    _concept(tmp_path, "ancient", created="2026-01-01", last_updated="2026-01-01")
    records = tr.load_concept_records(tmp_path)
    series = tr.growth_series(records, TODAY, weeks=4)
    assert series == [0, 1, 1, 1]  # 'ancient' falls outside the 4-week window


def test_growth_sparkline_rendered_in_report(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _concept(vault / "brain" / "concepts", "now",
             created="2026-06-15", last_updated="2026-06-15")
    _concept(vault / "brain" / "concepts", "prior",
             created="2026-06-07", last_updated="2026-06-07")
    out = vault / "pipeline" / "3-synthesis" / "trends.md"
    tr.build_trends(out, root=vault, today=TODAY)
    text = out.read_text(encoding="utf-8")
    assert "Created per week" in text
    assert "█" in text  # the peak week renders the tallest block


def test_growth_sparkline_omitted_without_created_history(tmp_path: Path) -> None:
    # A vault with no concepts yet must not render a zero-noise sparkline.
    vault = _vault(tmp_path)
    _append(vault / "pipeline" / "registry.md", _row("2026-06-15", "ai"))
    out = vault / "pipeline" / "3-synthesis" / "trends.md"
    tr.build_trends(out, root=vault, today=TODAY)
    assert "Created per week" not in out.read_text(encoding="utf-8")


def test_top_linked_concepts_by_degree(tmp_path: Path) -> None:
    # hub links to a and b; a links back to hub -> hub degree 3, a degree 2, b degree 1.
    _concept(tmp_path, "hub", created="2026-06-15", last_updated="2026-06-15",
             related=["a", "b"])
    _concept(tmp_path, "a", created="2026-06-15", last_updated="2026-06-15",
             related=["hub"])
    _concept(tmp_path, "b", created="2026-06-15", last_updated="2026-06-15")
    records = tr.load_concept_records(tmp_path)
    ranked = tr.top_linked(records, limit=3)
    assert ranked[0][0] == "hub"
    assert ranked[0][1] == 3


def test_tag_trends_rising_this_period(tmp_path: Path) -> None:
    # ai/agents updated twice this week, once last week -> rising (delta +1).
    _concept(tmp_path, "c1", created="2026-06-15", last_updated="2026-06-15",
             tags=["ai/agents"])
    _concept(tmp_path, "c2", created="2026-06-14", last_updated="2026-06-14",
             tags=["ai/agents"])
    _concept(tmp_path, "c3", created="2026-06-05", last_updated="2026-06-05",
             tags=["ai/agents"])
    records = tr.load_concept_records(tmp_path)
    trends = {t.tag: t for t in tr.tag_trends(records, TODAY)}
    assert trends["ai/agents"].current == 2
    assert trends["ai/agents"].prior == 1


# --------------------------------------------------------------------------- #
# render + build + CLI
# --------------------------------------------------------------------------- #


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "pipeline" / "3-synthesis").mkdir(parents=True)
    (tmp_path / "brain" / "concepts").mkdir(parents=True)
    return tmp_path


def test_default_trends_path() -> None:
    assert tr.default_trends_path(Path("/x"), TODAY) == \
        Path("/x/pipeline/3-synthesis/trends_2026-06-15.md")


def test_build_trends_writes_report(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _append(vault / "pipeline" / "registry.md", _row("2026-06-15", "ai"))
    _append(vault / "pipeline" / "registry.md", _row("2026-06-05", "ai"))
    _concept(vault / "brain" / "concepts", "agents",
             created="2026-06-15", last_updated="2026-06-15", tags=["ai/agents"])
    out = vault / "pipeline" / "3-synthesis" / "trends.md"
    tr.build_trends(out, root=vault, today=TODAY)
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# 📈 Trends — 2026-06-15")
    assert "ai" in text
    assert "Topic volume" in text
    assert "Knowledge growth" in text


def test_build_trends_section_uses_h2_for_embedding(tmp_path: Path) -> None:
    # The embeddable section demotes to H2 title + H3 subsections so it can sit
    # inside the weekly digest (a single H1) without a stray top-level heading.
    vault = _vault(tmp_path)
    _append(vault / "pipeline" / "registry.md", _row("2026-06-15", "ai"))
    section = tr.build_trends_section(root=vault, today=TODAY)
    assert section.startswith("## 📈 Trends")
    assert "### 📊 Topic volume" in section
    assert "\n# " not in section  # no lone H1 anywhere in the embedded section


def test_cli_writes_default_path(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    vault = _vault(tmp_path)
    _append(vault / "pipeline" / "registry.md", _row("2026-06-15", "ai"))
    monkeypatch.setattr(tr, "PROJECT_ROOT", vault)
    monkeypatch.setattr(sys, "argv", ["trends.py"])
    code = tr.main(today=TODAY)
    assert code == 0
    expected = vault / "pipeline" / "3-synthesis" / "trends_2026-06-15.md"
    assert expected.exists()
    assert str(expected) in capsys.readouterr().out
