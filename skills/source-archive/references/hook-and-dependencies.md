---
title: "source-archive — Optional hook, dependencies, Phase 2.5 stripping detail, STALE re-fetch"
type: reference
domain: meta-process
last_updated: 2026-06-15
applies_when: "Optional hook activation / manual invocation example / dependencies / Phase 2.5 instruction-stripping / Phase 4 STALE re-fetch handling"
---

# Optional hook, dependencies & detail

> SKILL.md keeps the phase summary; full detail here. The archive root is config-derived (default `pipeline/0-archive/`); written as `{{ARCHIVE_ROOT}}` below.

## Dependencies

Requires the WebFetch tool OR a browser-automation tool (navigate + extract page text); writes to `{{ARCHIVE_ROOT}}` (must be writable); reads `sources/trusted-registry.md` for the tier lookup. Bash for sha256 hashing. The archive step can run either fully manually (caller invokes it after each fetch) or, where the runtime supports it, via an automatic post-fetch hook.

## Optional hook implementation note

The archive step performs Phase 2-4. It can be wired in two ways, both optional:

- **Automatic post-fetch hook (where supported):** runtimes that expose a post-tool-use hook can fire the archive step natively whenever a web-fetch or browser-fetch tool returns. This requires no manual call from the caller. Configure it per the runtime's hook documentation; the hook receives the fetch payload (URL + returned content) and runs the same Phase 1-4 logic.

- **Manual invocation (default, always available):** when the runtime does not support post-tool-use hooks, the skill-caller (`research-grep`, `research-build`, `research-audit` supplementary fetch) runs the archive step **manually** right after the WebFetch. A minimal driver receives the fetch result as JSON and writes the archive:

  ```bash
  # Pass the fetch result (URL + returned body) to the archive step.
  # The driver performs: dedup (Phase 1), tier lookup + write (Phase 3),
  # filename generation, frontmatter assembly, hash drift check + audit_history (Phase 4).
  ```

  The caller then reads the frontmatter of the written file to obtain the local archive path.

  **NB on drift handling:** a fully automatic driver may choose to overwrite the file on hash drift (with an `audit_history` entry), which differs from the SKILL Phase 4 spec ('preserve old'). Automatic overwrite is acceptable only when the audit trail is not lost (the old hash is recorded in `audit_history`). For critical sources that require explicit preserve-old behaviour, the caller asks the user **before** running the archive step.

Double link for downstream citations: the caller reads the frontmatter of the saved file -> passes URL + local path into synthesis.

## Phase 2.5 — Instruction stripping (MODE=instruction-stripping only)

**Trigger:** `MODE=instruction-stripping` OR the caller explicitly requests a sanitized version (research-build for downstream LLM consumption / long-running multi-session work). **Purpose:** mitigate indirect prompt injection inherited from external content. **Skip:** the default `MODE=auto-archive` runs WITHOUT stripping (content is for human reading + hash drift check only).

**One shared engine — do NOT hand-apply the rules.** The strip core lives in `scripts/sanitize_incoming.py` and is the SAME engine the unattended `pipeline/1-incoming/` gate uses (`skills/research-build` PROFILE=internal-corpus consumes its output). It exposes a pure function `sanitize_text(text: str) -> SanitizeResult` (no I/O; `.clean_text`, `.findings`, `.stripped_classes`, `.severity`) and the file-level `sanitize_file(src: Path) -> FileOutcome`, which writes the sanitized companion atomically with the integrity-gated frontmatter. The deterministic ruleset it applies: S1 system-prompt mimicry (strip) · S2 delimiter injection (strip) · S3 universal jailbreak (strip) · S4 role-switching (flag) · S5 markdown image exfiltration (strip) · S6 external URL templated query (strip) · S7 shell/code injection (flag) · S8 multi-turn drift starters (flag) · S9 hidden invisible chars (strip). Class detail: [`instruction-stripping-patterns.md`](instruction-stripping-patterns.md).

**Steps:**
1. **Run the engine on the freshly written archive** — `sanitize_file(Path)` does steps 2–3 in one call:
   ```bash
   python3 -c "from pathlib import Path; from scripts.sanitize_incoming import sanitize_file; o = sanitize_file(Path('{{ARCHIVE_ROOT}}/<archive-filename>.md')); print(o.companion, o.result.severity, sorted(o.result.stripped_classes))"
   ```
   (For a one-off string — e.g. sanitizing fetched text already in context before it reaches synthesis — call `sanitize_text(text)` directly and read `.clean_text`.)
2. **Sanitized companion written:** `{{ARCHIVE_ROOT}}/sanitized/{same-filename}.md` (parallel dir, does NOT overwrite the original). The engine emits the audit frontmatter for you — the SAME companion shape the unattended gate verifies:
   ```yaml
   instruction_stripped: true
   stripped_at: 2026-05-10T12:34:56Z
   source_hash: <sha256 of the source archive>      # gate's drift check
   sanitized_hash: <sha256 of the companion>         # gate's integrity check
   stripped_classes: [S1, S5, S9]
   stripping_severity: critical | medium | clean
   ```
3. **Verify (optional):** `python3 scripts/sanitize_incoming.py gate --incoming {{ARCHIVE_ROOT}}` is the same gate synthesis runs — it refuses if a companion is missing, stale (source changed), or corrupt.
4. **Caller behavior:** downstream skills reading the sanitized companion **must** reference the original archive via `source_hash:` (the sha256 of the original source — audit-trail integrity).

**Anti-patterns:** replacing the original with the sanitized version (preservation invariant violated) · skipping stripping for a 'trusted' T1 source (an adversary may control the DNS/CDN/doc-edit path) · hand-rolling the S1–S9 strip in prose instead of calling `sanitize_incoming` (the two paths would diverge and the companion would not pass the shared gate) · forcing medium/informational classes (S4/S7/S8) to strip — the engine deliberately FLAGS them (documented false-positive risk).

## Phase 4 — STALE CACHE re-fetch handling

On STALE CACHE (Phase 1 found an archive older than 7 days): re-fetch the URL -> compute the new hash -> compare with `hash` from the existing frontmatter:
- **Same hash** -> update only `last_updated` + an audit_history entry 're-fetched, hash unchanged'.
- **Different hash** -> **do not overwrite** the existing content (preserve historical) + an audit_history entry with a note + flag `content_drift: true`. Ask the user (optional, critical sources): 'Refresh / preserve old / save both?'. Default — **preserve old** (audit trail > freshness); refresh only on explicit request.
