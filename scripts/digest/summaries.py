"""Summary extraction helpers for incoming digest items."""

from __future__ import annotations

import re

BYLINE_RE = re.compile(r"^by\b", re.IGNORECASE)
ABSTRACT_PREFIX_RE = re.compile(r"^.*?\bAbstract:\s*", re.IGNORECASE | re.DOTALL)
SUMMARY_MAX_CHARS = 240

# Code spans unwrap first so their content is kept verbatim; underscore forms
# bind only at word boundaries so snake_case identifiers survive.
_MD_CODE_RE = re.compile(r"`([^`]*)`")
_MD_EMPHASIS_RES = (
    re.compile(r"\*\*\*(.+?)\*\*\*"),
    re.compile(r"\*\*(.+?)\*\*"),
    re.compile(r"(?<!\w)__(.+?)__(?!\w)"),
    re.compile(r"\*([^\s*](?:[^*]*[^\s*])?)\*"),
    re.compile(r"(?<!\w)_([^\s_](?:[^_]*[^\s_])?)_(?!\w)"),
)


def strip_inline_markdown(text: str) -> str:
    """Drop inline emphasis/code markers (**, *, __, _, backticks), keep their text.

    Summaries are quoted into the digest's own markdown, where leaked markers
    either re-style the line or surface half-stripped (the "Fact.**" artifact),
    so orphan pair-halves are dropped too.
    """
    text = _MD_CODE_RE.sub(r"\1", text)
    for pattern in _MD_EMPHASIS_RES:
        text = pattern.sub(r"\1", text)
    return text.replace("**", "").replace("`", "")


def clean_summary(text: str) -> str:
    """Reduce a raw summary/abstract line to a trimmed takeaway."""
    text = strip_inline_markdown(text)
    text = ABSTRACT_PREFIX_RE.sub("", text, count=1).strip()
    if len(text) <= SUMMARY_MAX_CHARS:
        return text
    truncated = text[:SUMMARY_MAX_CHARS]
    boundary = max(truncated.rfind(". "), truncated.rfind("! "), truncated.rfind("? "))
    if boundary > SUMMARY_MAX_CHARS // 3:
        return truncated[: boundary + 1]
    return truncated.rstrip() + "…"


def first_takeaway(body: str) -> str:
    """Return the first key-takeaway bullet, else a cleaned body lead."""
    lines = body.splitlines()
    in_takeaways = False
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("## key takeaways"):
            in_takeaways = True
            continue
        if in_takeaways:
            if stripped.startswith("#"):
                break
            if stripped.startswith(("-", "*", "+")):
                return clean_summary(stripped.lstrip("-*+ ").strip())
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "---":
            continue
        if stripped.startswith(("#", "<!--")):
            continue
        core = stripped.strip("*_ ")
        if BYLINE_RE.match(core) or core.lower().startswith("source:"):
            continue
        return clean_summary(stripped)
    return ""


__all__ = [
    "ABSTRACT_PREFIX_RE",
    "BYLINE_RE",
    "SUMMARY_MAX_CHARS",
    "clean_summary",
    "first_takeaway",
    "strip_inline_markdown",
]
