"""Version-one problem-solution structure, not a factual-verification engine."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import yaml

MAX_BYTES = 1_000_000
SECTIONS = (
    "what it is",
    "why it matters",
    "key facts",
    "problem and symptoms",
    "applicability",
    "solution and alternatives",
    "verification",
    "how to apply it",
    "reuse observations",
    "open questions / gaps",
    "change history",
)
_SCOPES = {"observed_in_one_context", "reused_in_another_context"}


class UniqueLoader(yaml.SafeLoader):
    """Ambiguous duplicate metadata must not acquire two interpretations."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError("frontmatter keys must be unique strings")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def parse_record(text: str) -> tuple[dict[str, Any], dict[str, str]]:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("record exceeds byte limit")
    match = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", text, re.S)
    if not match:
        raise ValueError("record needs YAML frontmatter")
    loader = UniqueLoader(match[1])  # SafeLoader constructors; only duplicate mapping keys differ.
    try:
        meta = loader.get_single_data()
    except yaml.YAMLError as exc:
        raise ValueError("invalid YAML frontmatter") from exc
    finally:
        loader.dispose()
    if not isinstance(meta, dict):
        raise ValueError("frontmatter must be a mapping")
    sections: dict[str, str] = {}
    chunks = re.split(r"^##\s+(.+?)\s*$", text[match.end() :], flags=re.M)
    for pos in range(1, len(chunks), 2):
        heading = chunks[pos].casefold()
        if heading in sections:
            raise ValueError("duplicate section: " + heading)
        sections[heading] = chunks[pos + 1].strip()
    return meta, sections


def archive_path(value: object) -> bool:
    if not isinstance(value, str) or "\\" in value:
        return False
    p = PurePosixPath(value)
    return (
        str(p) == value
        and not p.is_absolute()
        and ".." not in p.parts
        and len(p.parts) >= 3
        and p.parts[:2] in {("pipeline", "0-archive"), ("pipeline", "3-synthesis")}
        and p.suffix == ".md"
    )


def source_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        p = urlsplit(value)
        return (
            p.scheme in {"http", "https"}
            and bool(p.hostname)
            and not p.username
            and not p.password
            and not any(
                k.casefold()
                in {
                    "token",
                    "api_key",
                    "key",
                    "secret",
                    "password",
                    "access_token",
                    "signature",
                    "sig",
                }
                for k, _ in parse_qsl(p.query) + parse_qsl(p.fragment)
            )
        )
    except ValueError:
        return False


def iso_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def validate_record(text: str) -> list[str]:
    """Validate structural evidence references; caller checks retained files and tags."""
    try:
        meta, sections = parse_record(text)
    except (ValueError, RecursionError) as exc:
        return [str(exc)]
    errors: list[str] = []
    for key, expected in {
        "type": "concept",
        "knowledge_kind": "problem_solution",
        "schema_version": 1,
        "visibility": "private",
    }.items():
        if meta.get(key) != expected or isinstance(meta.get(key), bool):
            errors.append(f"{key} must be {expected!r}")
    title = meta.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 200 or "\n" in title:
        errors.append("title must be a nonempty single line, at most 200 characters")
    language = meta.get("content_language")
    if not isinstance(language, str) or not re.fullmatch(
        r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language
    ):
        errors.append("content_language must be a language code")
    for field, pattern, minimum in (
        ("programming_languages", r"[a-z][a-z0-9+#.-]{0,39}", 0),
        ("problem_types", r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", 1),
        ("technologies", r"[a-zA-Z0-9][a-zA-Z0-9+#._/-]{0,79}", 0),
    ):
        values = meta.get(field)
        if field == "technologies" and values is None:
            values = meta.get("frameworks", [])  # compatibility with the approved pilot
        if (
            not isinstance(values, list)
            or not minimum <= len(values) <= 20
            or any(not isinstance(v, str) or not re.fullmatch(pattern, v) for v in values)
            or len(set(v for v in values if isinstance(v, str))) != len(values)
        ):
            errors.append(f"{field} must be a bounded list of unique canonical identifiers")
    if not isinstance(meta.get("evidence_scope"), str) or meta["evidence_scope"] not in _SCOPES:
        errors.append("evidence_scope is not supported")
    tags = meta.get("tags")
    if (
        not isinstance(tags, list)
        or not 2 <= len(tags) <= 5
        or any(not isinstance(t, str) for t in tags)
    ):
        errors.append("tags must contain 2–5 controlled tags")
    dates: dict[str, date] = {}
    for field in ("created", "last_updated", "last_verified"):
        if field == "last_verified" and field not in meta:
            continue
        parsed = iso_date(meta.get(field))
        if parsed is None or parsed > date.today():
            errors.append(f"{field} must be a valid nonfuture date")
        else:
            dates[field] = parsed
    if dates.get("created", date.min) > dates.get("last_updated", date.max):
        errors.append("last_updated precedes created")
    if "ttl_days" in meta and (type(meta["ttl_days"]) is not int or meta["ttl_days"] <= 0):
        errors.append("ttl_days must be a positive integer")
    for section in SECTIONS:
        if not sections.get(section):
            errors.append("missing or empty section: " + section)
    if not re.search(r"\[\s*(?:lesson|research):[^\]\n]+\]", sections.get("change history", "")):
        errors.append("change history needs a lesson/research provenance marker")
    if not re.search(r"^>\s*\*\*Confidence:\*\*\s*(?:low|medium|high)\s*$", text, re.M | re.I):
        errors.append("record needs explicit recorded confidence")
    references: set[str] = set()
    archives: set[str] = set()
    sources = meta.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 30:
        errors.append("sources must be a nonempty bounded structured list")
    else:
        for source in sources:
            if not isinstance(source, dict):
                errors.append("source must be a mapping")
                continue
            url, archive = source.get("url"), source.get("archive")
            if url is not None:
                if source_url(url):
                    references.add(url)
                else:
                    errors.append("invalid or credential-bearing source URL")
            if archive is not None:
                if archive_path(archive):
                    references.add(archive)
                    archives.add(archive)
                else:
                    errors.append("source archive must be a safe pipeline artifact path")
            if not url and not archive:
                errors.append("source needs a URL or retained archive")
            observed = iso_date(source.get("date"))
            if observed is None or observed > date.today():
                errors.append("source needs a nonfuture observation date")
    evidence = {a for a in archives if a.startswith("pipeline/3-synthesis/")}
    if not evidence or not any(a in sections.get("verification", "") for a in evidence):
        errors.append("verification must cite retained synthesis evidence")
    facts = re.findall(
        r"^\s*[-*]\s+(.+?)(?=\n\s*[-*]\s|\Z)", sections.get("key facts", ""), re.M | re.S
    )

    def cited(fact: str) -> bool:
        tokens = re.findall(r"https?://[^\s<>]+|pipeline/(?:0-archive|3-synthesis)/[^\s<>]+", fact)
        return bool(references.intersection(t.strip("`.,;:!?)[]") for t in tokens))

    if not facts or any(not cited(fact) for fact in facts):
        errors.append("every key fact must cite a declared source")
    if meta.get("evidence_scope") == "reused_in_another_context":
        reuse = meta.get("reuse_evidence")
        if (
            not isinstance(reuse, list)
            or not reuse
            or any(
                not isinstance(a, str)
                or a not in archives
                or a not in sections.get("reuse observations", "")
                for a in reuse
            )
        ):
            errors.append("broader evidence_scope needs declared, cited reuse_evidence")
    return errors
