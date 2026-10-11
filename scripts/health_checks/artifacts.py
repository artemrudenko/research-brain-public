"""Health signals derived from on-disk pipeline artifacts."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts import state
from scripts.brain_status import monitored_sources
from scripts.delivery import quiet, receipts
from scripts.registry import iter_registry_rows

# Digest delivery channels that count for the built-but-undelivered signal —
# mirrors the channel set the dispatcher owns (`alerts:` is not a digest channel).
_DIGEST_CHANNELS = ("email", "telegram", "rocketchat")


def registry_last_collected(root: Path) -> dict[str, date]:
    """Map category to its newest collected date from `pipeline/registry.md`."""
    newest: dict[str, date] = {}
    for row in iter_registry_rows(root / "pipeline" / "registry.md"):
        try:
            collected = date.fromisoformat(row.collected)
        except ValueError:
            continue
        if not row.category:
            continue
        if row.category not in newest or collected > newest[row.category]:
            newest[row.category] = collected
    return newest


def stale_feeds(root: Path, *, today: date, window: int) -> list[str]:
    """Monitored categories whose newest registry collection is older than `window`."""
    last_collected = registry_last_collected(root)
    if not last_collected:
        return []
    stale: list[str] = []
    seen: set[str] = set()
    for src in monitored_sources(root=root):
        category = src.category
        if category in seen or category not in last_collected:
            continue
        seen.add(category)
        if (today - last_collected[category]).days > window:
            stale.append(category)
    return stale


def _newest_digest(root: Path, *, today: date) -> tuple[Path, date] | None:
    """The newest dated `digest_YYYY-MM-DD.md` (future-dated files ignored)."""
    synthesis = root / "pipeline" / "3-synthesis"
    if not synthesis.exists():
        return None
    newest: tuple[Path, date] | None = None
    for path in synthesis.glob("digest_*.md"):
        stamp = path.stem[len("digest_"):]
        try:
            parsed = date.fromisoformat(stamp)
        except ValueError:
            continue
        if parsed > today:
            continue
        if newest is None or parsed > newest[1]:
            newest = (path, parsed)
    return newest


def last_digest_age_days(root: Path, *, today: date) -> int | None:
    """Days since the newest `digest_YYYY-MM-DD.md`, or None when none exist."""
    newest = _newest_digest(root, today=today)
    return None if newest is None else (today - newest[1]).days


def _any_digest_channel_enabled(root: Path) -> bool:
    """True when `config/channels.yaml` enables at least one digest channel.

    Deliberately conservative on ANY read/parse problem (missing file, no
    PyYAML, malformed YAML): a config we cannot read must not raise a delivery
    alarm — the config validator, not the health view, owns reporting that.
    """
    channels_path = root / "config" / "channels.yaml"
    try:
        import yaml

        data = yaml.safe_load(channels_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — unreadable config -> no alarm, by design  # nosec B110
        return False
    delivery = data.get("delivery") if isinstance(data, dict) else None
    if not isinstance(delivery, dict):
        return False
    for name in _DIGEST_CHANNELS:
        channel = delivery.get(name)
        if isinstance(channel, dict) and channel.get("enabled") is True:
            return True
    return False


def undelivered_digest(root: Path, *, today: date, window: int) -> str | None:
    """Stem of the newest digest that nobody received, past a grace `window`.

    The last-mile blind spot: a digest can be BUILT every week while delivery
    silently dies — the on-disk file keeps `last_digest_age_days` fresh, so the
    stale-digest trigger never fires (live-observed for 13 days). This signal
    reads the delivery receipts: the newest non-quiet digest, older than
    `window` days, with delivery enabled and no channel receipt in status
    `sent`, is a failure the user must hear about.

    Quiet digests are exempt (deliberately never sent), as is a config with no
    enabled channel (building locally is a legitimate workflow).
    """
    newest = _newest_digest(root, today=today)
    if newest is None:
        return None
    path, stamp = newest
    if (today - stamp).days <= window:
        return None  # still inside the delivery grace window
    if not _any_digest_channel_enabled(root):
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if quiet.is_quiet_digest(text):
        return None
    receipt_dir = state.state_root(
        root / "pipeline" / "3-synthesis" / ".delivered", project_root=root
    )
    receipt = receipts.load_receipt(receipt_dir / f"{path.stem}.json")
    if any(entry.get("status") == "sent" for entry in receipt.values()):
        return None
    return path.stem


__all__ = [
    "last_digest_age_days",
    "registry_last_collected",
    "stale_feeds",
]
