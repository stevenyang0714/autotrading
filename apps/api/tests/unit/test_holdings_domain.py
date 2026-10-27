"""Real holdings valued at a time T (M3.10, ADR-041 H3)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from autotrading.domain.holdings import (
    FX_STALE_DAYS,
    MONEY,
    PRICE,
    QUANTITY,
    STALE_MARK_DAYS,
    VALUATION_VERSION,
    WEIGHT,
    Entry,
    Fx,
    Kind,
    Mark,
    change,
    counted,
    held,
    value,
)
from autotrading.domain.markets import TW, Market
from autotrading.domain.splits import Split

SPY, TSMC = uuid4(), uuid4()
RECORDED = datetime(2026, 10, 27, 3, 0, tzinfo=UTC)
T = datetime(2026, 10, 27, 3, 12, tzinfo=UTC)  # 11:12 Singapore
TWD = Fx(Decimal("32.0"), date(2026, 10, 23), datetime(2026, 10, 26, 20, 0, tzinfo=UTC), "fx")


def entry(
    kind: Kind,
    day: date,
    *,
    account: str = "Firstrade",
    market: Market | None = None,
    instrument_id: UUID | None = None,
    quantity: str | None = None,
    price: str | None = None,
    amount: str | None = None,
    fee: str | None = None,
    currency: str = "USD",
    recorded_at: datetime = RECORDED,
    reverses_id: UUID | None = None,
) -> Entry:
    symbol = {SPY: "SPY", TSMC: "2330"}.get(instrument_id) if instrument_id else None
    return Entry(
        id=uuid4(),
        kind=kind,
        account=account,
        market=market,
        instrument_id=instrument_id,
        symbol=symbol,
        currency=currency,
        trade_date=day,
        quantity=Decimal(quantity) if quantity else None,
        price=Decimal(price) if price else None,
        amount=Decimal(amount) if amount else None,
        fee=Decimal(fee) if fee else None,
        recorded_at=recorded_at,
        reverses_id=reverses_id,
    )


def us(kind: Kind, day: date, quantity: str, price: str, **kw: object) -> Entry:
    return entry(kind, day, market="US", instrument_id=SPY, quantity=quantity, price=price, **kw)  # type: ignore[arg-type]


def tw(kind: Kind, day: date, quantity: str, price: str, **kw: object) -> Entry:
    return entry(
        kind,
        day,
        account="元大",
        market="TW",
        instrument_id=TSMC,
        currency="TWD",
        quantity=quantity,
        price=price,
        **kw,  # type: ignore[arg-type]
    )


def mark(close: str, session: date, published_at: datetime) -> Mark:
    return Mark(Decimal(close), session, published_at, "bar")


SPY_MARK = mark("610", date(2026, 10, 23), datetime(2026, 10, 24, 0, 0, tzinfo=UTC))
TSMC_MARK = mark("1500", date(2026, 10, 22), datetime(2026, 10, 22, 21, 20, tzinfo=UTC))


def test_the_valuation_parameters_are_pinned_to_their_version() -> None:
    # A change to any of these is a new valuation version (snapshots name the version used).
    assert VALUATION_VERSION == "0.1.0"
    assert STALE_MARK_DAYS == {"US": 5, "TW": 14}
    assert FX_STALE_DAYS == 10
    assert [str(q) for q in (MONEY, QUANTITY, PRICE, WEIGHT)] == [
        "0.01",
        "0.000001",
        "0.000001",
        "0.0001",
    ]


def test_average_cost_a_sell_and_fees_in_cash_only() -> None:
    entries = [
        entry("deposit", date(2026, 10, 1), amount="10000"),
        us("buy", date(2026, 10, 2), "10", "400", fee="1"),
        us("buy", date(2026, 10, 5), "10", "500"),
        us("sell", date(2026, 10, 6), "5", "600", fee="1"),
    ]
    result = value(entries, {SPY: SPY_MARK}, {}, None, T, T)
    (position,) = result.positions
    assert (position.quantity, position.cost, position.average_cost) == (
        Decimal("15.000000"),
        Decimal("6750.00"),
        Decimal("450.000000"),
    )
    assert (position.realized, position.market_value, position.unrealized) == (
        Decimal("750.00"),
        Decimal("9150.00"),
        Decimal("2400.00"),
    )
    (cash,) = result.cash
    assert cash.balance == Decimal("3998.00")  # 10000 - 4001 - 5000 + 2999
    assert result.equity_usd == Decimal("13148.00")
    assert (position.weight, cash.weight) == (Decimal("0.6959"), Decimal("0.3041"))
    (usd,) = result.totals
    assert (usd.realized, usd.unrealized, usd.contributions) == (
        Decimal("750.00"),
        Decimal("2400.00"),
        Decimal("10000.00"),
    )
    assert result.flags == () and position.flags == ()
    assert result.entries == 4


def test_a_reversal_removes_its_entry_from_every_time_once_recorded() -> None:
    later = RECORDED + timedelta(days=1)
    buy = us("buy", date(2026, 10, 2), "10", "400")
    wrong = us("buy", date(2026, 10, 5), "100", "500")
    fix = entry(
        "reversal",
        date(2026, 10, 5),
        reverses_id=wrong.id,
        recorded_at=later,
    )
    entries = [buy, wrong, fix]
    assert [e.id for e in counted(entries, T, RECORDED)] == [buy.id, wrong.id]
    assert [e.id for e in counted(entries, T, later)] == [buy.id]
    (position,) = value(entries, {SPY: SPY_MARK}, {}, None, later, later).positions
    assert position.quantity == Decimal("10.000000")


def test_splits_after_the_trade_scale_quantity_and_the_close_moves_to_the_basis() -> None:
    split = Split(date(2026, 6, 10), Decimal(1), Decimal(4))
    at = datetime(2026, 6, 10, 16, 0, tzinfo=UTC)  # noon in New York on the ex-date
    before_split = mark("420", date(2026, 6, 9), datetime(2026, 6, 10, 0, 0, tzinfo=UTC))
    entries = [us("buy", date(2026, 6, 1), "10", "400")]
    (position,) = value(entries, {SPY: before_split}, {SPY: [split]}, None, at, T).positions
    assert (position.quantity, position.average_cost, position.price) == (
        Decimal("40.000000"),
        Decimal("100.000000"),
        Decimal("105.000000"),
    )
    assert position.market_value == Decimal("4200.00")
    # A buy on the ex-date is already on the new basis.
    same_day = [us("buy", date(2026, 6, 10), "40", "100")]
    assert held(same_day, "Firstrade", SPY, [split], at, T) == 40


def test_a_taiwan_stock_dividend_adds_shares_without_cost() -> None:
    dividend = Split(date(2026, 7, 15), Decimal(1000), Decimal(1050), zone=TW.zone)
    at = datetime(2026, 7, 20, 3, 0, tzinfo=UTC)
    entries = [tw("buy", date(2026, 7, 1), "1000", "1000")]
    (position,) = value(entries, {}, {TSMC: [dividend]}, TWD, at, T).positions
    assert (position.quantity, position.cost, position.average_cost) == (
        Decimal("1050.000000"),
        Decimal("1000000.00"),
        Decimal("952.380952"),
    )


def test_a_trade_counts_from_the_start_of_its_date_in_its_market() -> None:
    taipei_midnight = datetime(2026, 10, 26, 16, 0, tzinfo=UTC)  # 2026-10-27 00:00 Taipei
    new_york_midnight = datetime(2026, 10, 27, 4, 0, tzinfo=UTC)  # 2026-10-27 00:00 EDT
    taiwan = [tw("buy", date(2026, 10, 27), "1000", "1500")]
    american = [us("buy", date(2026, 10, 27), "1", "600")]
    second = timedelta(seconds=1)
    assert counted(taiwan, taipei_midnight - second, T) == []
    assert len(counted(taiwan, taipei_midnight, T)) == 1
    assert counted(american, new_york_midnight - second, T) == []
    assert len(counted(american, new_york_midnight, T)) == 1


def test_twd_converts_at_the_rate_and_without_one_only_the_usd_total_is_missing() -> None:
    entries = [
        entry("deposit", date(2026, 10, 1), amount="1000"),
        entry("deposit", date(2026, 10, 1), account="元大", currency="TWD", amount="100000"),
        tw("buy", date(2026, 10, 2), "40", "1450", fee="20"),
    ]
    result = value(entries, {TSMC: TSMC_MARK}, {}, TWD, T, T)
    (position,) = result.positions
    assert (position.market_value, position.value_usd) == (Decimal("60000.00"), Decimal("1875.00"))
    twd = result.total("TWD")
    assert twd is not None and (twd.cash, twd.total) == (Decimal("41980.00"), Decimal("101980.00"))
    assert result.equity_usd == Decimal("4186.88")  # 1000 + 101980 / 32
    assert result.fx_lag_days == 3  # Monday 10-26 in New York, rate of Friday 10-23
    assert result.flags == ()
    missing = value(entries, {TSMC: TSMC_MARK}, {}, None, T, T)
    assert missing.equity_usd is None and missing.flags == ("fx_missing",)
    assert missing.positions[0].value_usd is None and missing.positions[0].weight is None
    usd = missing.total("USD")
    assert usd is not None and usd.total == Decimal("1000.00")
    old = Fx(TWD.value, date(2026, 10, 9), TWD.published_at, "fx")
    assert value(entries, {TSMC: TSMC_MARK}, {}, old, T, T).flags == ("fx_stale",)


def test_marks_are_stale_after_five_us_days_or_fourteen_taiwan_days() -> None:
    week_old = T - timedelta(days=6)
    entries = [us("buy", date(2026, 10, 1), "1", "600"), tw("buy", date(2026, 10, 1), "1", "1")]
    marks = {
        SPY: mark("610", date(2026, 10, 20), week_old),
        TSMC: mark("1500", date(2026, 10, 20), week_old),
    }
    by_symbol = {p.symbol: p.flags for p in value(entries, marks, {}, TWD, T, T).positions}
    assert by_symbol == {"SPY": ("stale_mark",), "2330": ()}
    marks[TSMC] = mark("1500", date(2026, 10, 10), T - timedelta(days=15))
    by_symbol = {p.symbol: p.flags for p in value(entries, marks, {}, TWD, T, T).positions}
    assert by_symbol["2330"] == ("stale_mark",)


def test_without_a_close_a_position_is_valued_at_cost_and_flagged() -> None:
    (position,) = value([us("buy", date(2026, 10, 1), "3", "100")], {}, {}, None, T, T).positions
    assert (position.market_value, position.unrealized, position.price) == (
        Decimal("300.00"),
        None,
        None,
    )
    assert position.flags == ("no_mark",)


def test_same_day_buys_apply_before_sells_and_reversing_a_buy_leaves_an_oversold_position() -> None:
    later = RECORDED + timedelta(hours=1)
    sell = us("sell", date(2026, 10, 2), "5", "620")
    buy = us("buy", date(2026, 10, 2), "5", "600", recorded_at=later)
    closed = value([sell, buy], {SPY: SPY_MARK}, {}, None, T, later)
    assert closed.positions == ()  # a closed position leaves only its realized gain
    usd = closed.total("USD")
    assert usd is not None and usd.realized == Decimal("100.00")
    undone = entry("reversal", date(2026, 10, 2), reverses_id=buy.id, recorded_at=later)
    (position,) = value([sell, buy, undone], {SPY: SPY_MARK}, {}, None, T, later).positions
    assert position.quantity == Decimal("-5.000000") and "oversold" in position.flags


def test_a_negative_cash_balance_is_flagged() -> None:
    result = value([us("buy", date(2026, 10, 2), "1", "600")], {SPY: SPY_MARK}, {}, None, T, T)
    assert result.cash[0].balance == Decimal("-600.00")
    assert result.flags == ("negative_cash",)


def test_the_change_leaves_out_deposits_and_withdrawals() -> None:
    first = datetime(2026, 10, 20, 3, 0, tzinfo=UTC)
    entries = [
        entry("deposit", date(2026, 10, 1), amount="1000"),
        us("buy", date(2026, 10, 2), "10", "100"),
        entry("deposit", date(2026, 10, 21), amount="500"),
        entry("withdrawal", date(2026, 10, 22), amount="200"),
        entry("dividend", date(2026, 10, 22), market="US", instrument_id=SPY, amount="5"),
    ]
    before = value(entries, {SPY: mark("100", date(2026, 10, 16), first)}, {}, None, first, T)
    after = value(entries, {SPY: mark("110", date(2026, 10, 23), T)}, {}, None, T, T)
    assert (before.equity_usd, after.equity_usd) == (Decimal("1000.00"), Decimal("1405.00"))
    assert change(before, after) == Decimal("105.00")  # +100 on the shares, +5 dividend
