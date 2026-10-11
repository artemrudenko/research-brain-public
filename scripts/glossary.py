#!/usr/bin/env python3
"""
glossary.py — append a plain-language glossary to a rendered digest.

The user-facing digest can carry acronyms and jargon ("RAG", "LLM", "MCP") that
a non-technical reader will not know. This module turns the curated
`config/glossary.yaml` (TERM → one-line explanation) into a `📖 Glossary`
section listing ONLY the terms that actually appear in a given digest — so a
plain digest adds nothing, and a jargon-heavy one gets exactly the definitions
it needs. It is deterministic (no LLM), so both the headless `build_digest.py`
path and the agent path get the same behavior.

Matching is whole-word and case-sensitive, with an optional trailing plural "s"
(so `API` matches `API` and `APIs` but never `capital` or `api`). The glossary's
own order is preserved in the rendered section.

Public API: :func:`load_glossary`, :func:`glossary_section`, :func:`append_glossary`.
"""
from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from pathlib import Path

from scripts._yaml import optional_yaml

# The section heading the glossary renders under (kept in sync with the digest's
# emoji-prefixed H2 style — see CONVENTIONS §17).
GLOSSARY_HEADING = "## 📖 Glossary"


def load_glossary(path: Path) -> dict[str, str]:
    """Read the `terms:` map (term → explanation) from a glossary YAML file.

    A missing file, a parse error, or a malformed shape all degrade gracefully
    to an empty mapping — the glossary is a presentation nicety and must never
    fail a digest build. A missing file is silent (it is the documented
    off-switch), but a parse error WARNs on stderr: a YAML typo silently
    disabling the glossary would be a debugging trap. When PyYAML is
    unavailable (the headless `python3` runtime), fall back to a dependency-
    free line parser instead of silently returning EMPTY — otherwise every
    headless digest ships glossary-less and the "uncovered acronyms" warning
    flags terms the file does define (the tags.yaml BUG 1 failure mode). Only
    string→string entries are kept; insertion order is preserved so the
    rendered section is stable.
    """
    if not path.exists():
        return {}
    yaml = optional_yaml()
    if yaml is None:
        # Headless: no PyYAML. Parse the fixed flat schema line-by-line instead
        # (mirrors validate_brain's tags.yaml fallback).
        return _parse_glossary_lines(path.read_text(encoding="utf-8"))
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 — parse error -> warn + no glossary, never a crash
        print(
            f"WARNING: glossary: could not parse {path}: {exc} — skipping glossary",
            file=sys.stderr,
        )
        return {}
    terms = raw.get("terms") if isinstance(raw, dict) else None
    if not isinstance(terms, dict):
        return {}
    return {
        str(term): str(explanation)
        for term, explanation in terms.items()
        if isinstance(term, str) and term.strip() and isinstance(explanation, str)
    }


def _parse_glossary_lines(text: str) -> dict[str, str]:
    """Parse the FIXED glossary.yaml schema WITHOUT PyYAML (headless `python3`).

    The shipped schema is deliberately flat — a single top-level `terms:` key
    whose children are 2-space `TERM: "explanation"` lines — so a line reader
    covers it exactly:

      - only the `terms:` block is read; any other top-level key ends it;
      - full-line `#` comments and blank lines are skipped;
      - the key is everything before the FIRST `:` (terms never contain one;
        explanations often do — "Retrieval-Augmented Generation: …" survives);
      - a matching pair of surrounding quotes on the value is stripped;
      - an empty value is skipped (PyYAML yields None there, which the strict
        string→string filter would drop too).

    Kept in lockstep with the PyYAML path by a shipped-file parity test.
    """
    terms: dict[str, str] = {}
    in_terms = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw[:1] not in (" ", "\t"):
            # A top-level key: enter at `terms:`, leave at any other.
            in_terms = stripped.split(":", 1)[0].strip() == "terms"
            continue
        if not in_terms or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and value:
            terms[key] = value
    return terms


def _appears(text: str, term: str) -> bool:
    """True when `term` occurs in `text` as a whole word (optional plural `s`).

    Word boundaries are enforced with lookarounds on `\\w` so a term never matches
    inside a larger word; matching is case-sensitive so an uppercase acronym does
    not fire on an unrelated lowercase word.
    """
    pattern = rf"(?<!\w){re.escape(term)}s?(?!\w)"
    return re.search(pattern, text) is not None


# Everyday capitalised tokens that look like acronyms but are not jargon a reader
# needs defined — kept out of the "uncovered" report to avoid noise. "TL"/"DR"
# are the two halves of the digest's own "TL;DR" heading (the tokenizer splits on
# the semicolon), so they would otherwise flag on every single digest. Well-known
# vendor names (IBM, HP, OpenAI, …) are proper nouns, not jargon — industry-news
# digests mention them constantly and defining them would read as condescending.
_COMMON_NON_JARGON = frozenset(
    {
        "OK", "US", "UK", "EU", "UN", "USA", "TV", "AM", "PM", "TL", "DR",
        # Vendors / organisations that recur in tech-news sources.
        "IBM", "HP", "OpenAI", "DeepMind", "AWS", "NVIDIA", "AMD", "MIT",
    }
)

# An acronym-shaped token: starts uppercase, ends uppercase/digit (so length ≥ 2),
# may carry internal lowercase or a slash (LoRA, CI/CD), with an optional plural
# "s". Word boundaries exclude a trailing slash too, so "CI/CD" stays one token.
_ACRONYM_RE = re.compile(r"(?<![\w/])([A-Z][A-Za-z0-9/]*[A-Z0-9])s?(?![\w/])")


def uncovered_acronyms(text: str, terms: Mapping[str, str]) -> list[str]:
    """Acronym-shaped tokens in `text` that the glossary does NOT define.

    A deterministic sufficiency check: it answers "does the glossary explain the
    jargon this digest actually uses?" so a build can warn when new domain
    acronyms (e.g. ``LoRA``, ``AEO``) slip in uncovered. Everyday capitalised
    words (``US``, ``OK``) are filtered out; the result is deduped and sorted.
    """
    found = {match.group(1) for match in _ACRONYM_RE.finditer(text)}
    return sorted(
        token
        for token in found
        if token not in terms and token not in _COMMON_NON_JARGON
    )


def glossary_section(
    text: str, terms: Mapping[str, str], *, heading: str = GLOSSARY_HEADING
) -> str:
    """Render the glossary section for the terms that appear in `text`.

    Returns an empty string when no glossary term is present, so a caller can
    append unconditionally and a jargon-free digest stays untouched. `heading`
    localizes the section title (digest chrome, delivery.language).
    """
    matched = [
        (term, explanation) for term, explanation in terms.items() if _appears(text, term)
    ]
    if not matched:
        return ""
    lines = [heading, ""]
    lines.extend(f"- **{term}** — {explanation}" for term, explanation in matched)
    return "\n".join(lines)


def append_glossary(
    markdown: str, glossary_path: Path, *, heading: str = GLOSSARY_HEADING
) -> str:
    """Append a glossary section to `markdown` for any terms it uses.

    Loads the glossary from `glossary_path`, matches it against the digest body,
    and appends the section (separated by a blank line). When nothing matches the
    digest is returned unchanged.
    """
    section = glossary_section(markdown, load_glossary(glossary_path), heading=heading)
    if not section:
        return markdown
    return f"{markdown.rstrip(chr(10))}\n\n{section}\n"
