"""Refresh windows shared by scheduled source refreshes (SEC M0.5, FRED M0.6, news M0.8).

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
from autotrading.domain.markets import BY_EXCHANGE
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


@dataclass(frozen=True)
class MultiDailySchedule:
    """A refresh several times a day at fixed Singapore times."""

    times: tuple[tuple[int, int], ...]

    def next_after(self, now: datetime) -> datetime:
        """The next scheduled run strictly after `now`, in UTC."""
        return min(DailySchedule(h, m).next_after(now) for h, m in self.times)


@dataclass(frozen=True)
class IntervalSchedule:
    """A refresh every `minutes` minutes, at `offset` minutes past each full interval (UTC)."""

    minutes: int
    offset: int = 0

    def next_after(self, now: datetime) -> datetime:
        """The next scheduled run strictly after `now`, in UTC."""
        step = timedelta(minutes=self.minutes)
        utc = now.astimezone(UTC)
        hour = utc.replace(minute=0, second=0, microsecond=0)
        base = hour + timedelta(minutes=self.offset) - step
        return base + (int((utc - base) // step) + 1) * step

    def slot(self, now: datetime) -> Window:
        """The interval `now` falls in: the idempotency window of a scheduled run."""
        end = self.next_after(now)
        return Window(start=end - timedelta(minutes=self.minutes), end=end)


# The only place refresh times are defined: the scheduler and the Data Health API read them.
SEC_EDGAR = DailySchedule(10, 0)  # M0.5, about 22:00 ET the previous evening
FRED = DailySchedule(10, 15)  # M0.6, after SEC
GDELT = IntervalSchedule(60, 20)  # M0.8, hourly at :20
# M3.7 (ADR-039 TW5): the TWSE OpenAPI files of a session appear about 05:20 Taipei on the next
# business day and stay until the following business day's (Friday's from Monday morning, the
# weekend still serving Thursday's); three slots a day, weekends too, each a full chance.
TWSE = MultiDailySchedule(((7, 40), (9, 40), (20, 40)))
# M3.7b (ADR-040 TW25): FinMind publishes the day's institutional flows about 20:00 and the
# foreign holdings about 21:00 Taipei; one run at 21:30 SGT.
FINMIND = DailySchedule(21, 30)
SCHEDULES: dict[str, DailySchedule | IntervalSchedule | MultiDailySchedule] = {
    "sec_edgar": SEC_EDGAR,
    "fred": FRED,
    "gdelt": GDELT,
    "twse_openapi": TWSE,
    "finmind": FINMIND,
}
# Buyback states (M1.4b): evaluated after the SEC and FRED refreshes of the day.
BUYBACK_STATES = DailySchedule(11, 0)
REGIME = DailySchedule(10, 55)  # M2.1: after FRED (10:15) and the daily closes (06:30)
# M2.2: after the closes, splits and dividends (06:30), SEC (10:00) and the buyback states
FACTORS = DailySchedule(11, 5)
# M2.3: the paper portfolio and its drawdown alert, after the buyback states and factors
PORTFOLIO = DailySchedule(11, 10)
# M2.4: the S3 ETF rotation, after the regime (10:55) and the factor snapshots (11:05)
ROTATION = DailySchedule(11, 15)
# M3.0: S4's daily assessment, after the factor snapshots (11:05) and before the backtests
MOMENTUM = DailySchedule(11, 17)
# M3.7: the Taiwan factor snapshots (definitions 0.2.0), after the 07:40 and 09:40 TWSE runs
TW_FACTORS = DailySchedule(9, 50)
# M2.5: the backtests, once a month after the month's first rotation assessment
BACKTESTS = DailySchedule(11, 20)
# Official RSS feeds (M0.8): every 30 minutes at :05 and :35, one run per feed.
NEWS_FEEDS = IntervalSchedule(30, 5)
# M3.0b: alert delivery to Telegram every 5 minutes, at :01, :06, ... (UTC)
DELIVERY = IntervalSchedule(5, 1)

# Alpaca (M0.7): daily SIP bars after the US close and the free plan's 15-minute SIP delay;
# snapshots run every SNAPSHOT_SECONDS during the session (see adapters/alpaca/refresh.py).
DAILY_BARS = DailySchedule(6, 30)
SNAPSHOT_SECONDS = 60
# Sources that update only during US market hours: freshness is judged session-aware.
INTRADAY_SOURCES = frozenset({"alpaca_iex"})


@lru_cache
def market_calendar(exchange: str = "XNYS") -> MarketCalendar:
    """An exchange's sessions from its calendar file, read once per process: NYSE
    (config/market_calendar.yaml, ADR-017) or TWSE (config/market_calendar_xtai.yaml, ADR-039)."""
    path = get_settings().resolved_config_dir() / BY_EXCHANGE[exchange].calendar_file
    return load_calendar(yaml.safe_load(path.read_text(encoding="utf-8")))
