from __future__ import annotations

import re
from pathlib import Path


def validate_sources(path: Path) -> list[str]:
    """Return errors for sources.md — needs a well-formed markdown table."""
    if not path.exists():
        return [f"{path.name}: file not found at {path}"]
    lines = path.read_text(encoding="utf-8").splitlines()

    # A well-formed table = a header row, a separator row of dashes, and
    # at least one data row, all pipe-delimited.
    for i in range(len(lines) - 2):
        header = lines[i].strip()
        sep = lines[i + 1].strip()
        body = lines[i + 2].strip()
        if (
            header.startswith("|")
            and sep.startswith("|")
            and re.fullmatch(r"\|[\s\-:|]+\|", sep)
            and body.startswith("|")
        ):
            return []
    return [f"{path.name}: no well-formed markdown table found"]


# A topic section header in topics.md, e.g. `## Topic: ai-ml`. The name after the
# colon is the controlled topic key the rest of the pipeline groups/collects by.
_TOPIC_HEADER = re.compile(r"^##\s+Topic:\s*(.+?)\s*$", re.MULTILINE)
# The matching block in sources.md, e.g. `## Category: ai-ml`.
_CATEGORY_HEADER = re.compile(r"^##\s+Category:\s*(.+?)\s*$", re.MULTILINE)


def _topic_names(path: Path) -> list[str]:
    """Extract the `## Topic:` names from topics.md (empty if file is absent)."""
    if not path.exists():
        return []
    return _TOPIC_HEADER.findall(path.read_text(encoding="utf-8"))


def _category_names(path: Path) -> list[str]:
    """Extract the `## Category:` names from sources.md (empty if file is absent)."""
    if not path.exists():
        return []
    return _CATEGORY_HEADER.findall(path.read_text(encoding="utf-8"))


def validate_topics(path: Path) -> list[str]:
    """Return errors for topics.md — a core config file driving collection+digest.

    It must exist and carry at least one well-formed `## Topic:` section (the
    shape `source-manage` / collection / digest all read). A missing or
    section-less file is a FAIL finding, not a warning: with no topics the
    pipeline has nothing to collect into or group by.
    """
    if not path.exists():
        return [f"{path.name}: file not found at {path}"]
    if not _topic_names(path):
        return [f"{path.name}: no `## Topic:` section found (malformed/empty)"]
    return []


# NOTE: the topics<->sources name sync check now lives in
# `scripts.config_validation.sources_cfg.check_topics_sources_sync` — it is
# format-aware (either side may be the YAML twin) and builds on the md name
# extractors above for the legacy paths.


