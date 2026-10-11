"""The controlled-vocabulary tag registry (config/tags.yaml) and normalization.

Loading (PyYAML fast path + dependency-free line parser for the headless
runtime), the comment-preserving text-surgery primitives shared with
promote_tags / manage_sources, and the tag normalizer (CONVENTIONS §11).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from scripts._yaml import optional_yaml
from scripts.hygiene.load import _strip_quotes

# A pending tag is promoted into the live vocabulary only once it recurs across
# at least this many concepts (CONVENTIONS §11).
PENDING_PROMOTION_THRESHOLD = 3


@dataclass
class TagRegistry:
    """The controlled vocabulary from config/tags.yaml (defensive defaults)."""

    valid: frozenset[str] = frozenset()  # domains + every domain/topic pair
    synonyms: dict[str, str] = field(default_factory=dict)  # alias -> canonical
    pending: frozenset[str] = frozenset()


def _build_registry(
    domains: dict[str, list[str]],
    synonyms: dict[str, str],
    pending: list[str] | frozenset[str],
) -> TagRegistry:
    """Assemble a TagRegistry from already-parsed mappings (path-agnostic).

    Shared by BOTH the PyYAML fast path and the line-based fallback so the two
    can never drift: the valid set is every domain plus each `domain/topic` pair.
    """
    valid: set[str] = set()
    for domain, topics in domains.items():
        valid.add(str(domain))
        for topic in topics:
            valid.add(f"{domain}/{topic}")
    return TagRegistry(
        valid=frozenset(valid),
        synonyms={str(k): str(v) for k, v in synonyms.items()},
        pending=frozenset(str(p) for p in pending),
    )


def _parse_tag_registry_lines(text: str) -> TagRegistry:
    """Parse the FIXED tags.yaml schema WITHOUT PyYAML (headless `python3`).

    The headless runtime has no PyYAML, so a yaml-only loader silently returns an
    empty registry — turning promote_tags into a no-op and suppressing every tag
    hygiene warning (BUG 1). This dependency-free, line-based parser reads the
    machine-owned schema directly (CONVENTIONS §11), mirroring the same approach
    `manage_sources._block_child_keys` uses on the same file:

      - `domains:` — a column-0 key whose children are 2-space `domain:` /
        `domain: []` lines, each optionally followed by deeper `- topic` items.
      - `synonyms:` — 2-space `alias: canonical` lines.
      - `pending:`  — `- tag` list items (or an inline `pending: []`).

    Anything not matching the schema is ignored; comments/blank lines are skipped.
    """
    domains: dict[str, list[str]] = {}
    synonyms: dict[str, str] = {}
    pending: list[str] = []

    section: str | None = None  # which top-level block we are inside
    current_domain: str | None = None  # the open `domain:` accumulating topics
    for raw in text.splitlines():
        # Drop a trailing `# comment` (the shipped file annotates topic rows like
        # `- agents   # ...`) before parsing the value, so comments never leak in.
        line = _strip_inline_comment(raw)
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip(" "))

        if indent == 0:
            # A new top-level key (e.g. `domains:`, `synonyms:`, `pending:`).
            key = stripped.split(":", 1)[0].strip()
            section = key
            current_domain = None
            # An inline `pending: [a, b]` / `pending: []` on the same line.
            if key == "pending":
                after = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
                pending.extend(_parse_flow_list(after))
            continue

        if section == "domains":
            if stripped.startswith("- ") and current_domain is not None:
                # A topic under the currently-open domain.
                domains[current_domain].append(stripped[2:].strip())
            elif ":" in stripped:
                # A `domain:` or inline `domain: []` / `domain: [a, b]` key.
                name, _, after = stripped.partition(":")
                current_domain = name.strip()
                domains[current_domain] = list(_parse_flow_list(after.strip()))
        elif section == "synonyms":
            if ":" in stripped and not stripped.startswith("-"):
                alias, _, canonical = stripped.partition(":")
                synonyms[alias.strip()] = canonical.strip()
        elif section == "pending":
            if stripped.startswith("- "):
                # Strip surrounding quotes so a quoted item (`- "ai/evals"`) yields
                # the same canonical token PyYAML would, keeping the headless
                # fallback's `pending` set byte-identical to the PyYAML path.
                pending.append(_strip_quotes(stripped[2:].strip()))

    return _build_registry(domains, synonyms, pending)


def _strip_inline_comment(line: str) -> str:
    """Drop a trailing YAML `# comment` from a line (preserves leading indent).

    A `#` only starts a comment when it begins the line or follows whitespace
    (YAML rule), so `domain/topic` values containing a literal `#` are safe.
    """
    cut = None
    for i, char in enumerate(line):
        if char == "#" and (i == 0 or line[i - 1] in " \t"):
            cut = i
            break
    return line if cut is None else line[:cut]


def _parse_flow_list(value: str) -> list[str]:
    """Parse a tags.yaml inline flow list (`[a, b]` / `[]`) into items.

    Distinct from `load._parse_inline_list` (which strips quotes for concept
    frontmatter): registry values (`domains:` / `pending:`) are never quoted, and
    keeping a separate name avoids one definition shadowing the other.
    """
    value = value.strip()
    if not value or not value.startswith("["):
        return []
    inner = value[1:-1] if value.endswith("]") else value[1:]
    return [item.strip() for item in inner.split(",") if item.strip()]


# --------------------------------------------------------------------------- #
# Shared tags.yaml text-surgery primitives (used by promote_tags + manage_sources)
# --------------------------------------------------------------------------- #
#
# These keep the comment-preserving registry edits (seed a domain, promote a
# pending tag) in ONE place so the two writers can never disagree about where a
# new domain key goes or what counts as an existing domain block (BUG 2/3, DRY).


def domains_insert_index(lines: list[str], domains_idx: int) -> int:
    """Index at which a new `  domain:` key should be inserted under `domains:`.

    Walks to the first column-0 non-blank/non-comment line that ENDS the
    `domains:` block (the next top-level key, e.g. `synonyms:`), then trims back
    over trailing BLANK *and* COMMENT lines — those belong to the NEXT block
    (the shipped file puts a `# synonyms` header above `synonyms:`), so a new key
    must land flush under the LAST real domain entry, not inside that header
    (BUG 3). `domains_idx` is the line index of the `domains:` key itself.
    """
    end = len(lines)
    for j in range(domains_idx + 1, len(lines)):
        stripped = lines[j].strip()
        if lines[j][:1] not in (" ", "\t") and stripped and not stripped.startswith("#"):
            end = j
            break
    # Pull the insertion point back over any trailing blank/comment lines so the
    # new key sits directly after the last indented (real) domain content.
    while end > domains_idx + 1:
        prev = lines[end - 1].strip()
        if prev == "" or prev.startswith("#"):
            end -= 1
        else:
            break
    return end


def domain_block_bounds(lines: list[str], domain: str) -> tuple[int, int] | None:
    """Return (header_idx, end_idx) of a `  <domain>:` block, or None if absent.

    Recognizes BOTH the block form (`  domain:`) and the inline-empty form
    (`  domain:` / `  domain: []`) that manage_sources seeds and promote_tags
    writes for a bare-tag promotion — so neither is mistaken for "absent" and
    re-appended as a duplicate key (BUG 2). `end_idx` is exclusive: the first
    line at indent ≤ 2 (a sibling domain or the block end).
    """
    header_re = re.compile(rf"^  {re.escape(domain)}:\s*(\[\s*\])?\s*$")
    header_idx = None
    for i, line in enumerate(lines):
        if header_re.match(line):
            header_idx = i
            break
    if header_idx is None:
        return None
    end = len(lines)
    for j in range(header_idx + 1, len(lines)):
        indent = len(lines[j]) - len(lines[j].lstrip())
        if lines[j].strip() and indent <= 2:
            end = j
            break
    return header_idx, end


def pending_block_bounds(lines: list[str]) -> tuple[int, int] | None:
    """Return (start_idx, end_idx) spanning the `pending:` block's item lines.

    `start_idx` is the line AFTER the `pending:` key; `end_idx` is exclusive — the
    first column-0 non-blank line that ends the block (the next top-level key) or
    EOF. Returns None when there is no `pending:` key. A pending-entry deletion
    MUST be scoped to this range: a bare pending tag (`- robotics`) can share its
    name with a domain *topic* (`ai/robotics`) elsewhere in the file, and an
    unscoped "delete the first `- robotics`" would remove that topic by mistake.
    """
    start = None
    for i, line in enumerate(lines):
        if line[:1] not in (" ", "\t") and line.split(":", 1)[0].strip() == "pending":
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].strip() and lines[j][:1] not in (" ", "\t"):
            end = j
            break
    return start, end


def load_tag_registry(tags_path: Path) -> TagRegistry:
    """Load config/tags.yaml; return empty-but-safe registry when absent.

    The file is created by a sibling skill/agent and may not exist yet, so a
    missing file yields a permissive registry rather than an error. When PyYAML
    is unavailable (the headless `python3` runtime), fall back to a dependency-
    free line-based parser instead of silently returning EMPTY — otherwise the
    promoter and the tag-hygiene warnings degrade to no-ops headless (BUG 1).
    """
    if not tags_path.exists():
        return TagRegistry()
    text = tags_path.read_text(encoding="utf-8")
    yaml = optional_yaml()
    if yaml is None:
        # Headless: no PyYAML. Parse the fixed schema line-by-line instead.
        return _parse_tag_registry_lines(text)
    try:
        data = yaml.safe_load(text) or {}
    except Exception:  # noqa: BLE001 — malformed registry -> permissive default
        return TagRegistry()
    if not isinstance(data, dict):
        return TagRegistry()

    domains_raw = data.get("domains")
    domains: dict[str, list[str]] = {}
    if isinstance(domains_raw, dict):
        for domain, topics in domains_raw.items():
            domains[str(domain)] = (
                [str(t) for t in topics] if isinstance(topics, list) else []
            )

    synonyms_raw = data.get("synonyms")
    synonyms = synonyms_raw if isinstance(synonyms_raw, dict) else {}

    pending_raw = data.get("pending")
    pending = pending_raw if isinstance(pending_raw, list) else []

    return _build_registry(domains, synonyms, pending)


# --------------------------------------------------------------------------- #
# Tag normalization (CONVENTIONS §11)
# --------------------------------------------------------------------------- #


def _singularize(word: str) -> str:
    """Naive English singularizer for tag tokens (no external deps).

    Covers the common plural endings that show up in tags; deliberately simple
    (KISS) — it only needs to catch obvious `agents`→`agent` style drift.
    """
    lower = word.lower()
    if lower.endswith("ies") and len(lower) > 3:
        return lower[:-3] + "y"
    if lower.endswith(("ses", "xes", "zes", "ches", "shes")):
        return lower[:-2]
    if lower.endswith("s") and not lower.endswith("ss") and len(lower) > 1:
        return lower[:-1]
    return lower


def _fold_tag(tag: str) -> str:
    """Case-fold, hyphenate whitespace/underscores per nested segment (no singular)."""
    segments = []
    for segment in tag.strip().split("/"):
        token = segment.strip().lower().replace(" ", "-").replace("_", "-")
        token = re.sub(r"-{2,}", "-", token).strip("-")
        if token:
            segments.append(token)
    return "/".join(segments)


def normalize_tag(tag: str, registry: TagRegistry | None = None) -> str:
    """Normalize a tag to its canonical form (CONVENTIONS §11).

    Steps: case/whitespace/hyphen fold, then singularize each segment. The
    controlled vocabulary wins when it knows the tag — so `Ai/Agents` folds to
    `ai/agents` (kept as-is because the registry uses that plural), while a tag
    the registry has never seen is singularized (`Projects` → `project`).
    """
    folded = _fold_tag(tag)
    if registry is not None and folded in registry.valid:
        return folded  # registry is the authority — don't over-singularize
    singular = "/".join(_singularize(seg) for seg in folded.split("/") if seg)
    if registry is not None and folded in registry.synonyms:
        return folded  # an alias resolves later; keep the folded alias here
    return singular
