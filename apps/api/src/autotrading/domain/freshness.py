"""Source freshness (glossary term `data_freshness`).

now - last successful ingest, compared with the source's freshness SLA -> fresh | stale | failing.
"""

from datetime import datetime, timedelta
from typing import Literal

FreshnessStatus = Literal["fresh", "stale", "failing"]


def freshness_status(
    *,
    now: datetime,
    enabled: bool,
    sla_seconds: int,
    last_success_at: datetime | None,
    last_attempt_failed: bool,
) -> FreshnessStatus | None:
    """None for a disabled source: it is not expected to update, so it is not judged.

    `last_attempt_failed` refers to the most recent finished run (failed or dead-lettered);
    a failing source is reported as failing even if its last success is still within SLA.
    """
    if not enabled:
        return None
    if last_attempt_failed:
        return "failing"
    if last_success_at is None or now - last_success_at > timedelta(seconds=sla_seconds):
        return "stale"
    return "fresh"
