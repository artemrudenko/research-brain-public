"""Drift tests: every shipped skill is catalogued in the docs a user actually reads.

`skills/` is the engine, and three surfaces claim to enumerate it: the AGENTS.md
trigger table (which calls itself "the authoritative list"), the USER_GUIDE §3
skill catalog, and the README repository map. `discover-sources` and
`author-manage` shipped in 0.10.0 but reached only the first one, so both
user-facing catalogs advertised 23 of the 25 skills that exist — a capability the
product has and never mentions. These tests pin the three surfaces to the
filesystem, so a new skill cannot ship undocumented.

Dev-only skills are excluded exactly the way the distribution archive excludes
them — by the `export-ignore` entries in `.gitattributes` (today `skills/release/`,
the contributor release ritual). Deriving the exclusion instead of hardcoding it
means a newly export-ignored skill drops out of the expectation automatically,
and a newly SHIPPED one is required to be documented.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = PROJECT_ROOT / "skills"
GITATTRIBUTES = PROJECT_ROOT / ".gitattributes"

# `| **setup-wizard** | When to use | Triggers |` — the AGENTS.md trigger table.
_AGENTS_ROW = re.compile(r"^\|\s*\*\*([a-z][a-z-]+)\*\*\s*\|", re.MULTILINE)
# `| **`setup-wizard`** | … |` — the USER_GUIDE §3 catalog (name in inline code).
_USER_GUIDE_ROW = re.compile(r"^\|\s*\*\*`([a-z][a-z-]+)`\*\*\s*\|", re.MULTILINE)
# Inline-code tokens inside the README's one-line `skills/` map row.
_README_TOKEN = re.compile(r"`([a-z][a-z*-]+)`")

# The README row groups the four research-chain skills as `research-*`; that is a
# deliberate, readable summary of a five-name family, not drift. Any other skill
# must be named outright.
_README_FAMILIES = {"research-*": ("research-frame", "research-grep",
                                   "research-build", "research-audit")}


def _export_ignored_skills() -> set[str]:
    """Skill names carrying `export-ignore` in `.gitattributes` (dev-only)."""
    ignored: set[str] = set()
    for line in GITATTRIBUTES.read_text(encoding="utf-8").splitlines():
        if "export-ignore" not in line or line.lstrip().startswith("#"):
            continue
        pattern = line.split()[0].strip("/")
        if pattern.startswith("skills/"):
            ignored.add(pattern.split("/")[1])
    return ignored


@pytest.fixture(scope="module")
def shipped_skills() -> list[str]:
    """Every skill an end user's install actually receives."""
    dev_only = _export_ignored_skills()
    assert dev_only, (
        ".gitattributes no longer export-ignores any skill — if the release "
        "ritual now ships, this test's premise changed deliberately"
    )
    names = sorted(
        p.name
        for p in SKILLS_DIR.iterdir()
        if p.is_dir() and (p / "SKILL.md").exists() and p.name not in dev_only
    )
    assert names, "no shipped skills found under skills/"
    return names


def _missing(skills: list[str], documented: set[str]) -> list[str]:
    return [name for name in skills if name not in documented]


def test_agents_trigger_table_lists_every_shipped_skill(
    shipped_skills: list[str],
) -> None:
    text = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    documented = set(_AGENTS_ROW.findall(text))
    assert not _missing(shipped_skills, documented), (
        "AGENTS.md calls its trigger table the authoritative skill list, but "
        f"these shipped skills have no row: {_missing(shipped_skills, documented)}"
    )


def test_user_guide_catalog_lists_every_shipped_skill(
    shipped_skills: list[str],
) -> None:
    text = (PROJECT_ROOT / "USER_GUIDE.md").read_text(encoding="utf-8")
    documented = set(_USER_GUIDE_ROW.findall(text))
    assert not _missing(shipped_skills, documented), (
        "USER_GUIDE.md §3 is the user's skill catalog; these shipped skills are "
        f"absent from it: {_missing(shipped_skills, documented)}"
    )


def test_readme_repository_map_names_every_shipped_skill(
    shipped_skills: list[str],
) -> None:
    row = next(
        (
            line
            for line in (PROJECT_ROOT / "README.md").read_text(encoding="utf-8").splitlines()
            if line.startswith("| `skills/` |")
        ),
        None,
    )
    assert row is not None, "README repository map has no `skills/` row"
    documented = set(_README_TOKEN.findall(row))
    for family, members in _README_FAMILIES.items():
        if family in documented:
            documented.update(members)
    assert not _missing(shipped_skills, documented), (
        "the README repository map enumerates the skills; these shipped ones are "
        f"missing: {_missing(shipped_skills, documented)}"
    )


# The internal decks (export-ignored, `docs/decks/`) enumerate the skills by name.
# Their counts are prose that dates itself, but an *omitted* skill is drift the team
# has been bitten by twice, so the name lists are pinned. Markup differs per deck:
# the RU showcase uses `class="skn"` rows, the presentation a `class="sk"` chip cloud.
_DECK_NAME_PATTERNS = {
    "research-brain-showcase.html": re.compile(r'class="skn">([a-z][a-z-]+)<'),
    "research-brain-presentation.html": re.compile(
        r'class="sk"><span class="dot">●</span>([a-z][a-z-]+)<'
    ),
}


@pytest.mark.parametrize("deck", sorted(_DECK_NAME_PATTERNS))
def test_internal_decks_enumerate_the_shipped_skills(
    deck: str, shipped_skills: list[str]
) -> None:
    path = PROJECT_ROOT / "docs" / "decks" / deck
    if not path.exists():  # decks are export-ignored — absent in a shipped install
        pytest.skip(f"{deck} not present (dev-only artifact)")
    listed = set(_DECK_NAME_PATTERNS[deck].findall(path.read_text(encoding="utf-8")))
    assert listed == set(shipped_skills), (
        f"{deck}'s skill list drifted "
        f"(missing: {sorted(set(shipped_skills) - listed)}, "
        f"stale: {sorted(listed - set(shipped_skills))})"
    )


def test_dev_only_skills_stay_out_of_the_user_facing_catalogs() -> None:
    """The release ritual is export-ignored — a user's install has no such skill,
    so advertising it in the shipped docs would point at a file that isn't there."""
    dev_only = _export_ignored_skills()
    for doc in ("AGENTS.md", "USER_GUIDE.md"):
        text = (PROJECT_ROOT / doc).read_text(encoding="utf-8")
        rows = set(_AGENTS_ROW.findall(text)) | set(_USER_GUIDE_ROW.findall(text))
        leaked = sorted(dev_only & rows)
        assert not leaked, f"{doc} catalogs dev-only skill(s) that never ship: {leaked}"
