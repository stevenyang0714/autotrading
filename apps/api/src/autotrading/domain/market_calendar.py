"""US equity market sessions (M0.7, ADR-017): NYSE regular hours with holidays and early
closes from config/market_calendar.yaml. Pure; all times are aware datetimes."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Session:
    day: date
    open: datetime  # UTC
    close: datetime  # UTC


@dataclass(frozen=True)
class MarketCalendar:
    holidays: frozenset[date]
    early_closes: frozenset[date]
    covered_until: date
    open_time: time = time(9, 30)
    close_time: time = time(16, 0)
    early_close_time: time = time(13, 0)

    def session(self, day: date) -> Session | None:
        """The regular session on `day` (New York date), or None on weekends and holidays."""
        if day.weekday() >= 5 or day in self.holidays:
            return None
        close = self.early_close_time if day in self.early_closes else self.close_time
        return Session(
            day=day,
            open=datetime.combine(day, self.open_time, NEW_YORK).astimezone(UTC),
            close=datetime.combine(day, close, NEW_YORK).astimezone(UTC),
        )

    def is_open(self, at: datetime) -> bool:
        session = self.session(at.astimezone(NEW_YORK).date())
        return session is not None and session.open <= at < session.close

    def last_close(self, at: datetime) -> datetime:
        """The most recent session close at or before `at`."""
        day = at.astimezone(NEW_YORK).date()
        for back in range(15):
            session = self.session(day - timedelta(days=back))
            if session is not None and session.close <= at:
                return session.close
        raise ValueError(f"no session close in the 15 days before {at.isoformat()}")

    def next_open(self, at: datetime) -> datetime:
        """The next session open strictly after `at`."""
        day = at.astimezone(NEW_YORK).date()
        for ahead in range(15):
            session = self.session(day + timedelta(days=ahead))
            if session is not None and session.open > at:
                return session.open
        raise ValueError(f"no session open in the 15 days after {at.isoformat()}")

    def sessions_between(self, start: date, end: date) -> list[Session]:
        days = (end - start).days + 1
        found = (self.session(start + timedelta(days=i)) for i in range(max(days, 0)))
        return [s for s in found if s is not None]


def load_calendar(data: dict[str, object]) -> MarketCalendar:
    """Build the calendar from the parsed config/market_calendar.yaml."""

    def days(key: str) -> frozenset[date]:
        raw = data.get(key) or []
        assert isinstance(raw, list)
        return frozenset(d if isinstance(d, date) else date.fromisoformat(str(d)) for d in raw)

    def clock(value: object) -> time:
        return time.fromisoformat(str(value))

    regular = data.get("regular") or {}
    assert isinstance(regular, dict)
    covered = data["covered_until"]
    return MarketCalendar(
        holidays=days("holidays"),
        early_closes=days("early_closes"),
        covered_until=covered if isinstance(covered, date) else date.fromisoformat(str(covered)),
        open_time=clock(regular.get("open", "09:30")),
        close_time=clock(regular.get("close", "16:00")),
        early_close_time=clock(data.get("early_close", "13:00")),
    )
