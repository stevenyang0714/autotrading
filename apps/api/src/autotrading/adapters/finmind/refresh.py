"""FinMind refresh orchestration (M3.7b, ADR-040 TW25): the daily flows run and the one-time
history runs, without the broker.

M3.11 (ADR-042 SC4, SC5): the listed companies' history (prices since 2024 and ex-dividend
results), one code and dataset per run under a fixed window, so a re-run queues only what has
not succeeded; and the Taiwan screens' candidates' institutional flows, in runs of at most
CANDIDATE_CHUNK codes."""

from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
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
from autotrading.db.models import IngestionRun, PriceBar, Source
from autotrading.domain.market_calendar import MarketCalendar
from autotrading.domain.markets import TW
from autotrading.ingestion.job import Window, idempotency_key
from autotrading.ingestion.runner import IngestionRunner
from autotrading.ingestion.schedule import refresh_window
from autotrading.repositories.listed import DEPOSITARY_RECEIPTS, listed_at
from autotrading.repositories.universe import TaiwanUniverse

WINDOW_DAYS = 10  # FinMind revises recent days; the window is part of the run key
HISTORY_DATASETS = (PRICE, MARGIN, PER, DIVIDENDS, INSTITUTIONAL, SHAREHOLDING)
LISTED_HISTORY_START = date(2024, 1, 1)
LISTED_DATASETS = (PRICE, DIVIDENDS)
LISTED_WINDOW = Window()  # fixed: the run key is the code, dataset and dates only
CANDIDATE_CHUNK = 20  # codes per candidates' flows run: 20 requests, about 4 minutes


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


def first_twse_session(session: Session, instrument_ids: list[UUID]) -> date | None:
    """The first session the TWSE daily job stored a bar for, among these instruments."""
    if not instrument_ids:
        return None
    return session.scalar(
        select(func.min(PriceBar.bar_date)).where(
            PriceBar.instrument_id.in_(instrument_ids),
            PriceBar.feed == "twse",
            PriceBar.adjustment == "raw",
        )
    )


def start_listed_history(
    runner: IngestionRunner,
    *,
    universe: TaiwanUniverse,
    today: date,
    datasets: tuple[str, ...] = LISTED_DATASETS,
    start: date = LISTED_HISTORY_START,
) -> list[UUID]:
    """One run per listed company and dataset over [start, the day before the first TWSE
    session of the listed companies] (yesterday before there is one): prices for the companies
    outside the universe (whose history since 2016 is stored), ex-dividend results for all.
    Runs whose key has succeeded are left out; empty when the source is disabled."""
    with runner.sessions() as session:
        if not _enabled(session):
            return []
        listed = {
            code: c for code, c in listed_at(session).items() if c.industry != DEPOSITARY_RECEIPTS
        }
        outside = [c.instrument_id for code, c in listed.items() if code not in universe.codes]
        first = first_twse_session(session, outside)
        end = (first or today) - timedelta(days=1)
        planned = [
            {"code": code, "dataset": dataset, "start": start.isoformat(), "end": end.isoformat()}
            for dataset in datasets
            for code in sorted(listed)
            if not (dataset == PRICE and code in universe.codes)
        ]
        keys = {
            idempotency_key(SOURCE_ID, FinMindHistoryJob.name, params, LISTED_WINDOW): params
            for params in planned
        }
        done = set(
            session.scalars(
                select(IngestionRun.idempotency_key).where(
                    IngestionRun.status == "succeeded", IngestionRun.idempotency_key.in_(keys)
                )
            )
        )
    return [
        runner.create_run(FinMindHistoryJob.name, params, LISTED_WINDOW)
        for key, params in keys.items()
        if key not in done
    ]


def start_candidate_flows(
    runner: IngestionRunner, *, now: datetime, manual: bool, codes: list[str]
) -> list[UUID]:
    """The institutional flows of the Taiwan screens' candidates over the last WINDOW_DAYS, in
    runs of at most CANDIDATE_CHUNK codes; empty when the source is disabled or there are none."""
    if not codes:
        return []
    with runner.sessions() as session:
        if not _enabled(session):
            return []
    today = now.astimezone(TW.zone).date()
    start = today - timedelta(days=WINDOW_DAYS)
    window = refresh_window(now, manual=manual)
    return [
        runner.create_run(
            FinMindFlowsJob.name,
            {
                "codes": codes[i : i + CANDIDATE_CHUNK],
                "start": start.isoformat(),
                "end": today.isoformat(),
                "datasets": [INSTITUTIONAL],
                "slot": "candidates",
            },
            window,
        )
        for i in range(0, len(codes), CANDIDATE_CHUNK)
    ]
