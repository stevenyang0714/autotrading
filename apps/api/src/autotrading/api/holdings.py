"""Real holdings (M3.10, ADR-041 H8): Steven's ledger and its valuation.

- GET /holdings values the ledger at T (default now) as recorded now: each position at the last
  close known at T, cash per account and currency, totals per currency, and the USD total
  through the last DEXTAUS rate known at T, with the change over the previous 24 hours less
  deposits and withdrawals.
- Entries are append-only and audited (actor `web`), written at the database's now. A mistake is
  corrected by reversing the entry (one reversal each), then entering it again.
- Holdings stay on this machine: the API binds to localhost, and nothing here is pushed or sent
  anywhere (H12). There is no order, broker or execution field; requests with unknown fields are
  refused.
"""

import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from autotrading.api.data_health import SessionDep
from autotrading.api.research import KnownAt
from autotrading.db.models import Entity, HoldingEntry, Instrument
from autotrading.domain.holdings import (
    BASE_CURRENCY,
    FX_SERIES,
    FX_STALE_DAYS,
    ZONE_OF_CURRENCY,
    Entry,
    Valuation,
    change,
    document,
    held,
)
from autotrading.domain.markets import MARKETS, Market
from autotrading.repositories.audit import set_actor
from autotrading.repositories.holdings import (
    ACTOR,
    fx_source_url,
    latest_snapshot,
    ledger,
    splits_of,
    valuation_at,
)
from autotrading.repositories.identifiers import current_identifier
from autotrading.repositories.labels import label

router = APIRouter(tags=["holdings"])

USER = "steven"  # one user (errata E1); the API binds to localhost only
CHANGE_WINDOW = timedelta(days=1)
SYMBOL_PATTERNS: dict[Market, str] = {
    "US": r"^[A-Z][A-Z0-9.]{0,9}$",  # Alpaca's convention: BRK.B
    "TW": r"^[0-9][0-9A-Z]{3,5}$",  # TWSE codes: 2330, 0050, 00878, 00632R
}
DETAIL = (
    "Your holdings as you recorded them, kept on this machine only. Each position is marked at "
    "the last end-of-day close known at the time shown (TWSE listings in TWD, US listings in "
    "USD) and TWD is converted at the last DEXTAUS rate. A record, not advice: nothing here is "
    "ever sent to a broker."
)

Account = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Symbol = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, max_length=10)]


# ---------- valuation ----------


class MarkOut(BaseModel):
    close: Decimal
    session: date
    published_at: datetime
    row_id: str


class PositionOut(BaseModel):
    account: str
    market: Market
    instrument_id: UUID
    symbol: str
    name: str | None
    name_zh: str | None
    currency: str
    quantity: Decimal
    cost: Decimal
    average_cost: Decimal | None
    realized: Decimal
    mark: MarkOut | None
    price: Decimal | None
    market_value: Decimal
    unrealized: Decimal | None
    value_usd: Decimal | None
    weight: Decimal | None
    flags: list[str]


class CashOut(BaseModel):
    account: str
    currency: str
    balance: Decimal
    value_usd: Decimal | None
    weight: Decimal | None


class CurrencyTotalOut(BaseModel):
    currency: str
    positions: Decimal
    cash: Decimal
    total: Decimal
    realized: Decimal
    unrealized: Decimal
    contributions: Decimal


class FxOut(BaseModel):
    series_id: str
    value: Decimal  # TWD per USD
    observation_date: date
    published_at: datetime
    row_id: str
    source_url: str | None
    lag_days: int
    stale: bool


class SnapshotRef(BaseModel):
    id: UUID
    known_at: datetime
    system_time: datetime
    equity_usd: Decimal | None
    trigger: str


class HoldingsOut(BaseModel):
    known_at: datetime
    system_time: datetime
    valuation_version: str
    base_currency: str
    equity_usd: Decimal | None
    change_usd: Decimal | None  # over CHANGE_WINDOW, less deposits and withdrawals
    change_since: datetime
    positions: list[PositionOut]
    cash: list[CashOut]
    totals: list[CurrencyTotalOut]
    fx: FxOut | None
    flags: list[str]
    entries: int
    latest_snapshot: SnapshotRef | None
    detail: str


def _names(session: Session, instrument_ids: set[UUID]) -> dict[UUID, str]:
    """The issuer name of held instruments that have one."""
    if not instrument_ids:
        return {}
    rows = session.execute(
        select(Instrument.id, Entity.name)
        .join(Entity, Entity.id == Instrument.entity_id)
        .where(Instrument.id.in_(instrument_ids))
    )
    return {instrument_id: name for instrument_id, name in rows}


def display_name(
    symbol: str, instrument_id: UUID | None, issuers: dict[UUID, str]
) -> tuple[str | None, str | None]:
    """(name, Chinese name): the universe label, else the issuer's name, else none."""
    found = label(symbol)
    if found.name != symbol:
        return found.name, found.zh
    if instrument_id is not None and instrument_id in issuers:
        return issuers[instrument_id], None
    return None, None


def holdings_out(session: Session, valuation: Valuation, before: Valuation) -> HoldingsOut:
    stored = document(valuation)
    issuers = _names(session, {p.instrument_id for p in valuation.positions})
    positions = []
    for raw, position in zip(stored["positions"], valuation.positions, strict=True):
        name, name_zh = display_name(position.symbol, position.instrument_id, issuers)
        positions.append(PositionOut.model_validate({**raw, "name": name, "name_zh": name_zh}))
    fx = None
    if valuation.fx is not None and valuation.fx_lag_days is not None:
        fx = FxOut(
            series_id=FX_SERIES,
            value=valuation.fx.value,
            observation_date=valuation.fx.observation_date,
            published_at=valuation.fx.published_at,
            row_id=valuation.fx.row_id,
            source_url=fx_source_url(session, valuation.fx.row_id),
            lag_days=valuation.fx_lag_days,
            stale=valuation.fx_lag_days > FX_STALE_DAYS,
        )
    snapshot = latest_snapshot(session, valuation.known_at)
    return HoldingsOut(
        known_at=valuation.known_at,
        system_time=valuation.system_time,
        valuation_version=valuation.version,
        base_currency=BASE_CURRENCY,
        equity_usd=valuation.equity_usd,
        change_usd=change(before, valuation),
        change_since=before.known_at,
        positions=positions,
        cash=[CashOut.model_validate(c) for c in stored["cash"]],
        totals=[CurrencyTotalOut.model_validate(t) for t in stored["totals"]],
        fx=fx,
        flags=list(valuation.flags),
        entries=valuation.entries,
        latest_snapshot=(
            SnapshotRef(
                id=snapshot.id,
                known_at=snapshot.known_at,
                system_time=snapshot.system_time,
                equity_usd=snapshot.equity_usd,
                trigger=snapshot.trigger,
            )
            if snapshot
            else None
        ),
        detail=DETAIL,
    )


def _now(session: Session) -> datetime:
    return session.execute(select(func.now())).scalar_one()


@router.get("/holdings")
def holdings(session: SessionDep, known_at: KnownAt = None) -> HoldingsOut:
    """The holdings at T (default now) as recorded now."""
    now = _now(session)
    at = known_at or now
    valuation = valuation_at(session, at, now)
    before = valuation_at(session, at - CHANGE_WINDOW, now)
    return holdings_out(session, valuation, before)


# ---------- entries ----------


EntryStatus = Literal["counted", "reversed", "reversal"]


class EntryOut(BaseModel):
    id: UUID
    kind: str
    account: str
    market: str | None
    symbol: str | None
    name: str | None
    name_zh: str | None
    currency: str
    trade_date: date
    quantity: Decimal | None
    price: Decimal | None
    amount: Decimal | None
    fee: Decimal | None
    note: str | None
    reverses_id: UUID | None
    reversed_by: UUID | None
    status: EntryStatus
    recorded_at: datetime


class EntriesOut(BaseModel):
    entries: list[EntryOut]  # newest first
    accounts: list[str]  # every account label used, for the form


class NewHoldingEntry(BaseModel):
    """A ledger entry as typed on the Holdings page. Unknown fields are refused."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["buy", "sell", "dividend", "deposit", "withdrawal", "fee"]
    account: Account
    trade_date: date
    market: Market | None = None
    symbol: Symbol | None = None
    currency: Literal["USD", "TWD"] | None = None
    quantity: Decimal | None = Field(None, gt=0, le=10**9, decimal_places=6)
    price: Decimal | None = Field(None, gt=0, le=10**7, decimal_places=6)
    amount: Decimal | None = Field(None, gt=0, le=10**12, decimal_places=2)
    fee: Decimal | None = Field(None, ge=0, le=10**7, decimal_places=2)
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None

    @model_validator(mode="after")
    def _fields_of_kind(self) -> "NewHoldingEntry":
        listed = self.kind in ("buy", "sell", "dividend")
        if listed:
            if self.market is None or not self.symbol:
                raise ValueError(f"a {self.kind} needs a market and a symbol")
            if not re.match(SYMBOL_PATTERNS[self.market], self.symbol):
                example = "SPY or BRK.B" if self.market == "US" else "2330 or 0050"
                raise ValueError(f"{self.symbol} is not a {self.market} symbol (e.g. {example})")
            if self.currency not in (None, MARKETS[self.market].currency):
                raise ValueError(f"{self.market} listings are in {MARKETS[self.market].currency}")
        elif self.market or self.symbol:
            raise ValueError(f"a {self.kind} is cash: no market or symbol")
        elif self.currency is None:
            raise ValueError(f"a {self.kind} needs a currency")
        trade = self.kind in ("buy", "sell")
        if trade != (self.quantity is not None and self.price is not None):
            raise ValueError("a buy or sell has a quantity and a price; other kinds have neither")
        if trade == (self.amount is not None):
            raise ValueError("a dividend, deposit, withdrawal or fee has an amount; a trade not")
        if self.fee is not None and not trade:
            raise ValueError("a fee on its own is the kind `fee`")
        return self

    @property
    def currency_code(self) -> str:
        return MARKETS[self.market].currency if self.market else str(self.currency)


class ReverseEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


def entries_out(session: Session, rows: list[HoldingEntry]) -> list[EntryOut]:
    reversed_by = {row.reverses_id: row.id for row in rows if row.reverses_id is not None}
    issuers = _names(session, {r.instrument_id for r in rows if r.instrument_id is not None})
    out = []
    for row in sorted(rows, key=lambda r: (r.recorded_at, str(r.id)), reverse=True):
        name, name_zh = (
            display_name(row.symbol, row.instrument_id, issuers) if row.symbol else (None, None)
        )
        status: EntryStatus = "counted"
        if row.kind == "reversal":
            status = "reversal"
        elif row.id in reversed_by:
            status = "reversed"
        out.append(
            EntryOut(
                id=row.id,
                kind=row.kind,
                account=row.account,
                market=row.market,
                symbol=row.symbol,
                name=name,
                name_zh=name_zh,
                currency=row.currency,
                trade_date=row.trade_date,
                quantity=row.quantity,
                price=row.price,
                amount=row.amount,
                fee=row.fee,
                note=row.note,
                reverses_id=row.reverses_id,
                reversed_by=reversed_by.get(row.id),
                status=status,
                recorded_at=row.recorded_at,
            )
        )
    return out


@router.get("/holdings/entries")
def holding_entries(session: SessionDep) -> EntriesOut:
    rows = list(session.scalars(select(HoldingEntry)))
    return EntriesOut(
        entries=entries_out(session, rows),
        accounts=sorted({row.account for row in rows}),
    )


def _commit(session: Session, conflict: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=conflict) from exc


def _instrument(session: Session, market: Market, symbol: str) -> UUID:
    found = current_identifier(session, "ticker", MARKETS[market].namespace, symbol)
    if found is None or found.instrument_id is None:
        raise HTTPException(
            status_code=422, detail=f"{symbol} is not a {market} instrument this platform tracks"
        )
    return found.instrument_id


def _check_sell(
    session: Session, body: NewHoldingEntry, instrument_id: UUID, now: datetime
) -> None:
    """A sell never takes the account's quantity below zero, on its date or now."""
    assert body.market is not None and body.symbol is not None and body.quantity is not None
    entries = ledger(session)
    selling = Entry(
        id=UUID(int=0),
        kind="sell",
        account=body.account,
        market=body.market,
        instrument_id=instrument_id,
        symbol=body.symbol,
        currency=body.currency_code,
        trade_date=body.trade_date,
        quantity=body.quantity,
        price=body.price,
        amount=None,
        fee=body.fee,
        recorded_at=now,
    )
    splits = splits_of(session, instrument_id, body.market, now, None)
    for at in (selling.basis_at, now):
        if held([*entries, selling], body.account, instrument_id, splits, at, now) < 0:
            raise HTTPException(
                status_code=422,
                detail=f"selling {body.quantity} {body.symbol} would leave {body.account} short "
                f"(on {body.trade_date} or now): record the buy first",
            )


@router.post("/holdings/entries", status_code=201)
def create_holding_entry(body: NewHoldingEntry, session: SessionDep) -> EntryOut:
    set_actor(session, ACTOR)
    now = _now(session)
    zone = MARKETS[body.market].zone if body.market else ZONE_OF_CURRENCY[body.currency_code]
    if body.trade_date > now.astimezone(zone).date():
        raise HTTPException(status_code=422, detail="the trade date is after today")
    instrument_id = None
    if body.market is not None and body.symbol is not None:
        instrument_id = _instrument(session, body.market, body.symbol)
        if body.kind == "sell":
            _check_sell(session, body, instrument_id, now)
    row = HoldingEntry(
        kind=body.kind,
        account=body.account,
        market=body.market,
        instrument_id=instrument_id,
        symbol=body.symbol,
        currency=body.currency_code,
        trade_date=body.trade_date,
        quantity=body.quantity,
        price=body.price,
        amount=body.amount,
        fee=body.fee,
        note=body.note or None,
        user_id=USER,
    )
    session.add(row)
    _commit(session, "the entry could not be saved; reload and try again")
    return entries_out(session, [row])[0]


@router.post("/holdings/entries/{entry_id}/reverse", status_code=201)
def reverse_holding_entry(entry_id: UUID, body: ReverseEntry, session: SessionDep) -> EntryOut:
    """Undo an entry from every time on: a reversal pointing at it (one each)."""
    original = session.get(HoldingEntry, entry_id)
    if original is None:
        raise HTTPException(status_code=404, detail=f"no holdings entry {entry_id}")
    if original.kind == "reversal":
        raise HTTPException(status_code=409, detail="a reversal cannot be reversed")
    set_actor(session, ACTOR)
    if session.scalar(select(HoldingEntry.id).where(HoldingEntry.reverses_id == entry_id)):
        raise HTTPException(status_code=409, detail="this entry is already reversed")
    row = HoldingEntry(
        kind="reversal",
        account=original.account,
        currency=original.currency,
        trade_date=original.trade_date,
        reverses_id=original.id,
        note=body.note or None,
        user_id=USER,
    )
    session.add(row)
    _commit(session, "this entry is already reversed")
    return next(e for e in entries_out(session, [row, original]) if e.id == row.id)
