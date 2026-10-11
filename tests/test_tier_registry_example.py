"""
test_tier_registry_example.py — integrity of the shipped tier-registry templates.

The source tier-registry is opt-in: `research-audit` FULL mode, `source-archive`
tiering and the `research-frame` always-volatile override only activate when the
user provides `sources/trusted-registry.md` (+ `sources/always-volatile-domains.md`).
To make that discoverable, the repo ships ready-to-copy `*.example.md` templates;
the user copies one, drops the `.example`, and edits it.

These tests pin the templates so they can't silently drift away from the schema
the skills actually parse — the registry table columns + the T1/T2/T3 tier
vocabulary (`skills/source-archive/SKILL.md` Phase 3, `research-audit`
`references/tier-rules.md`), and the always-volatile override columns.
"""
import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

REGISTRY_EXAMPLE = _PROJECT_ROOT / "sources" / "trusted-registry.example.md"
VOLATILE_EXAMPLE = _PROJECT_ROOT / "sources" / "always-volatile-domains.example.md"

# The columns source-archive copies on a host hit (SKILL.md Phase 3).
REGISTRY_COLUMNS = ["host", "tier", "topics", "volatility", "access"]
# The closed tier vocabulary research-audit grades against.
VALID_TIERS = {"T1", "T2", "T3"}


def _table_rows(text: str) -> list[list[str]]:
    """Parse markdown `| a | b |` table rows into stripped cell lists.

    Skips the header separator row (cells of only `-`/`:`) and any non-table
    lines, so prose around the table doesn't break the check.
    """
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells and all(set(c) <= {"-", ":"} and c for c in cells):
            continue  # separator row
        rows.append(cells)
    return rows


def test_registry_example_exists_and_has_schema_columns() -> None:
    assert REGISTRY_EXAMPLE.exists(), f"missing template: {REGISTRY_EXAMPLE}"
    rows = _table_rows(REGISTRY_EXAMPLE.read_text(encoding="utf-8"))
    assert rows, "registry template has no table rows"
    header = [c.lower() for c in rows[0]]
    for col in REGISTRY_COLUMNS:
        assert col in header, f"registry template header missing `{col}` column"


def test_registry_example_only_uses_valid_tiers() -> None:
    text = REGISTRY_EXAMPLE.read_text(encoding="utf-8")
    rows = _table_rows(text)
    header = [c.lower() for c in rows[0]]
    tier_idx = header.index("tier")
    data_rows = [r for r in rows[1:] if len(r) > tier_idx]
    assert data_rows, "registry template has no example source rows"
    for row in data_rows:
        assert row[tier_idx] in VALID_TIERS, (
            f"row {row!r} uses tier {row[tier_idx]!r}; must be one of {VALID_TIERS}"
        )


def test_volatile_example_exists_and_documents_override() -> None:
    assert VOLATILE_EXAMPLE.exists(), f"missing template: {VOLATILE_EXAMPLE}"
    text = VOLATILE_EXAMPLE.read_text(encoding="utf-8")
    # The override's defining effect is a tighter recency window (3 months);
    # the template must make that concrete so a copier knows what it does.
    assert re.search(r"recency", text, re.IGNORECASE), "volatile template omits recency override"
    assert "3mo" in text or "3 mo" in text or "90" in text, (
        "volatile template should state the 3-month (90-day) recency override"
    )
