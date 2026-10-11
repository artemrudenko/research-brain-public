"""fm.py — the shared Markdown frontmatter reader for the pipeline.

Every stage that reads a note needs the same two operations: split the leading
``---``…``---`` block from the body, and turn that block into a dict. Before this
module those lived as near-identical private copies across ``hygiene/load``,
``trends``, ``digest/scan`` and others, which drifted subtly and scattered the
one rule that actually matters — where frontmatter ends. This module is the
single owner of that rule.

Three deliberate NON-owners remain, because a shared helper would be *wrong* for
them:

* ``sanitize_incoming._split_frontmatter`` splits on ``"\\n"`` (not
  ``splitlines()``) because it RE-EMITS the body and must preserve its exact
  bytes — trailing newline and CRLF endings included. ``splitlines()`` +
  ``"\\n".join`` would silently rewrite them, so it stays local by design.
* ``frontmatter_lint.frontmatter_block`` uses a looser ``find("\\n---")`` scan
  tuned to SKILL.md linting; it is intentionally separate.
* ``validate-pipeline-frontmatter._extract_block`` is a stricter *validator*: the
  opening fence must be exactly ``---`` on line 1 (BOM tolerated), and it returns
  ``None`` vs a block to tell "no block" apart from "empty block" — a distinction
  :func:`split_frontmatter` deliberately conflates. It also reports YAML parse
  errors as messages rather than degrading to ``{}``. Folding it in would either
  change its contract or add a near-duplicate variant, so it stays local.

PyYAML is imported lazily and optionally: a missing parser degrades to a
dependency-free stdlib reader (:func:`parse_frontmatter`) or to ``{}``, so the
headless runtime — which ships without PyYAML — never loses frontmatter it can
otherwise read.
"""

from __future__ import annotations

import re


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return ``(raw frontmatter block, body)``.

    Only a leading ``---`` fence opens frontmatter; it ends at the next line that
    is exactly ``---`` after ``strip()`` — NOT a line that merely starts with
    ``---`` (e.g. ``----``). No opening fence, or an unclosed one, yields
    ``("", text)`` so a note without frontmatter is treated as all-body rather
    than mis-sliced. The returned block excludes both fences; the body excludes
    the closing fence line.
    """
    if not text.startswith("---"):
        return "", text
    lines = text.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
    return "", text  # unclosed fence -> treat as no frontmatter


def parse_frontmatter(block: str) -> dict[str, object]:
    """Parse a frontmatter block to a dict, preferring PyYAML.

    Falls back to a small stdlib reader that understands the flat scalars and the
    inline/block lists the vault uses (``tags``, ``related_concept``, ``sources``)
    so a missing parser never breaks a read. An empty block, a parse error, or a
    non-mapping block all yield ``{}``.
    """
    if not block.strip():
        return {}
    try:
        # NOT the scripts._yaml seam: delivery's direct-script fallback chain
        # (deliver.py -> `import quiet` -> `from fm import …`) loads this module
        # BARE, with no `scripts` package importable — an absolute seam import
        # breaks that documented mode (pinned by
        # test_delivery_health_hook_works_as_direct_script).
        import yaml  # noqa: PLC0415 — lazy optional import
    except ImportError:
        return _parse_frontmatter_fallback(block)
    try:
        data = yaml.safe_load(block)
    except Exception:  # noqa: BLE001 — any parse error -> best-effort fallback
        return _parse_frontmatter_fallback(block)
    return data if isinstance(data, dict) else {}


def parse_scalars(block: str) -> dict[str, str]:
    """Parse a frontmatter block as flat ``key: value`` string pairs (stdlib only).

    A minimal reader for stages that only need top-level scalars (``collected``,
    ``category``, ``title``, ``last_updated``, …): every line containing a colon
    becomes one entry, later keys winning. Lists and nesting are NOT interpreted —
    use :func:`parse_frontmatter` when structure matters.
    """
    fields: dict[str, str] = {}
    for raw in block.splitlines():
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def insert_after_frontmatter(text: str, block: str) -> str:
    """Insert `block` just after the closing `---` of frontmatter (or at the top).

    When `text` opens with a `---` frontmatter fence, `block` is spliced in after
    the closing fence, separated by a blank line, and a trailing newline on `text`
    is preserved. With no frontmatter (or an unclosed fence), `block` is prepended
    with a blank line. Used to stamp an archive/status block into a concept note
    without disturbing its frontmatter.
    """
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                merged = lines[: i + 1] + ["", block] + lines[i + 1 :]
                out = "\n".join(merged)
                return out + "\n" if text.endswith("\n") else out
    out = f"{block}\n\n{text}"
    return out


# The only escapes the vault writers put inside a double-quoted scalar
# (``extract_vault_notes._yaml_quote``): a backslash before `"` or `\`.
_DQUOTE_ESCAPE_RE = re.compile(r'\\(["\\])')


def _strip_quotes(value: str) -> str:
    """Strip a single matching pair of surrounding quotes.

    Double-quoted scalars also get their ``\\"`` / ``\\\\`` escapes reversed, so
    the fallback returns the same text PyYAML would (writers escape on write via
    ``extract_vault_notes._yaml_quote``). Single-quoted scalars stay verbatim:
    YAML escapes there via ``''``, never backslashes, and our writers emit none.
    """
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        if value[0] == '"':
            return _DQUOTE_ESCAPE_RE.sub(r"\1", inner)
        return inner
    return value


def _parse_inline_list(value: str) -> list[str]:
    """Parse a ``[a, b, c]`` inline YAML list into stripped string items."""
    inner = value.strip()[1:-1].strip()
    if not inner:
        return []
    return [_strip_quotes(part) for part in inner.split(",") if part.strip()]


def _parse_frontmatter_fallback(block: str) -> dict[str, object]:
    """Minimal stdlib frontmatter reader (no PyYAML).

    Handles ``key: scalar``, ``key: [inline, list]``, and block lists where
    ``key:`` is followed by ``  - item`` lines. Block-mapping list items (e.g. a
    ``sources:`` entry that is itself a ``- url: ...`` mapping) are captured as
    opaque markers so emptiness checks still work; their inner fields are not
    needed here.
    """
    result: dict[str, object] = {}
    lines = block.splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        index += 1
        if not stripped or stripped.startswith("#") or ":" not in raw:
            continue
        # Only treat top-level (unindented) keys as keys.
        if raw[:1] in (" ", "\t"):
            continue
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            result[key] = _parse_inline_list(value)
        elif value:
            result[key] = _strip_quotes(value)
        else:
            # Possible block list: collect following indented `- ...` lines.
            items: list[str] = []
            while index < len(lines):
                follow = lines[index]
                fstripped = follow.strip()
                if follow[:1] in (" ", "\t") and fstripped.startswith("-"):
                    items.append(fstripped.lstrip("- ").strip())
                    index += 1
                elif follow[:1] in (" ", "\t") and fstripped:
                    # Continuation of a block-mapping list item (e.g. source
                    # fields) — keep the list non-empty without parsing detail.
                    index += 1
                else:
                    break
            result[key] = items
    return result
