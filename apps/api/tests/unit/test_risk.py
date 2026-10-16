"""Paper portfolio and risk check (M2.3, ADR-031): every limit at its boundary."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from autotrading.domain.provenance import end_of_day
from autotrading.domain.risk import (
    Bar,
    Fill,
    Market,
    Proposal,
    RiskRulesFile,
    Trade,
    check,
    portfolio,
    standard_proposal,
)
from autotrading.domain.splits import Split
from autotrading.settings import get_settings

RULES = RiskRulesFile.model_validate(
    yaml.safe_load(Path(get_settings().resolved_config_dir() / "risk_rules.yaml").read_text())
).active()
# A released version never changes (ADR-031): a new rule_version is the only way to edit one.
PINNED = {"0.1.0": "7f04d48de3b3ded92d9d95e51f841610a483c646b885dbf790dfb8bdf9dfb4d5"}
LAST = date(2026, 10, 9)  # a Friday
T = end_of_day(LAST)


def sessions(count: int, last: date = LAST) -> list[date]:
    days: list[date] = []
    day = last
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return list(reversed(days))


def bars(
    closes: list[float], volume: float = 1_000_000, last: date = LAST, feed: str = "end_of_day"
) -> list[Bar]:
    return [
        Bar(day, Decimal(str(c)), Decimal(str(volume)), feed, end_of_day(day))
        for day, c in zip(sessions(len(closes), last), closes, strict=True)
    ]


def market(ticker: str, closes: list[float], **kwargs: object) -> Market:
    return Market(
        ticker,
        bars(closes, **{k: v for k, v in kwargs.items() if k in ("volume", "last", "feed")}),  # type: ignore[arg-type]
        kwargs.get("splits", []),  # type: ignore[arg-type]
        Decimal("1.2"),
        RULES.sectors[ticker].sector if ticker in RULES.sectors else None,
    )


def trade(
    ticker: str, quantity: float, price: float, day: date, side: str = "buy", **kw: object
) -> Trade:
    return Trade(
        decision_id=f"{ticker}-{day}-{side}",
        ticker=ticker,
        side=side,  # type: ignore[arg-type]
        quantity=Decimal(str(quantity)),
        entry=Fill(day, Decimal(str(price)), end_of_day(day)),
        known_at=end_of_day(day),
        max_loss=Decimal(500),
        exit=kw.get("exit"),  # type: ignore[arg-type]
        exit_known_at=kw.get("exit_known_at"),  # type: ignore[arg-type]
    )


def limits(result: object) -> dict[str, str]:
    return {r.limit_id: r.status for r in result.limits}  # type: ignore[attr-defined]


def proposal(ticker: str, quantity: float, max_loss: float | None = 1000) -> Proposal:
    return Proposal(
        ticker=ticker,
        side="buy",
        quantity=Decimal(str(quantity)),
        max_loss=None if max_loss is None else Decimal(str(max_loss)),
    )


def test_the_active_rule_set_is_pinned() -> None:
    assert RULES.rule_version == "0.1.0"
    assert RULES.content_sha256() == PINNED["0.1.0"]
    assert RULES.capital == 100_000
    assert set(RULES.sectors) >= {"AAPL", "MSFT", "GOOGL", "META", "NVDA", "JPM", "XOM"}


def test_an_empty_book_passes_a_modest_trade_and_the_standard_position() -> None:
    aapl = market("AAPL", [100.0] * 30)
    book = portfolio(RULES, T, [], {"AAPL": aapl})
    assert (book.equity, book.gross, book.drawdown_pct, book.positions) == (100_000, 0, 0, [])
    result = check(RULES, T, book, proposal("AAPL", 50), aapl)
    assert result.verdict == "pass"
    assert result.notional == Decimal("5000.00")
    standard = standard_proposal(RULES, "AAPL", Decimal(100))
    assert (standard.quantity, standard.max_loss, standard.side) == (
        Decimal(50),
        Decimal("1000.00"),
        "buy",
    )
    assert check(RULES, T, book, standard, aapl).verdict == "pass"


def test_position_size_at_and_above_ten_percent() -> None:
    aapl = market("AAPL", [100.0] * 30)
    book = portfolio(RULES, T, [], {"AAPL": aapl})
    assert (
        limits(check(RULES, T, book, proposal("AAPL", 100), aapl))["position"] == "pass"
    )  # 10.00%
    over = check(RULES, T, book, proposal("AAPL", 100.01), aapl)  # 10.001%: shown as 10.00
    position = next(r for r in over.limits if r.limit_id == "position")
    assert (position.status, position.value, over.verdict) == ("veto", Decimal("10.00"), "veto")
    # held shares count: 60 held + 50 new = 11%
    held = portfolio(RULES, T, [trade("AAPL", 60, 100, LAST - timedelta(days=3))], {"AAPL": aapl})
    assert limits(check(RULES, T, held, proposal("AAPL", 50), aapl))["position"] == "veto"


def test_the_maximum_loss_must_be_stated_and_at_most_one_percent() -> None:
    aapl = market("AAPL", [100.0] * 30)
    book = portfolio(RULES, T, [], {"AAPL": aapl})
    missing = check(RULES, T, book, proposal("AAPL", 10, None), aapl)
    assert limits(missing)["max_loss_stated"] == "veto" and missing.verdict == "veto"
    assert limits(check(RULES, T, book, proposal("AAPL", 10, 1000), aapl))["max_loss"] == "pass"
    assert limits(check(RULES, T, book, proposal("AAPL", 10, 1001), aapl))["max_loss"] == "veto"


def test_sector_concentration_with_unlimited_and_unknown_sectors() -> None:
    aapl, msft, nvda = (market(t, [100.0] * 30) for t in ("AAPL", "MSFT", "NVDA"))
    held = [
        trade("AAPL", 100, 100, LAST - timedelta(days=3)),
        trade("MSFT", 100, 100, LAST - timedelta(days=3)),
    ]
    book = portfolio(RULES, T, held, {"AAPL": aapl, "MSFT": msft, "NVDA": nvda})
    assert [(s.sector, s.pct, s.limited) for s in book.sectors] == [
        ("information_technology", Decimal("20.00"), True)
    ]
    assert limits(check(RULES, T, book, proposal("NVDA", 100), nvda))["sector"] == "pass"  # 30%
    assert limits(check(RULES, T, book, proposal("NVDA", 101), nvda))["sector"] == "veto"
    unknown = Market("ZZZ", bars([100.0] * 30), [], None, None)
    result = check(RULES, T, book, proposal("ZZZ", 10), unknown)
    assert limits(result)["sector"] == "veto"
    spy = market("SPY", [100.0] * 30)
    assert limits(check(RULES, T, book, proposal("SPY", 50), spy))["sector"] == "pass"


def test_trade_against_average_volume() -> None:
    thin = market("AAPL", [100.0] * 30, volume=5000)
    book = portfolio(RULES, T, [], {"AAPL": thin})
    assert limits(check(RULES, T, book, proposal("AAPL", 50), thin))["volume"] == "pass"  # 1%
    assert limits(check(RULES, T, book, proposal("AAPL", 51), thin))["volume"] == "veto"
    young = market("AAPL", [100.0] * 19)
    book = portfolio(RULES, T, [], {"AAPL": young})
    result = check(RULES, T, book, proposal("AAPL", 1), young)
    assert limits(result)["volume"] == "veto"
    assert "fewer than 20 sessions" in next(
        r.detail for r in result.limits if r.limit_id == "volume"
    )


def test_gross_exposure_without_leverage() -> None:
    names = ["AAPL", "JPM", "XOM", "AZO", "GOOGL", "LOW", "MSFT", "META", "ORLY"]
    markets = {t: market(t, [100.0] * 30) for t in names}
    markets["NVDA"] = market("NVDA", [100.0] * 30)
    # 9 positions of 10% each... but sectors cap: use a mix that stays within 30% per sector
    held = [
        trade(t, 100, 100, LAST - timedelta(days=3))
        for t in ["AAPL", "JPM", "XOM", "AZO", "GOOGL", "LOW", "META", "ORLY"]
    ]
    held += [
        trade("JPM", 60, 100, LAST - timedelta(days=2)),
        trade("XOM", 60, 100, LAST - timedelta(days=2)),
    ]
    book = portfolio(RULES, T, held, markets)
    assert book.gross_pct == Decimal("92.00")
    assert limits(check(RULES, T, book, proposal("NVDA", 80), markets["NVDA"]))["gross"] == "pass"
    assert limits(check(RULES, T, book, proposal("NVDA", 81), markets["NVDA"]))["gross"] == "veto"


@pytest.mark.parametrize(
    ("closes_last", "feed", "status"),
    [
        (LAST, "end_of_day", "pass"),
        (LAST - timedelta(days=6), "end_of_day", "veto"),
        (LAST, "fixture", "veto"),
    ],
)
def test_the_price_must_be_a_recent_end_of_day_close(
    closes_last: date, feed: str, status: str
) -> None:
    aapl = market("AAPL", [100.0] * 30, last=closes_last, feed=feed)
    book = portfolio(RULES, T, [], {"AAPL": aapl})
    assert limits(check(RULES, T, book, proposal("AAPL", 10), aapl))["price"] == status


def test_a_short_counts_by_its_size_and_a_split_never_looks_like_a_gain() -> None:
    days = sessions(30)
    split = Split(days[20], Decimal(1), Decimal(4))
    nvda = market("NVDA", [400.0] * 20 + [100.0] * 10, splits=[split])
    short = trade("NVDA", 10, 400, days[5], side="sell")
    book = portfolio(RULES, T, [short], {"NVDA": nvda})
    position = book.positions[0]
    assert (position.shares, position.entry_price, position.mark) == (
        Decimal(40),
        Decimal(100),
        Decimal(100),
    )
    assert (position.market_value, position.pnl, position.weight_pct) == (
        Decimal("-4000.00"),
        0,
        Decimal("4.00"),
    )
    assert (book.gross, book.net, book.equity) == (
        Decimal("4000.00"),
        Decimal("-4000.00"),
        Decimal("100000.00"),
    )


def test_exits_realize_pnl_and_leave_the_book() -> None:
    days = sessions(30)
    aapl = market("AAPL", [100.0] * 20 + [110.0] * 10)
    closed = trade(
        "AAPL",
        10,
        100,
        days[2],
        exit=Fill(days[25], Decimal(110), end_of_day(days[25])),
        exit_known_at=end_of_day(days[25]),
    )
    book = portfolio(RULES, T, [closed], {"AAPL": aapl})
    assert (book.positions, book.realized_pnl, book.equity) == (
        [],
        Decimal("100.00"),
        Decimal("100100.00"),
    )
    # as known before the exit, the trade is still open
    before = portfolio(RULES, end_of_day(days[24]), [closed], {"AAPL": aapl})
    assert len(before.positions) == 1 and before.positions[0].pnl == Decimal("100.00")


def test_the_equity_curve_peak_and_drawdown() -> None:
    days = sessions(30)
    path = [100.0] * 10 + [150.0] * 10 + [50.0] * 10
    aapl = market("AAPL", path)
    held = trade("AAPL", 200, 100, days[5])
    book = portfolio(RULES, T, [held], {"AAPL": aapl})
    assert book.peak_equity == Decimal("110000.00")  # +50 a share on 200 shares
    assert book.equity == Decimal("90000.00")
    assert book.drawdown_pct == Decimal("18.18")
    assert book.curve[0].day == days[5] and book.curve[-1].equity == Decimal("90000.00")


def test_the_same_inputs_always_give_the_same_verdict() -> None:
    aapl = market("AAPL", [100.0] * 30)
    book = portfolio(RULES, T, [trade("AAPL", 40, 100, LAST - timedelta(days=3))], {"AAPL": aapl})
    first = check(RULES, T, book, proposal("AAPL", 70), aapl)
    again = check(
        RULES,
        T,
        portfolio(RULES, T, [trade("AAPL", 40, 100, LAST - timedelta(days=3))], {"AAPL": aapl}),
        proposal("AAPL", 70),
        aapl,
    )
    assert first == again and first.verdict == "veto"


def test_a_drawdown_alert_when_the_threshold_is_crossed_either_way() -> None:
    from uuid import uuid4

    from autotrading.repositories.risk import drawdown_alert

    days = sessions(30)
    aapl = market("AAPL", [100.0] * 10 + [150.0] * 10 + [50.0] * 10)
    book = portfolio(RULES, T, [trade("AAPL", 200, 100, days[5])], {"AAPL": aapl})
    snapshot = uuid4()
    down = drawdown_alert(RULES, book, Decimal("4.2"), snapshot)
    assert down is not None
    assert (down.kind, down.level, down.previous_level, down.direction) == ("portfolio", 1, 0, "up")
    assert down.title == "Paper portfolio drawdown reached 18.18% (alert at 10%)"
    assert down.evidence[0]["table"] == "portfolio_snapshots"
    assert drawdown_alert(RULES, book, Decimal("12"), snapshot) is None  # still beyond
    flat = portfolio(RULES, T, [], {})
    back = drawdown_alert(RULES, flat, Decimal("12"), snapshot)
    assert back is not None and (back.level, back.direction) == (0, "down")
    assert drawdown_alert(RULES, flat, None, snapshot) is None  # never crossed
