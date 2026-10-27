"""FinMind refresh orchestration (M3.7b, ADR-040 TW25): the daily flows run and the one-time
history runs, without the broker."""

from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from autotrading.adapters.finmind.client import (
    DIVIDENDS,
    INSTITUTIONAL,
    MARGIN,
    PER,
    PRICE,
    SHAREHOLDING,
    SOURCE_ID,
)
from autotrading.adapters.finmind.daily import FinMindFlowsJob
from autotrading.adapters.finmind.history import HISTORY_START, FinMindHistoryJob
from autotrading.adapters.twse.instruments import existing_instruments
from autotrading.db.models import PriceBar, Source
from autotrading.domain.market_calendar import MarketCalendar
from autotrading.domain.markets import TW
from autotrading.ingestion.runner import IngestionRunner
from autotrading.ingestion.schedule import refresh_window
from autotrading.repositories.universe import TaiwanUniverse

WINDOW_DAYS = 10  # FinMind revises recent days; the window is part of the run key
HISTORY_DATASETS = (PRICE, MARGIN, PER, DIVIDENDS, INSTITUTIONAL, SHAREHOLDING)


def _enabled(session: Session) -> bool:
    source = session.get(Source, SOURCE_ID)
    return source is not None and bool(source.enabled)


def codes_missing_closes(
    session: Session, codes: list[str], calendar: MarketCalendar, start: date, end: date
) -> list[str]:
    """The codes with a calendar session in [start, end] (up to yesterday) and no stored raw
    close for it: a lost TWSE session FinMind can fill (KI-27)."""
    ids = existing_instruments(session, codes)
    expected = {s.day for s in calendar.sessions_between(start, end)}
    out = []
    for code, instrument_id in ids.items():
        stored = set(
            session.scalars(
                select(PriceBar.bar_date).where(
                    PriceBar.instrument_id == instrument_id,
                    PriceBar.adjustment == "raw",
                    PriceBar.superseded_at.is_(None),
                    PriceBar.bar_date >= start,
                    PriceBar.bar_date <= end,
                )
            )
        )
        if expected - stored:
            out.append(code)
    return out


def start_flows(
    runner: IngestionRunner,
    *,
    now: datetime,
    manual: bool,
    universe: TaiwanUniverse,
    calendar: MarketCalendar,
) -> UUID | None:
    """The day's flows run; None when the source is disabled."""
    today = now.astimezone(TW.zone).date()
    start = today - timedelta(days=WINDOW_DAYS)
    with runner.sessions() as session:
        if not _enabled(session):
            return None
        price_codes = codes_missing_closes(
            session, list(universe.codes), calendar, start, today - timedelta(days=1)
        )
    params: dict[str, object] = {
        "codes": list(universe.codes),
        "start": start.isoformat(),
        "end": today.isoformat(),
    }
    if price_codes:
        params["price_codes"] = price_codes
    return runner.create_run(FinMindFlowsJob.name, params, refresh_window(now, manual=manual))


def start_history(
    runner: IngestionRunner,
    *,
    now: datetime,
    universe: TaiwanUniverse,
    end: date,
    start: date = HISTORY_START,
) -> list[UUID]:
    """One run per code and dataset over [start, end]; empty when the source is disabled."""
    with runner.sessions() as session:
        if not _enabled(session):
            return []
    window = refresh_window(now, manual=True)
    return [
        runner.create_run(
            FinMindHistoryJob.name,
            {"code": code, "dataset": dataset, "start": start.isoformat(), "end": end.isoformat()},
            window,
        )
        for code in universe.codes
        for dataset in HISTORY_DATASETS
    ]
