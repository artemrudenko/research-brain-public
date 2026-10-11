from __future__ import annotations


def _block_child_keys(tags_text: str, block: str) -> set[str]:
    """Return the immediate child keys of a top-level `block:` mapping in tags.yaml.

    A dependency-free, line-based parser for the FIXED tags.yaml schema (machine-
    owned, §11): a top-level `block:` at column 0, whose children are one-level
    (2-space) indented `key:` (domains) or `key: value` (synonyms) lines; deeper
    `    - topic` list items are skipped. PyYAML is deliberately NOT used here —
    it is an optional dependency absent from the headless `python3` runtime, so a
    yaml-based guard silently returned empty and let duplicate/colliding tags
    through. This parser works regardless of PyYAML.
    """
    keys: set[str] = set()
    lines = tags_text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.rstrip() == f"{block}:"), None)
    if start is None:
        return keys
    for ln in lines[start + 1:]:
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(ln) - len(ln.lstrip(" "))
        # A column-0, non-blank, non-comment line is the next top-level key -> stop.
        if indent == 0:
            break
        # Immediate children sit at one indent level and are `key:`/`key: value`,
        # not `- topic` list items (which belong to a domain's topic list).
        if indent == 2 and not stripped.startswith("-") and ":" in stripped:
            keys.add(stripped.split(":", 1)[0].strip())
    return keys


def _domain_keys(tags_text: str) -> set[str]:
    """Top-level domain keys already present under `domains:` (so a slug that is
    already a domain is detected and never re-seeded)."""
    return _block_child_keys(tags_text, "domains")


def _synonym_aliases(tags_text: str) -> set[str]:
    """Alias keys under `synonyms:` (alias -> canonical domain/topic). A slug that
    is already an alias normalizes to a canonical tag on its own, so seeding a
    same-named bare domain would shadow the synonym — the caller skips it."""
    return _block_child_keys(tags_text, "synonyms")

