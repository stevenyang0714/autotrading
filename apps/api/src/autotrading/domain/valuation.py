"""Market capitalization, enterprise value and multiples as known at a time (M1.2, ADR-022).

Pure functions over the facts known at the As known on time T, the daily closes known at T and
the splits effective by then. Each result names its inputs; nothing is estimated.

- Price: the last daily consolidated (SIP) close known at T, raw. Only an `end_of_day` close
  feeds a valuation: fixture or demo closes, closes older than STALE_AFTER and intraday quotes
  never do (errata E4); every value is then unavailable, with the reason.
- Shares (V2): the most recently dated count known at T, cover page or balance sheet, moved to
  the close's split basis; companies with several classes count every common class.
- Enterprise value: market cap + total debt - cash at the latest balance-sheet date with both
  (domain/derived.py, unreported short debt counted as 0 and named).
- TTM flows: the last four quarters (domain/quarters.py). EBITDA = operating income + D&A.
- TTM diluted EPS (V1): last fiscal year + this year to date - last year to date, all reported;
  the fiscal-year value alone right after a 10-K. Each input on the close's split basis.
- Not meaningful (n/m): P/E with TTM EPS <= 0, EV/EBITDA with EBITDA <= 0, P/B with equity
  <= 0.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from autotrading.domain.derived import ValueFact, net_debt
from autotrading.domain.fundamentals import FISCAL_YEAR_DAYS
from autotrading.domain.quarters import YTD_DAYS, quarters, trailing_twelve_months
from autotrading.domain.splits import Split, adjust

NEW_YORK = ZoneInfo("America/New_York")
STALE_AFTER = timedelta(days=5)  # covers weekends and holidays; a longer gap is stale
RATIO = Decimal("0.01")
SHARE_METRICS = ("shares_outstanding_cover", "shares_outstanding")

PriceStatus = Literal["ok", "fixture", "demo", "stale", "none"]
Reason = Literal["unavailable", "not_meaningful"]
Unit = Literal["USD", "USD/shares", "x", "percent", "shares", "flag"]  # flag: 1 yes, 0 no


class DatedFact(ValueFact, Protocol):
    @property
    def reported_at(self) -> datetime: ...


@dataclass(frozen=True)
class Close:
    day: date
    close: Decimal
    feed_status: str
    published_at: datetime
    zone: ZoneInfo = NEW_YORK  # the market's zone of `day` (Taipei for TWSE closes)


@dataclass(frozen=True)
class PriceInput:
    status: PriceStatus
    close: Close | None
    detail: str


def select_price(closes: Iterable[Close], at: datetime) -> PriceInput:
    """The last daily close public at `at`, and whether a valuation may use it."""
    known = [c for c in closes if c.published_at <= at]
    if not known:
        return PriceInput("none", None, "no daily close known at this time")
    last = max(known, key=lambda c: c.day)
    if last.feed_status in ("fixture", "demo"):
        status: PriceStatus = "fixture" if last.feed_status == "fixture" else "demo"
        return PriceInput(status, last, f"the close is {last.feed_status} data")
    if last.feed_status != "end_of_day":
        return PriceInput("stale", last, f"the close is {last.feed_status}, not end of day")
    if at.astimezone(NEW_YORK).date() - last.day > STALE_AFTER:
        return PriceInput("stale", last, f"the last close ({last.day}) is older than five days")
    return PriceInput("ok", last, "end-of-day consolidated close")


def close_basis(close: Close) -> datetime:
    """The split basis of a close: every split effective by the end of its day."""
    return datetime.combine(close.day, time(23, 59, 59), tzinfo=close.zone)


@dataclass(frozen=True)
class Input[FactT: DatedFact]:
    name: str  # a metric id, or "price"
    value: Decimal | None
    period_start: date | None
    period_end: date | None
    sources: tuple[FactT, ...] = ()  # the reported facts behind it
    note: str | None = None


@dataclass(frozen=True)
class Valued[FactT: DatedFact]:
    metric_id: str
    unit: Unit
    value: Decimal | None
    reason: Reason | None = None
    detail: str | None = None
    inputs: list[Input[FactT]] = field(default_factory=list)


def _split_basis[FactT: DatedFact](
    metric: str, fact: FactT, basis: datetime, splits: Sequence[Split]
) -> tuple[Decimal, str | None]:
    adjusted = adjust(metric, fact.value, fact.reported_at, basis, splits)
    if adjusted is None:
        return fact.value, None
    return adjusted.value, f"split-adjusted from {fact.value} (factor {adjusted.factor})"


def share_count[FactT: DatedFact](
    facts: Sequence[FactT],
    basis: datetime,
    splits: Sequence[Split],
    on_or_before: date | None = None,
) -> Input[FactT] | None:
    """V2: the most recently dated count, cover page or balance sheet, on the close's basis;
    with `on_or_before`, the latest dated by then (a period end's market cap, ADR-025 B12)."""
    counts = [
        f
        for f in facts
        if f.metric_id in SHARE_METRICS
        and f.period_start is None
        and (on_or_before is None or f.period_end <= on_or_before)
    ]
    if not counts:
        return None
    latest = max(counts, key=lambda f: (f.period_end, f.metric_id == SHARE_METRICS[0]))
    value, note = _split_basis("shares_outstanding", latest, basis, splits)
    return Input(latest.metric_id, value, None, latest.period_end, (latest,), note)


def ttm_eps[FactT: DatedFact](
    facts: Sequence[FactT], basis: datetime, splits: Sequence[Split]
) -> Input[FactT] | None:
    """V1: last fiscal year + this year to date - last year to date (all reported EPS)."""
    eps = [f for f in facts if f.metric_id == "eps_diluted" and f.period_start is not None]
    years = [
        f
        for f in eps
        if f.period_start is not None and (f.period_end - f.period_start).days in FISCAL_YEAR_DAYS
    ]
    if not years:
        return None
    year = max(years, key=lambda f: f.period_end)
    start = year.period_end + timedelta(days=1)

    def ytd(of_start: date) -> dict[int, FactT]:
        out: dict[int, FactT] = {}
        for f in eps:
            if f.period_start == of_start:
                days = (f.period_end - of_start).days
                n = next((q for q, span in YTD_DAYS.items() if days in span), None)
                if n is not None:
                    out[n] = f
        return out

    current = ytd(start)
    year_value, year_note = _split_basis("eps_diluted", year, basis, splits)
    if not current:
        return Input(
            "eps_diluted_ttm",
            year_value,
            year.period_start,
            year.period_end,
            (year,),
            "fiscal year" + (f"; {year_note}" if year_note else ""),
        )
    n = max(current)
    assert year.period_start is not None
    prior = ytd(year.period_start).get(n)
    if prior is None:
        return None
    now_value, _ = _split_basis("eps_diluted", current[n], basis, splits)
    prior_value, _ = _split_basis("eps_diluted", prior, basis, splits)
    return Input(
        "eps_diluted_ttm",
        year_value + now_value - prior_value,
        prior.period_end + timedelta(days=1),
        current[n].period_end,
        (year, current[n], prior),
        f"fiscal year + {n * 3} months this year - {n * 3} months last year",
    )


def ttm_flow[FactT: DatedFact](facts: Sequence[FactT], metric: str) -> Input[FactT] | None:
    ttm = trailing_twelve_months(quarters(facts, metric))
    if ttm is None:
        return None
    total, last = ttm
    sources = tuple(dict.fromkeys(f for q in last for f in q.inputs))
    return Input(
        f"{metric}_ttm",
        total,
        last[0].period_start,
        last[-1].period_end,
        sources,
        "sum of the last four quarters",
    )


def latest_net_debt[FactT: DatedFact](facts: Sequence[FactT]) -> Input[FactT] | None:
    """Net debt at the latest balance-sheet date with non-current debt (M1.2)."""
    index = {(f.metric_id, f.period_start, f.period_end): f for f in facts}
    ends = sorted(
        {
            f.period_end
            for f in facts
            if f.metric_id == "long_term_debt_noncurrent" and f.period_start is None
        },
        reverse=True,
    )
    for end in ends:
        derived = net_debt(index, end)
        if derived is not None:
            sources = tuple(f for _, f in derived.inputs if f is not None)
            note = (
                "not reported, counted as 0: " + ", ".join(derived.assumed_zero)
                if derived.assumed_zero
                else None
            )
            return Input("net_debt", derived.value, None, end, sources, note)
    return None


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    return (numerator / denominator).quantize(RATIO)


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal:
    return (numerator / denominator * 100).quantize(RATIO)


def valuation[FactT: DatedFact](
    facts: Sequence[FactT], price: PriceInput, splits: Sequence[Split]
) -> list[Valued[FactT]]:
    """Market cap, EV and the six multiples, in display order."""
    if price.status != "ok" or price.close is None:
        return [
            Valued(m, u, None, "unavailable", f"no valuation price: {price.detail}")
            for m, u in METRICS
        ]
    close = price.close
    basis = close_basis(close)
    quote: Input[FactT] = Input("price", close.close, None, close.day, (), "end-of-day close")
    shares = share_count(facts, basis, splits)
    eps = ttm_eps(facts, basis, splits)
    revenue = ttm_flow(facts, "revenue")
    debt = latest_net_debt(facts)
    equity = _latest_instant(facts, "stockholders_equity")
    ebitda = _combine(
        ttm_flow(facts, "operating_income"),
        ttm_flow(facts, "depreciation_amortization"),
        "ebitda_ttm",
        1,
        "operating income + depreciation and amortization, last four quarters",
    )
    fcf = _combine(
        ttm_flow(facts, "operating_cash_flow"),
        ttm_flow(facts, "capex"),
        "free_cash_flow_ttm",
        -1,
        "operating cash flow - capex, last four quarters",
    )
    cap = (
        Input[FactT](
            "market_cap", (close.close * shares.value).quantize(Decimal(1)), None, close.day
        )
        if shares is not None and shares.value is not None
        else None
    )
    ev = (
        Input[FactT](
            "enterprise_value", (cap.value + debt.value).quantize(Decimal(1)), None, close.day
        )
        if cap is not None and cap.value is not None and debt is not None and debt.value is not None
        else None
    )
    # metric -> (needed inputs by label, value from their values, test for "not meaningful")
    rules: dict[
        str, tuple[dict[str, Input[FactT] | None], Callable[[list[Decimal]], Decimal], str | None]
    ] = {
        "market_cap": (
            {"price": quote, "shares outstanding": shares},
            lambda v: _whole(v[0] * v[1]),
            None,
        ),
        "enterprise_value": (
            {"market cap": cap, "net debt": debt},
            lambda v: _whole(v[0] + v[1]),
            None,
        ),
        "pe_ratio_ttm": (
            {"price": quote, "TTM diluted EPS": eps},
            lambda v: _ratio(v[0], v[1]),
            "TTM EPS",
        ),
        "ev_to_ebitda": (
            {"enterprise value": ev, "TTM EBITDA (operating income + D&A)": ebitda},
            lambda v: _ratio(v[0], v[1]),
            "TTM EBITDA",
        ),
        "ev_to_sales": (
            {"enterprise value": ev, "TTM revenue": revenue},
            lambda v: _ratio(v[0], v[1]),
            "TTM revenue",
        ),
        "price_to_book": (
            {"market cap": cap, "stockholders' equity": equity},
            lambda v: _ratio(v[0], v[1]),
            "stockholders' equity",
        ),
        "fcf_yield": (
            {"TTM free cash flow": fcf, "market cap": cap},
            lambda v: _percent(v[0], v[1]),
            None,
        ),
        "earnings_yield": (
            {"TTM diluted EPS": eps, "price": quote},
            lambda v: _percent(v[0], v[1]),
            None,
        ),
    }
    out: list[Valued[FactT]] = []
    for metric, unit in METRICS:
        needed, compute, positive = rules[metric]
        absent = [label for label, value in needed.items() if value is None or value.value is None]
        if absent:
            out.append(
                Valued(metric, unit, None, "unavailable", "not reported: " + ", ".join(absent))
            )
            continue
        inputs = [value for value in needed.values() if value is not None]
        values = [value.value for value in inputs if value.value is not None]
        if positive is not None and values[1] <= 0:
            out.append(
                Valued(metric, unit, None, "not_meaningful", f"{positive} is not positive", inputs)
            )
            continue
        out.append(Valued(metric, unit, compute(values), inputs=inputs))
    return out


METRICS: tuple[tuple[str, Unit], ...] = (
    ("market_cap", "USD"),
    ("enterprise_value", "USD"),
    ("pe_ratio_ttm", "x"),
    ("ev_to_ebitda", "x"),
    ("ev_to_sales", "x"),
    ("price_to_book", "x"),
    ("fcf_yield", "percent"),
    ("earnings_yield", "percent"),
)


def _whole(value: Decimal) -> Decimal:
    return value.quantize(Decimal(1))


def _latest_instant[FactT: DatedFact](facts: Sequence[FactT], metric: str) -> Input[FactT] | None:
    found = [f for f in facts if f.metric_id == metric and f.period_start is None]
    if not found:
        return None
    latest = max(found, key=lambda f: f.period_end)
    return Input(metric, latest.value, None, latest.period_end, (latest,))


def _combine[FactT: DatedFact](
    first: Input[FactT] | None, second: Input[FactT] | None, name: str, sign: int, note: str
) -> Input[FactT] | None:
    """first + sign * second, when both cover the same four quarters."""
    if first is None or second is None or first.period_end != second.period_end:
        return None
    if first.value is None or second.value is None:
        return None
    return Input(
        name,
        first.value + sign * second.value,
        first.period_start,
        first.period_end,
        first.sources + second.sources,
        note,
    )
