# source-archive — Common Rules

Platform-agnostic rules. SKILL.md references this file in Phase 0.

---

## Paths

The archive root is **config-derived**, not hardcoded. Resolution order:

1. If `config/sources.yaml` declares an archive root, use it.
2. Otherwise default to `pipeline/0-archive/`.

This file writes the resolved root as `{{ARCHIVE_ROOT}}`. All paths are relative to the project root (`{{VAULT_ROOT}}`); never absolute.

- **Archive root:** `{{ARCHIVE_ROOT}}` (default `pipeline/0-archive/`)
- **Filename pattern:** `{{ARCHIVE_ROOT}}/{YYYY-MM-DD}_{host}_{slug}.md`
- **Sanitized companions:** `{{ARCHIVE_ROOT}}/sanitized/{filename}.md`
- **Manual handoff pattern:** `{{ARCHIVE_ROOT}}/{YYYY-MM-DD}_{host}_MANUAL.md`
- **Trusted registry:** `sources/trusted-registry.md` (OPTIONAL — for tier lookup; if absent, archive without a tier field, no error. Per `docs/CONVENTIONS.md` §10)
- **Always-volatile domains:** `sources/always-volatile-domains.md` (OPTIONAL — for recency override; if absent, use the default 7-day dedup window)
- **Article template:** `assets/output-template.md`

---

## Filename construction

### Host extraction

```
URL  = "https://docs.example.com/guides/quickstart"
host = "docs.example.com"               # no protocol, no www. prefix
```

If the URL contains `www.` — strip it. If a subdomain matters (e.g. `blog.example.com` vs `docs.example.com`) — preserve it.

### Slug extraction

```
URL path     = "/guides/quickstart"
last_segment = "quickstart"
url_hash     = sha256(normalized_url)[:6]   # e.g. "a1b2c3" — over the FULL normalized URL
slug         = "quickstart-a1b2c3"          # last-segment (kebab-case, ≤40 chars) + "-" + url_hash
```

If the last segment is empty (URL ends with `/`) -> use the second-to-last segment.

**Always append the 6-char `url_hash`** (a hash of the full normalized URL, per
`scripts/normalize_url.py`). The last path segment alone is NOT unique — `/docs/install`
and `/blog/install` share the segment `install` and would otherwise collide on one archive
file (the second silently skipped as a cache hit). The hash disambiguates different paths
that share a last segment. If the segment itself exceeds 40 chars, truncate it to 40 BEFORE
appending the hash:

```
"/docs/install"  -> "install-a1b2c3"
"/blog/install"  -> "install-d4e5f6"     # different hash -> no collision
"how-to-build-a-cross-platform-agent-with-a-tool-and-a-runtime" -> "how-to-build-a-cross-platform-agent-with-9f8e7d"
```

### Date

`YYYY-MM-DD` today's date at creation. **On re-fetch** (STALE CACHE) — the date in the filename stays the **original** (when the archive was first created); only `last_updated` in frontmatter is updated. This matters for the audit trail — the file path = when we first saw this source.

---

## Dedup window — 7 days

Cache hit threshold: **7 days**.

Rationale:
- 7 days covers a typical research-session timeframe
- Long enough to avoid multiple re-fetches in a single week
- Short enough not to miss fresh changes (an alternative — 14 days — is too long for volatile sources)

Override:
- `MODE=force-refetch` — ignore the window
- An always-volatile host (per `sources/trusted-registry.md` column `volatility=volatile`, **if the registry exists**) -> **3 days** instead of 7. If the registry is absent, this override simply does not apply — the default 7-day window stands.

---

## Hash algorithm

**SHA-256** of UTF-8 encoded content.

Format in frontmatter: `hash: sha256:{hex}` (64 hex chars).

Applied to the **full content** of the file after fetch — verbatim text without the markdown frontmatter (frontmatter is added after the hash is computed).

Drift detection threshold:
- Exact match -> unchanged
- Any difference -> DRIFT (even whitespace) — preserve old + log an audit_history entry

---

## Tier lookup logic (OPTIONAL — registry absence is not an error)

```
0. If sources/trusted-registry.md does NOT exist:
   - Skip tier lookup entirely. Archive WITHOUT a tier field (omit `tier:`, or set
     `tier: unregistered`). This is NOT an error — continue the archive write.
   - Do NOT ask the user to register (there is no registry to append to).
   - Downstream research-audit runs in soft mode (missing registry → tier-grading skipped).
1. Read sources/trusted-registry.md
2. Find the row matching host (exact match)
3. If found:
   - Copy tier, topics, volatility, access fields into the archive frontmatter
4. If NOT found:
   - tier: unregistered
   - access: webfetch (assumption — verify if it fails)
   - Ask the user (after a successful archive): "New host {host} — add it to the registry? Tier?"
     - Options: T1 / T2 / T3 / Skip (leave unregistered)
     - On T1/T2/T3 — append a row to sources/trusted-registry.md
```

---

## Frontmatter mandatory fields for type:source

- `title` (extract from `<title>` or `<h1>` content)
- `type: source`
- `status: active` (or `pending` for manual handoff)
- `created`, `last_updated` (today)
- `topic_tags` (copy from the registry topics field, or infer from content)
- `url`, `host`, `fetched_at`, `fetched_via`, `hash`, `access`
- `tier` — mandatory **only when a `sources/trusted-registry.md` exists**. If the registry is absent, `tier` is omitted (or `tier: unregistered`) and the archive is still valid (per `docs/CONVENTIONS.md` §10).

Optional:
- `author`, `published` — extract from `<meta>` if available
- `needed_for` — path to the research brief if one is active in the current session

---

## Audit history schema

On re-fetch / drift:

```yaml
audit_history:
  - date: 2026-05-02
    by: source-archive
    result: "re-fetched, hash unchanged"
  - date: 2026-05-09
    by: source-archive
    result: "re-fetched, hash changed (content drift); old version preserved"
    drift_details: "section X added; pricing values updated"
```

`drift_details` — optional, filled only when there is an obvious structural diff (a section added/removed). A detailed line-by-line diff is not needed — the old file is preserved and can be inspected.

---

## Manual handoff details

On a login wall / SSO / CAPTCHA / paywall block:

1. Create a placeholder `{{ARCHIVE_ROOT}}/{YYYY-MM-DD}_{host}_MANUAL.md` with frontmatter:
   ```yaml
   ---
   title: "(pending) {URL or guessed title}"
   type: source
   status: pending
   created: 2026-05-02
   last_updated: 2026-05-29

   url: "https://..."
   host: ...
   tier: unregistered
   fetched_via: manual
   access: manual
   needed_for: "{path to the research brief or artifact slug}"

   hash: null                          # no content yet
   ---
   ```
2. File body:
   ```
   # PENDING manual handoff

   **Block reason:** login wall / SSO / CAPTCHA / paywall (choose one)

   **Action required from the user:**
   1. Open the URL in a browser
   2. Authenticate / dismiss the block
   3. Copy the page content
   4. Paste it under the "## Content" section below
   5. Update frontmatter: `status: active`, `fetched_at: {today}`, compute the hash via `shasum -a 256`

   ## Content

   (PENDING — to be filled by the user)
   ```
3. A reference to the placeholder goes into `research-brief.md` (if any) and/or `verification-log.md`
4. The skill returns the placeholder path to the caller + flag `manual_handoff_pending: true`

---

## Caller integration

### Pattern for research-grep / research-build

```python
# Pseudo-code for a manual archive call (where no automatic hook exists)

def fetch_with_archive(url, brief_path=None):
    # Phase 1 — pre-fetch check
    existing = glob(f"{ARCHIVE_ROOT}/*_{host}_{slug}.md")
    if existing and age(existing[0]) < 7_days:
        return read(existing[0])  # CACHE HIT

    # Phase 2 — fetch
    try:
        content = WebFetch(url)
        fetched_via = "webfetch"
    except FetchError:
        try:
            content = browser_fetch(url)
            fetched_via = "browser"
        except FetchError:
            return create_manual_placeholder(url, brief_path)

    # Phase 3 — write archive
    hash = sha256(content)
    tier = lookup_registry(host)
    archive_path = write_archive(url, content, hash, tier, fetched_via, brief_path)

    return {"url": url, "local_archive": archive_path, "content": content}
```

### Double link for downstream

After archiving — the caller receives both paths and **must** include both in any citations in downstream documents:

```markdown
According to the vendor docs[^1] [(local copy)][^1-local], a skill description should be <= 500 words.

[^1]: https://docs.example.com/guides/skills
[^1-local]: pipeline/0-archive/2026-05-02_docs.example.com_skills.md
```

Within the Obsidian vault, the local copy can also be referenced as a `[[wikilink]]` so it shows up in the graph view and backlinks.

---

## Anti-pattern guards

- **Do not overwrite an existing file on drift** — preserve the old version, log it in audit_history.
- **Do not ignore `tier: unregistered`** — it must trigger a question to add the source.
- **Do not store secrets** — if the URL contains API keys / tokens / signed params, strip them before archiving (or do not archive at all — return an error).
