from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from scripts.sources.validation import (
    _EXAMPLE_MARKER,
    _ROW_COMMENT_RE,
    _TABLE_HEADER,
    _TABLE_SEP,
    _is_example_row,
    _strip_row_comment,
)

__all__ = [
    "_EXAMPLE_MARKER",
    "_ROW_COMMENT_RE",
    "_TABLE_HEADER",
    "_TABLE_SEP",
    "_append_section",
    "_category_block",
    "_is_example_row",
    "_iter_source_rows",
    "_read",
    "_remove_section",
    "_section_bounds",
    "_set_active_cell",
    "_strip_row_comment",
    "_table_insert_index",
    "_topic_block",
]

# --------------------------------------------------------------------------- #


def _read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    return path.read_text(encoding="utf-8")


def _section_bounds(lines: list[str], heading: str) -> tuple[int, int] | None:
    """Return (start, end) line indices of a `## <heading>` section.

    `end` is exclusive and points at the next `## ` heading (or end of file).
    Returns None when the heading is absent.
    """
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return start, end


def _iter_source_rows(lines: list[str]) -> Iterator[tuple[int, list[str]]]:
    """Yield (line_index, 6-cell list) for every real source row in `lines`.

    A "source row" is a pipe-delimited line that — after its trailing HTML
    comment is stripped — has exactly 6 cells whose first cell is an http(s)
    URL. Header/separator/non-source rows are skipped, as are shipped EXAMPLE
    placeholder rows (so the mutators agree with the reader and neither dedup
    against nor mutate a placeholder — FIX 2). This is the single place that
    turns a raw line into structured cells, so dedup (add_source), toggling
    (set_source_active), deletion (remove_source) and parsing (_parse_categories)
    all agree on what a row is and where its URL lives (FIX 1, DRY).
    """
    for index, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        if _is_example_row(line):
            continue  # shipped placeholder — not a real monitored source
        # Strip the trailing `<!-- -->` comment before counting cells so a
        # commented row parses as 6 cells (not 7), matching brain_status.
        body = _strip_row_comment(line).strip()
        cells = [c.strip() for c in body.strip("|").split("|")]
        if len(cells) != 6 or not cells[0].startswith("http"):
            continue  # header / separator / candidate / non-source row
        yield index, cells


def _topic_block(name: str) -> str:
    """Render a fresh `## Topic:` section body for topics.md."""
    return (
        f"## Topic: {name}\n"
        f"\n"
        f"- **Name:** `{name}`\n"
        f"- **Save folder:** `pipeline/1-incoming/{name}/`\n"
        f"- **Frontmatter tags:** `[{name}]`\n"
        f"- **Include rules:** Substantive pieces directly about {name}.\n"
        f"- **Exclude rules:** Off-topic content, low-signal hype, and items "
        f"that belong to a different topic.\n"
    )


def _category_block(name: str) -> str:
    """Render a fresh `## Category:` block (empty source table) for sources.md."""
    return (
        f"## Category: {name}\n"
        f"\n"
        f"> Maps to topic `{name}` in `config/topics.md` (same name).\n"
        f"\n"
        f"**Save folder:** `pipeline/1-incoming/{name}/`\n"
        f"**Registry category:** `{name}`\n"
        f"\n"
        f"### Active sources\n"
        f"\n"
        f"{_TABLE_HEADER}\n"
        f"{_TABLE_SEP}\n"
        f"\n"
        f"### Filter rules\n"
        f"Include: what belongs in this topic.\n"
        f"Exclude: off-topic, low-signal, or items that belong to another topic.\n"
    )


def _append_section(text: str, block: str) -> str:
    """Append a section block to a markdown file, with one blank-line gap."""
    body = text.rstrip("\n")
    return f"{body}\n\n{block.rstrip(chr(10))}\n"


def _remove_section(text: str, heading: str) -> str:
    """Drop a `## <heading>` section, leaving a clean single blank-line gap.

    Removes exactly the target section plus its OWN trailing `---` rule (and the
    blank line(s) that sat around that rule), so a removed topic that ended in a
    `---` separator does not leave a dangling rule nor glue the previous heading
    onto the next survivor. The blank-line gap between the surrounding sections is
    normalized to a single blank line (FIX 3).
    """
    lines = text.splitlines(keepends=True)
    bounds = _section_bounds([ln.rstrip("\n") for ln in lines], heading)
    if bounds is None:
        return text
    start, end = bounds
    # Swallow forward over the section's own trailing separator: blank line(s)
    # and a single `---` rule that belong to THIS section, so removing the
    # section also removes the rule it owned (not the next section's content).
    while end < len(lines) and lines[end].strip() == "":
        end += 1
    if end < len(lines) and lines[end].strip() == "---":
        end += 1
        while end < len(lines) and lines[end].strip() == "":
            end += 1
    del lines[start:end]
    # Collapse any run of blank lines now left at the seam down to one, so the
    # surviving sections keep a single clean blank-line gap between them.
    while start > 0 and start < len(lines) and lines[start].strip() == "" and (
        lines[start - 1].strip() == ""
    ):
        del lines[start]
    return "".join(lines)




def _table_insert_index(lines: list[str], start: int, end: int) -> int:
    """Find the index right after the last Active-sources data row.

    Locates the header+separator inside the category section, then returns the
    index after the final contiguous `|`-row (so new rows append to the bottom
    of the table, preserving order).
    """
    sep_idx = None
    for i in range(start, end):
        if lines[i].strip() == _TABLE_HEADER:
            sep_idx = i + 1  # the separator row follows the header
            break
    if sep_idx is None:  # pragma: no cover - new categories always have a table
        raise LookupError("Active-sources table header not found")

    insert_at = sep_idx + 1
    while insert_at < end and lines[insert_at].strip().startswith("|"):
        insert_at += 1
    return insert_at



def _set_active_cell(line: str, old_value: str, new_value: str) -> str:
    """Replace the Active value in a row while preserving comments/formatting.

    Splits the line into table body and any trailing comment, swaps the last
    cell's value in the body only, then reattaches the untouched comment tail.
    """
    match = _ROW_COMMENT_RE.search(line)
    # Everything from the comment onward (incl. its leading whitespace) is the
    # untouched tail; the part before it is the table body we edit.
    split_at = match.start() if match else len(line)
    body, tail = line[:split_at], line[split_at:]
    # The Active cell is the last `| value |` in the body. Swap just its value,
    # anchored on the closing pipe, so the rest of the row stays byte-stable.
    new_body = re.sub(
        rf"(\|\s*){re.escape(old_value)}(\s*\|\s*)$",
        rf"\g<1>{new_value}\g<2>",
        body.rstrip(),
        count=1,
    )
    # Re-attach the whitespace that sat between the table body and the comment.
    gap = body[len(body.rstrip()):]
    return f"{new_body}{gap}{tail}"
