"""Refresh windows shared by scheduled source refreshes (SEC M0.5, FRED M0.6).

The window is part of each run's idempotency key:
- scheduled: the Singapore calendar day, so a repeated trigger the same day is skipped;
- manual (`make sec-refresh`, `make fred-refresh`): start of that day to now, so it always runs.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from autotrading.ingestion.job import Window

REFRESH_TIMEZONE = ZoneInfo("Asia/Singapore")


def refresh_window(now: datetime, *, manual: bool) -> Window:
    day_start = now.astimezone(REFRESH_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    start = day_start.astimezone(UTC)
    end = now.astimezone(UTC) if manual else (day_start + timedelta(days=1)).astimezone(UTC)
    return Window(start=start, end=end)
