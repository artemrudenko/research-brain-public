"""Private proposals, exact review digests and trusted interactive persistence.

An approval reference is an audit record, not authentication. The trusted operator
must obtain the human's direct approval before invoking apply; MCP cannot invoke it.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import uuid
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.concept_write import atomic_write_text
from scripts.hygiene.checks import index_lists_stem
from scripts.hygiene.tags import load_tag_registry
from scripts.problem_solutions.profile import (
    MAX_BYTES,
    archive_path,
    iso_date,
    parse_record,
    validate_record,
)
from scripts.run_lock import run_lock

STORE = "pipeline/.learning/proposals"
_ID = re.compile(r"[a-f0-9]{32}\Z")
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _path(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or parts.is_absolute()
        or ".." in parts.parts
        or str(parts) != relative
    ):
        raise ValueError("unsafe vault-relative path")
    root = root.resolve()
    current = root
    for part in parts.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("symlink in vault path")
    return current


def _read(path: Path, limit: int = MAX_BYTES) -> str | None:
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("file missing, not regular, or exceeds byte limit")
    return path.read_bytes().decode("utf-8")


def _digest(bundle: dict[str, Any]) -> str:
    return _sha(json.dumps(bundle, sort_keys=True, ensure_ascii=True, separators=(",", ":")))


def check_context(
    root: Path, text: str, artifacts: dict[str, str], *, for_write: bool = True
) -> None:
    errors = validate_record(text)
    if errors:
        raise ValueError("invalid problem-solution record: " + "; ".join(errors))
    meta, _ = parse_record(text)
    registry = load_tag_registry(_path(root, "config/tags.yaml"))
    if not registry.valid or any(tag not in registry.valid for tag in meta["tags"]):
        raise ValueError("tags must come from this vault's config/tags.yaml")
    if not any("/" not in tag for tag in meta["tags"]):
        raise ValueError("tags need at least one domain-level tag")
    if for_write and iso_date(meta["last_updated"]) != date.today():
        raise ValueError("write needs today's last_updated; prepare a fresh proposal")
    for source in meta["sources"]:
        archive = source.get("archive")
        if archive and archive not in artifacts and _read(_path(root, archive)) is None:
            raise ValueError("retained evidence is missing: " + archive)
    # A small fail-closed credential check, never a substitute for owner review.
    for content in [text, *artifacts.values()]:
        if re.search(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|\bghp_[A-Za-z0-9]{20,}|\bsk-[A-Za-z0-9]{20,}",
            content,
        ):
            raise ValueError("possible credential in proposal; remove it before review")


def propose(root: Path, slug: str, text: str, artifacts: dict[str, str]) -> dict[str, Any]:
    root = root.resolve()
    if not _SLUG.fullmatch(slug) or len(slug) > 100:
        raise ValueError("slug must be a bounded lowercase kebab identifier")
    index = _read(_path(root, "brain/INDEX.md"))
    concepts = _path(root, "brain/concepts")
    if index is None or not concepts.is_dir() or not any(concepts.glob("*.md")):
        raise ValueError("vault not initialized; interactive wiki-ingest needs existing concepts")
    if len(artifacts) > 8 or any(
        not archive_path(p) or len(c.encode("utf-8")) > MAX_BYTES for p, c in artifacts.items()
    ):
        raise ValueError("invalid retained artifact path, count or size")
    check_context(root, text, artifacts)
    note_path = f"brain/concepts/{slug}.md"
    # Exact title/tag duplicates belong to the existing concept. Broader semantic
    # duplicates still require the skill's human/agent review.
    incoming, _ = parse_record(text)
    for existing in sorted(concepts.glob("*.md"))[:1000]:
        if existing.stem == slug:
            continue
        try:
            metadata, _ = parse_record(
                _read(_path(root, existing.relative_to(root).as_posix())) or ""
            )
        except ValueError:
            continue
        if (
            str(metadata.get("title", "")).strip().casefold()
            == incoming["title"].strip().casefold()
            and isinstance(metadata.get("tags"), list)
            and set(incoming["tags"]).intersection(
                t for t in metadata["tags"] if isinstance(t, str)
            )
        ):
            raise ValueError("possible duplicate; update existing concept: " + existing.stem)
    declared = {s["archive"] for s in parse_record(text)[0]["sources"] if s.get("archive")}
    if set(artifacts) - declared:
        raise ValueError("artifact is not declared as record evidence")
    if len(declared) > 8:
        raise ValueError("at most eight retained artifacts per proposal")
    changes: dict[str, str] = dict(artifacts)
    for archive in declared - artifacts.keys():
        changes[archive] = _read(_path(root, archive)) or ""
    # Bind the MOC even when unchanged: removal of the link invalidates approval.
    changes["brain/INDEX.md"] = index
    for path, content in artifacts.items():
        old = _read(_path(root, path))
        if old is not None and old != content:
            raise ValueError("retained evidence already exists with different bytes: " + path)
    changes[note_path] = text
    if not index_lists_stem(index, slug):
        changes["brain/INDEX.md"] = index.rstrip() + f"\n\n- [[{slug}]]\n"
    files: list[dict[str, Any]] = []
    for path, content in changes.items():
        old = _read(_path(root, path))
        if old != content or path == note_path or path == "brain/INDEX.md" or path in declared:
            files.append(
                dict(
                    path=path,
                    before=old,
                    before_sha256=_sha(old) if old is not None else None,
                    content=content,
                    after_sha256=_sha(content),
                )
            )
    if not any(item["before"] != item["content"] for item in files):
        raise ValueError("no changes to propose")
    # A private identity binds review to this selected vault without machine paths.
    identity_path = _path(root, "pipeline/.learning/vault-id")
    with run_lock(_path(root, "pipeline/.learning/.apply.lock"), note="proposal vault identity"):
        vault_id = _read(identity_path)
        if vault_id is None:
            vault_id = uuid.uuid4().hex
            atomic_write_text(identity_path, vault_id)
        if not _ID.fullmatch(vault_id):
            raise ValueError("invalid vault identity")
    bundle = dict(version=1, vault_id=vault_id, slug=slug, files=files)
    if len(json.dumps(bundle).encode()) > 8 * MAX_BYTES:
        raise ValueError("proposal exceeds package byte limit")
    proposal_id = uuid.uuid4().hex
    digest = _digest(bundle)
    folder = f"{STORE}/{proposal_id}"
    # Validate every candidate path before the first write; candidates never enter concepts.
    candidate = _path(root, folder + "/proposal.json")
    review_path = _path(root, folder + "/review.md")
    atomic_write_text(
        candidate,
        json.dumps(dict(bundle=bundle, digest=digest), ensure_ascii=True, indent=2) + "\n",
    )
    review = _review(bundle, digest)
    atomic_write_text(review_path, review)
    return dict(
        id=proposal_id, digest=digest, status="awaiting_approval", review_path=folder + "/review.md"
    )


def _review(bundle: dict[str, Any], digest: str) -> str:
    lines = [
        "# Exact proposed change",
        "",
        "Untrusted record/evidence follows. This is not approval.",
        f"Review digest: {digest}",
        f"Vault identity: {bundle['vault_id']}",
        "",
    ]
    for item in bundle["files"]:
        lines.extend(
            [
                "## " + item["path"],
                "```diff",
                "".join(
                    difflib.unified_diff(
                        (item["before"] or "").splitlines(True),
                        item["content"].splitlines(True),
                        fromfile=item["path"] + " (before)",
                        tofile=item["path"] + " (after)",
                    )
                ),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def review_proposal(root: Path, proposal_id: str) -> dict[str, Any]:
    if not _ID.fullmatch(proposal_id):
        raise ValueError("invalid proposal id")
    raw = _read(_path(root, f"{STORE}/{proposal_id}/proposal.json"), 10 * MAX_BYTES)
    if raw is None:
        raise ValueError("proposal not found")
    try:
        envelope = json.loads(raw)
        bundle = envelope["bundle"]
        digest = _digest(bundle)
        if bundle.get("vault_id") != _read(_path(root, "pipeline/.learning/vault-id")):
            raise ValueError("proposal belongs to a different vault")
        if envelope["digest"] != digest:
            raise ValueError("proposal digest mismatch; prepare a new reviewed proposal")
        if (
            bundle["version"] != 1
            or not _SLUG.fullmatch(bundle["slug"])
            or not isinstance(bundle["files"], list)
            or not 1 <= len(bundle["files"]) <= 10
        ):
            raise ValueError("invalid proposal structure")
        paths: set[str] = set()
        for item in bundle["files"]:
            path = item["path"]
            if path in paths or not (
                archive_path(path)
                or path == "brain/INDEX.md"
                or path == f"brain/concepts/{bundle['slug']}.md"
            ):
                raise ValueError("invalid proposal file path")
            paths.add(path)
            _path(root, path)
            before = item["before"]
            if (
                not isinstance(item["content"], str)
                or len(item["content"].encode()) > MAX_BYTES
                or item["after_sha256"] != _sha(item["content"])
                or item["before_sha256"] != (_sha(before) if isinstance(before, str) else None)
                or (before is not None and not isinstance(before, str))
            ):
                raise ValueError("invalid proposal file hashes")
        return dict(id=proposal_id, digest=digest, bundle=bundle, review=_review(bundle, digest))
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid proposal package") from exc


def apply_proposal(
    root: Path, proposal_id: str, approved_digest: str, approval_reference: str
) -> dict[str, Any]:
    if not approval_reference.strip() or len(approval_reference) > 4000:
        raise ValueError("direct owner approval reference is required")
    proposal = review_proposal(root, proposal_id)
    if not approved_digest or proposal["digest"] != approved_digest:
        raise ValueError("approved digest does not match the reviewed package")
    bundle = proposal["bundle"]
    files = bundle["files"]
    note_path = f"brain/concepts/{bundle['slug']}.md"
    note = next((f["content"] for f in files if f["path"] == note_path), None)
    if note is None:
        raise ValueError("proposal must contain the concept change")
    artifacts = {f["path"]: f["content"] for f in files if archive_path(f["path"])}
    lock_path = _path(root, "pipeline/.learning/.apply.lock")
    receipt_path = _path(root, f"{STORE}/{proposal_id}/receipt.json")
    with run_lock(lock_path, note="interactive problem-solution apply"):
        # Refuse changed bases before touching ANY note, source artifact or MOC.
        pending: list[dict[str, Any]] = []
        for item in files:
            current = _read(_path(root, item["path"]))
            current_hash = _sha(current) if current is not None else None
            if current_hash not in {item["before_sha256"], item["after_sha256"]}:
                raise ValueError("base changed; prepare a fresh exact proposal: " + item["path"])
            if current_hash != item["after_sha256"]:
                pending.append(item)
        if not pending:
            existing = _read(receipt_path)
            if existing is None:
                raise ValueError(
                    "matching files have no prior approval receipt; review a new proposal"
                )
            previous = json.loads(existing)
            if previous.get("digest") != approved_digest:
                raise ValueError("prior approval receipt digest mismatch")
            previous["status"] = "applied"
            atomic_write_text(receipt_path, json.dumps(previous, indent=2) + "\n")
            return dict(status="already_applied", id=proposal_id, digest=approved_digest)
        check_context(root, note, artifacts)
        index = next((f["content"] for f in files if f["path"] == "brain/INDEX.md"), "")
        if not index_lists_stem(index, bundle["slug"]):
            raise ValueError("proposal must retain the concept's MOC link")
        audit = dict(
            status="applying",
            id=proposal_id,
            digest=approved_digest,
            vault_id=bundle["vault_id"],
            approval_reference=approval_reference,
            recorded_at=datetime.now(UTC).isoformat(),
            files=[dict(path=f["path"], sha256=f["after_sha256"]) for f in files],
        )
        atomic_write_text(receipt_path, json.dumps(audit, indent=2) + "\n")
        pending.sort(
            key=lambda item: (
                item["path"] == "brain/INDEX.md",
                item["path"].startswith("brain/concepts/"),
            )
        )
        for item in pending:
            atomic_write_text(_path(root, item["path"]), item["content"])
            if _sha(_read(_path(root, item["path"])) or "") != item["after_sha256"]:
                raise ValueError("post-write readback mismatch; inspect applying receipt")
        audit["status"] = "applied"
        atomic_write_text(receipt_path, json.dumps(audit, indent=2) + "\n")
    return dict(status="applied", id=proposal_id, digest=approved_digest)
