"""Real holdings (M3.10, ADR-041 H3): Steven's ledger valued at a time T. Pure; no I/O.

- An entry counts at T once its trade date has begun in its zone (New York for US listings and
  USD cash, Taipei for TWSE listings and TWD cash) and it was recorded by the system time S. A
  reversed entry and its reversal never count: a correction applies to every T once recorded,
  and to none before.
- A position is one instrument on one account at average cost. A buy adds its quantity, and
  quantity times price to the cost; a sell realizes its proceeds less the average cost of the shares
  sold. Within one trade date buys come before sells (a day trade recorded sell first is not
  oversold). Fees reduce cash only, never the cost. Splits and stock dividends effective after
  the trade date and by T scale the quantity; the cost is unchanged.
- Cash is per account and currency: deposits, sells and cash dividends add; withdrawals, buys
  and fees subtract. A negative balance is flagged, not refused (a deposit may be missing).
- A position is marked at the last end-of-day close known at T, moved to T's split basis, and
  flagged stale when older than 5 days (US) or 14 days (TW closes up to nine days at Lunar New
  Year). Without a close it is valued at its cost and flagged.
- USD is the base currency: a TWD amount is divided by the last DEXTAUS rate (TWD per USD)
  known at T. Without a rate the USD total is unavailable (each currency's total still shows);
  a rate older than 10 days is flagged. Weights are shares of the USD total.
- The change since an earlier valuation leaves out deposits and withdrawals in between
  (converted at the later rate), so moving money in or out is not a gain or a loss.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic_core import to_jsonable_python

from autotrading.domain.markets import MARKETS, TW, US, Market
from autotrading.domain.splits import Split, splits_between

VALUATION_VERSION = "0.1.0"
BASE_CURRENCY = "USD"
FX_SERIES = "DEXTAUS"  # Taiwan dollars to one US dollar, noon buying rate in New York (H.10)
STALE_MARK_DAYS: dict[Market, int] = {"US": 5, "TW": 14}
FX_STALE_DAYS = 10
MONEY = Decimal("0.01")
QUANTITY = Decimal("0.000001")
PRICE = Decimal("0.000001")
WEIGHT = Decimal("0.0001")

Kind = Literal["buy", "sell", "dividend", "deposit", "withdrawal", "fee", "reversal"]
KINDS: tuple[Kind, ...] = ("buy", "sell", "dividend", "deposit", "withdrawal", "fee", "reversal")
TRADES: frozenset[Kind] = frozenset({"buy", "sell"})
CASH_KINDS: frozenset[Kind] = frozenset({"deposit", "withdrawal", "fee"})
Currency = Literal["USD", "TWD"]
CURRENCIES: tuple[Currency, ...] = ("USD", "TWD")
ZONE_OF_CURRENCY: dict[str, ZoneInfo] = {"USD": US.zone, "TWD": TW.zone}
PositionFlag = Literal["stale_mark", "no_mark", "oversold"]
Flag = Literal["negative_cash", "fx_missing", "fx_stale"]


@dataclass(frozen=True)
class Entry:
    id: UUID
    kind: Kind
    account: str
    market: Market | None
    instrument_id: UUID | None
    symbol: str | None
    currency: str
    trade_date: date
    quantity: Decimal | None
    price: Decimal | None
    amount: Decimal | None
    fee: Decimal | None
    recorded_at: datetime
    reverses_id: UUID | None = None

    @property
    def zone(self) -> ZoneInfo:
        return MARKETS[self.market].zone if self.market else ZONE_OF_CURRENCY[self.currency]

    @property
    def starts_at(self) -> datetime:
        """The start of the trade date in its zone: the entry counts from then."""
        return datetime.combine(self.trade_date, time(0, 0), tzinfo=self.zone)

    @property
    def basis_at(self) -> datetime:
        """The split basis of the trade: every split effective by the end of its day."""
        return datetime.combine(self.trade_date, time(23, 59, 59), tzinfo=self.zone)


@dataclass(frozen=True)
class Mark:
    """An end-of-day close (raw, on its own day's basis)."""

    close: Decimal
    session: date
    published_at: datetime
    row_id: str


@dataclass(frozen=True)
class Fx:
    """A DEXTAUS observation: TWD per USD."""

    value: Decimal
    observation_date: date
    published_at: datetime
    row_id: str


@dataclass(frozen=True)
class Position:
    account: str
    market: Market
    instrument_id: UUID
    symbol: str
    currency: str
    quantity: Decimal  # on T's split basis
    cost: Decimal  # the remaining cost
    average_cost: Decimal | None  # per share on T's basis
    realized: Decimal
    mark: Mark | None
    price: Decimal | None  # the close moved to T's split basis
    market_value: Decimal  # at the close, or at cost without one
    unrealized: Decimal | None
    value_usd: Decimal | None
    weight: Decimal | None  # share of the USD total
    flags: tuple[PositionFlag, ...]


@dataclass(frozen=True)
class Cash:
    account: str
    currency: str
    balance: Decimal
    value_usd: Decimal | None
    weight: Decimal | None


@dataclass(frozen=True)
class CurrencyTotal:
    currency: str
    positions: Decimal  # market value of the open positions
    cash: Decimal
    total: Decimal
    realized: Decimal  # closed and open positions
    unrealized: Decimal  # marked positions only
    contributions: Decimal  # deposits less withdrawals to T


@dataclass(frozen=True)
class Valuation:
    version: str
    known_at: datetime
    system_time: datetime
    positions: tuple[Position, ...]
    cash: tuple[Cash, ...]
    totals: tuple[CurrencyTotal, ...]
    fx: Fx | None
    fx_lag_days: int | None
    equity_usd: Decimal | None
    flags: tuple[Flag, ...]
    entries: int  # entries counted

    def total(self, currency: str) -> CurrencyTotal | None:
        return next((t for t in self.totals if t.currency == currency), None)


@dataclass
class _Book:
    account: str
    market: Market
    instrument_id: UUID
    symbol: str
    currency: str
    quantity: Fraction = Fraction(0)
    cost: Fraction = Fraction(0)
    realized: Fraction = Fraction(0)
    oversold: bool = False


@dataclass
class _Totals:
    positions: Fraction = Fraction(0)
    cash: Fraction = Fraction(0)
    realized: Fraction = Fraction(0)
    unrealized: Fraction = Fraction(0)
    contributions: Fraction = Fraction(0)
    used: bool = False
    accounts: set[str] = field(default_factory=set)


def _decimal(value: Fraction, quantum: Decimal) -> Decimal:
    return (Decimal(value.numerator) / Decimal(value.denominator)).quantize(quantum)


def _factor(splits: Iterable[Split], since: datetime, at: datetime) -> Fraction:
    factor = Fraction(1)
    for split in splits_between(splits, since, at):
        factor *= split.ratio
    return factor


def counted(entries: Iterable[Entry], at: datetime, system_time: datetime) -> list[Entry]:
    """The entries that count at (T, S), in the order they apply."""
    known = [e for e in entries if e.recorded_at <= system_time]
    reversed_ids = {e.reverses_id for e in known if e.kind == "reversal"}
    return sorted(
        (
            e
            for e in known
            if e.kind != "reversal" and e.id not in reversed_ids and e.starts_at <= at
        ),
        key=lambda e: (e.trade_date, e.kind == "sell", e.recorded_at, str(e.id)),
    )


def held(
    entries: Iterable[Entry],
    account: str,
    instrument_id: UUID,
    splits: Sequence[Split],
    at: datetime,
    system_time: datetime,
) -> Fraction:
    """The quantity of one instrument on one account at (T, S), on T's split basis."""
    quantity = Fraction(0)
    for e in counted(entries, at, system_time):
        if e.kind in TRADES and e.account == account and e.instrument_id == instrument_id:
            assert e.quantity is not None
            q = Fraction(e.quantity) * _factor(splits, e.basis_at, at)
            quantity += q if e.kind == "buy" else -q
    return quantity


def _usd(amount: Fraction, currency: str, fx: Fx | None) -> Fraction | None:
    if currency == BASE_CURRENCY:
        return amount
    if fx is None:
        return None
    return amount / Fraction(fx.value)


def value(
    entries: Iterable[Entry],
    marks: Mapping[UUID, Mark],
    splits: Mapping[UUID, Sequence[Split]],
    fx: Fx | None,
    at: datetime,
    system_time: datetime,
) -> Valuation:
    """The holdings at T as recorded by S, with the closes, splits and rate known at T."""
    used = counted(entries, at, system_time)
    books: dict[tuple[str, UUID], _Book] = {}
    cash: dict[tuple[str, str], Fraction] = defaultdict(Fraction)
    totals: dict[str, _Totals] = defaultdict(_Totals)
    for e in used:
        totals[e.currency].used = True
        key = (e.account, e.currency)
        if e.kind in TRADES:
            assert e.instrument_id and e.market and e.symbol and e.quantity and e.price
            book = books.setdefault(
                (e.account, e.instrument_id),
                _Book(e.account, e.market, e.instrument_id, e.symbol, e.currency),
            )
            q = Fraction(e.quantity) * _factor(splits.get(e.instrument_id, ()), e.basis_at, at)
            gross = Fraction(e.quantity) * Fraction(e.price)
            fee = Fraction(e.fee or 0)
            if e.kind == "buy":
                book.quantity += q
                book.cost += gross
                cash[key] -= gross + fee
            else:
                if book.quantity <= 0:
                    cost_out, book.oversold = Fraction(0), True
                elif q > book.quantity:
                    cost_out, book.oversold = book.cost, True
                else:
                    cost_out = book.cost * q / book.quantity
                book.realized += gross - cost_out
                book.cost -= cost_out
                book.quantity -= q
                cash[key] += gross - fee
        else:
            assert e.amount is not None
            amount = Fraction(e.amount)
            if e.kind in ("deposit", "dividend"):
                cash[key] += amount
            else:
                cash[key] -= amount
            if e.kind == "deposit":
                totals[e.currency].contributions += amount
            elif e.kind == "withdrawal":
                totals[e.currency].contributions -= amount

    open_books = [b for b in books.values() if b.quantity != 0 or b.oversold]
    for book in books.values():
        totals[book.currency].realized += book.realized

    priced: list[tuple[_Book, Fraction, Fraction | None, Mark | None, list[PositionFlag]]] = []
    for book in open_books:
        mark = marks.get(book.instrument_id)
        flags: list[PositionFlag] = ["oversold"] if book.oversold else []
        price: Fraction | None = None
        if mark is None:
            flags.append("no_mark")
            market_value = book.cost
        else:
            basis = datetime.combine(
                mark.session, time(23, 59, 59), tzinfo=MARKETS[book.market].zone
            )
            price = Fraction(mark.close) / _factor(splits.get(book.instrument_id, ()), basis, at)
            market_value = book.quantity * price
            if at - mark.published_at > timedelta(days=STALE_MARK_DAYS[book.market]):
                flags.append("stale_mark")
            totals[book.currency].unrealized += market_value - book.cost
        totals[book.currency].positions += market_value
        priced.append((book, market_value, price, mark, flags))
    for (_, currency), balance in cash.items():
        totals[currency].cash += balance

    missing_rate = fx is None and any(
        c != BASE_CURRENCY and (t.positions or t.cash) for c, t in totals.items()
    )
    equity: Fraction | None = None
    if not missing_rate:
        equity = Fraction(0)
        for currency, t in totals.items():
            converted = _usd(t.positions + t.cash, currency, fx)
            equity += converted if converted is not None else 0
    equity_usd = _decimal(equity, MONEY) if equity is not None else None

    def weight(amount_usd: Fraction | None) -> Decimal | None:
        if amount_usd is None or equity is None or equity <= 0:
            return None
        return _decimal(amount_usd / equity, WEIGHT)

    positions = []
    for book, market_value, price, mark, flags in sorted(
        priced, key=lambda p: (p[0].market, p[0].symbol, p[0].account)
    ):
        in_usd = _usd(market_value, book.currency, fx)
        positions.append(
            Position(
                account=book.account,
                market=book.market,
                instrument_id=book.instrument_id,
                symbol=book.symbol,
                currency=book.currency,
                quantity=_decimal(book.quantity, QUANTITY),
                cost=_decimal(book.cost, MONEY),
                average_cost=(
                    _decimal(book.cost / book.quantity, PRICE) if book.quantity > 0 else None
                ),
                realized=_decimal(book.realized, MONEY),
                mark=mark,
                price=_decimal(price, PRICE) if price is not None else None,
                market_value=_decimal(market_value, MONEY),
                unrealized=_decimal(market_value - book.cost, MONEY) if mark else None,
                value_usd=_decimal(in_usd, MONEY) if in_usd is not None else None,
                weight=weight(in_usd),
                flags=tuple(flags),
            )
        )
    balances = []
    for (account, currency), balance in sorted(cash.items()):
        in_usd = _usd(balance, currency, fx)
        balances.append(
            Cash(
                account=account,
                currency=currency,
                balance=_decimal(balance, MONEY),
                value_usd=_decimal(in_usd, MONEY) if in_usd is not None else None,
                weight=weight(in_usd),
            )
        )

    lag = (at.astimezone(US.zone).date() - fx.observation_date).days if fx else None
    overall: list[Flag] = []
    if any(balance < 0 for balance in cash.values()):
        overall.append("negative_cash")
    if missing_rate:
        overall.append("fx_missing")
    if lag is not None and lag > FX_STALE_DAYS:
        overall.append("fx_stale")
    return Valuation(
        version=VALUATION_VERSION,
        known_at=at,
        system_time=system_time,
        positions=tuple(positions),
        cash=tuple(balances),
        totals=tuple(
            CurrencyTotal(
                currency=currency,
                positions=_decimal(t.positions, MONEY),
                cash=_decimal(t.cash, MONEY),
                total=_decimal(t.positions + t.cash, MONEY),
                realized=_decimal(t.realized, MONEY),
                unrealized=_decimal(t.unrealized, MONEY),
                contributions=_decimal(t.contributions, MONEY),
            )
            for currency, t in sorted(totals.items(), key=lambda kv: CURRENCIES.index(kv[0]))
            if t.used
        ),
        fx=fx,
        fx_lag_days=lag,
        equity_usd=equity_usd,
        flags=tuple(overall),
        entries=len(used),
    )


def change(before: Valuation, after: Valuation) -> Decimal | None:
    """The change in USD equity from `before` to `after`, less the deposits and withdrawals
    between them (converted at the later rate). None when either total is unavailable."""
    if before.equity_usd is None or after.equity_usd is None:
        return None
    flows = Fraction(0)
    for currency in CURRENCIES:
        moved = Fraction(_contributions(after, currency) - _contributions(before, currency))
        if not moved:
            continue
        converted = _usd(moved, currency, after.fx)
        if converted is None:
            return None
        flows += converted
    return _decimal(Fraction(after.equity_usd) - Fraction(before.equity_usd) - flows, MONEY)


def _contributions(valuation: Valuation, currency: str) -> Decimal:
    total = valuation.total(currency)
    return total.contributions if total else Decimal(0)


def document(valuation: Valuation) -> dict[str, Any]:
    """The valuation as stored in a snapshot (and recomputed by the verify): JSON values only,
    decimals as strings."""
    stored: dict[str, Any] = to_jsonable_python(asdict(valuation))
    return stored
