"""
test_brain_status.py — offline tests for the read-only brain-status queries.

Every test builds a self-contained fake vault under a tmp dir (its own
config/ + pipeline/3-synthesis/ layout) and drives `brain_status` against it,
so the tests are deterministic and never touch the real vault. No network.

Coverage: monitored_sources (parse + active-only filter + no-active case),
cadence (plain-language schedule summary), list_digests (newest-first ordering
+ truncation to N + empty case), and latest_findings (extraction from the
latest digest, the quiet-week "nothing new" case, and the no-digests case).
"""
from pathlib import Path

import pytest

from scripts import brain_status as bs  # noqa: E402

# A test-owned snapshot of the EXAMPLE config (NOT the live `config/`), so the
# template-integrity check below holds in a configured deployment too.
EXAMPLE_CONFIG = Path(__file__).resolve().parent / "fixtures" / "example_config"


# --------------------------------------------------------------------------- #
# Fixtures / sample content
# --------------------------------------------------------------------------- #

# A two-category sources.md in the RETIRED legacy table format (schema_version 1).
# Since 0.8.0 the runtime never reads it (CONVENTIONS §2.3) — tests use it only to
# seed legacy/stale `.md` states next to (or instead of) the active YAML config.
SAMPLE_SOURCES = """\
# config/sources.md — Source registry

**Updated:** 2026-06-01

## Category: ai-news

**Save folder:** `pipeline/1-incoming/ai-news/`
**Registry category:** `ai-news`

### Active sources

| URL | Type | Tier | Priority | Filter | Active |
|-----|------|------|----------|--------|--------|
| https://ai.example.com/feed.xml | rss | high | high | all articles | yes |
| https://medium.com/tag/ai/latest | medium-tag | low | medium | on-topic only | no |  <!-- parked -->

### Candidates (not yet automated)

| URL | Type | Note |
|-----|------|------|
| https://other.example.org/blog | blog | parked idea |

## Category: security

**Save folder:** `pipeline/1-incoming/security/`

### Active sources

| URL | Type | Tier | Priority | Filter | Active |
|-----|------|------|----------|--------|--------|
| https://sec.example.com/rss | rss | medium | high | CVEs and advisories | yes |
"""


# The same two-category monitored set in the ACTIVE YAML format (schema_version 2,
# CONVENTIONS §2.3): a parked `active: false` Medium row that the default
# active-only view must skip, plus one active feed per category.
SAMPLE_SOURCES_YAML = """\
schema_version: 2
categories:
  - name: ai-news
    sources:
      - url: "https://ai.example.com/feed.xml"
        type: rss
        tier: high
        priority: high
        filter: all articles
        active: true
      - url: "https://medium.com/tag/ai/latest"
        type: medium-tag
        tier: low
        priority: medium
        filter: on-topic only
        active: false
  - name: security
    sources:
      - url: "https://sec.example.com/rss"
        type: rss
        tier: medium
        priority: high
        filter: CVEs and advisories
        active: true
"""


SAMPLE_SCHEDULE = """\
collect:
  cron: "0 9 */3 * *"
  max_articles_per_topic: 10
curate:
  cron: "0 8 * * 1"
  min_text_chars: 500
synthesis:
  cron: "30 8 * * 1"
  min_sources_per_topic: 3
digest:
  cron: "0 9 * * 1"
  lookback_days: 7
timezone: "Europe/Minsk"
"""


# A normal (non-quiet) digest in the exact shape `build_digest.render` writes.
DIGEST_NORMAL = """\
# Weekly digest — 2026-06-15

_3 new sources across 2 topics, 1 updated concept._

**Knowledge base health:** 12 concepts · 0 orphans · 1 stale

## New sources (last 7 days)

### ai-news
- "Transformers get faster" [high] — A new attention kernel halves latency.
- "Open weights released" — A lab open-sourced a 70B model.

### security
- "Critical CVE in libfoo" [medium] — Remote code execution, patch now.

## Updated concepts (last 7 days)

- Retrieval-augmented generation [high] — Grounding an LLM in fetched documents.
  - ✓ Confirmed by 3 independent sources

## Needs attention

Nothing pending.
"""


# A quiet-week digest, exactly as `build_digest.render` writes it.
DIGEST_QUIET = """\
# Weekly digest — 2026-06-08

Quiet week — no new sources and no concept updates in the last 7 days.
"""


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """A minimal fake vault skeleton; tests populate the bits they need."""
    (tmp_path / "config").mkdir()
    (tmp_path / "pipeline" / "3-synthesis").mkdir(parents=True)
    return tmp_path


def _write_sources(vault: Path, text: str = SAMPLE_SOURCES) -> None:
    (vault / "config" / "sources.md").write_text(text, encoding="utf-8")


def _write_sources_yaml(vault: Path, text: str = SAMPLE_SOURCES_YAML) -> None:
    (vault / "config" / "sources.yaml").write_text(text, encoding="utf-8")


def _write_schedule(vault: Path, text: str = SAMPLE_SCHEDULE) -> None:
    (vault / "config" / "schedule.yaml").write_text(text, encoding="utf-8")


def _write_digest(vault: Path, name: str, text: str) -> None:
    (vault / "pipeline" / "3-synthesis" / name).write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# monitored_sources
# --------------------------------------------------------------------------- #


def test_monitored_sources_active_only(vault: Path) -> None:
    _write_sources_yaml(vault)
    sources = bs.monitored_sources(root=vault)
    # Two active sources (one per category); the parked `active: false` Medium
    # entry is excluded by default.
    assert len(sources) == 2
    urls = {s.url for s in sources}
    assert "https://ai.example.com/feed.xml" in urls
    assert "https://sec.example.com/rss" in urls
    assert "https://medium.com/tag/ai/latest" not in urls


def test_monitored_sources_record_fields(vault: Path) -> None:
    _write_sources_yaml(vault)
    sources = bs.monitored_sources(root=vault)
    by_url = {s.url: s for s in sources}
    ai = by_url["https://ai.example.com/feed.xml"]
    assert ai.category == "ai-news"
    assert ai.type == "rss"
    assert ai.tier == "high"
    assert ai.priority == "high"
    assert ai.active is True


def test_monitored_sources_include_inactive(vault: Path) -> None:
    _write_sources_yaml(vault)
    sources = bs.monitored_sources(root=vault, active_only=False)
    # Now the parked Medium entry is included too (3 active+inactive sources).
    assert len(sources) == 3
    inactive = [s for s in sources if not s.active]
    assert len(inactive) == 1
    assert inactive[0].url == "https://medium.com/tag/ai/latest"


def test_monitored_sources_no_active(vault: Path) -> None:
    # A config whose only source is parked -> empty active result, no crash.
    _write_sources_yaml(
        vault,
        "schema_version: 2\n"
        "categories:\n"
        "  - name: empty\n"
        "    sources:\n"
        "      - url: \"https://x.example.com/rss\"\n"
        "        type: rss\n"
        "        tier: low\n"
        "        priority: low\n"
        "        filter: \"none\"\n"
        "        active: false\n",
    )
    assert bs.monitored_sources(root=vault) == []


def test_monitored_sources_missing_file(vault: Path) -> None:
    # No sources.yaml at all -> empty list, never an exception.
    assert bs.monitored_sources(root=vault) == []


# A legacy sources.md whose only rows are EXAMPLE placeholders (the pre-0.8.0
# template shape): each row carries the `# EXAMPLE — replace` marker in its
# trailing comment. Placeholders are template furniture, not user config — the
# dir is NOT an unmigrated legacy install, and nothing is monitored.
EXAMPLE_ONLY_SOURCES = """\
## Category: example-topic

### Active sources

| URL | Type | Tier | Priority | Filter | Active |
|-----|------|------|----------|--------|--------|
| https://example.com/feed.xml | rss | high | high | all articles | yes |  <!-- # EXAMPLE — replace -->
| https://medium.com/tag/example/latest | medium-tag | low | medium | on-topic | no |  <!-- # EXAMPLE — replace -->
"""


def test_monitored_sources_excludes_example_placeholder_rows(vault: Path) -> None:
    # An unconfigured pre-0.8.0 install holds only EXAMPLE rows in the legacy
    # .md — brain_status must report ZERO real monitored sources (never
    # "monitoring example.com"): the .md is not the active config, and with no
    # YAML twin nothing is monitored. FIX 3 holds through the format change.
    _write_sources(vault, EXAMPLE_ONLY_SOURCES)
    assert bs.monitored_sources(root=vault, active_only=False) == []
    assert bs.monitored_sources(root=vault) == []


def test_unmigrated_legacy_dir_reads_empty_and_cli_points_at_migration(
    vault: Path, capsys, monkeypatch
) -> None:
    # 0.8.0 (YAML-only): a real row still living in sources.md with no YAML twin
    # is the UNMIGRATED legacy state. The API stays a non-raising status read
    # (health/doctor must keep answering) and returns [] — but the CLI must not
    # be silent about WHY: `brain_status.py sources` prints the migrate-config
    # pointer so the user never mistakes an unreadable config for an empty one.
    _write_sources(
        vault,
        EXAMPLE_ONLY_SOURCES
        + "| https://real.example/rss | rss | high | high | real | yes |\n",
    )
    assert bs.monitored_sources(root=vault, active_only=False) == []

    monkeypatch.setattr(bs, "_PROJECT_ROOT", vault)
    rc = bs.main(["sources"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "migrate-config" in err


def test_monitored_sources_shipped_template_has_zero_real_sources(tmp_path: Path) -> None:
    # The shipped template must monitor no real sources — a fresh clone must
    # not start fetching example feeds. Validate the committed example snapshot
    # via a temp root, so the guard holds regardless of a real deployment's
    # configured sources (it never reads the live config/): the ACTIVE
    # sources.yaml is empty, and the retained EXAMPLE sources.md beside it must
    # stay ignored.
    (tmp_path / "config").mkdir()
    for name in ("sources.yaml", "sources.md"):
        (tmp_path / "config" / name).write_text(
            (EXAMPLE_CONFIG / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    records = bs.monitored_sources(root=tmp_path, active_only=False)
    assert records == []


# --------------------------------------------------------------------------- #
# cadence
# --------------------------------------------------------------------------- #


def test_cadence_summary_fields(vault: Path) -> None:
    _write_schedule(vault)
    summary = bs.cadence(root=vault)
    assert summary.timezone == "Europe/Minsk"
    assert summary.lookback_days == 7
    # One entry per scheduled block, each with a cron string.
    blocks = {b.name: b for b in summary.blocks}
    assert set(blocks) == {"collect", "curate", "synthesis", "digest"}
    assert blocks["collect"].cron == "0 9 */3 * *"
    assert blocks["digest"].cron == "0 9 * * 1"


def test_cadence_plain_language(vault: Path) -> None:
    _write_schedule(vault)
    summary = bs.cadence(root=vault)
    collect = next(b for b in summary.blocks if b.name == "collect")
    # The human-readable cadence phrase is non-empty and mentions a recognizable
    # cue from the cron (every 3 days).
    assert collect.description
    assert "3 day" in collect.description.lower()


def test_cadence_missing_file_defaults(vault: Path) -> None:
    # No schedule.yaml -> defaults (UTC, default lookback), never a crash.
    summary = bs.cadence(root=vault)
    assert summary.timezone == "UTC"
    assert summary.lookback_days == bs.DEFAULT_LOOKBACK_DAYS


# --------------------------------------------------------------------------- #
# list_digests
# --------------------------------------------------------------------------- #


def test_list_digests_newest_first(vault: Path) -> None:
    _write_digest(vault, "digest_2026-06-01.md", DIGEST_NORMAL)
    _write_digest(vault, "digest_2026-06-15.md", DIGEST_NORMAL)
    _write_digest(vault, "digest_2026-06-08.md", DIGEST_QUIET)
    digests = bs.list_digests(root=vault)
    dates = [d.date.isoformat() for d in digests]
    assert dates == ["2026-06-15", "2026-06-08", "2026-06-01"]


def test_list_digests_truncates_to_n(vault: Path) -> None:
    for day in ("01", "08", "15", "22"):
        _write_digest(vault, f"digest_2026-06-{day}.md", DIGEST_NORMAL)
    digests = bs.list_digests(n=2, root=vault)
    assert len(digests) == 2
    assert digests[0].date.isoformat() == "2026-06-22"
    assert digests[1].date.isoformat() == "2026-06-15"


def test_list_digests_summary_line(vault: Path) -> None:
    _write_digest(vault, "digest_2026-06-15.md", DIGEST_NORMAL)
    _write_digest(vault, "digest_2026-06-08.md", DIGEST_QUIET)
    by_date = {d.date.isoformat(): d for d in bs.list_digests(root=vault)}
    # The normal digest's one-liner is its volume headline.
    assert "3 new sources" in by_date["2026-06-15"].summary
    # The quiet digest is recognized as quiet.
    assert by_date["2026-06-08"].is_quiet
    assert "quiet" in by_date["2026-06-08"].summary.lower()


def test_list_digests_empty(vault: Path) -> None:
    # No digests yet -> empty list, never a crash.
    assert bs.list_digests(root=vault) == []


# An agent-authored digest may open with a `---` YAML frontmatter block. The
# summary must skip the frontmatter and use the real headline, not return "---".
DIGEST_WITH_FRONTMATTER = """\
---
title: Weekly digest
date: 2026-06-15
---

# Weekly digest — 2026-06-15

_4 new sources across 3 topics._

## New sources (last 7 days)
- "Something happened" — details.
"""


def test_digest_summary_skips_frontmatter(vault: Path) -> None:
    # A frontmatter-prefixed digest must summarize as its volume headline, not as
    # the leading `---` fence. FIX 4.
    _write_digest(vault, "digest_2026-06-15.md", DIGEST_WITH_FRONTMATTER)
    entry = bs.list_digests(root=vault)[0]
    assert entry.summary == "4 new sources across 3 topics."
    assert entry.summary != "---"


# --------------------------------------------------------------------------- #
# latest_findings
# --------------------------------------------------------------------------- #


def test_latest_findings_from_normal_digest(vault: Path) -> None:
    _write_digest(vault, "digest_2026-06-08.md", DIGEST_QUIET)
    _write_digest(vault, "digest_2026-06-15.md", DIGEST_NORMAL)
    findings = bs.latest_findings(root=vault)
    # It reads the NEWEST digest (06-15), not the quiet earlier one.
    assert findings.digest_date.isoformat() == "2026-06-15"
    assert not findings.is_quiet
    assert not findings.no_digests
    # Highlights include the new-source titles and the updated concept.
    joined = " || ".join(findings.highlights)
    assert "Transformers get faster" in joined
    assert "Critical CVE in libfoo" in joined
    assert "Retrieval-augmented generation" in joined


def test_latest_findings_quiet_week(vault: Path) -> None:
    _write_digest(vault, "digest_2026-06-08.md", DIGEST_QUIET)
    findings = bs.latest_findings(root=vault)
    # Quiet week -> a clear "nothing new" signal, no highlights, no crash.
    assert findings.is_quiet
    assert findings.highlights == []
    assert findings.message
    assert "quiet" in findings.message.lower() or "nothing" in findings.message.lower()


def test_latest_findings_no_digests(vault: Path) -> None:
    # No digests at all -> a clear "no digests yet" signal, never a crash.
    findings = bs.latest_findings(root=vault)
    assert findings.no_digests
    assert findings.highlights == []
    assert findings.message


# --------------------------------------------------------------------------- #
# Read-only guarantee
# --------------------------------------------------------------------------- #


def test_queries_do_not_write(vault: Path) -> None:
    _write_sources_yaml(vault)
    _write_schedule(vault)
    _write_digest(vault, "digest_2026-06-15.md", DIGEST_NORMAL)

    def files() -> list[str]:
        # Whole-vault view: catches a stray write anywhere, including a query
        # quietly seeding config/ YAML twins (that is the mutators' job only).
        return sorted(str(p.relative_to(vault)) for p in vault.rglob("*") if p.is_file())

    before = files()
    bs.monitored_sources(root=vault)
    bs.cadence(root=vault)
    bs.list_digests(root=vault)
    bs.latest_findings(root=vault)
    # No new files were created by the read-only queries.
    assert files() == before


# --------------------------------------------------------------------------- #
# Regression: quiet-week match is body-scoped (M6)
# --------------------------------------------------------------------------- #

_DIGEST_QUIET_IN_FRONTMATTER = """\
---
title: Not a quiet week at all
---

# Weekly digest — 2026-06-15

_5 new sources across 2 topics._

## New sources
- "Real finding" — details.
"""


def test_m6_quiet_phrase_in_frontmatter_is_not_flagged(vault: Path) -> None:
    # "quiet week" appearing only in the frontmatter title must NOT mark the
    # digest as a quiet week — the body has real volume.
    _write_digest(vault, "digest_2026-06-15.md", _DIGEST_QUIET_IN_FRONTMATTER)
    entry = bs.list_digests(root=vault)[0]
    assert entry.summary == "5 new sources across 2 topics."


# --------------------------------------------------------------------------- #
# Regression: describe_cron sub-daily cadences (cycle-3 sweep)
# --------------------------------------------------------------------------- #


def test_describe_cron_sub_daily_minute_step() -> None:
    # `*/15 * * * *` must read as "every 15 minutes", not "every day".
    assert bs.describe_cron("*/15 * * * *") == "every 15 minutes"
    assert bs.describe_cron("*/1 * * * *") == "every 1 minute"


def test_describe_cron_hour_step() -> None:
    assert bs.describe_cron("0 */3 * * *") == "every 3 hours"


def test_describe_cron_still_handles_daily_and_weekly() -> None:
    # No regression on the patterns the project actually uses.
    assert bs.describe_cron("0 9 * * 1").startswith("every Monday")
    assert bs.describe_cron("0 9 * * *").startswith("every day")
    assert bs.describe_cron("0 9 */3 * *").startswith("every 3 days")


def test_monitored_sources_prefers_yaml_config(vault: Path) -> None:
    # When the YAML twins exist they ARE the config — a stale sources.md next to
    # them must be ignored (CONVENTIONS §2.3).
    _write_sources(vault)  # stale legacy file
    (vault / "config" / "sources.yaml").write_text(
        "schema_version: 2\n"
        "categories:\n"
        "  - name: yaml-only\n"
        "    sources:\n"
        "      - url: \"https://yaml.example.com/feed\"\n"
        "        type: rss\n"
        "        tier: high\n"
        "        priority: high\n"
        "        filter: all\n"
        "        active: true\n"
        "      - url: \"https://paused.example.com/feed\"\n"
        "        type: rss\n"
        "        tier: low\n"
        "        priority: low\n"
        "        filter: all\n"
        "        active: false\n",
        encoding="utf-8",
    )
    active = bs.monitored_sources(root=vault)
    assert [(s.category, s.url) for s in active] == [
        ("yaml-only", "https://yaml.example.com/feed")
    ]
    everything = bs.monitored_sources(root=vault, active_only=False)
    assert {s.url for s in everything} == {
        "https://yaml.example.com/feed", "https://paused.example.com/feed",
    }


def test_monitored_sources_malformed_yaml_degrades_to_empty(vault: Path) -> None:
    # A broken YAML config must not crash the read-only status path — the loud
    # failure belongs to validate_config/doctor; status degrades to "none".
    (vault / "config" / "sources.yaml").write_text("categories: 3\n", encoding="utf-8")
    assert bs.monitored_sources(root=vault) == []
