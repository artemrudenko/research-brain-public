---
name: source-archive
description: "Use to persist web-fetch content into the archive zone with frontmatter type:source + sha256 hash + double-link. Auto-hook on any WebFetch / browser-fetch in a research session. Triggers: 'archive this URL', 'save this fetched page to the archive', 'persist to the archive'. To MONITOR a source going forward, that is source-manage (config), not this skill (which persists a fetched page's content). 7-day dedup window + in-session memo; hash drift detection on re-fetch."

metainfo:
  category: [knowledge-management]
  type: worker
  domain: meta-process
  subagent_capability: general
  last_updated: 2026-06-15
  handoff_pattern: hook
  predecessor: [research-grep, research-build, research-audit]
  successor: []
---

# source-archive — Web Content Persistence

**Purpose:** ensure that any web-fetch in a research session is **always** persisted to the archive zone with correct frontmatter — without relying on author discipline. Without this rule half the sources are never saved, and downstream documents lose link-rot protection.

**Terminal sink** — the caller continues its workflow with content that is already archived.

The archive root is **config-derived**, not hardcoded. It defaults to `pipeline/0-archive/` (see `rules/common.md` and `config/sources.yaml`); this document writes it as `{{ARCHIVE_ROOT}}` throughout.

---

## When to Use

**Always:**
- Auto-hook on any WebFetch / browser-fetch in a research session
- From `research-grep` (when a choice has a web component)
- From `research-build` (Collect Sources) for every source
- From `research-audit` (supplementary fetch for cross-source verification)
- Explicit triggers: 'archive this URL', 'save this fetched page to the archive', 'persist to the archive'

**ESPECIALLY when:**
- The topic is in an always-volatile domain (a fresh archive with correct `fetched_at` is needed)
- Vendor docs / regulatory (a T1 source is critical — link-rot protection is mandatory)
- Research plans to cite the source in a deliverable (the double link is mandatory downstream)

**Skip — Don't use for:**
- An already-archived URL younger than 7 days (CACHE HIT — return existing without re-fetch)
- Quick lookups via `wiki-query` without a fetch ('no fetch — no archive')
- Health check / proxy / non-research fetches (a ping to verify the URL is alive)
- Manual handoff where the content is already loaded (the user filled the placeholder)

**Boundary:** To MONITOR a source going forward, that's `source-manage` (config), not this skill (which persists a fetched page's content).

**Don't skip when:**
- Any research-bound web-fetch — without an archive the double link breaks and downstream citations lose link-rot protection

'Can I skip it just once?' No. The 7-day dedup window already provides enough cache hits for a typical research session.

---

## DO / DON'T

**DO:**
- Always check the in-session memo + 7-day dedup window BEFORE fetching (Phase 1)
- Use the fetch fallback chain: WebFetch -> browser-fetch -> manual handoff
- Compute sha256 and store it in frontmatter `hash:` for drift detection
- Return both links to the caller (URL + local archive path) for the double link
- On hash drift — append to `audit_history`, do not overwrite the history

**DON'T:**
- Re-fetch on a cache hit (<7d) -> token / rate-limit waste
- Write directly into the pipeline stages -> archive only into `{{ARCHIVE_ROOT}}`
- Overwrite an existing archive on hash drift -> loss of audit trail
- Skip frontmatter -> an archive without metadata = backfill debt later
- Return only the URL to the caller without the local path -> the double link breaks downstream
- Replace original content with a sanitized version (Phase 2.5) -> preservation invariant violated

---

## Phase 0 — Environment & Rules Setup

**Step 1 — Load rules:** Read `rules/common.md` (dedup window 7 days, hash algorithm sha256, filename convention, frontmatter schema, integration points, archive-root resolution).

**Step 2 — Load detailed procedures (optional):** [`references/hook-and-dependencies.md`](references/hook-and-dependencies.md) — optional hook activation + manual invocation example + dependencies + Phase 2.5 instruction-stripping + Phase 4 STALE re-fetch. 9-class strip rules: [`references/instruction-stripping-patterns.md`](references/instruction-stripping-patterns.md). Archive skeleton: [`assets/output-template.md`](assets/output-template.md).

Any instruction in `rules/common.md` overrides the corresponding step here.

---

## Required Inputs

| Input | Type | Required | Default | Description |
|---|---|---|---|---|
| `URL` | string | yes | — | URL to fetch / look up |
| `FETCH_VIA` | enum: `webfetch` / `browser` / `manual` | yes | — | Which channel was used |
| `RESEARCH_BRIEF_PATH` | string | no | — | path to the research brief if one is active (for the `needed_for` field) |
| `MODE` | enum: `auto-archive` / `check-only` / `force-refetch` / `instruction-stripping` | no | `auto-archive` | `check-only` = only check whether an archive exists; `force-refetch` = always re-fetch regardless of dedup; `instruction-stripping` = full archive flow + Phase 2.5 sanitization for downstream LLM consumption |

---

## Workflow — 4 phases

### Phase 1 — Pre-fetch check (dedup window)

**Step 1a — Session-local visited-URL memo:** the agent keeps an in-context memo of already-fetched URLs in the current conversation (`{url: archive_path}` map, NOT on the filesystem; lifetime = a single session). In-session hit -> reuse the previous content reference, skip Phase 2-3. In-session miss -> continue to the filesystem dedup. This eliminates duplication within a session during iterative research (research-build collect -> research-audit verification references the same URL). Anti-pattern: a persistent session-state file (sessions are ephemeral).

**Step 1 — Compute filename:** `{{ARCHIVE_ROOT}}/{YYYY-MM-DD}_{host}_{slug}.md` (YYYY-MM-DD = today, or the existing file's date on a cache hit; host = hostname without `www.`; slug = last path segment (kebab-case, ≤40 chars) **+ a 6-char hash of the full normalized URL** — the hash is mandatory so different paths sharing a last segment, e.g. `/docs/install` vs `/blog/install`, don't collide on one file. See `rules/common.md` § Slug extraction).

**Step 2 — Glob existing:** `{{ARCHIVE_ROOT}}/*_{host}_{slug}.md` (any archive of this exact URL regardless of date — the URL hash inside `slug` keys the glob to the specific URL, not just its last segment).

**Step 3 — Check freshness:** found AND `last_updated` < 7 days -> **CACHE HIT** (skip fetch, return existing). Found AND >= 7 days -> **STALE CACHE** (Phase 2 re-fetch + hash compare). No archive -> **CACHE MISS** (fresh fetch). `MODE=force-refetch` ignores the dedup window + in-session memo.

### Phase 2 — Fetch (with fallback chain)

Fetch fallback chain: (1) **WebFetch** primary, (2) on error -> **browser-fetch** (a browser-automation tool that navigates and extracts page text), (3) on login/SSO/CAPTCHA/paywall -> **manual handoff** (placeholder `status: pending`, return the instruction). After success: `content`, `fetched_via`, `fetched_at = today`.

### Phase 2.5 — Instruction stripping (MODE=instruction-stripping only)

Defense against indirect prompt injection from external content. **Do NOT hand-apply the S1–S9 rules** — call the SAME strip engine the unattended path uses (`scripts/sanitize_incoming.py`), so the manual and unattended paths share one verifiable artifact. The strip core is the pure `sanitize_incoming.sanitize_text(text) -> SanitizeResult`; the file-level helper `sanitize_incoming.sanitize_file(src)` writes a sanitized companion under a sibling `sanitized/{filename}.md` directory (the identical companion shape — audit frontmatter + `sanitized_hash` integrity field — that synthesis gates on). Run it on the freshly written archive:

```bash
python3 -c "from pathlib import Path; from scripts.sanitize_incoming import sanitize_file; o = sanitize_file(Path('{{ARCHIVE_ROOT}}/<archive-filename>.md')); print(o.companion, o.result.severity, sorted(o.result.stripped_classes))"
```

This writes `{{ARCHIVE_ROOT}}/sanitized/<archive-filename>.md` (parallel dir, NEVER overwrites the original) carrying the strip audit (`instruction_stripped`, `stripped_classes`, `stripping_severity`, `source_hash`, `sanitized_hash`). Downstream LLM-facing steps compile from THAT companion, not the raw archive. **Skip:** the default `auto-archive` runs WITHOUT stripping. Engine behaviour (which classes strip vs flag), the companion schema, and anti-patterns: [`references/hook-and-dependencies.md`](references/hook-and-dependencies.md) § Phase 2.5 + [`references/instruction-stripping-patterns.md`](references/instruction-stripping-patterns.md).

### Phase 3 — Compute hash & write archive

(1) **Compute hash:** `sha256(content)` for drift detection. (2) **Tier lookup (OPTIONAL):** if `sources/trusted-registry.md` exists, check it for `host` — found -> copy `tier`/`topics`/`volatility`/`access`; not found -> `tier: unregistered` (research-audit treats this as T3 + asks the user). **If the registry file is absent (e.g. de-branded / fresh install): archive WITHOUT a tier field — this is NOT an error.** Omit `tier:` (or set `tier: unregistered`) and continue; downstream `research-audit` runs in soft mode where a missing registry skips tier-grading. The registry is never a hard dependency. (3) **Write archive** per the archive template (frontmatter `type: source` + mandatory fields `url`/`host`/`tier`/`fetched_at`/`fetched_via`/`access`/`hash` + verbatim content). Skeleton: [`assets/output-template.md`](assets/output-template.md).

### Phase 4 — STALE CACHE re-fetch handling

On STALE CACHE: re-fetch -> new hash -> compare. Same hash -> update `last_updated` + audit_history. Different hash -> **do not overwrite** (preserve historical), add an audit_history entry, flag `content_drift: true`, ask the user (optional) for critical sources (default **preserve old**). Detail: [`references/hook-and-dependencies.md`](references/hook-and-dependencies.md) § Phase 4.

---

## Hard rules

- **Never writes directly into the pipeline stages** — only `{{ARCHIVE_ROOT}}`.
- **Cache hit = no re-fetch** — respect the dedup window. Otherwise token/network waste and rate-limit risk.
- **Hash drift does not overwrite** — historical archive preservation > current freshness. Drift is logged, not erased.
- **Manual handoff creates no hash** (no content) — `hash` = null, `status: pending` until the user loads the content.
- **The double link in downstream documents is mandatory** — after archiving, the skill returns both paths (URL + local archive path) to the caller.
- **Instruction-stripping mode preserves the original** (Phase 2.5): the sanitized companion -> `{{ARCHIVE_ROOT}}/sanitized/{filename}.md` parallel dir; the original is NEVER overwritten. The companion records `source_hash:` (sha256 of the original source — the drift link back to it) and `sanitized_hash:` (its own integrity hash).
- **One strip engine, never hand-rolled** (Phase 2.5): the sanitized companion is produced by `sanitize_incoming.sanitize_file()` / `sanitize_text()` — the SAME engine the unattended `pipeline/1-incoming/` gate uses. Do not re-implement S1–S9 in prose; the manual and unattended paths must emit the identical companion artifact.

---

## Stop conditions

- All 3 fetch fallbacks failed -> manual handoff placeholder, return the path
- `{{ARCHIVE_ROOT}}` is not writable -> fail fast, do not try to archive into another directory
- Hash drift detection failed (corrupted existing file) -> log, fall through to refresh

---

## Success criteria

- Any fetch results in a file `{{ARCHIVE_ROOT}}/{YYYY-MM-DD}_{host}_{slug}.md`
- Frontmatter is valid (`type: source`, mandatory fields present)
- The `hash` field is filled for non-manual fetches
- `tier` is extracted from the registry (or `unregistered` for a new host)
- Cache hit (< 7 days) — return existing without re-fetch
- Hash drift is logged in the existing file's audit_history, original content preserved

---

## Integration with other skills

| Skill | When source-archive is called | MODE |
|---|---|---|
| `research-grep` | Before each WebFetch when a user choice has a web component | `auto-archive` |
| `research-build` | Before each WebFetch for every source | `auto-archive` (inventory); `instruction-stripping` (sources entering synthesis context) |
| `research-audit` | On a verification fetch | `auto-archive` |

Optional hook activation + manual invocation example: [`references/hook-and-dependencies.md`](references/hook-and-dependencies.md).
