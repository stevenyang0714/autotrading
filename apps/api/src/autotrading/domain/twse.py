"""TWSE OpenAPI files (M3.7, ADR-039): parsing and checks. Pure; no I/O.

Every OpenAPI endpoint serves only the latest session (TW1). The parsers are strict: a missing
field raises, so a changed file fails the run instead of storing half of it.

- Dates: ROC calendar ("1151021", "115/10/21" = 2026-10-21) or Gregorian ("20261021").
- Numbers: thousands separators removed; "", "--" and "-" are no value.
- MI_MARGN has no date: its session is the one STOCK_DAY_ALL names in the same run, checked by
  the chain of balances (each 前日餘額 must equal the stored 今日餘額 of the session before; TW6).
- Reference price: TWSE's change is against the session's reference price, so
  reference = close - change. With no corporate action the reference is the previous close;
  on an ex-date it is the previous close less the cash dividend, over one plus the stock
  dividend. A larger gap than one tick is an action this source did not tell (TW9).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

ROC_OFFSET = 1911
NO_VALUE = frozenset({"", "--", "-", "---"})


class TwseFormatError(ValueError):
    """A TWSE file is not in the expected shape."""


# ---------- values ----------


def roc_date(text: str) -> date:
    """'1151021' or '115/10/21' (ROC year 115) -> 2026-10-21."""
    raw = text.strip()
    if "/" in raw:
        year, month, day = raw.split("/")
    elif raw.isdigit() and len(raw) in (6, 7):
        year, month, day = raw[:-4], raw[-4:-2], raw[-2:]
    else:
        raise TwseFormatError(f"not an ROC date: {text!r}")
    return date(int(year) + ROC_OFFSET, int(month), int(day))


def gregorian_date(text: str) -> date:
    """'20261021' -> 2026-10-21."""
    raw = text.strip()
    if not (raw.isdigit() and len(raw) == 8):
        raise TwseFormatError(f"not a date: {text!r}")
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))


def number(text: Any) -> Decimal | None:
    """A TWSE number ('1,236', '-0.0400', '28.05'), or None for no value."""
    raw = str(text).strip().replace(",", "")
    if raw in NO_VALUE:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise TwseFormatError(f"not a number: {text!r}") from None
    if not value.is_finite():
        raise TwseFormatError(f"not a finite number: {text!r}")
    return value


def count(text: Any) -> Decimal:
    """A quantity of MI_MARGN, where a blank cell is zero."""
    found = number(text)
    return Decimal(0) if found is None else found


def _field(row: Mapping[str, Any], key: str) -> str:
    if key not in row:
        raise TwseFormatError(f"field {key!r} missing (fields: {', '.join(row)})")
    return str(row[key])


def _rows(payload: Any) -> list[Mapping[str, Any]]:
    if not isinstance(payload, list) or not all(isinstance(r, dict) for r in payload):
        raise TwseFormatError("expected a JSON array of objects")
    return payload


# ---------- STOCK_DAY_ALL ----------


@dataclass(frozen=True)
class DayRow:
    code: str
    name: str
    session: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None  # None: no trade that session
    change: Decimal | None
    volume: Decimal  # shares
    value: Decimal  # TWD
    transactions: Decimal


def day_rows(payload: Any) -> list[DayRow]:
    """/exchangeReport/STOCK_DAY_ALL (上市個股日成交資訊)."""
    return [
        DayRow(
            code=_field(r, "Code").strip(),
            name=_field(r, "Name").strip(),
            session=roc_date(_field(r, "Date")),
            open=number(_field(r, "OpeningPrice")),
            high=number(_field(r, "HighestPrice")),
            low=number(_field(r, "LowestPrice")),
            close=number(_field(r, "ClosingPrice")),
            change=number(_field(r, "Change")),
            volume=count(_field(r, "TradeVolume")),
            value=count(_field(r, "TradeValue")),
            transactions=count(_field(r, "Transaction")),
        )
        for r in _rows(payload)
    ]


def session_of(rows: Sequence[DayRow]) -> date:
    """The one session a STOCK_DAY_ALL file is for."""
    sessions = {r.session for r in rows}
    if len(sessions) != 1:
        raise TwseFormatError(f"STOCK_DAY_ALL names {len(sessions)} sessions, expected one")
    return sessions.pop()


# ---------- BWIBBU_d ----------


@dataclass(frozen=True)
class ValuationRow:
    code: str
    session: date
    close: Decimal | None
    pe: Decimal | None  # blank when the company has a loss
    pb: Decimal | None
    dividend_yield: Decimal | None  # percent
    dividend_year: int | None  # Gregorian year of the dividends the yield uses
    fiscal_quarter: str | None  # the earnings and book value quarter, e.g. 2026Q2


def valuation_rows(payload: Any) -> list[ValuationRow]:
    """/exchangeReport/BWIBBU_d (上市個股日本益比、殖利率及股價淨值比)."""
    out = []
    for r in _rows(payload):
        year = _field(r, "DividendYear").strip()
        quarter = _field(r, "FiscalYearQuarter").strip()
        out.append(
            ValuationRow(
                code=_field(r, "Code").strip(),
                session=gregorian_date(_field(r, "Date")),
                close=number(_field(r, "ClosePrice")),
                pe=number(_field(r, "PEratio")),
                pb=number(_field(r, "PBratio")),
                dividend_yield=number(_field(r, "DividendYield")),
                dividend_year=int(year) + ROC_OFFSET if year.isdigit() else None,
                fiscal_quarter=quarter or None,
            )
        )
    return out


# ---------- MI_MARGN ----------

# Field -> measure id, all in lots (張, 1,000 shares) except none: TW6, ADR-039.
MARGIN_FIELDS: dict[str, str] = {
    "融資買進": "margin_purchase",
    "融資賣出": "margin_sale",
    "融資現金償還": "margin_cash_redemption",
    "融資前日餘額": "margin_balance_previous",
    "融資今日餘額": "margin_balance",
    "融資限額": "margin_limit",
    "融券買進": "short_covering",
    "融券賣出": "short_sale",
    "融券現券償還": "short_stock_redemption",
    "融券前日餘額": "short_balance_previous",
    "融券今日餘額": "short_balance",
    "融券限額": "short_limit",
    "資券互抵": "margin_short_offset",
}


@dataclass(frozen=True)
class MarginRow:
    code: str
    values: Mapping[str, Decimal]  # measure id -> lots
    note: str | None  # 註記


def margin_rows(payload: Any) -> list[MarginRow]:
    """/exchangeReport/MI_MARGN (集中市場融資融券餘額): no date field."""
    out = []
    for r in _rows(payload):
        note = _field(r, "註記").strip()
        out.append(
            MarginRow(
                code=_field(r, "股票代號").strip(),
                values={m: count(_field(r, f)) for f, m in MARGIN_FIELDS.items()},
                note=note or None,
            )
        )
    return out


MarginStatus = Literal["verified", "partial", "unverified", "not_updated"]


@dataclass(frozen=True)
class MarginDating:
    """Whether a MI_MARGN file is the session STOCK_DAY_ALL names (TW6)."""

    status: MarginStatus
    mismatched: tuple[str, ...] = ()  # codes whose previous balance is not the stored one

    @property
    def accepted(self) -> bool:
        return self.status != "not_updated"


def margin_dating(
    rows: Iterable[MarginRow],
    previous: Mapping[str, Mapping[str, Decimal]] | None,
    *,
    adjacent: bool,
) -> MarginDating:
    """Check the file against the balances stored for the latest margin session before
    (`previous`: code -> margin_balance and short_balance; None when none is stored).
    `adjacent`: that stored session is the one right before the file's session.

    - every 今日餘額 equals the stored one: the file is still that session's, not updated;
    - nothing stored, or the stored session is not the one before: unverified (accepted, and
      checked again at the next session);
    - every code's 前日餘額 equals the stored 今日餘額: verified;
    - some do: partial (each mismatching code named); none do: not updated.
    """
    chosen = [r for r in rows if previous is None or r.code in previous]
    if not chosen:
        return MarginDating("not_updated")
    if previous is None:
        return MarginDating("unverified")
    pairs = (
        ("margin_balance_previous", "margin_balance"),
        ("short_balance_previous", "short_balance"),
    )
    if all(r.values[today] == previous[r.code][today] for r in chosen for _, today in pairs):
        return MarginDating("not_updated")
    if not adjacent:
        return MarginDating("unverified")
    linked = {
        r.code
        for r in chosen
        if all(r.values[before] == previous[r.code][today] for before, today in pairs)
    }
    if len(linked) == len(chosen):
        return MarginDating("verified")
    if not linked:
        return MarginDating("not_updated")
    return MarginDating("partial", tuple(sorted(r.code for r in chosen if r.code not in linked)))


# ---------- TWT48U_ALL ----------


@dataclass(frozen=True)
class ExRightRow:
    code: str
    ex_date: date
    kind: str  # 權 (rights or stock dividend), 息 (cash dividend), 權息 (both)
    cash: Decimal | None  # TWD per share; None while not announced
    stock_ratio: Decimal | None  # 無償配股率
    subscription_ratio: Decimal | None  # 現金增資認購率 (rights offering, not modelled)


def ex_right_rows(payload: Any) -> list[ExRightRow]:
    """/exchangeReport/TWT48U_ALL (上市股票除權除息預告表)."""
    return [
        ExRightRow(
            code=_field(r, "Code").strip(),
            ex_date=roc_date(_field(r, "Date")),
            kind=_field(r, "Exdividend").strip(),
            cash=number(_field(r, "CashDividend")),
            stock_ratio=number(_field(r, "StockDividendRatio")),
            subscription_ratio=number(_field(r, "SubscriptionRatio")),
        )
        for r in _rows(payload)
    ]


# ---------- t187ap03_L ----------


@dataclass(frozen=True)
class CompanyRow:
    code: str
    name: str  # 公司名稱
    short_name: str  # 公司簡稱
    english_short_name: str
    industry: str  # 產業別 code
    shares: Decimal | None  # 已發行普通股數或TDR原股發行股數
    as_of: date  # 出表日期
    listed_on: date | None = None  # 上市日期


def company_rows(payload: Any) -> list[CompanyRow]:
    """/opendata/t187ap03_L (上市公司基本資料)."""
    return [
        CompanyRow(
            code=_field(r, "公司代號").strip(),
            name=_field(r, "公司名稱").strip(),
            short_name=_field(r, "公司簡稱").strip(),
            english_short_name=_field(r, "英文簡稱").strip(),
            industry=_field(r, "產業別").strip(),
            shares=number(_field(r, "已發行普通股數或TDR原股發行股數")),
            as_of=roc_date(_field(r, "出表日期")),
            listed_on=_optional_date(_field(r, "上市日期")),
        )
        for r in _rows(payload)
    ]


def _optional_date(text: str) -> date | None:
    """A Gregorian date ('19620209'), or None when the cell is blank."""
    return None if text.strip() in NO_VALUE else gregorian_date(text)


@dataclass(frozen=True)
class Ranked:
    code: str
    name: str
    market_cap: Decimal  # TWD


def rank_market_cap(days: Iterable[DayRow], companies: Iterable[CompanyRow]) -> list[Ranked]:
    """Listed companies by close x issued common shares, largest first (TW2). ETFs have no
    company row and drop out; a company without a close or a share count is left out."""
    closes = {d.code: d.close for d in days if d.close is not None}
    ranked = [
        Ranked(c.code, c.short_name, closes[c.code] * c.shares)
        for c in companies
        if c.code in closes and c.shares
    ]
    return sorted(ranked, key=lambda r: (-r.market_cap, r.code))


# ---------- holidaySchedule ----------


@dataclass(frozen=True)
class HolidayRow:
    day: date
    name: str


def holiday_rows(payload: Any) -> list[HolidayRow]:
    """/holidaySchedule/holidaySchedule (有價證券集中交易市場開（休）市日期), current year."""
    return [
        HolidayRow(roc_date(_field(r, "Date")), _field(r, "Name").strip()) for r in _rows(payload)
    ]


def closures(rows: Iterable[HolidayRow]) -> set[date]:
    """The weekday closures of the schedule: every listed weekday except the 開始交易日 and
    最後交易日 lines, which are sessions."""
    return {r.day for r in rows if r.day.weekday() < 5 and "交易日" not in r.name}


# ---------- reference price (TW9) ----------

STOCK_TICKS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal(10), Decimal("0.01")),
    (Decimal(50), Decimal("0.05")),
    (Decimal(100), Decimal("0.1")),
    (Decimal(500), Decimal("0.5")),
    (Decimal(1000), Decimal(1)),
)
ETF_TICKS: tuple[tuple[Decimal, Decimal], ...] = ((Decimal(50), Decimal("0.01")),)


def tick(price: Decimal, etf: bool) -> Decimal:
    """The TWSE tick (升降單位) at a price: stocks 0.01 to 5, ETFs 0.01 or 0.05."""
    for below, size in ETF_TICKS if etf else STOCK_TICKS:
        if price < below:
            return size
    return Decimal("0.05") if etf else Decimal(5)


@dataclass(frozen=True)
class ReferenceGap:
    code: str
    session: date
    reference: Decimal  # close - change, as TWSE published it
    expected: Decimal  # the previous close less the recorded actions
    previous_close: Decimal
    previous_session: date
    actions: tuple[str, ...] = field(default=())

    def note(self) -> str:
        told = f" after {', '.join(self.actions)}" if self.actions else ""
        return (
            f"{self.code} {self.session}: TWSE's reference price {self.reference} differs from "
            f"the previous close {self.previous_close} ({self.previous_session}){told}, "
            f"expected {self.expected}: an action this source does not list (capital "
            "reduction, rights offering or a dividend not yet recorded)"
        )


def reference_gap(
    code: str,
    session: date,
    close: Decimal,
    change: Decimal,
    previous_session: date,
    previous_close: Decimal,
    *,
    etf: bool,
    cash: Decimal = Decimal(0),
    stock_ratio: Decimal = Decimal(0),
) -> ReferenceGap | None:
    """The gap between TWSE's reference price and the previous close less the recorded cash
    and stock dividends of `session`, or None within one tick."""
    reference = close - change
    expected = (previous_close - cash) / (1 + stock_ratio)
    if abs(reference - expected) <= tick(previous_close, etf):
        return None
    actions = tuple(
        a
        for a in (
            f"a cash dividend of {cash}" if cash else "",
            f"a stock dividend of {stock_ratio}" if stock_ratio else "",
        )
        if a
    )
    return ReferenceGap(
        code,
        session,
        reference,
        expected.quantize(Decimal("0.0001")),
        previous_close,
        previous_session,
        actions,
    )
