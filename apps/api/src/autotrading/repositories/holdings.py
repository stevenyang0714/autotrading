"""Real holdings storage (M3.10, ADR-041 H1-H3, H13): the ledger rows as domain entries, the
inputs known at (T, S) (closes, splits, the DEXTAUS rate), the valuation, and the daily snapshot
and its verify.

The ledger is kept apart from the paper portfolio (H4): nothing here reads or writes the
journal, the risk book or any rule, and no research view reads the ledger.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from autotrading.api.valuation import recorded_by
from autotrading.db.models import (
    HoldingEntry,
    HoldingSnapshot,
    MacroObservation,
    PriceBar,
    SplitEvent,
)
from autotrading.domain.holdings import (
    FX_SERIES,
    TRADES,
    Entry,
    Fx,
    Kind,
    Mark,
    Valuation,
    counted,
    document,
    value,
)
from autotrading.domain.markets import MARKETS, Market
from autotrading.domain.splits import Split
from autotrading.repositories.facts import as_of_query

ACTOR = "web"


def entry_of(row: HoldingEntry) -> Entry:
    return Entry(
        id=row.id,
        kind=cast(Kind, row.kind),  # the kind CHECK
        account=row.account,
        market=cast(Market | None, row.market),  # the market CHECK
        instrument_id=row.instrument_id,
        symbol=row.symbol,
        currency=row.currency,
        trade_date=row.trade_date,
        quantity=row.quantity,
        price=row.price,
        amount=row.amount,
        fee=row.fee,
        recorded_at=row.recorded_at,
        reverses_id=row.reverses_id,
    )


def ledger(session: Session, system_time: datetime | None = None) -> list[Entry]:
    """Every entry recorded by S (default: all), reversals included."""
    rows = session.scalars(
        select(HoldingEntry)
        .where(recorded_by(HoldingEntry.recorded_at, system_time))
        .order_by(HoldingEntry.recorded_at, HoldingEntry.id)
    )
    return [entry_of(row) for row in rows]


def last_mark(
    session: Session, instrument_id: UUID, at: datetime, system_time: datetime | None
) -> Mark | None:
    """The last raw end-of-day close whose close is known at T, as held at S (any age)."""
    known = as_of_query(PriceBar, known_at=at, system_time=system_time).where(
        PriceBar.instrument_id == instrument_id,
        PriceBar.adjustment == "raw",
        PriceBar.bar_time <= at,
    )
    row = aliased(PriceBar, known.subquery())
    bar = session.scalars(select(row).order_by(row.bar_time.desc()).limit(1)).first()
    if bar is None:
        return None
    return Mark(bar.close, bar.bar_date, bar.published_at, str(bar.id))


def splits_of(
    session: Session,
    instrument_id: UUID,
    market: Market,
    at: datetime,
    system_time: datetime | None,
) -> list[Split]:
    """The splits and stock dividends public at T, as recorded by S, in the market's zone."""
    zone = MARKETS[market].zone
    return [
        Split(s.ex_date, s.old_rate, s.new_rate, zone=zone)
        for s in session.scalars(
            select(SplitEvent)
            .where(
                SplitEvent.instrument_id == instrument_id,
                SplitEvent.published_at <= at,
                recorded_by(SplitEvent.recorded_at, system_time),
            )
            .order_by(SplitEvent.ex_date)
        )
    ]


def fx_at(session: Session, at: datetime, system_time: datetime | None) -> Fx | None:
    """The latest DEXTAUS observation public at T, as held at S."""
    known = as_of_query(MacroObservation, known_at=at, system_time=system_time).where(
        MacroObservation.series_id == FX_SERIES
    )
    shown = aliased(MacroObservation, known.subquery())
    row = session.scalars(select(shown).order_by(shown.observation_date.desc()).limit(1)).first()
    if row is None:
        return None
    return Fx(row.value, row.observation_date, row.published_at, str(row.id))


def fx_source_url(session: Session, row_id: str) -> str | None:
    return session.scalar(
        select(MacroObservation.source_url).where(MacroObservation.id == UUID(row_id))
    )


def held_instruments(entries: Iterable[Entry]) -> dict[UUID, Market]:
    return {
        e.instrument_id: e.market
        for e in entries
        if e.kind in TRADES and e.instrument_id is not None and e.market is not None
    }


def valuation_at(session: Session, at: datetime, system_time: datetime) -> Valuation:
    """The holdings at T as recorded by S, with the closes, splits and rate known at T as the
    database held them at S."""
    entries = ledger(session, system_time)
    instruments = held_instruments(counted(entries, at, system_time))
    marks = {}
    splits = {}
    for instrument_id, market in instruments.items():
        found = last_mark(session, instrument_id, at, system_time)
        if found is not None:
            marks[instrument_id] = found
        splits[instrument_id] = splits_of(session, instrument_id, market, at, system_time)
    return value(entries, marks, splits, fx_at(session, at, system_time), at, system_time)


def record_snapshot(
    session: Session, at: datetime, system_time: datetime, trigger: str
) -> HoldingSnapshot | None:
    """Store the holdings at T (daily, H2). None when nothing was ever recorded."""
    if not ledger(session, system_time):
        return None
    valuation = valuation_at(session, at, system_time)
    stored = document(valuation)
    row = HoldingSnapshot(
        known_at=at,
        system_time=system_time,
        valuation_version=valuation.version,
        equity_usd=valuation.equity_usd,
        cash={t.currency: str(t.cash) for t in valuation.totals},
        fx=stored["fx"],
        positions=len(valuation.positions),
        holdings=stored,
        trigger=trigger,
    )
    session.add(row)
    session.flush()
    return row


def recompute(session: Session, row: HoldingSnapshot) -> dict[str, Any]:
    """A stored snapshot computed again at its own (T, S) (H13)."""
    return document(valuation_at(session, row.known_at, row.system_time))


def latest_snapshot(session: Session, at: datetime) -> HoldingSnapshot | None:
    return session.scalars(
        select(HoldingSnapshot)
        .where(HoldingSnapshot.known_at <= at)
        .order_by(HoldingSnapshot.known_at.desc(), HoldingSnapshot.system_time.desc())
        .limit(1)
    ).first()
