"""Plain-language health report rendering."""

from __future__ import annotations

from scripts.health_checks.model import HealthSummary, Status
from scripts.health_checks.signals import FAILURE_STATUSES

STATUS_BANNER: dict[Status, str] = {
    Status.OK: "✅ System health: OK",
    Status.DEGRADED: "⚠️ System health: DEGRADED — needs attention",
    Status.UNKNOWN: "❓ System health: UNKNOWN — configured but never ran",
    Status.UNCONFIGURED: "⚙️ System health: UNCONFIGURED — no sources set up yet",
}


def render(summary: HealthSummary, *, stale_feed_days: int) -> str:
    """A plain-language, marker-prefixed health report."""
    lines: list[str] = []
    lines.append(STATUS_BANNER[summary.status])

    if summary.last_digest_age_days is None:
        lines.append("• Digest: none produced yet.")
    else:
        marker = "⚠️" if summary.digest_stale else "•"
        plural = "" if summary.last_digest_age_days == 1 else "s"
        lines.append(
            f"{marker} Last digest: {summary.last_digest_age_days} day{plural} ago"
            + (" (stale — expected weekly)" if summary.digest_stale else "")
        )
        if summary.digest_stale:
            lines.append("  Next action: run the pipeline now.")

    if summary.undelivered_digest:
        lines.append(
            f"❌ Digest built but never delivered: {summary.undelivered_digest}.md "
            "— no channel has a `sent` receipt"
        )
        lines.append(
            "  Next action: send it — python3 scripts/delivery/deliver.py "
            f"pipeline/3-synthesis/{summary.undelivered_digest}.md "
            '(or say "send the digest").'
        )

    if summary.delivery:
        for channel, status in sorted(summary.delivery.items()):
            marker = "❌" if status in FAILURE_STATUSES else "•"
            lines.append(f"{marker} Delivery [{channel}]: {status}")
            if status == "skipped-mcp-only":
                lines.append(
                    "  Next action: this channel is MCP-only, so headless runs "
                    "deliver nothing — send via the agent (digest-deliver skill) "
                    "or switch it to smtp / bot-api in config/channels.yaml."
                )
            elif status in FAILURE_STATUSES:
                lines.append(
                    "  Next action: fix the channel configuration or secret, then rerun "
                    "python3 scripts/delivery/deliver.py <digest.md>."
                )
    else:
        lines.append("• Delivery: no attempts recorded yet.")

    if summary.dead_feeds:
        for feed in summary.dead_feeds:
            noun = "fetch" if feed.consecutive_failures == 1 else "fetches"
            lines.append(
                f"❌ Source unreachable: {feed.source} "
                f"({feed.consecutive_failures} consecutive failed {noun})"
            )
            lines.append(
                "  Next action: fix or pause the source with source-manage, then run "
                "the pipeline now."
            )
    lines.append(f"• Live sources: {summary.live_feed_count}")

    if summary.failed_run:
        lines.append("❌ Last weekly run: failed")
        lines.append(
            "  Next action: run python3 scripts/doctor.py, fix the failing section, "
            "then run the pipeline now."
        )

    if summary.run_overdue:
        lines.append("⚠️ Run overdue: no recent run (weekly run expected)")
        lines.append("  Next action: check scheduler registration, then run the pipeline now.")

    for topic in summary.stale_feeds:
        lines.append(
            f"• Registry quiet: {topic} "
            f"(no new items in over {stale_feed_days} days — may be a slow feed, "
            "not necessarily down)"
        )

    for topic in summary.gate_skipped:
        lines.append(f"⚠️ Topic gate-skipped: {topic} (dropped by sanitize/synthesis gate)")
        lines.append(
            "  Next action: run python3 scripts/sanitize_incoming.py sanitize, then run "
            "the pipeline now."
        )

    if summary.brain_health:
        lines.append(f"• Knowledge base: {summary.brain_health}")

    if summary.last_event_ts:
        lines.append(
            f"• Last activity: {summary.last_event_kind} at {summary.last_event_ts}"
        )
    return "\n".join(lines)


def ops_headline(summary: HealthSummary) -> str | None:
    """One plain-language line naming why the system is DEGRADED; None otherwise."""
    if summary.status is not Status.DEGRADED:
        return None
    reasons: list[str] = []
    if summary.dead_feeds:
        count = len(summary.dead_feeds)
        reasons.append(f"{count} unreachable source{'' if count == 1 else 's'}")
    failed_channels = sorted(
        ch for ch, st in summary.delivery.items() if st in FAILURE_STATUSES
    )
    if failed_channels:
        reasons.append(f"delivery failed ({', '.join(failed_channels)})")
    if summary.failed_run:
        reasons.append("last run failed")
    if summary.run_overdue:
        reasons.append("run overdue")
    if summary.digest_stale:
        reasons.append("digest stale")
    if summary.gate_skipped:
        count = len(summary.gate_skipped)
        reasons.append(f"{count} topic{'' if count == 1 else 's'} gate-skipped")
    detail = " · ".join(reasons) if reasons else "see `status` for details"
    return f"{detail} — say 'status' for the full picture"


__all__ = [
    "STATUS_BANNER",
    "ops_headline",
    "render",
]
