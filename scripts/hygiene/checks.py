"""Every hygiene check, the write-time contract gate, and the quarantine mover.

The advisory checks (orphans, broken links, missing sources, staleness, tag
hygiene, INDEX completeness) share their primitives with the write-time
`gate_concepts` gate so the two can never drift (CONVENTIONS §11/§13).
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from scripts.hygiene.load import load_concept
from scripts.hygiene.model import Concept, Warning
from scripts.hygiene.tags import (
    PENDING_PROMOTION_THRESHOLD,
    TagRegistry,
    normalize_tag,
)

# `[[concepts/foo-bar]]` / `[[concepts/foo-bar|Alias]]` wikilink reference.
_CONCEPT_LINK_RE = re.compile(r"\[\[\s*concepts/([^\]|#]+?)\s*(?:[|#][^\]]*)?\]\]")
# `[[authors/ada-lovelace]]` reference — the target of a concept's contributors:.
_AUTHOR_LINK_RE = re.compile(r"\[\[\s*authors/([^\]|#]+?)\s*(?:[|#][^\]]*)?\]\]")
_VAULT_LINK_RE = re.compile(
    r"\[\[\s*(?:concepts|lessons|playbooks|authors)/([^\]|#]+?)\s*(?:[|#][^\]]*)?\]\]"
)

# The body section whose every bullet must trace to a cited source (the heading
# the wiki-ingest template and the shipped seed concepts use verbatim).
_KEY_FACTS_HEADING_RE = re.compile(r"^\s*#{2,}\s+key\s+facts\s*$", re.IGNORECASE)
# Any markdown bullet line (`- ...` / `* ...`), capturing its content.
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*\S.*)$")
# A markdown `## heading` line that closes the open section.
_ANY_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")
# An inline source reference a key-fact bullet may carry: a `Source:` token, a
# `[[wikilink]]`, or an http(s) URL — the conventions real concepts already use.
_INLINE_SOURCE_RE = re.compile(r"(?:\bsource\s*:)|(?:\[\[)|(?:https?://)", re.IGNORECASE)


def _outbound_targets(concept: Concept) -> set[str]:
    """Stems this concept links OUT to (via related_concept: + body wikilinks)."""
    targets: set[str] = set()
    refs = list(concept.related)
    refs.extend(f"[[concepts/{m}]]" for m in _CONCEPT_LINK_RE.findall(concept.body))
    for ref in refs:
        match = _CONCEPT_LINK_RE.search(ref)
        if not match:
            continue
        target = match.group(1).strip()
        if target.endswith(".md"):
            target = target[:-3]
        if target and target != concept.stem:  # self-links aren't graph edges
            targets.add(target)
    return targets


def check_orphan(
    concept: Concept,
    linked_stems: set[str],
    tag_to_concepts: dict[str, set[str]],
    registry: TagRegistry,
) -> Warning | None:
    """Classify a concept's graph connectivity (CONVENTIONS §13).

    Tags are NOT graph edges in Obsidian — only `[[links]]` are — so a concept
    is a true ORPHAN when it has no inbound and no outbound link, EVEN IF it
    shares a tag with another note. A note that has no link but DOES share a tag
    is downgraded to the softer "weakly-linked (tag-only)" finding: reachable via
    the tag pane, but absent from the graph view.

    `linked_stems` is the set of stems touched by any real graph edge (the union
    of every concept's outbound targets, restricted to existing notes, plus the
    sources of those edges). A concept in that set is connected and clears.
    """
    if concept.stem in linked_stems:
        return None  # part of at least one [[link]] edge -> connected

    # No graph edge. Does it at least share a tag with another concept?
    shares_tag = any(
        any(other != concept.stem for other in tag_to_concepts.get(
            normalize_tag(tag, registry), set()))
        for tag in concept.tags
    )
    if shares_tag:
        return Warning(
            kind="weakly-linked",
            concept=concept.stem,
            message=(
                f"'{concept.stem}' is weakly-linked (tag-only) — it shares a tag "
                f"but has no [[concepts/...]] link, so it is absent from the graph "
                f"view. Add a related_concept link to connect it."
            ),
        )
    return Warning(
        kind="orphan",
        concept=concept.stem,
        message=(
            f"'{concept.stem}' is an orphan — no related_concept link and no "
            f"inbound/outbound [[concepts/...]] link. Add a [[concepts/...]] link."
        ),
    )


def check_broken_links(concept: Concept, existing_stems: set[str]) -> list[Warning]:
    """Flag `[[concepts/X]]` references (frontmatter + body) with no target file."""
    warnings: list[Warning] = []
    seen: set[str] = set()
    # related_concept entries plus any inline body links.
    refs = list(concept.related)
    refs.extend(f"[[concepts/{m}]]" for m in _CONCEPT_LINK_RE.findall(concept.body))
    for ref in refs:
        match = _CONCEPT_LINK_RE.search(ref)
        if not match:
            continue
        target = match.group(1).strip()
        # Tolerate an explicit `.md` suffix in the link target.
        if target.endswith(".md"):
            target = target[:-3]
        if target in seen:
            continue
        seen.add(target)
        if target not in existing_stems:
            warnings.append(
                Warning(
                    kind="broken-link",
                    concept=concept.stem,
                    message=(
                        f"'{concept.stem}' links to [[concepts/{target}]] but "
                        f"brain/concepts/{target}.md does not exist."
                    ),
                )
            )
    return warnings


def check_contributor_links(concept: Concept, author_stems: set[str]) -> list[Warning]:
    """Flag `contributors:` entries pointing at a non-existent author node.

    The author↔concept link is authoritative ON the concept (Stage 9, Q3): a
    concept carries `contributors: ["[[authors/<slug>]]"]`. A contributor whose
    `brain/authors/<slug>.md` does not exist is a dangling reference — reported
    as a broken-link finding, the same class the concept↔concept check uses.
    """
    warnings: list[Warning] = []
    seen: set[str] = set()
    for ref in concept.contributors:
        match = _AUTHOR_LINK_RE.search(ref)
        if not match:
            continue
        target = match.group(1).strip()
        if target.endswith(".md"):
            target = target[:-3]
        if not target or target in seen:
            continue
        seen.add(target)
        if target not in author_stems:
            warnings.append(
                Warning(
                    kind="broken-link",
                    concept=concept.stem,
                    message=(
                        f"'{concept.stem}' lists contributor [[authors/{target}]] but "
                        f"brain/authors/{target}.md does not exist."
                    ),
                )
            )
    return warnings


def _is_verifiable_url(candidate: str) -> bool:
    """True only for a well-formed, fetchable http(s) URL with a real host.

    A prefix check (`startswith("https://")`) is not enough: `https://`,
    `https:///path`, `https://not a url`, and `https://h:99999/x` all start with the
    scheme yet cite nothing checkable. Validate via `urlsplit` — scheme, a non-empty
    hostname, a parseable (in-range) port — and reject any whitespace / control
    character a real URL never contains.
    """
    text = candidate.strip()
    if not text:
        return False
    if any(ch.isspace() or ord(ch) < 0x20 for ch in text):
        return False
    try:
        parts = urlsplit(text)
        if parts.scheme.lower() not in ("http", "https"):
            return False
        if not parts.hostname:  # scheme but no host (e.g. https:/// )
            return False
        _ = parts.port  # raises ValueError on an out-of-range port (e.g. 99999)
    except ValueError:
        return False
    return True


def _source_has_url(entry: object) -> bool:
    """True if a `sources:` entry carries a verifiable http(s) URL.

    Handles both parser shapes: PyYAML yields a mapping (`{"url": "...", ...}`) or a
    bare string, while the stdlib fallback flattens a `- url: "..."` item to the
    string `url: "..."`. An entry like `"invalid"` (a non-URL placeholder) — or a
    malformed one like `https://` / `https:///x` — has no verifiable provenance and
    must NOT satisfy the anti-hallucination gate.
    """
    if isinstance(entry, dict):
        url = entry.get("url", "")
        return isinstance(url, str) and _is_verifiable_url(url)
    if isinstance(entry, str):
        text = entry.strip()
        if text.lower().startswith("url:"):  # fallback-flattened `url: "https://…"`
            text = text[len("url:"):].strip()
        text = text.strip("\"'")
        return _is_verifiable_url(text)
    return False


def check_missing_sources(concept: Concept) -> Warning | None:
    """Flag a `type: concept` note lacking a source with a verifiable http(s) URL.

    A non-empty list alone is not enough: `sources: ["invalid"]` cites no checkable
    provenance, so the anti-hallucination contract (CONVENTIONS §5.1) requires at
    least one entry that carries a real URL.
    """
    if concept.note_type != "concept":
        return None
    if any(_source_has_url(s) for s in concept.sources):
        return None
    return Warning(
        kind="missing-sources",
        concept=concept.stem,
        message=(
            f"'{concept.stem}' has no verifiable source — every concept must cite at "
            f"least one source with an http(s) URL (anti-hallucination, CONVENTIONS §5.1)."
        ),
    )


def _has_vault_reference(note: Concept) -> bool:
    """True when a lesson/playbook is connected to the vault graph."""
    if note.related or note.parent_playbook or note.source_concepts:
        return True
    return _VAULT_LINK_RE.search(note.body) is not None


def check_lesson_navigation(note: Concept) -> Warning | None:
    """Flag a lesson that cannot be reached from a concept or playbook."""
    if note.note_type != "lesson" or _has_vault_reference(note):
        return None
    return Warning(
        kind="orphan",
        concept=note.stem,
        message=(
            f"'{note.stem}' is an orphan lesson — add related_concept or "
            f"parent_playbook so it is reachable from the vault graph."
        ),
    )


def check_playbook_navigation(note: Concept) -> Warning | None:
    """Flag a playbook draft with no concept/lesson/playbook connection."""
    if note.note_type != "playbook" or _has_vault_reference(note):
        return None
    return Warning(
        kind="orphan",
        concept=note.stem,
        message=(
            f"'{note.stem}' is an orphan playbook — link at least one related "
            f"concept, source concept, lesson, or existing playbook."
        ),
    )


def _key_fact_bullets(body: str) -> list[str]:
    """Return the bullet contents under the first `## Key facts` section.

    Empty when the concept has no such section (conservative: a note that does
    not use the key-facts format is never flagged). The section runs from its
    heading to the next markdown heading (or end of body).
    """
    lines = body.splitlines()
    bullets: list[str] = []
    current: list[str] = []
    in_section = False
    seen_blank_after_bullet = False

    def flush_current() -> None:
        nonlocal current, seen_blank_after_bullet
        if current:
            bullets.append(" ".join(current))
        current = []
        seen_blank_after_bullet = False

    for line in lines:
        if _KEY_FACTS_HEADING_RE.match(line):
            in_section = True
            continue
        if not in_section:
            continue
        if _ANY_HEADING_RE.match(line):  # next heading closes the section
            flush_current()
            break
        match = _BULLET_RE.match(line)
        if match:
            flush_current()
            current = [match.group(1)]
            continue
        if not current:
            continue
        if not line.strip():
            seen_blank_after_bullet = True
            continue
        if line.startswith((" ", "\t")) and not seen_blank_after_bullet:
            current.append(line.strip())
            continue
        flush_current()
    else:
        flush_current()
    return bullets


def check_keyfacts_citation(concept: Concept) -> list[Warning]:
    """Flag `## Key facts` bullets that carry no inline source reference (CHECK 1).

    The anti-hallucination contract (the wiki-ingest write contract, CONVENTIONS §5.1) requires
    every key fact to trace to a cited source — a fact with no traceable source is
    a hallucination risk. Today the gate only proves the concept HAS a verifiable
    URL in `sources:`, not that each fact cites one, so a fabricated fact attached
    to a real-but-unrelated URL passes. This deterministic check requires every
    bullet under `## Key facts` to carry an inline `Source:` token, a `[[wikilink]]`,
    or a URL — the exact conventions the template and the shipped seed concepts use.

    Conservative by design: a concept with no `## Key facts` section is never
    flagged, so notes that don't use the key-facts format are unaffected.
    """
    warnings: list[Warning] = []
    for bullet in _key_fact_bullets(concept.body):
        if not _INLINE_SOURCE_RE.search(bullet):
            warnings.append(
                Warning(
                    kind="uncited-fact",
                    concept=concept.stem,
                    message=(
                        f"'{concept.stem}' has a key fact with no inline source — "
                        f"every '## Key facts' bullet must cite a source "
                        f"(Source:/[[wikilink]]/URL): \"{bullet[:80]}\" "
                        f"(anti-hallucination, CONVENTIONS §5.1)."
                    ),
                )
            )
    return warnings


def check_pending_cap(concept: Concept, registry: TagRegistry) -> Warning | None:
    """Flag a concept introducing more than ONE new `pending:` tag (CHECK 2).

    The controlled-vocabulary rule is "≤1 new tag per concept, into `pending:`
    only" (CONVENTIONS §11), but pending tags were allowed unconditionally —
    letting a single note seed several off-vocabulary tags that promote_tags can
    later auto-promote (silent vocabulary drift). This caps the escape hatch: a
    concept carrying more than one tag that resolves into the registry's
    `pending:` quarantine fails the gate.

    No-op when the registry has no `pending:` set (nothing to bound).
    """
    pending = _normalized_pending(registry)
    if not pending:
        return None
    pending_tags = sorted(
        {tag for tag in concept.tags if normalize_tag(tag, registry) in pending}
    )
    if len(pending_tags) <= 1:
        return None
    return Warning(
        kind="pending-cap",
        concept=concept.stem,
        message=(
            f"'{concept.stem}' introduces {len(pending_tags)} new pending tags "
            f"({', '.join(pending_tags)}) — at most ONE new tag per concept may go "
            f"into pending: (CONVENTIONS §11); keep one and drop the rest."
        ),
    )


def check_stale(concept: Concept, *, today: date) -> Warning | None:
    """Flag a concept whose `last_verified + ttl_days` is in the past."""
    if concept.last_verified is None or concept.ttl_days is None:
        return None
    # A negative ttl is invalid — it would shift the expiry BEFORE the
    # verification date and instantly mark a freshly-verified concept stale.
    # Ignore it rather than emitting a bogus stale warning (FIX 4).
    if concept.ttl_days < 0:
        return None
    expires = concept.last_verified + timedelta(days=concept.ttl_days)
    if expires < today:
        return Warning(
            kind="stale",
            concept=concept.stem,
            message=(
                f"'{concept.stem}' is stale — last verified {concept.last_verified} "
                f"+ {concept.ttl_days}d expired {expires}; needs re-verification."
            ),
        )
    return None


def _normalized_pending(registry: TagRegistry) -> frozenset[str]:
    """The `pending:` set in normalized form, so a candidate tag matches it.

    A pending entry like `ai/evals` normalizes to `ai/eval` (singularized, since
    it isn't in the live vocabulary), and a written tag is compared in its
    normalized form — so the pending set must be normalized the same way for the
    two to line up. Includes the raw forms too, costing nothing and tolerating an
    already-singular pending entry.
    """
    return frozenset(registry.pending) | frozenset(
        normalize_tag(p, registry) for p in registry.pending
    )


def _is_off_vocabulary(normalized: str, registry: TagRegistry) -> bool:
    """True when a normalized tag is off-vocabulary (live, not a sanctioned tag).

    Off-vocabulary means: not in the live `domains` vocabulary, not a known
    synonym alias, and NOT quarantined under `pending:` (the sanctioned "new tag"
    path). Shared by the advisory `check_tags` scan and the write-time strict gate
    so the two can never disagree about what counts as off-vocabulary.
    """
    return (
        normalized not in registry.valid
        and normalized not in registry.synonyms
        and normalized not in _normalized_pending(registry)
    )


def check_tags(
    concepts: list[Concept], registry: TagRegistry
) -> list[Warning]:
    """Tag-hygiene findings: normalization, synonym merges, pending, one-offs.

    Per CONVENTIONS §11:
      - report tags whose normalized form (lowercase/singular/hyphen) differs;
      - report alias→canonical merges resolved via the synonyms map;
      - flag off-vocabulary tags absent from the registry AND its `pending:`
        quarantine (add to the registry or fix the tag);
      - promote a `pending:` tag once it recurs across ≥3 concepts;
      - flag one-off tags (used by exactly one note) to fold up to a domain.

    The off-vocabulary check only runs when the registry is actually populated:
    an empty registry (config/tags.yaml missing / not yet created by the sibling
    setup agent) is permissive, so we don't flag every tag as "off-vocabulary".
    """
    warnings: list[Warning] = []
    registry_populated = bool(registry.valid)

    # Count usage of each raw tag and each normalized tag across concepts.
    normalized_usage: dict[str, set[str]] = {}
    for concept in concepts:
        for tag in concept.tags:
            normalized = normalize_tag(tag, registry)
            normalized_usage.setdefault(normalized, set()).add(concept.stem)

            # Normalization drift — the written form differs from its canonical.
            if normalized != tag:
                warnings.append(
                    Warning(
                        kind="tag",
                        concept=concept.stem,
                        message=f"tag '{tag}' should be normalized to '{normalized}'.",
                    )
                )

            # Synonym merge — alias resolves to a different canonical tag.
            canonical = registry.synonyms.get(normalized)
            if canonical and canonical != normalized:
                warnings.append(
                    Warning(
                        kind="tag",
                        concept=concept.stem,
                        message=f"tag '{normalized}' is an alias — merge to '{canonical}'.",
                    )
                )

            # Off-vocabulary — not in the live vocabulary, not a known synonym,
            # and not quarantined in `pending:`. The author either has to add it
            # to the registry or fix the tag. (Skipped when the registry is empty
            # so a missing config doesn't flag everything.)
            if registry_populated and _is_off_vocabulary(normalized, registry):
                warnings.append(
                    Warning(
                        kind="tag",
                        concept=concept.stem,
                        message=(
                            f"tag '{normalized}' is off-vocabulary — not in "
                            f"config/tags.yaml (domains, synonyms, or pending). "
                            f"Add it to the registry or fix the tag."
                        ),
                    )
                )

    # Pending tags that now recur across enough notes to promote.
    for pending_tag in sorted(registry.pending):
        normalized = normalize_tag(pending_tag, registry)
        users = normalized_usage.get(normalized, set())
        if len(users) >= PENDING_PROMOTION_THRESHOLD:
            warnings.append(
                Warning(
                    kind="tag",
                    concept="",
                    message=(
                        f"pending tag '{pending_tag}' now recurs across {len(users)} "
                        f"concepts — promote it into the vocabulary (config/tags.yaml)."
                    ),
                )
            )

    # One-off tags: used by exactly one note AND not a domain-level tag.
    for normalized, users in sorted(normalized_usage.items()):
        if len(users) != 1:
            continue
        if "/" not in normalized:  # bare domain tag is fine on its own
            continue
        if normalized in registry.valid:  # part of the controlled vocabulary
            continue
        (only_user,) = tuple(users)
        domain = normalized.split("/")[0]
        warnings.append(
            Warning(
                kind="tag",
                concept=only_user,
                message=(
                    f"one-off tag '{normalized}' is used by a single note — fold it up "
                    f"to domain '{domain}' or drop it."
                ),
            )
        )

    return warnings


# --------------------------------------------------------------------------- #
# INDEX completeness (W1 — the hand-maintained MOC can drift)
# --------------------------------------------------------------------------- #

# `[[stem]]` / `[[stem|Alias]]` / `[[concepts/stem]]` wikilinks in the MOC.
_INDEX_WIKILINK_RE = re.compile(r"\[\[\s*(?:concepts/)?([^\]|#]+?)\s*(?:[|#][^\]]*)?\]\]")


def index_lists_stem(index_text: str, stem: str) -> bool:
    """True when the MOC text references `stem` — by `[[wikilink]]` or raw text.

    Shared by the advisory drift check below and `concept_write`'s write-time
    safety-net append, so the "is it listed?" predicate can never fork: an entry
    the check accepts is exactly one the writer won't duplicate.
    """
    linked = {target.strip().lower() for target in _INDEX_WIKILINK_RE.findall(index_text)}
    lowered_stem = stem.lower()
    return lowered_stem in linked or lowered_stem in index_text.lower()


def check_index_completeness(
    concepts: list[Concept], index_path: Path
) -> list[Warning]:
    """Flag non-seed concepts absent from the `brain/INDEX.md` MOC fallback.

    `brain/INDEX.md` is LLM/hand-maintained (CONVENTIONS §14) and can drift
    behind the vault. This is advisory only — this pass never rewrites the MOC
    (the write-time safety net in `concept_write` lists what IT writes; drift
    from any other write path surfaces here); we just warn when a concept is
    reachable in neither the MOC's `[[wikilinks]]` nor its raw text (by filename
    stem or title). A missing MOC is treated as permissive (nothing to check
    against) rather than flagging every concept.
    """
    if not concepts or not index_path.exists():
        return []
    text = index_path.read_text(encoding="utf-8")

    warnings: list[Warning] = []
    for concept in concepts:
        # Mentioned by wikilink, by raw filename stem, or by readable title text.
        if index_lists_stem(text, concept.stem):
            continue
        warnings.append(
            Warning(
                kind="missing-from-index",
                concept=concept.stem,
                message=(
                    f"'{concept.stem}' is not listed in brain/INDEX.md — the MOC "
                    f"fallback has drifted. Add a `[[{concept.stem}]]` entry."
                ),
            )
        )
    return warnings


# --------------------------------------------------------------------------- #
# Write-time gate + quarantine
# --------------------------------------------------------------------------- #


def gate_concepts(paths: list[Path], registry: TagRegistry) -> list[Warning]:
    """Write-time contract gate over the GIVEN concept files (CONVENTIONS §11).

    The unattended synthesis path runs this against only the concepts it WROTE
    this run (passed via `--paths`), so a freshly-authored note that breaks the
    tagging/citation contract fails the run rather than silently landing in the
    vault. Unlike the advisory full-vault scan, this checks ONLY the two
    write-time invariants — and it ignores the cold-start orphan relaxation,
    seed/example skipping, and graph-connectivity checks that don't apply to a
    just-written note:

      - every `type: concept` note must cite at least one `sources:` entry;
      - every key fact (a `## Key facts` bullet) must carry an inline source
        reference — a fact with no traceable source is a hallucination risk (CHECK 1);
      - a concept may introduce at most ONE new `pending:` tag — more is silent
        vocabulary drift (CHECK 2);
      - every LIVE tag must be in the controlled vocabulary — `pending:` tags are
        allowed (the sanctioned new-tag path), an off-vocabulary live tag is not.

    Reuses `check_missing_sources` and `_is_off_vocabulary` so the gate and the
    advisory scan can never drift. Returns the in-scope violations (empty == pass).
    """
    warnings: list[Warning] = []
    for path in paths:
        concept = load_concept(path)
        missing = check_missing_sources(concept)
        if missing:
            warnings.append(missing)
        warnings.extend(check_keyfacts_citation(concept))
        pending_cap = check_pending_cap(concept, registry)
        if pending_cap:
            warnings.append(pending_cap)
        for tag in concept.tags:
            normalized = normalize_tag(tag, registry)
            # Skip the off-vocabulary check when the registry is empty/missing —
            # a permissive vocabulary must not fail every tag (mirrors check_tags).
            if registry.valid and _is_off_vocabulary(normalized, registry):
                warnings.append(
                    Warning(
                        kind="tag",
                        concept=concept.stem,
                        message=(
                            f"tag '{normalized}' is off-vocabulary — not in "
                            f"config/tags.yaml (domains, synonyms, or pending)."
                        ),
                    )
                )
    return warnings


def quarantine_failing_concepts(
    paths: list[Path],
    violations: list[Warning],
    dest: Path,
    restore_from: Path | None = None,
) -> list[Path]:
    """Set aside every in-scope file that produced a violation; restore when possible.

    The unattended synthesis path validates the concepts it just wrote; on a strict
    failure it previously left the offending notes in `brain/concepts/`, where a
    later `build_digest` run could still surface an invalid (e.g. unsourced) concept.
    The bad write is always moved into `dest` (preserved for inspection). Then:

      - if `restore_from/<name>` exists — a pre-write backup of a concept that was
        valid BEFORE this run — the last-known-good version is restored to the vault.
        This is the failed-UPDATE case: a corrupting re-write must NOT delete the
        prior good note (which would break inbound links and lose knowledge).
      - otherwise (a brand-new, never-valid concept) the note is simply evicted.

    Files are matched to violations by stem. Returns the list of quarantined paths.
    """
    failing_stems = {v.concept for v in violations}
    moved: list[Path] = []
    for path in paths:
        if path.stem not in failing_stems or not path.is_file():
            continue
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / path.name
        # Avoid clobbering a same-named earlier quarantine entry. Use a random token
        # (not just the pid) so two evictions of the same filename within ONE process
        # still get distinct names — the quarantine must preserve every evicted file.
        if target.exists():
            target = dest / f"{path.stem}.{os.getpid()}.{os.urandom(4).hex()}{path.suffix}"
        path.replace(target)  # move the bad write aside (atomic rename)
        backup = (restore_from / path.name) if restore_from else None
        if backup is not None and backup.is_file():
            # Roll the live note back to its last-known-good version. Copy to a temp
            # in the same dir then atomically replace, so a mid-copy failure can't
            # leave a truncated concept where a valid one used to be.
            tmp = path.with_name(f".{path.name}.restore.{os.getpid()}")
            try:
                shutil.copy2(backup, tmp)
                os.replace(tmp, path)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
        moved.append(target)
    return moved
