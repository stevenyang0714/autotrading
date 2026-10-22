"""domain/market_calendar against the real calendar files: NYSE (config/market_calendar.yaml)
and TWSE (config/market_calendar_xtai.yaml, M3.7)."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import yaml

from autotrading.domain.market_calendar import MarketCalendar, load_calendar
from autotrading.settings import Settings


def calendar(name: str = "market_calendar.yaml") -> MarketCalendar:
    path = Settings(_env_file=None).resolved_config_dir() / name  # type: ignore[call-arg]
    return load_calendar(yaml.safe_load(path.read_text(encoding="utf-8")))


TAIPEI = ZoneInfo("Asia/Taipei")


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


# ---------- TWSE (M3.7, ADR-039 TW4) ----------


def test_the_taiwan_session_is_09_00_to_13_30_taipei_time() -> None:
    cal = calendar("market_calendar_xtai.yaml")
    assert cal.zone == TAIPEI
    session = cal.session(date(2026, 10, 21))
    assert session is not None
    assert session.open == datetime(2026, 10, 21, 1, 0, tzinfo=UTC)  # 09:00 Taipei
    assert session.close == datetime(2026, 10, 21, 5, 30, tzinfo=UTC)  # 13:30 Taipei
    # the New York calendar is unchanged and keeps its own zone
    assert calendar().zone == ZoneInfo("America/New_York")


def test_taiwan_holidays_follow_the_twse_schedule_not_new_york() -> None:
    cal = calendar("market_calendar_xtai.yaml")
    assert cal.session(date(2026, 10, 26)) is None  # 臺灣光復節 (補假): NYSE is open
    assert calendar().session(date(2026, 10, 26)) is not None
    assert cal.session(date(2026, 11, 26)) is not None  # Thanksgiving: TWSE is open
    assert cal.session(date(2026, 2, 12)) is None  # settlement only, no trading
    # the Lunar New Year closure: last session 2026-02-11, next 2026-02-23
    assert cal.next_open(datetime(2026, 2, 11, 6, 0, tzinfo=UTC)) == datetime(
        2026, 2, 23, 1, 0, tzinfo=UTC
    )


def test_last_close_reads_the_taipei_date() -> None:
    cal = calendar("market_calendar_xtai.yaml")
    # Saturday 2026-10-24 07:40 Taipei is still Friday 2026-10-23 in New York
    saturday = datetime(2026, 10, 24, 7, 40, tzinfo=TAIPEI)
    assert cal.last_close(saturday) == datetime(2026, 10, 23, 5, 30, tzinfo=UTC)
    tuesday = datetime(2026, 10, 27, 7, 40, tzinfo=TAIPEI)  # Monday 10-26 is a holiday
    assert cal.last_close(tuesday) == datetime(2026, 10, 23, 5, 30, tzinfo=UTC)
