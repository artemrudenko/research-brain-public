from __future__ import annotations

import re
import sys
from pathlib import Path
from types import ModuleType

from scripts import schema
from scripts._yaml import optional_yaml
from scripts.collection.feed import FeedItem
from scripts.collection.text import _NO_SUMMARY_NOTE, strip_html, to_iso_date
from scripts.content_metadata import AuthorIdentity, ContentMetadata, safe_url
from scripts.content_metadata.normalize import clean_person_name, clean_text
from scripts.normalize_url import normalize

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TAGS = _PROJECT_ROOT / "config" / "tags.yaml"
_TAG_NON_ALNUM = re.compile(r"[^a-z0-9/]+")


def _load_yaml() -> ModuleType:
    """Import PyYAML lazily with a clear, actionable message on failure."""
    yaml = optional_yaml()
    if yaml is None:
        print(
            "ERROR: PyYAML is required to write collected-article frontmatter.\n"
            "       Install it with: pip install pyyaml "
            "(or: pip install -r requirements.txt)",
            file=sys.stderr,
        )
        sys.exit(2)
    return yaml


# --------------------------------------------------------------------------- #


def _yaml_scalar_line(key: str, value: str) -> str:
    """One valid `key: value` YAML line — PyYAML quotes as needed (mirrors inbox)."""
    flat = " ".join(str(value).split())
    return _load_yaml().safe_dump(
        {key: flat}, default_flow_style=False, allow_unicode=True, sort_keys=False
    ).strip()


def _yaml_block_line(key: str, value: object) -> str:
    """One valid `key:` block with a NESTED value, serialised by PyYAML.

    The flat `_yaml_scalar_line` above is what keeps a hostile scalar harmless;
    this is its structured twin, and the safety argument is identical — PyYAML
    decides every quote, so an author named `- name: evil` is emitted as a
    quoted string rather than becoming a second list entry. The structure is
    ours; only the leaf values come from the document.

    `sort_keys=False` keeps the authored key order (name, url, id) so the block
    reads the way a person would write it.
    """
    return _load_yaml().safe_dump(
        {key: value}, default_flow_style=False, allow_unicode=True, sort_keys=False
    ).strip()


def _author_mapping(author: AuthorIdentity) -> dict[str, str]:
    """One `authors:` entry, re-cleaned at the boundary.

    The extractor already bounds and flattens these, but `AuthorIdentity` is a
    plain dataclass any caller can build, and this is the last point before the
    value is written to disk — so the name is re-flattened and the URL's scheme
    re-checked here rather than trusted. Empty fields are omitted, never emitted
    blank: a reader should not have to tell `url: ""` from "no profile known".
    """
    entry = {"name": clean_person_name(author.name)}
    url = safe_url(author.url)
    if url:
        entry["url"] = url
    if author.identifier:
        entry["id"] = clean_text(author.identifier)
    return entry


def _metadata_lines(metadata: ContentMetadata | None, source_url: str) -> list[str]:
    """The optional enrichment fields, each emitted only when it has a value.

    Additive by construction: with nothing to say this returns [], and the
    frontmatter is byte-identical to what the pre-metadata writer produced. That
    is what lets old articles and new ones share one validator.
    """
    lines: list[str] = []
    if metadata is None:
        metadata = ContentMetadata()

    authors = [_author_mapping(a) for a in metadata.authors if clean_person_name(a.name)]
    if authors:
        lines.append(_yaml_block_line("authors", authors))
    if metadata.publication:
        lines.append(_yaml_scalar_line("publication", metadata.publication))
    if source_url:
        lines.append(_yaml_scalar_line("source_url", source_url))
    if metadata.content_type:
        lines.append(_yaml_scalar_line("content_type", metadata.content_type))
    # Provenance is only meaningful next to the authors it explains.
    provenance = metadata.evidence.get("authors", "")
    if authors and provenance:
        lines.append(_yaml_scalar_line("metadata_source", provenance))
    return lines


def _frontmatter(
    *, source: str, url: str, title: str, author: str,
    date_published: str, collected: str, category: str,
    tags: list[str], tier: str,
    metadata: ContentMetadata | None = None, source_url: str = "",
) -> str:
    """A CONVENTIONS §5 strict frontmatter block, emitted as valid YAML.

    Every scalar is serialised by PyYAML so arbitrary feed metadata (a title with
    a colon, an author like `a: b`) can't produce a malformed block; tags stay a
    flow sequence and dates are emitted bare (an ISO date is YAML-safe and the
    pipeline's lightweight date parsers reject a quoted one) — exactly like
    `inbox._frontmatter`. `tier` is emitted ONLY when non-empty.
    """
    yaml = _load_yaml()
    flow_tags = yaml.safe_dump(list(tags), default_flow_style=True, allow_unicode=True).strip()
    lines = [
        "---",
        f"schema_version: {schema.CURRENT['article']}",
        _yaml_scalar_line("source", source),
        _yaml_scalar_line("url", url),
        _yaml_scalar_line("title", title),
        _yaml_scalar_line("author", author),
        f"date_published: {date_published}",
        f"collected: {collected}",
        _yaml_scalar_line("category", category),
        f"tags: {flow_tags}",
    ]
    if tier:
        lines.append(_yaml_scalar_line("tier", tier))
    lines.extend(_metadata_lines(metadata, source_url))
    lines.append("---")
    return "\n".join(lines)


def build_article(
    item: FeedItem,
    *,
    source_name: str,
    category: str,
    tags: list[str],
    collected: str,
    tier: str,
    metadata: ContentMetadata | None = None,
    source_url: str = "",
) -> str:
    """Render the full file text for a feed item (strict frontmatter + body).

    The `url:` field carries the NORMALIZED url (the registry dedup key), the body
    is the stripped plain text, and an HTML comment stands in for the LLM summary
    the headless path can't produce. `tier` is omitted from the frontmatter when
    empty. The output begins with `---` so it passes the strict pipeline validator.
    """
    normalized_url = normalize(item.url)
    title = item.title or "Untitled"
    # The display byline prefers an extracted author: it is the one that may be
    # attributed (a profile URL, an ORCID), where the feed string is a bare name.
    # Shape is unchanged — the digest reader matches on `*By … · …*`.
    extracted = [a for a in (metadata.authors if metadata else ()) if clean_person_name(a.name)]
    author = (
        clean_person_name(extracted[0].name) if extracted else (item.author.strip() or "unknown")
    )
    date_published = to_iso_date(item.date_published, fallback=collected)
    front = _frontmatter(
        source=source_name, url=normalized_url, title=title, author=author,
        date_published=date_published, collected=collected, category=category,
        tags=tags, tier=tier, metadata=metadata, source_url=source_url,
    )
    body = strip_html(item.body)
    return (
        f"{front}\n\n"
        f"# {title}\n\n"
        f"*By {author} · {date_published}*\n\n"
        f"---\n\n"
        f"{_NO_SUMMARY_NOTE}\n\n"
        f"{body}\n\n"
        f"---\n"
        f"*Source: {normalized_url}*\n"
    )


def _load_seed_tag_registry(tags_path: Path = DEFAULT_TAGS) -> tuple[set[str], dict[str, str]]:
    """Allowed tags + synonyms for RSS `<category>` seed tags.

    Collection keeps the topic/category tag unconditionally for backwards
    compatibility, then admits feed-provided categories only when they normalize
    through the controlled vocabulary. Unknown feed labels are dropped rather
    than expanding the vocabulary from untrusted source metadata.
    """
    if not tags_path.exists():
        return set(), {}
    try:
        data = _load_yaml().safe_load(tags_path.read_text(encoding="utf-8")) or {}
    except OSError:
        return set(), {}
    if not isinstance(data, dict):
        return set(), {}
    valid: set[str] = set()
    domains = data.get("domains")
    if isinstance(domains, dict):
        for domain, topics in domains.items():
            domain_s = str(domain).strip()
            if not domain_s:
                continue
            valid.add(domain_s)
            if isinstance(topics, list):
                for topic in topics:
                    topic_s = str(topic).strip()
                    if topic_s:
                        valid.add(f"{domain_s}/{topic_s}")
    synonyms: dict[str, str] = {}
    raw_synonyms = data.get("synonyms")
    if isinstance(raw_synonyms, dict):
        for raw_key, raw_value in raw_synonyms.items():
            key = _normalize_seed_label(str(raw_key))
            value = str(raw_value).strip()
            if key and value:
                synonyms[key] = value
    return valid, synonyms


def _normalize_seed_label(label: str) -> str:
    """Normalize an RSS category label into the tag-registry spelling axis."""
    lowered = label.strip().lower().replace("_", "-")
    return _TAG_NON_ALNUM.sub("-", lowered).strip("-")


def _article_tags(
    category: str, item_categories: list[str], *, tags_path: Path = DEFAULT_TAGS
) -> list[str]:
    """Topic tag plus controlled-vocabulary RSS seed tags, de-duplicated."""
    valid, synonyms = _load_seed_tag_registry(tags_path)
    tags: list[str] = []
    seen: set[str] = set()

    def add(tag: str) -> None:
        if tag and tag not in seen:
            tags.append(tag)
            seen.add(tag)

    add(category)
    for raw in item_categories:
        normalized = _normalize_seed_label(raw)
        if not normalized:
            continue
        canonical = synonyms.get(normalized, normalized)
        if canonical in valid:
            add(canonical)
    return tags


