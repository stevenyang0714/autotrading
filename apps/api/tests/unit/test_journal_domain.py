"""Evidence comparison and paper performance (M1.6, ADR-027 J2, J3)."""

from datetime import UTC, date, datetime
from decimal import Decimal

from autotrading.domain.journal import Mark, compare, paper_return
from autotrading.domain.splits import Split


def mark(day: date, close: str) -> Mark:
    return Mark(
        day, Decimal(close), datetime.combine(day, datetime.min.time(), UTC).replace(hour=21)
    )


ENTRY, LATER = date(2026, 5, 1), date(2026, 6, 1)


def test_compare_reports_changed_fields_and_missing_rows() -> None:
    stored = {"value": "100", "period_end": "2025-09-27"}
    assert compare(stored, dict(stored)).status == "identical"
    changed = compare(stored, {"value": "101", "period_end": "2025-09-27"})
    assert (changed.status, changed.changed) == ("differs", ["value"])
    assert compare(stored, {**stored, "extra": 1}).changed == ["extra"]
    assert compare(stored, None).status == "missing"


def test_a_long_trade_against_spy() -> None:
    result = paper_return(
        "buy",
        Decimal(10),
        mark(ENTRY, "200"),
        mark(LATER, "220"),
        [],
        mark(ENTRY, "500"),
        mark(LATER, "510"),
        max_loss=Decimal(500),
    )
    assert (result.status, result.return_pct, result.pnl) == (
        "ok",
        Decimal("10.00"),
        Decimal("200.00"),
    )
    assert (result.benchmark_return_pct, result.relative) == (Decimal("2.00"), Decimal("8.00"))
    assert result.max_loss_breached is False


def test_a_short_trade_gains_when_the_price_falls_and_flags_the_maximum_loss() -> None:
    falls = paper_return(
        "sell", Decimal(10), mark(ENTRY, "200"), mark(LATER, "180"), [], None, None
    )
    assert (falls.return_pct, falls.pnl, falls.relative) == (
        Decimal("10.00"),
        Decimal("200.00"),
        None,
    )
    rises = paper_return(
        "sell", Decimal(10), mark(ENTRY, "200"), mark(LATER, "260"), [], None, None, Decimal(500)
    )
    assert (rises.return_pct, rises.pnl, rises.max_loss_breached) == (
        Decimal("-30.00"),
        Decimal("-600.00"),
        True,
    )


def test_a_split_after_entry_scales_the_entry_not_the_result() -> None:
    four_for_one = Split(date(2026, 5, 15), Decimal(1), Decimal(4))
    result = paper_return(
        "buy", Decimal(10), mark(ENTRY, "200"), mark(LATER, "55"), [four_for_one], None, None
    )
    assert (result.split_factor, result.entry_basis) == (Decimal(4), Decimal("50.000000"))
    assert (result.return_pct, result.pnl) == (Decimal("10.00"), Decimal("200.00"))  # 40 x $5
    # A split before the entry close changes nothing.
    earlier = Split(date(2026, 4, 1), Decimal(1), Decimal(4))
    assert (
        paper_return(
            "buy", Decimal(1), mark(ENTRY, "200"), mark(LATER, "220"), [earlier], None, None
        ).split_factor
        == 1
    )


def test_a_no_trade_shows_the_move_unsigned_and_without_money() -> None:
    result = paper_return(None, None, mark(ENTRY, "200"), mark(LATER, "180"), [], None, None)
    assert (result.return_pct, result.pnl, result.max_loss_breached) == (
        Decimal("-10.00"),
        None,
        None,
    )


def test_without_a_close_there_is_no_return() -> None:
    result = paper_return("buy", Decimal(1), None, mark(LATER, "1"), [], None, None)
    assert (result.status, result.detail) == ("unavailable", "no end-of-day close at the decision")
