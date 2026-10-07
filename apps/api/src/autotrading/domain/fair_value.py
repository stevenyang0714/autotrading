"""Fair value models (M1.3a, ADR-023): DCF, reverse DCF and relative valuation, as known at a
time T. Pure functions; every input is what was public at T, so the same inputs and the same
assumption version always give the same output. Model output, not fact (02 §32.2).

DCF (F1, F2): enterprise, two-stage, annual, discounted at year end.
- Base cash flow: owner free cash flow, the last four quarters: operating cash flow - capex -
  stock-based compensation (SBC can be kept in by the assumption set). Not meaningful <= 0.
- Discount rate r = the 10-year Treasury yield known at T (FRED DGS10) + the equity risk
  premium of the assumption set.
- Years 1-5 grow at the scenario's rate g; years 6-10 fade linearly from g to the terminal
  rate; the terminal value at year 10 is FCF10 x (1 + terminal) / (r - terminal).
- Per share = (enterprise value - net debt) / shares (M1.2: net debt at the latest balance
  date, shares on the valuation price's split basis).
- Bear, base and bull differ only in g (F3 defaults: 0%, 5%, 10%; terminal 2.5%; ERP 5%).
Reverse DCF: the g that makes the base value per share equal the valuation price.
Relative valuation: each M1.2 multiple at every month end since 2016, each from the facts,
close and splits known then; the current value's percentile in that history, and the
history's median.
"""

from bisect import bisect_left, bisect_right
from calendar import monthrange
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autotrading.domain.provenance import end_of_day
from autotrading.domain.splits import Split
from autotrading.domain.valuation import (
    NEW_YORK,
    Close,
    DatedFact,
    Input,
    select_price,
    ttm_flow,
    valuation,
)

STAGE_ONE_YEARS = 5
FADE_YEARS = 5
CENTS = Decimal("0.01")
RATE = Decimal("0.0001")  # 0.01 percentage point
REVERSE_RANGE = (Decimal("-0.5"), Decimal("1.0"))
REVERSE_ITERATIONS = 80
MIN_SPREAD = Decimal("0.01")  # terminal growth must stay a point below the discount rate
DEFAULT_VERSION = "default"


class Assumptions(BaseModel):
    """One assumption set; rates in percent (5 means 5%)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    equity_risk_premium: Decimal = Field(ge=2, le=10, decimal_places=2)
    terminal_growth: Decimal = Field(ge=-2, le=5, decimal_places=2)
    growth_bear: Decimal = Field(ge=-20, le=40, decimal_places=2)
    growth_base: Decimal = Field(ge=-20, le=40, decimal_places=2)
    growth_bull: Decimal = Field(ge=-20, le=40, decimal_places=2)
    subtract_sbc: bool = True

    @model_validator(mode="after")
    def ordered(self) -> "Assumptions":
        if not self.growth_bear <= self.growth_base <= self.growth_bull:
            raise ValueError("growth must be ordered: bear <= base <= bull")
        return self


DEFAULT_ASSUMPTIONS = Assumptions(
    equity_risk_premium=Decimal(5),
    terminal_growth=Decimal("2.5"),
    growth_bear=Decimal(0),
    growth_base=Decimal(5),
    growth_bull=Decimal(10),
    subtract_sbc=True,
)

Scenario = Literal["bear", "base", "bull"]
SCENARIOS: tuple[Scenario, ...] = ("bear", "base", "bull")


def percent(value: Decimal) -> Decimal:
    return value / 100


def growth_path(growth: Decimal, terminal: Decimal) -> list[Decimal]:
    """Yearly growth for years 1-10: `growth` for five years, then a linear fade to
    `terminal` (year 10 grows at the terminal rate)."""
    fade = [
        growth + (terminal - growth) * Decimal(year) / FADE_YEARS
        for year in range(1, FADE_YEARS + 1)
    ]
    return [growth] * STAGE_ONE_YEARS + fade


@dataclass(frozen=True)
class Dcf:
    per_share: Decimal
    enterprise_value: Decimal
    explicit_value: Decimal  # present value of years 1-10
    terminal_value: Decimal  # present value of the terminal value


def dcf(
    fcf: Decimal,
    growth: Decimal,
    terminal: Decimal,
    rate: Decimal,
    net_debt: Decimal,
    shares: Decimal,
) -> Dcf:
    """All rates as fractions (0.05). Exact decimal arithmetic, so it is reproducible."""
    with localcontext() as ctx:
        ctx.prec = 40
        flow = fcf
        explicit = Decimal(0)
        discount = Decimal(1)
        for year_growth in growth_path(growth, terminal):
            flow = flow * (1 + year_growth)
            discount = discount * (1 + rate)
            explicit += flow / discount
        terminal_value = flow * (1 + terminal) / (rate - terminal) / discount
        enterprise = explicit + terminal_value
        per_share = (enterprise - net_debt) / shares
    return Dcf(per_share, enterprise, explicit, terminal_value)


def reverse_growth(
    price: Decimal,
    fcf: Decimal,
    terminal: Decimal,
    rate: Decimal,
    net_debt: Decimal,
    shares: Decimal,
) -> Decimal | None:
    """The stage-one growth that makes the value per share equal the price (bisection; the
    value rises with growth when the base cash flow is positive). None outside the range."""

    def gap(g: Decimal) -> Decimal:
        return dcf(fcf, g, terminal, rate, net_debt, shares).per_share - price

    low, high = REVERSE_RANGE
    if gap(low) > 0 or gap(high) < 0:
        return None
    for _ in range(REVERSE_ITERATIONS):
        middle = (low + high) / 2
        if gap(middle) < 0:
            low = middle
        else:
            high = middle
    return ((low + high) / 2).quantize(RATE)


@dataclass(frozen=True)
class RiskFree:
    value: Decimal  # percent, e.g. 4.12
    observation_date: date
    published_at: datetime


@dataclass(frozen=True)
class FairValue[FactT: DatedFact]:
    status: Literal["ok", "unavailable", "not_meaningful"]
    detail: str | None
    discount_rate: Decimal | None  # percent
    base_fcf: Input[FactT] | None
    scenarios: dict[Scenario, Dcf]
    implied_upside: Decimal | None  # percent
    margin_of_safety: Decimal | None  # percent
    reverse_growth: Decimal | None  # percent
    reverse_detail: str | None  # why there is no reverse growth


OWNER_FCF_PARTS = {
    "operating_cash_flow": "operating cash flow",
    "capex": "capex",
    "stock_based_compensation": "stock-based compensation",
}


def owner_fcf[FactT: DatedFact](facts: Sequence[FactT], subtract_sbc: bool) -> Input[FactT] | str:
    """Operating cash flow - capex (- SBC), the last four quarters, all over the same period;
    or why there is none."""
    metrics = list(OWNER_FCF_PARTS)[: 3 if subtract_sbc else 2]
    parts = {metric: ttm_flow(facts, metric) for metric in metrics}
    absent = [OWNER_FCF_PARTS[m] for m, part in parts.items() if part is None or part.value is None]
    if absent:
        reason = "not reported for the last four quarters: " + ", ".join(absent)
        if absent == [OWNER_FCF_PARTS["stock_based_compensation"]]:
            reason += " (an assumption set can leave SBC out)"
        return reason
    found = [part for part in parts.values() if part is not None]
    if len({part.period_end for part in found}) != 1:
        return "its parts cover different quarters"
    ocf, *outflows = found
    assert ocf.value is not None
    value = ocf.value - sum((p.value for p in outflows if p.value is not None), Decimal(0))
    return Input(
        "owner_fcf",
        value,
        ocf.period_start,
        ocf.period_end,
        tuple(dict.fromkeys(f for p in found for f in p.sources)),
        "operating cash flow - capex" + (" - SBC" if subtract_sbc else "") + ", last four quarters",
    )


def fair_value[FactT: DatedFact](
    facts: Sequence[FactT],
    assumptions: Assumptions,
    risk_free: RiskFree | None,
    net_debt: Input[FactT] | None,
    shares: Input[FactT] | None,
    price: Decimal | None,
) -> FairValue[FactT]:
    """DCF scenarios and reverse DCF; `price` is the M1.2 valuation price (None if unusable)."""
    found = owner_fcf(facts, assumptions.subtract_sbc)
    base = found if isinstance(found, Input) else None

    def unavailable(detail: str, rate: Decimal | None = None) -> FairValue[FactT]:
        return FairValue("unavailable", detail, rate, base, {}, None, None, None, detail)

    missing = [
        label
        for label, value in (
            ("10-year Treasury yield", risk_free),
            ("net debt", net_debt),
            ("shares outstanding", shares),
        )
        if value is None
    ]
    reasons = ["not reported: " + ", ".join(missing)] if missing else []
    if isinstance(found, str):
        reasons.append(f"owner free cash flow: {found}")
    if reasons:
        return unavailable("; ".join(reasons))
    assert risk_free and base and net_debt and shares
    assert base.value is not None and net_debt.value is not None and shares.value is not None
    rate_percent = risk_free.value + assumptions.equity_risk_premium
    rate, terminal = percent(rate_percent), percent(assumptions.terminal_growth)
    if base.value <= 0:
        detail = "owner free cash flow is not positive"
        return FairValue("not_meaningful", detail, rate_percent, base, {}, None, None, None, detail)
    if rate - terminal < MIN_SPREAD:
        return unavailable(
            "terminal growth must stay at least one point below the discount rate", rate_percent
        )
    growth = {
        "bear": assumptions.growth_bear,
        "base": assumptions.growth_base,
        "bull": assumptions.growth_bull,
    }
    scenarios = {
        name: _rounded(
            dcf(base.value, percent(growth[name]), terminal, rate, net_debt.value, shares.value)
        )
        for name in SCENARIOS
    }
    upside = margin = implied = None
    reverse_detail: str | None = "no valuation price"
    if price is not None and price > 0:
        value = scenarios["base"].per_share
        upside = ((value / price - 1) * 100).quantize(CENTS)
        margin = ((value - price) / value * 100).quantize(CENTS) if value > 0 else None
        solved = reverse_growth(price, base.value, terminal, rate, net_debt.value, shares.value)
        implied = (solved * 100).quantize(CENTS) if solved is not None else None
        reverse_detail = None if solved is not None else "outside -50% to +100% a year"
    return FairValue(
        "ok", None, rate_percent, base, scenarios, upside, margin, implied, reverse_detail
    )


def _rounded(value: Dcf) -> Dcf:
    return Dcf(
        value.per_share.quantize(CENTS),
        value.enterprise_value.quantize(Decimal(1)),
        value.explicit_value.quantize(Decimal(1)),
        value.terminal_value.quantize(Decimal(1)),
    )


# ---------- relative valuation ----------


@dataclass(frozen=True)
class Relative:
    metric_id: str
    current: Decimal | None
    median: Decimal | None
    percentile: Decimal | None  # share of month ends at or below the current value, percent
    observations: int
    since: date | None


def relative(
    metric_id: str, current: Decimal | None, history: Sequence[tuple[date, Decimal]]
) -> Relative:
    values = sorted(v for _, v in history)
    if not values:
        return Relative(metric_id, current, None, None, 0, None)
    middle = len(values) // 2
    median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    rank = (
        (Decimal(bisect_right(values, current)) / len(values) * 100).quantize(Decimal(1))
        if current is not None
        else None
    )
    return Relative(
        metric_id, current, median.quantize(CENTS), rank, len(values), min(d for d, _ in history)
    )


RELATIVE_METRICS = (
    "pe_ratio_ttm",
    "ev_to_ebitda",
    "ev_to_sales",
    "price_to_book",
    "fcf_yield",
    "earnings_yield",
)
HISTORY_SINCE = date(2016, 1, 1)
CLOSE_WINDOW = timedelta(days=10)  # longer than STALE_AFTER: older closes are stale anyway


def month_ends(since: date, at: datetime) -> list[datetime]:
    """The end of the last calendar day of each month from `since` (New York), up to `at`."""
    out: list[datetime] = []
    year, month = since.year, since.month
    while True:
        point = end_of_day(date(year, month, monthrange(year, month)[1]))
        if point > at:
            return out
        out.append(point)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def snapshots[RowT](
    rows: Iterable[RowT],
    times: Iterable[datetime],
    key: Callable[[RowT], tuple[object, ...]],
    published: Callable[[RowT], datetime],
    recorded: Callable[[RowT], datetime],
) -> Iterator[tuple[datetime, list[RowT]]]:
    """In-memory `as_of` (ADR-012) at each of `times`, ascending, in one pass: per key, the
    latest version published by then (ties on publication go to the later recorded row)."""
    ordered = sorted(rows, key=lambda r: (published(r), recorded(r)))
    best: dict[tuple[object, ...], RowT] = {}
    index = 0
    for at in times:
        while index < len(ordered) and published(ordered[index]) <= at:
            best[key(ordered[index])] = ordered[index]
            index += 1
        yield at, list(best.values())


def known_at[RowT](
    rows: Iterable[RowT],
    at: datetime,
    key: Callable[[RowT], tuple[object, ...]],
    published: Callable[[RowT], datetime],
    recorded: Callable[[RowT], datetime],
) -> list[RowT]:
    return next(snapshots(rows, [at], key, published, recorded))[1]


def multiple_history[FactT: DatedFact](
    points: Iterable[tuple[datetime, Sequence[FactT]]],
    closes: Sequence[Close],
    splits: Sequence[tuple[datetime, Split]],
) -> dict[str, list[tuple[date, Decimal]]]:
    """Each relative-valuation multiple at every point, from the facts known then (as given),
    the close known then and the splits published by then. Points without a valuation price
    or with an unavailable or n/m value are left out."""
    history: dict[str, list[tuple[date, Decimal]]] = {m: [] for m in RELATIVE_METRICS}
    ordered = sorted(closes, key=lambda c: c.day)
    days = [c.day for c in ordered]
    for at, facts in points:
        day = at.astimezone(NEW_YORK).date()
        recent = ordered[bisect_left(days, day - CLOSE_WINDOW) : bisect_right(days, day)]
        price = select_price(recent, at)
        if price.status != "ok":
            continue
        known = [split for published, split in splits if published <= at]
        for value in valuation(facts, price, known):
            if value.metric_id in history and value.value is not None:
                history[value.metric_id].append((day, value.value))
    return history
