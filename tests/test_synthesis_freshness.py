"""Tests for scripts/synthesis_freshness.py — content-hash re-synthesis trigger.

Before this, weekly-synthesis re-synthesized an already-covered topic only when
its doc was >30 days old AND the curated index had changed — so substantial new
material on an existing topic could sit unused for ~30 days. This module replaces
the time gate with a content-hash trigger: a topic is eligible whenever it has no
synthesis yet (NEW) or its curated index.md changed since the last synthesis
(STALE), regardless of age. The last-synthesized index hash lives in a sidecar
`pipeline/3-synthesis/{topic}/.synthesis-meta.json`, so the plain-Markdown
research doc is left untouched.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from scripts import synthesis_freshness as sf

_TODAY = date(2026, 6, 20)


@pytest.fixture(autouse=True)
def _isolate_state_env(monkeypatch):
    """Clear RESEARCH_BRAIN_STATE_DIR so these in-repo tests are hermetic.

    The freshness sidecar relocates onto a persistent volume when this var is set;
    a developer who has it exported must still see this suite pass. The
    relocation-specific tests below re-set it explicitly.
    """
    monkeypatch.delenv("RESEARCH_BRAIN_STATE_DIR", raising=False)


def _index(curated_root: Path, topic: str, n_sources: int) -> Path:
    d = curated_root / topic
    d.mkdir(parents=True, exist_ok=True)
    lines = [f"# {topic} — curated sources", ""]
    for i in range(n_sources):
        lines.append(f"- [title {i}](../../1-incoming/{topic}/2026-06-15_{i}.md) — summary {i}.")
    path = d / "index.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _companion(incoming_root: Path, topic: str, name: str, body: str) -> Path:
    """Create a sanitized companion file under 1-incoming/{topic}/sanitized/."""
    d = incoming_root / topic / "sanitized"
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    path.write_text(body, encoding="utf-8")
    return path


# ── primitives ───────────────────────────────────────────────────────────────


def test_index_hash_changes_with_content(tmp_path):
    idx = _index(tmp_path, "ai-agents", 3)
    h1 = sf.index_hash(idx)
    idx.write_text(idx.read_text(encoding="utf-8") + "\n- [new](x) — extra.\n", encoding="utf-8")
    h2 = sf.index_hash(idx)
    assert h1 != h2
    assert isinstance(h1, str) and len(h1) == 64


def test_count_sources(tmp_path):
    idx = _index(tmp_path, "ai-agents", 4)
    assert sf.count_sources(idx) == 4


# ── status classification ────────────────────────────────────────────────────


def test_status_new_when_no_sidecar(tmp_path):
    curated, synth = tmp_path / "2-curated", tmp_path / "3-synthesis"
    _index(curated, "ai-agents", 3)
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=3) is sf.Status.NEW


def test_status_below_threshold(tmp_path):
    curated, synth = tmp_path / "2-curated", tmp_path / "3-synthesis"
    _index(curated, "ai-agents", 2)
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=3) is sf.Status.BELOW_THRESHOLD


def test_status_fresh_after_stamp(tmp_path):
    curated, synth = tmp_path / "2-curated", tmp_path / "3-synthesis"
    _index(curated, "ai-agents", 3)
    sf.stamp(curated, synth, "ai-agents", when=_TODAY)
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=3) is sf.Status.FRESH


def test_status_stale_when_index_changes_after_stamp(tmp_path):
    """The core item-3 behavior: new material on an existing topic → STALE now,
    not after 30 days."""
    curated, synth = tmp_path / "2-curated", tmp_path / "3-synthesis"
    idx = _index(curated, "ai-agents", 3)
    sf.stamp(curated, synth, "ai-agents", when=_TODAY)

    # A new source arrives the same day.
    idx.write_text(
        idx.read_text(encoding="utf-8") + "- [fresh](../../1-incoming/ai-agents/new.md) — new.\n",
        encoding="utf-8",
    )
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=3) is sf.Status.STALE


def test_status_stale_when_companion_contents_are_swapped(tmp_path):
    """combined_hash must key companions by PATH, not just concatenated bytes —
    swapping two companions' contents between filenames is a real corpus change
    and must read STALE, not falsely FRESH (a path-blind hash would miss it)."""
    curated, synth = tmp_path / "2-curated", tmp_path / "3-synthesis"
    incoming = tmp_path / "1-incoming"
    _index(curated, "ai-agents", 2)
    _companion(incoming, "ai-agents", "2026-06-15_0.md", "ALPHA")
    _companion(incoming, "ai-agents", "2026-06-15_1.md", "BETA")
    sf.stamp(curated, synth, "ai-agents", when=_TODAY)
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=2) is sf.Status.FRESH

    # Swap the two companions' bodies between filenames — same total bytes, new mapping.
    _companion(incoming, "ai-agents", "2026-06-15_0.md", "BETA")
    _companion(incoming, "ai-agents", "2026-06-15_1.md", "ALPHA")
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=2) is sf.Status.STALE


def test_is_fresh_true_after_stamp_false_when_changed_or_unstamped(tmp_path):
    curated, synth = tmp_path / "2-curated", tmp_path / "3-synthesis"
    idx = _index(curated, "ai-agents", 3)
    # Never synthesized → not fresh.
    assert sf.is_fresh(curated, synth, "ai-agents") is False
    # Stamped against the current corpus → fresh.
    sf.stamp(curated, synth, "ai-agents", when=_TODAY)
    assert sf.is_fresh(curated, synth, "ai-agents") is True
    # Corpus changes after the stamp → no longer fresh.
    idx.write_text(idx.read_text(encoding="utf-8") + "- [x](y) — z.\n", encoding="utf-8")
    assert sf.is_fresh(curated, synth, "ai-agents") is False
    # Missing curated index → not fresh.
    assert sf.is_fresh(curated, synth, "no-such-topic") is False


def test_eligible_topics_returns_new_and_stale_only(tmp_path):
    curated, synth = tmp_path / "2-curated", tmp_path / "3-synthesis"
    _index(curated, "fresh-topic", 3)
    sf.stamp(curated, synth, "fresh-topic", when=_TODAY)  # FRESH → excluded
    _index(curated, "new-topic", 3)                       # NEW → included
    idx_stale = _index(curated, "stale-topic", 3)
    sf.stamp(curated, synth, "stale-topic", when=_TODAY)
    idx_stale.write_text(idx_stale.read_text(encoding="utf-8") + "- [x](y) — z.\n", encoding="utf-8")  # STALE
    _index(curated, "thin-topic", 1)                      # BELOW_THRESHOLD → excluded

    eligible = dict(sf.eligible_topics(curated, synth, min_sources=3))
    assert eligible == {"new-topic": sf.Status.NEW, "stale-topic": sf.Status.STALE}


def test_stamp_default_date_is_utc(tmp_path, monkeypatch):
    """The production default for `synthesized_at` (no `when=`) is the UTC date.

    The persisted-date axis must agree with health.py and the rest of the durability
    layer, which all source "today" from UTC (datetime.now(timezone.utc).date()) — so
    no module disagrees by a calendar day near midnight. We patch the module clock to a
    fixed UTC instant and assert the stamped date is that UTC date. With the old local
    `date.today()` default this assertion fails (it ignores the patched UTC clock)."""
    curated, synth = tmp_path / "2-curated", tmp_path / "3-synthesis"
    _index(curated, "ai-agents", 3)

    fixed_utc = datetime(2026, 6, 20, 23, 30, tzinfo=UTC)

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_utc if tz is None else fixed_utc.astimezone(tz)

    monkeypatch.setattr(sf, "datetime", _FixedDateTime)

    sidecar = sf.stamp(curated, synth, "ai-agents")  # no when= → production default
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["synthesized_at"] == "2026-06-20"


def test_stamp_is_idempotent_and_records_hash(tmp_path):
    curated, synth = tmp_path / "2-curated", tmp_path / "3-synthesis"
    idx = _index(curated, "ai-agents", 3)
    sf.stamp(curated, synth, "ai-agents", when=_TODAY)
    meta = synth / "ai-agents" / sf.SIDECAR_NAME
    assert meta.exists()
    incoming = tmp_path / "1-incoming"
    assert sf.recorded_hash(synth, "ai-agents") == sf.combined_hash(idx, incoming, "ai-agents")


# ── corpus-content & sanitizer-version coverage ──────────────────────────────


def test_status_stale_when_companion_text_changes(tmp_path):
    """index.md unchanged, but a sanitized companion's bytes change → STALE.

    This is the confirmed incompleteness: re-synthesis must fire when the actual
    synthesized corpus content changes, not only when the index listing changes.
    """
    curated = tmp_path / "2-curated"
    incoming = tmp_path / "1-incoming"
    synth = tmp_path / "3-synthesis"
    _index(curated, "ai-agents", 3)
    comp = _companion(incoming, "ai-agents", "2026-06-15_0.md", "original body")
    sf.stamp(curated, synth, "ai-agents", when=_TODAY)
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=3) is sf.Status.FRESH

    comp.write_text("MUTATED body", encoding="utf-8")  # index.md untouched
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=3) is sf.Status.STALE


def test_status_fresh_when_uncurated_companion_added(tmp_path):
    """A companion for an article the curated index does NOT list is not a
    synthesis input — collect+sanitize alone (no curate) must not read as a
    corpus change. The arrival gets its invalidation moment when curate
    promotes it and the index itself changes. (Reversed 2026-07-14: the
    whole-dir hash killed every digest lead on the first mid-cycle collect.)"""
    curated = tmp_path / "2-curated"
    incoming = tmp_path / "1-incoming"
    synth = tmp_path / "3-synthesis"
    _index(curated, "ai-agents", 3)
    _companion(incoming, "ai-agents", "2026-06-15_0.md", "body a")
    sf.stamp(curated, synth, "ai-agents", when=_TODAY)

    _companion(incoming, "ai-agents", "2026-07-13_new-arrival.md", "collected, not curated")
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=3) is sf.Status.FRESH


def test_is_fresh_survives_collect_only_arrivals(tmp_path):
    """The live 2026-07-13 incident: synthesis stamped on the 8th, a collect
    landed new sanitized companions on the 13th, and every per-topic digest
    lead was suppressed. Uncurated arrivals must leave is_fresh True."""
    curated, synth = tmp_path / "2-curated", tmp_path / "3-synthesis"
    incoming = tmp_path / "1-incoming"
    _index(curated, "ai-agents", 3)
    _companion(incoming, "ai-agents", "2026-06-15_0.md", "synthesized body")
    sf.stamp(curated, synth, "ai-agents", when=_TODAY)
    assert sf.is_fresh(curated, synth, "ai-agents")

    _companion(incoming, "ai-agents", "2026-07-13_fresh-collect.md", "not yet curated")
    assert sf.is_fresh(curated, synth, "ai-agents"), (
        "a collect-only arrival must not kill the topic's digest lead"
    )


def test_status_stale_when_sanitizer_version_bumps(tmp_path, monkeypatch):
    """Bumping SANITIZER_VERSION forces re-synthesis of everything."""
    curated = tmp_path / "2-curated"
    incoming = tmp_path / "1-incoming"
    synth = tmp_path / "3-synthesis"
    _index(curated, "ai-agents", 3)
    _companion(incoming, "ai-agents", "2026-06-15_0.md", "body a")
    sf.stamp(curated, synth, "ai-agents", when=_TODAY)
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=3) is sf.Status.FRESH

    monkeypatch.setattr(sf, "SANITIZER_VERSION", sf.SANITIZER_VERSION + "-bumped")
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=3) is sf.Status.STALE


def test_fresh_after_stamp_with_no_companions(tmp_path):
    """A topic with no sanitized companions degrades gracefully (index + version
    only) — stamp then status is FRESH, no crash."""
    curated = tmp_path / "2-curated"
    synth = tmp_path / "3-synthesis"
    _index(curated, "ai-agents", 3)  # no companions created
    sf.stamp(curated, synth, "ai-agents", when=_TODAY)
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=3) is sf.Status.FRESH


def test_old_sidecar_without_combined_hash_reads_stale(tmp_path):
    """An old sidecar (only the legacy source_index_hash, no combined hash) must
    read as STALE — the safe direction — not crash and not falsely FRESH."""
    curated = tmp_path / "2-curated"
    synth = tmp_path / "3-synthesis"
    idx = _index(curated, "ai-agents", 3)
    legacy_dir = synth / "ai-agents"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / sf.SIDECAR_NAME).write_text(
        json.dumps({"source_index_hash": sf.index_hash(idx), "synthesized_at": "2026-01-01"}),
        encoding="utf-8",
    )
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=3) is sf.Status.STALE


# ── CLI ──────────────────────────────────────────────────────────────────────


def test_cli_list_prints_eligible(tmp_path, capsys):
    curated, synth = tmp_path / "2-curated", tmp_path / "3-synthesis"
    _index(curated, "new-topic", 3)
    rc = sf.main(["list", "--curated", str(curated), "--synthesis", str(synth), "--min-sources", "3"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "new-topic" in out


def test_cli_stamp_then_list_excludes_topic(tmp_path, capsys):
    curated, synth = tmp_path / "2-curated", tmp_path / "3-synthesis"
    _index(curated, "ai-agents", 3)
    assert sf.main(["stamp", "ai-agents", "--curated", str(curated), "--synthesis", str(synth)]) == 0
    capsys.readouterr()
    sf.main(["list", "--curated", str(curated), "--synthesis", str(synth), "--min-sources", "3"])
    assert "ai-agents" not in capsys.readouterr().out


def test_cli_list_empty_when_nothing_eligible(tmp_path, capsys):
    curated, synth = tmp_path / "2-curated", tmp_path / "3-synthesis"
    rc = sf.main(["list", "--curated", str(curated), "--synthesis", str(synth)])
    assert rc == 0
    assert "no topics" in capsys.readouterr().out.lower()


# ── durable runtime state — RESEARCH_BRAIN_STATE_DIR relocates the sidecar ────

_STATE_ENV = "RESEARCH_BRAIN_STATE_DIR"


def test_sidecar_in_repo_when_state_env_unset(tmp_path, monkeypatch):
    # Default (env unset): the sidecar resolves to the exact in-repo path.
    monkeypatch.delenv(_STATE_ENV, raising=False)
    synth = tmp_path / "pipeline" / "3-synthesis"
    assert sf._sidecar(synth, "ai-agents") == synth / "ai-agents" / sf.SIDECAR_NAME


def test_sidecar_relocates_under_state_dir(tmp_path, monkeypatch):
    # env SET: the sidecar relocates under the state dir, preserving the
    # pipeline/3-synthesis/{topic}/.synthesis-meta.json substructure (project root
    # is the synthesis root's grandparent).
    state_dir = tmp_path / "volume"
    synth = tmp_path / "repo" / "pipeline" / "3-synthesis"
    monkeypatch.setenv(_STATE_ENV, str(state_dir))
    assert sf._sidecar(synth, "ai-agents") == (
        state_dir / "pipeline" / "3-synthesis" / "ai-agents" / sf.SIDECAR_NAME
    )


def test_freshness_under_state_dir_survives_wiped_repo(tmp_path, monkeypatch):
    # The durability guarantee: with the state dir set, a topic stamped on run 1
    # lives on the persistent volume, so a wiped repo (fresh clone / redeploy)
    # still reads FRESH — it does NOT needlessly re-synthesize every topic.
    state_dir = tmp_path / "volume"
    root = tmp_path / "repo"
    curated = root / "pipeline" / "2-curated"
    synth = root / "pipeline" / "3-synthesis"
    monkeypatch.setenv(_STATE_ENV, str(state_dir))

    _index(curated, "ai-agents", 3)
    sf.stamp(curated, synth, "ai-agents", when=_TODAY)
    # The sidecar was written onto the volume, not inside the repo's synthesis dir.
    assert (state_dir / "pipeline" / "3-synthesis" / "ai-agents" / sf.SIDECAR_NAME).exists()
    assert not (synth / "ai-agents" / sf.SIDECAR_NAME).exists()

    # Simulate a wiped repo synthesis dir: the freshness check still reads FRESH
    # via the volume, so the topic is not re-synthesized.
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=3) is sf.Status.FRESH


def test_status_stays_fresh_after_no_op_resanitize(tmp_path):
    """The weekly orchestrator re-runs `sanitize` before every synthesis pass.
    With no new content, the topic must stay FRESH — a churned companion
    (e.g. a refreshed stripped_at) would re-synthesize every topic every week."""
    from scripts import sanitize_incoming as si

    curated, synth = tmp_path / "2-curated", tmp_path / "3-synthesis"
    incoming = tmp_path / "1-incoming"
    topic_dir = incoming / "ai-agents"
    topic_dir.mkdir(parents=True)
    (topic_dir / "a1.md").write_text(
        "---\ntitle: t\nurl: https://example.com/a\n---\n\nSteady content.\n",
        encoding="utf-8",
    )
    _index(curated, "ai-agents", 3)

    si.sanitize_tree(incoming, now=datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC))
    sidecar = sf.stamp(curated, synth, "ai-agents", when=_TODAY)
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=3) is sf.Status.FRESH
    assert sidecar.exists()

    si.sanitize_tree(incoming, now=datetime(2026, 6, 27, 12, 0, 0, tzinfo=UTC))
    assert sf.topic_status(curated, synth, "ai-agents", min_sources=3) is sf.Status.FRESH
    assert sidecar.exists()
