"""Refresh windows shared by scheduled source refreshes (SEC M0.5, FRED M0.6).

The window is part of each run's idempotency key:
- scheduled: the Singapore calendar day, so a repeated trigger the same day is skipped;
- manual (`make sec-refresh`, `make fred-refresh`): start of that day to now, so it always runs.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import yaml

from autotrading.domain.market_calendar import MarketCalendar, load_calendar
from autotrading.ingestion.job import Window
from autotrading.settings import get_settings

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

# Alpaca (M0.7): daily SIP bars after the US close and the free plan's 15-minute SIP delay;
# snapshots run every SNAPSHOT_SECONDS during the session (see adapters/alpaca/refresh.py).
DAILY_BARS = DailySchedule(6, 30)
SNAPSHOT_SECONDS = 60
# Sources that update only during US market hours: freshness is judged session-aware.
INTRADAY_SOURCES = frozenset({"alpaca_iex"})


@lru_cache
def market_calendar() -> MarketCalendar:
    """NYSE sessions from config/market_calendar.yaml (ADR-017), read once per process."""
    path = get_settings().resolved_config_dir() / "market_calendar.yaml"
    return load_calendar(yaml.safe_load(path.read_text(encoding="utf-8")))
