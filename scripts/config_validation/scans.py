from __future__ import annotations

import re
from pathlib import Path

# --------------------------------------------------------------------------- #
# Placeholder detection (non-fatal)
# --------------------------------------------------------------------------- #

# Template-leftover signals: the canonical `# EXAMPLE — replace` row marker, the
# shipped example domains, and the unfilled `**Updated:**` date. Deliberately NOT
# a bare `EXAMPLE` — that matched shipped DOCUMENTATION subdomains (e.g. the
# "feed URL shapes" reference's `EXAMPLE.substack.com`), which stay even in a
# fully-configured instance and so warned forever (false positive).
PLACEHOLDER_PATTERN = re.compile(r"EXAMPLE — replace|example\.com|example\.org|YYYY-MM-DD")


def _strip_comments_for_scan(text: str, name: str) -> str:
    """Drop comments so placeholder detection sees real config CONTENT only.

    Shipped configs carry documentation comments (e.g. `# e.g. ["you@example.com"]`)
    that contain the placeholder pattern yet remain even in a fully-configured
    instance — matching them would WARN forever. YAML `#` line-comments (a `#` that
    begins a line or follows whitespace, the YAML rule) and Markdown `<!-- … -->`
    comments are removed; a real placeholder VALUE (in a table row / YAML value) is
    left intact and still flagged."""
    if name.endswith((".yaml", ".yml")):
        out = []
        for line in text.splitlines():
            cut = None
            for i, ch in enumerate(line):
                if ch == "#" and (i == 0 or line[i - 1] in " \t"):
                    cut = i
                    break
            out.append(line if cut is None else line[:cut])
        return "\n".join(out)
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def detect_placeholders(config_dir: Path) -> list[str]:
    """Return per-file notes where EXAMPLE placeholders are still present.

    Only the ACTIVE config format counts: a legacy sources.md/topics.md whose
    YAML twin exists is a frozen fallback (CONVENTIONS §2.3) that keeps its
    template markers forever — flagging it would WARN a fully-configured,
    migrated install for the rest of its life.
    """
    notes = []
    for name in (
        "sources.md",
        "topics.md",
        "sources.yaml",
        "topics.yaml",
        "channels.yaml",
        "schedule.yaml",
    ):
        path = config_dir / name
        if not path.exists():
            continue
        if name.endswith(".md") and path.with_suffix(".yaml").exists():
            continue  # dormant legacy fallback — the YAML twin is the config
        content = _strip_comments_for_scan(path.read_text(encoding="utf-8"), name)
        if PLACEHOLDER_PATTERN.search(content):
            notes.append(name)
    return notes


# --------------------------------------------------------------------------- #
# Inline-secret detection (fatal — CONVENTIONS §8)
# --------------------------------------------------------------------------- #

# A secret-bearing key (token / password / webhook / api_key / api-key) whose
# value is a long literal (>=16 chars of token-ish characters) — i.e. a real
# secret pasted inline instead of a `*_env: NAME` reference.
SECRET_LEAK_PATTERN = re.compile(
    r"(token|password|webhook|api[_-]?key)[^:=]*[:=]\s*['\"]?([A-Za-z0-9_\-:./]{16,})",
    re.IGNORECASE,
)

# Lines that only declare an env-var NAME (the sanctioned form) are allowed:
# the key ends in `_env` and its value is a bare env-var identifier. The name may
# be ANY case (`SMTP_PASSWORD`, `my_smtp_password`, `My_Mixed_Case_User`).
# To still catch a real token pasted onto a `*_env:` key (a token is also bare
# letters/digits/underscores, e.g. `ghp_16CharsTokenValueHere`), the value must
# look like underscore-separated WORDS: each segment ≤ 20 alphanumerics. Real
# env-var names are short words; tokens carry a long unbroken base62/hex run that
# exceeds this, so they fall through to SECRET_LEAK_PATTERN.
SECRET_ENV_REF_PATTERN = re.compile(
    r"\b[A-Za-z0-9_]*_env\s*[:=]\s*[A-Za-z0-9]{1,20}(?:_[A-Za-z0-9]{1,20})*\s*$",
)


def detect_inline_secrets(config_dir: Path) -> list[str]:
    """Return errors for config files that paste a real secret inline.

    A secret-shaped key whose value is a long literal token is flagged, unless
    the line is the sanctioned `*_env: NAME` env-var reference (CONVENTIONS §8).
    """
    errors = []
    # search.yaml / research.yaml are the optional provider-config files where a
    # Tavily/Perplexity api_key would plausibly be pasted (CONVENTIONS §8) — scan
    # them too. Missing files are skipped below, so optional files are safe.
    for name in (
        "channels.yaml",
        "schedule.yaml",
        "sources.md",
        "topics.md",
        "sources.yaml",
        "topics.yaml",
        "search.yaml",
        "research.yaml",
    ):
        path = config_dir / name
        if not path.exists():
            continue
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.split("#", 1)[0].rstrip()  # ignore trailing comments
            if not line.strip():
                continue
            # The `*_env: NAME` reference is the allowed way to name a secret.
            if SECRET_ENV_REF_PATTERN.search(line):
                continue
            if SECRET_LEAK_PATTERN.search(line):
                errors.append(
                    f"{name}:{lineno}: looks like an inline secret — store it in "
                    f".env and reference it via a `*_env: NAME` key (CONVENTIONS §8)"
                )
    return errors


