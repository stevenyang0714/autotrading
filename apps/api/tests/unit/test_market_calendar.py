"""domain/market_calendar against the real config/market_calendar.yaml."""

from datetime import UTC, date, datetime

import yaml

from autotrading.domain.market_calendar import MarketCalendar, load_calendar
from autotrading.settings import Settings


def calendar() -> MarketCalendar:
    path = Settings(_env_file=None).resolved_config_dir() / "market_calendar.yaml"  # type: ignore[call-arg]
    return load_calendar(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_regular_session_follows_new_york_daylight_saving() -> None:
    cal = calendar()
    winter = cal.session(date(2026, 3, 6))  # before DST starts on 2026-03-08
    summer = cal.session(date(2026, 3, 9))
    assert winter is not None and winter.open == datetime(2026, 3, 6, 14, 30, tzinfo=UTC)
    assert summer is not None and summer.open == datetime(2026, 3, 9, 13, 30, tzinfo=UTC)
    assert summer.close == datetime(2026, 3, 9, 20, 0, tzinfo=UTC)


def test_holidays_weekends_and_early_closes() -> None:
    cal = calendar()
    assert cal.session(date(2026, 11, 26)) is None  # Thanksgiving
    assert cal.session(date(2026, 1, 19)) is None  # MLK Day
    assert cal.session(date(2026, 10, 3)) is None  # Saturday
    early = cal.session(date(2026, 11, 27))
    assert early is not None and early.close == datetime(
        2026, 11, 27, 18, 0, tzinfo=UTC
    )  # 13:00 EST


def test_open_last_close_and_next_open() -> None:
    cal = calendar()
    monday_noon_et = datetime(2026, 10, 5, 16, 0, tzinfo=UTC)
    assert cal.is_open(monday_noon_et)
    assert not cal.is_open(datetime(2026, 10, 5, 20, 0, tzinfo=UTC))  # 16:00 ET: closed
    saturday = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    assert cal.last_close(saturday) == datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
    assert cal.next_open(saturday) == datetime(2026, 10, 5, 13, 30, tzinfo=UTC)
    before_thanksgiving = datetime(2026, 11, 25, 22, 0, tzinfo=UTC)
    assert cal.next_open(before_thanksgiving) == datetime(2026, 11, 27, 14, 30, tzinfo=UTC)


def test_calendar_covers_the_coming_year() -> None:
    assert calendar().covered_until >= date(2027, 12, 31)
