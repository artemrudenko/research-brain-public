from __future__ import annotations

import urllib.error
from collections.abc import Callable, Iterable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# rot silently with no signal until a collect run comes back empty. `--check-feeds`
# probes each URL so a dead feed surfaces at setup.
# --------------------------------------------------------------------------- #

# A liveness probe: given a URL, fetch it (return body) or raise on any failure.
FetchFn = Callable[[str], str]


def extract_source_urls(sources_path: Path) -> list[str]:
    """Return the enabled http(s) source URLs from the sources config, either format.

    A `.yaml` path parses as the schema-2 shape via the shared store loader (a
    malformed file yields no URLs — the schema validator reports the loud error
    before liveness probing ever runs). The legacy markdown path scans table
    rows: only real data rows carry a URL in the first cell, so the header, the
    dash separator, and the shipped `| full URL | … |` template placeholder row
    all fall out naturally (none starts with http). In both formats a disabled
    feed is skipped — it must not raise a dead-feed warning."""
    if not sources_path.exists():
        return []
    if sources_path.suffix in (".yaml", ".yml"):
        from scripts.sources import store  # noqa: PLC0415 — lazy, keeps import light

        try:
            categories = store.load_categories(sources_path)
        except (ValueError, RuntimeError):
            return []
        return [s.url for c in categories for s in c.sources if s.active]
    urls: list[str] = []
    for line in sources_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        url = cells[0] if cells else ""
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        # Active is the last column in the documented layout; an explicit `no`
        # disables the feed. A missing/other value fails open (still probed).
        if len(cells) >= 6 and cells[-1].strip().lower() == "no":
            continue
        urls.append(url)
    return urls


def _default_fetch(url: str) -> str:
    """Probe via the collector's SSRF-guarded fetch (imported lazily so the common
    schema-only path never pulls in the collector)."""
    # Lazy on purpose: the schema-only path never pulls in the collector. The
    # package root is importable in every supported flow (installed venv, or a
    # CLI entry's own prelude on a zero-install direct run).
    from scripts import collect  # noqa: PLC0415 — intentional lazy import

    return collect.fetch(url)


def check_feed_liveness(urls: Iterable[str], *, fetch: FetchFn | None = None) -> list[str]:
    """Probe each URL and return one WARN line per unreachable feed.

    Best-effort and injectable: `fetch` defaults to the SSRF-guarded collector
    fetch, but tests pass a fake so no network is touched. Any failure (DNS,
    timeout, HTTP error, SSRF refusal) marks the feed unreachable — advisory only,
    never a schema failure, since network flakiness must not fail the gate."""
    probe = fetch if fetch is not None else _default_fetch
    warnings: list[str] = []
    for url in urls:
        try:
            probe(url)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            warnings.append(f"{url}: unreachable ({exc})")
    return warnings


