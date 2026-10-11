---
title: "Instruction-stripping patterns (prompt-injection mitigation)"
type: reference
domain: meta-process
status: active
created: 2026-05-10
last_updated: 2026-06-15
parent_skill: source-archive
---

# Instruction-stripping patterns

> Reference checklist for `source-archive mode=instruction-stripping`. Applied when archived content will be consumed downstream as LLM context (research-build / research-grep / wiki-ingest / long-running multi-session work). Defense layer against indirect prompt injection (the LLM01 risk class) inherited from retrieved content.

The archive root is config-derived (default `pipeline/0-archive/`); written as `{{ARCHIVE_ROOT}}` below.

**Principle:** **'retrieved content is untrusted — indirect prompt injection is the most under-estimated vector'**.

---

## 9 stripping classes

| # | Class | Pattern (regex / heuristic) | Action | Severity |
|---|---|---|---|---|
| **S1** | System-prompt mimicry | `(?i)(you are now|ignore (previous|all) instructions|disregard (above|prior)|new instructions:|from now on you are|forget (everything|all) (you|previous)|act as (an? )?(?:admin|root|system))` | Replace span with placeholder `[STRIPPED:S1]` | critical |
| **S2** | Delimiter injection | `(?i)(<\|im_start\|>|<\|im_end\|>|---END SYSTEM---|---END PROMPT---|<system>|</system>|<user>|</user>|<assistant>|</assistant>)` | Strip span entirely | critical |
| **S3** | Universal jailbreak | `(?i)(summarize (all of )?the above( in bullet points)?|reveal your (instructions|system prompt)|what are your (instructions|guidelines)|repeat (your )?(instructions|system prompt))` | Replace with `[STRIPPED:S3]` | critical |
| **S4** | Role-switching | `(?i)(pretend (to be|that you are)|act as (an? )?[a-z]+|simulate (an? )?[a-z]+|you('re| are) now (an? )?[a-z]+|imagine you are)` | Flag for review (medium FP rate — false positive on legitimate role-play research content) | medium |
| **S5** | Markdown image exfiltration | `!\[[^\]]*\]\(https?://[^\)]+\?[^\)]*\{[^}]+\}[^\)]*\)` (image with templated URL containing braces) | Strip entire image markdown | critical |
| **S6** | External URL with templated query | `https?://[^\s]+\?[^&\s]*\{[^}]+\}` (URL containing `{template}` placeholders) | Replace URL with `[STRIPPED-URL:S6]` | critical |
| **S7** | Shell/code injection patterns | `(?i)(os\.system\(|subprocess\.|exec\(|eval\(|\|\s*sh\b|\|\s*bash\b|; ?(rm|cat|curl|wget) )` in the content body (not in legitimate code blocks) | Flag for review; strip if outside fenced code | medium |
| **S8** | Multi-turn drift starters | `(?i)(first,? agree (that|to)|building on (your )?previous|continuing from (where|our)|as (we|you) (just )?discussed|remember when (you|we))` | Replace span with `[STRIPPED:S8]` (mild — may be legitimate continuation in a research narrative) | informational |
| **S9** | Hidden invisible characters | `[‮​-‏⁠﻿]` (RTL override, zero-width chars) | Strip silently | critical |

---

## Application logic

```
Input: raw content from {{ARCHIVE_ROOT}}/{date}_{host}_{slug}.md (post-Phase 3 write)
Output: sanitized version + audit-trail of stripped spans

Algorithm:
  1. Apply S1, S2, S3, S5, S6, S9 (critical) — mandatory strip
  2. Apply S4, S7 (medium) — flag for review, strip only if confidence is high
  3. Apply S8 (informational) — log only, don't strip (high false-positive rate)

  4. Output structure:
     - sanitized content -> {{ARCHIVE_ROOT}}/sanitized/{same-filename}.md
     - audit log -> companion frontmatter additions (written by sanitize_incoming.py):
         instruction_stripped: true
         stripped_at: 2026-05-10T12:34:56Z
         source_hash: {sha256 of the original source file}
         sanitized_hash: {sha256 of the whole companion, self-field neutralized}
         stripped_classes: [S1, S5, S9]          # STRIPPED classes only — flagged-not-stripped (S4/S7/S8) are NOT listed
         stripping_severity: critical | medium | clean
```

---

## Decision matrix: when to strip vs preserve

| Use case | Action |
|---|---|
| Research-build fetch (planned synthesis) | **STRIP** — content will be consumed by the LLM during synthesis (active injection risk) |
| Hash drift check (re-fetch only) | **NO STRIP** — only hash verification, no content consumption by the LLM |
| Quick-lookup web supplement (factual answer) | **NO STRIP** — short read, low injection surface |
| Long-running multi-session work | **STRIP MANDATORY** — a long-running session is the greatest exposure window |
| Manual handoff placeholder (no content yet) | **N/A** — no content to strip |

---

## Anti-patterns

- **Aggressive stripping without preservation:** the original content is always preserved and linked from the sanitized companion frontmatter via `source_hash:` (the sha256 of the original source); the sanitized version is a companion, not a replacement.
- **Stripping S8 by default:** multi-turn drift starters appear in legitimate research narrative ('Building on previous research, ...') — a high false-positive rate makes default-strip counterproductive.
- **Treating the sanitized version as 'safe forever':** new attack patterns emerge; re-run stripping when the threat model is updated.
- **Skipping stripping for 'trusted' T1 sources:** indirect injection means even T1 vendor docs can be hijacked if an adversary controls a path (DNS, CDN, doc edit).

---

## Cross-references

- `brain/concepts/llm-defense-patterns.md` — full LLM-security defense theory (if present in the vault)
- `sources/trusted-registry.md` — source tier registry consulted in Phase 3

---

## Change log

| Date | What | Trigger |
|---|---|---|
| 2026-05-10 | Created the instruction-stripping patterns reference. 9 stripping classes (S1-S9) with regex/heuristic + severity + action. Decision matrix for when to strip. | Initial authoring |
