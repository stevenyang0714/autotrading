"""Refresh windows shared by scheduled source refreshes (SEC M0.5, FRED M0.6).

The window is part of each run's idempotency key:
- scheduled: the Singapore calendar day, so a repeated trigger the same day is skipped;
- manual (`make sec-refresh`, `make fred-refresh`): start of that day to now, so it always runs.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from autotrading.ingestion.job import Window

REFRESH_TIMEZONE = ZoneInfo("Asia/Singapore")


def refresh_window(now: datetime, *, manual: bool) -> Window:
    day_start = now.astimezone(REFRESH_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    start = day_start.astimezone(UTC)
    end = now.astimezone(UTC) if manual else (day_start + timedelta(days=1)).astimezone(UTC)
    return Window(start=start, end=end)


@dataclass(frozen=True)
class DailySchedule:
    """A refresh once a day at a fixed Singapore time."""

    hour: int
    minute: int = 0

    def next_after(self, now: datetime) -> datetime:
        """The next scheduled run strictly after `now`, in UTC."""
        local = now.astimezone(REFRESH_TIMEZONE)
        today = datetime.combine(local.date(), time(self.hour, self.minute), REFRESH_TIMEZONE)
        upcoming = today if today > local else today + timedelta(days=1)
        return upcoming.astimezone(UTC)


# The only place refresh times are defined: the scheduler and the Data Health API read it.
SCHEDULES: dict[str, DailySchedule] = {
    "sec_edgar": DailySchedule(10, 0),  # M0.5, about 22:00 ET the previous evening
    "fred": DailySchedule(10, 15),  # M0.6, after SEC
}
