"""FinMind datasets (M3.7b, ADR-040): parsing into the shapes the TWSE adapter stores. Pure.

Every dataset is a JSON array of objects with a Gregorian `date` and `stock_id`. The parsers
are strict: a missing field raises, so a changed dataset fails the run instead of storing half
of it. Numbers arrive as JSON numbers; they are read through `Decimal(str(x))`.

- Prices become the TWSE `DayRow` (same fields as STOCK_DAY_ALL: shares, TWD, trades).
- Margin rows become the TWSE margin measure ids, in lots (the same units as MI_MARGN: checked
  against the recorded 2026-10-21 files, TW19).
- PER rows become the three exchange valuation measures.
- Ex-dividend results (TW20): a 息 row is a cash dividend whose amount must reproduce the
  reference price (before − cash); a 權 row's `stock_and_cache_dividend` is not a ratio, so the
  stock dividend ratio is derived from before / reference − 1; a 權息 row cannot be split from
  two prices and is left out with a note.
- Institutional investors are summed per session into net buying by group, in shares; foreign
  shareholding is read as shares and percents.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from autotrading.domain.twse import DayRow, ValuationRow, tick

FOUR = Decimal("0.0001")
# FinMind margin field -> the TWSE measure id (domain/twse.MARGIN_FIELDS), all in lots.
MARGIN_MEASURES: dict[str, str] = {
    "MarginPurchaseBuy": "margin_purchase",
    "MarginPurchaseSell": "margin_sale",
    "MarginPurchaseCashRepayment": "margin_cash_redemption",
    "MarginPurchaseYesterdayBalance": "margin_balance_previous",
    "MarginPurchaseTodayBalance": "margin_balance",
    "MarginPurchaseLimit": "margin_limit",
    "ShortSaleBuy": "short_covering",
    "ShortSaleSell": "short_sale",
    "ShortSaleCashRepayment": "short_stock_redemption",
    "ShortSaleYesterdayBalance": "short_balance_previous",
    "ShortSaleTodayBalance": "short_balance",
    "ShortSaleLimit": "short_limit",
    "OffsetLoanAndShort": "margin_short_offset",
}
# Institutional investor groups as FinMind names them (TWSE's T86 columns).
FOREIGN = ("Foreign_Investor", "Foreign_Dealer_Self")
TRUST = ("Investment_Trust",)
DEALER = ("Dealer_self", "Dealer_Hedging")
FLOW_UNITS: dict[str, str] = {
    "inst_foreign_buy": "shares",
    "inst_foreign_sell": "shares",
    "inst_foreign_net": "shares",
    "inst_trust_net": "shares",
    "inst_dealer_net": "shares",
    "inst_total_net": "shares",
}
SHAREHOLDING_UNITS: dict[str, str] = {
    "foreign_shares": "shares",
    "shares_issued": "shares",
    "foreign_ratio": "percent",
    "foreign_limit_ratio": "percent",
}


class FinMindFormatError(ValueError):
    """A FinMind dataset is not in the expected shape."""


def _rows(payload: Any) -> list[Mapping[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise FinMindFormatError("expected a FinMind envelope with a data array of objects")
    return data


def _field(row: Mapping[str, Any], key: str) -> Any:
    if key not in row:
        raise FinMindFormatError(f"field {key!r} missing (fields: {', '.join(row)})")
    return row[key]


def number(value: Any) -> Decimal | None:
    """A FinMind number (JSON number or numeric string), or None for an empty value."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        found = Decimal(str(value).strip())
    except InvalidOperation:
        raise FinMindFormatError(f"not a number: {value!r}") from None
    if not found.is_finite():
        raise FinMindFormatError(f"not a finite number: {value!r}")
    return found


def amount(value: Any) -> Decimal:
    found = number(value)
    return Decimal(0) if found is None else found


def _day(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise FinMindFormatError(f"not a date: {value!r}") from None


# ---------- TaiwanStockPrice ----------


def price_rows(payload: Any) -> list[DayRow]:
    """TaiwanStockPrice as STOCK_DAY_ALL rows: volume in shares, value in TWD, `spread` the
    change, `Trading_turnover` the number of trades. FinMind's `spread` is the change against the
    previous close on an ordinary session, but 0 on an ex-date (checked on every recorded ex-date,
    tests/fixtures/finmind_prices; ADR-042 SC6): the session's reference price comes from the
    ex-dividend results (`ex_reference_price`), never from it."""
    return [
        DayRow(
            code=str(_field(r, "stock_id")).strip(),
            name="",
            session=_day(_field(r, "date")),
            open=number(_field(r, "open")),
            high=number(_field(r, "max")),
            low=number(_field(r, "min")),
            close=number(_field(r, "close")),
            change=number(_field(r, "spread")),
            volume=amount(_field(r, "Trading_Volume")),
            value=amount(_field(r, "Trading_money")),
            transactions=amount(_field(r, "Trading_turnover")),
        )
        for r in _rows(payload)
    ]


# ---------- TaiwanStockMarginPurchaseShortSale ----------


@dataclass(frozen=True)
class MarginDay:
    code: str
    session: date
    values: Mapping[str, Decimal]  # measure id -> lots
    note: str | None


def margin_days(payload: Any) -> list[MarginDay]:
    out = []
    for r in _rows(payload):
        note = str(r.get("Note") or "").strip()
        out.append(
            MarginDay(
                code=str(_field(r, "stock_id")).strip(),
                session=_day(_field(r, "date")),
                values={m: amount(_field(r, f)) for f, m in MARGIN_MEASURES.items()},
                note=note or None,
            )
        )
    return out


# ---------- TaiwanStockPER ----------


def valuation_rows(payload: Any) -> list[ValuationRow]:
    """TaiwanStockPER as BWIBBU rows; FinMind gives no close, dividend year or quarter."""
    return [
        ValuationRow(
            code=str(_field(r, "stock_id")).strip(),
            session=_day(_field(r, "date")),
            close=None,
            pe=number(_field(r, "PER")),
            pb=number(_field(r, "PBR")),
            dividend_yield=number(_field(r, "dividend_yield")),
            dividend_year=None,
            fiscal_quarter=None,
        )
        for r in _rows(payload)
    ]


# ---------- TaiwanStockDividendResult (TW20) ----------


@dataclass(frozen=True)
class DividendResult:
    code: str
    ex_date: date
    kind: str  # 息, 權 or 權息 as FinMind states it
    cash: Decimal | None  # TWD per share (息)
    stock_ratio: Decimal | None  # new shares per share (權), derived from the prices
    before_price: Decimal
    reference_price: Decimal
    accepted: bool
    note: str | None


def dividend_results(payload: Any, *, etf: bool = False) -> list[DividendResult]:
    """Each ex-date with the action the prices reproduce; a row that does not is kept with
    `accepted=False` and the reason, never stored."""
    out = []
    for r in _rows(payload):
        code = str(_field(r, "stock_id")).strip()
        ex_date = _day(_field(r, "date"))
        kind = str(_field(r, "stock_or_cache_dividend")).strip()
        stated = amount(_field(r, "stock_and_cache_dividend"))
        before = number(_field(r, "before_price"))
        reference = number(_field(r, "reference_price"))
        if before is None or reference is None or before <= 0 or reference <= 0:
            out.append(
                DividendResult(
                    code,
                    ex_date,
                    kind,
                    None,
                    None,
                    before or Decimal(0),
                    reference or Decimal(0),
                    False,
                    "no prices",
                )
            )
            continue
        cash = ratio = None
        accepted, note = True, None
        if kind == "息":
            cash = stated
            if abs(before - cash - reference) > tick(before, etf) or cash <= 0:
                accepted = False
                note = (
                    f"{code} {ex_date}: cash {cash} does not reproduce the reference price "
                    f"({before} - {cash} vs {reference})"
                )
        elif kind == "權":
            ratio = (before / reference - 1).quantize(FOUR)
            if not Decimal("0.0001") <= ratio <= Decimal(1):
                accepted = False
                note = f"{code} {ex_date}: stock dividend ratio {ratio} out of range"
        else:
            accepted = False
            note = (
                f"{code} {ex_date}: a combined ex-rights and ex-dividend ({kind}) cannot be "
                "split from two prices; not stored"
            )
        out.append(
            DividendResult(code, ex_date, kind, cash, ratio, before, reference, accepted, note)
        )
    return out


# ---------- TaiwanStockInstitutionalInvestorsBuySell ----------


@dataclass(frozen=True)
class FlowDay:
    code: str
    session: date
    values: Mapping[str, Decimal]  # measure id -> shares
    groups: tuple[str, ...]  # the FinMind names present


def _total(
    groups: Mapping[str, tuple[Decimal, Decimal]], names: Iterable[str], side: int
) -> Decimal:
    return sum((groups[n][side] for n in names if n in groups), Decimal(0))


def flow_days(payload: Any) -> tuple[list[FlowDay], list[str]]:
    """Net buying per session and group, in shares, and notes for sessions left out (no
    foreign-investor row: the file is incomplete for that day)."""
    buys: dict[tuple[str, date], dict[str, tuple[Decimal, Decimal]]] = defaultdict(dict)
    for r in _rows(payload):
        key = (str(_field(r, "stock_id")).strip(), _day(_field(r, "date")))
        buys[key][str(_field(r, "name")).strip()] = (
            amount(_field(r, "buy")),
            amount(_field(r, "sell")),
        )
    days, notes = [], []
    for (code, session), groups in sorted(buys.items()):
        if "Foreign_Investor" not in groups:
            notes.append(f"{code} {session}: no foreign investor row; flows not stored")
            continue

        foreign_buy, foreign_sell = _total(groups, FOREIGN, 0), _total(groups, FOREIGN, 1)
        trust = _total(groups, TRUST, 0) - _total(groups, TRUST, 1)
        dealer = _total(groups, DEALER, 0) - _total(groups, DEALER, 1)
        days.append(
            FlowDay(
                code,
                session,
                {
                    "inst_foreign_buy": foreign_buy,
                    "inst_foreign_sell": foreign_sell,
                    "inst_foreign_net": foreign_buy - foreign_sell,
                    "inst_trust_net": trust,
                    "inst_dealer_net": dealer,
                    "inst_total_net": foreign_buy - foreign_sell + trust + dealer,
                },
                tuple(sorted(groups)),
            )
        )
    return days, notes


# ---------- TaiwanStockShareholding ----------


@dataclass(frozen=True)
class ShareholdingDay:
    code: str
    session: date
    values: Mapping[str, Decimal]  # measure id -> shares or percent


def shareholding_days(payload: Any) -> list[ShareholdingDay]:
    return [
        ShareholdingDay(
            code=str(_field(r, "stock_id")).strip(),
            session=_day(_field(r, "date")),
            values={
                "foreign_shares": amount(_field(r, "ForeignInvestmentShares")),
                "shares_issued": amount(_field(r, "NumberOfSharesIssued")),
                "foreign_ratio": amount(_field(r, "ForeignInvestmentSharesRatio")),
                "foreign_limit_ratio": amount(_field(r, "ForeignInvestmentUpperLimitRatio")),
            },
        )
        for r in _rows(payload)
    ]
