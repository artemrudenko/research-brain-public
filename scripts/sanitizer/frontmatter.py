"""Frontmatter-aware sanitization helpers."""

from __future__ import annotations

import re

from scripts.sanitizer.model import SanitizeResult
from scripts.sanitizer.rules import sanitize_text

# A single-line `key: value` (key captured so we never sanitize keys) and a
# block-sequence item `  - value`. Flow collections (`tags: [a, b]`) are sanitized
# item-by-item so they keep their list type. Block scalars (`key: |` / `key: >`)
# are sanitized over their continuation text.
_FM_KEY_VALUE = re.compile(r"^(?P<indent>\s*)(?P<key>[^\s:#][^:]*):[ \t]+(?P<value>\S.*)$")
_FM_LIST_ITEM = re.compile(r"^(?P<indent>\s*)-[ \t]+(?P<value>\S.*)$")
# A block-scalar header VALUE: `|` / `>` with an optional chomping/indent
# indicator (`|-`, `>+`, `|2`) and an optional trailing comment.
_FM_BLOCK_SCALAR = re.compile(r"^[|>][+-]?\d*[ \t]*(#.*)?$")


def _yaml_safe_scalar(value: str) -> str:
    """Emit `value` as a YAML-safe double-quoted scalar.

    This keeps placeholders like `[STRIPPED:S1]` as plain strings instead of
    letting YAML reparse them as flow sequences.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _split_flow_items(inner: str) -> list[str]:
    """Split a flow-sequence interior on top-level commas."""
    items: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(inner):
        ch = inner[i]
        if quote is not None:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(inner):
                buf.append(inner[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == ",":
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    items.append("".join(buf))
    return items


def _unquote_flow_scalar(item: str) -> str:
    """Return the scalar value of a possibly quoted YAML flow item."""
    if len(item) >= 2 and item[0] == item[-1] and item[0] in ("'", '"'):
        inner = item[1:-1]
        if item[0] == '"':
            return inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner.replace("''", "'")
    return item


def _sanitize_flow_sequence(value: str, result: SanitizeResult) -> str | None:
    """Sanitize each scalar item in a YAML flow sequence, preserving list shape.

    A stripped item stays one quoted list entry; the whole value is never collapsed
    into one re-quoted string.
    """
    text = value.strip()
    if not (len(text) >= 2 and text.startswith("[") and text.endswith("]")):
        return None
    inner = text[1:-1]
    if inner.strip() == "":
        return None
    new_items: list[str] = []
    changed = False
    for raw in _split_flow_items(inner):
        item = raw.strip()
        content = _unquote_flow_scalar(item)
        sub = sanitize_text(content)
        if sub.clean_text == content:
            new_items.append(item)
            continue
        result.findings.extend(sub.findings)
        new_items.append(_yaml_safe_scalar(sub.clean_text))
        changed = True
    if not changed:
        return None
    return "[" + ", ".join(new_items) + "]"


def _sanitize_frontmatter(frontmatter: str, result: SanitizeResult) -> str:
    """Run strip rules over frontmatter values while preserving YAML structure."""
    out_lines: list[str] = []
    block_indent: int | None = None
    for line in frontmatter.split("\n"):
        if block_indent is not None:
            # Inside a block scalar: content is indented deeper than the header key
            # (blank lines belong to it too). A line at indent <= header ends it.
            indent = len(line) - len(line.lstrip(" "))
            if line.strip() != "" and indent <= block_indent:
                block_indent = None
            else:
                lead = line[: len(line) - len(line.lstrip())]
                content = line[len(lead) :]
                sub = sanitize_text(content)
                result.findings.extend(sub.findings)
                out_lines.append(lead + sub.clean_text if sub.clean_text != content else line)
                continue

        kv = _FM_KEY_VALUE.match(line)
        match = kv or _FM_LIST_ITEM.match(line)
        if match is None:
            stripped = line.strip()
            # Blank lines and comments are structure. Everything else is sanitized,
            # including value-less `key:` shaped lines; folded plain scalars can be
            # crafted to look like bare keys and would otherwise pass as clean.
            if stripped == "" or stripped.startswith("#"):
                out_lines.append(line)
                continue
            lead = line[: len(line) - len(line.lstrip())]
            content = line[len(lead) :]
            sub = sanitize_text(content)
            result.findings.extend(sub.findings)
            out_lines.append(lead + sub.clean_text if sub.clean_text != content else line)
            continue

        value = match.group("value")
        if kv is not None and _FM_BLOCK_SCALAR.match(value):
            block_indent = len(line) - len(line.lstrip(" "))
            out_lines.append(line)
            continue

        flow = _sanitize_flow_sequence(value, result)
        if flow is not None:
            out_lines.append(line[: match.start("value")] + flow)
            continue

        sub = sanitize_text(value)
        result.findings.extend(sub.findings)
        if sub.clean_text == value:
            out_lines.append(line)
            continue
        prefix = line[: match.start("value")]
        out_lines.append(prefix + _yaml_safe_scalar(sub.clean_text))
    return "\n".join(out_lines)


def _split_frontmatter(raw: str) -> tuple[str, str]:
    """Return (frontmatter_block_without_fences, body). Empty fm if none.

    The closing fence must be a line whose stripped content is exactly `---`, so
    this agrees with the digest reader and does not split on `----b` style lines.
    """
    if not raw.startswith("---"):
        return "", raw
    lines = raw.split("\n")
    end_index: int | None = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        return "", raw
    fm = "\n".join(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :])
    return fm, body


__all__ = [
    "_FM_BLOCK_SCALAR",
    "_FM_KEY_VALUE",
    "_FM_LIST_ITEM",
    "_sanitize_flow_sequence",
    "_sanitize_frontmatter",
    "_split_flow_items",
    "_split_frontmatter",
    "_unquote_flow_scalar",
    "_yaml_safe_scalar",
]
