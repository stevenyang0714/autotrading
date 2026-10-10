"""Research Record (M1.3b, ADR-024): a company's economics, quality and capital allocation per
period, as known at a time T. Pure functions over the facts known at T; each value names its
inputs, so the page can show the filings behind it. Nothing is estimated (ADR-013): a missing
input leaves the value unavailable with the input named; a non-positive denominator makes it
not meaningful (n/m), with the reason.

Periods: the last five fiscal years, and the last four quarters (TTM) when they end after the
latest fiscal year. Opening balances are those of the day before a period starts (the prior
fiscal year end; for TTM the quarter end a year earlier); averages are (opening + closing) / 2.

- revenue growth = revenue / revenue of the period before - 1
- gross, operating and net margin = gross profit, operating income, net income / revenue
- effective tax rate = income tax expense / pretax income; n/m when pretax income <= 0. A tax
  benefit gives a negative rate, kept as reported and noted.
- ROIC (R2) = NOPAT / average invested capital; NOPAT = operating income x (1 - tax rate);
  invested capital = stockholders' equity + total debt - cash (unreported short-term debt
  counted as 0 and named, D4); n/m when pretax income or either invested capital <= 0.
- ROE = net income / average stockholders' equity; n/m when either equity <= 0.
- FCF conversion = free cash flow / net income; n/m when net income <= 0.
- net debt / EBITDA = net debt at the period end / (operating income + D&A); n/m when EBITDA
  <= 0. Net cash gives a negative ratio.
- Capital allocation (R3): free cash flow, buybacks, dividends and SBC as reported. Dividends
  of a period with no dividend figure at all count as 0 and are named (as D4); cash returned =
  buybacks + dividends; cash returned / FCF (n/m when FCF <= 0); diluted share change =
  weighted diluted shares / those a year earlier - 1, both on the split basis of T (TTM: the
  latest reported quarter against the same quarter a year earlier).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from autotrading.domain.derived import Derived, free_cash_flow, net_debt
from autotrading.domain.fundamentals import FISCAL_YEAR_DAYS, annual_periods
from autotrading.domain.quarters import Quarter, quarters, trailing_twelve_months
from autotrading.domain.splits import Split, adjust
from autotrading.domain.valuation import RATIO, DatedFact, Input, Unit, Valued

YEARS = 5
PeriodKind = Literal["ttm", "fiscal_year"]
Section = Literal["economics", "quality", "capital_allocation"]

# Display order: (section, metric, unit).
ROWS: tuple[tuple[Section, str, Unit], ...] = (
    ("economics", "revenue_growth", "percent"),
    ("economics", "gross_margin", "percent"),
    ("economics", "operating_margin", "percent"),
    ("economics", "net_margin", "percent"),
    ("quality", "roic", "percent"),
    ("quality", "roe", "percent"),
    ("quality", "effective_tax_rate", "percent"),
    ("quality", "fcf_conversion", "percent"),
    ("quality", "net_debt_to_ebitda", "x"),
    ("capital_allocation", "free_cash_flow", "USD"),
    ("capital_allocation", "share_repurchases", "USD"),
    ("capital_allocation", "dividends_paid", "USD"),
    ("capital_allocation", "stock_based_compensation", "USD"),
    ("capital_allocation", "cash_returned", "USD"),
    ("capital_allocation", "cash_returned_to_fcf", "percent"),
    ("capital_allocation", "diluted_shares_change", "percent"),
)
# The reported metrics the record reads.
RESEARCH_METRICS = (
    "revenue",
    "gross_profit",
    "operating_income",
    "pretax_income",
    "income_tax_expense",
    "net_income",
    "depreciation_amortization",
    "operating_cash_flow",
    "capex",
    "share_repurchases",
    "dividends_paid",
    "stock_based_compensation",
    "diluted_shares",
    "stockholders_equity",
    "cash",
    "long_term_debt_noncurrent",
    "long_term_debt_current",
    "commercial_paper",
)
LABELS = {
    "revenue": "revenue",
    "gross_profit": "gross profit",
    "operating_income": "operating income",
    "pretax_income": "pretax income",
    "income_tax_expense": "income tax expense",
    "net_income": "net income",
    "depreciation_amortization": "depreciation and amortization",
    "operating_cash_flow": "operating cash flow",
    "capex": "capex",
    "share_repurchases": "share repurchases",
    "dividends_paid": "dividends paid",
    "stock_based_compensation": "stock-based compensation",
    "diluted_shares": "diluted shares",
    "stockholders_equity": "stockholders' equity",
}
TTM_SOURCES = ("revenue", "net_income", "operating_cash_flow")


@dataclass(frozen=True)
class Window:
    kind: PeriodKind
    start: date
    end: date

    @property
    def opening(self) -> date:
        """The balance-sheet date before the period: its opening balances."""
        return self.start - timedelta(days=1)


@dataclass(frozen=True)
class Record[FactT: DatedFact]:
    periods: list[Window]  # newest first: TTM (when later than the last fiscal year), years
    rows: list[tuple[Section, str, Unit, list[Valued[FactT]]]]  # one value per period


def percent(numerator: Decimal, denominator: Decimal) -> Decimal:
    return (numerator / denominator * 100).quantize(RATIO)


def growth(now: Decimal, before: Decimal) -> Decimal:
    return ((now / before - 1) * 100).quantize(RATIO)


class Book[FactT: DatedFact]:
    """The facts known at T, indexed, with quarter series computed once per metric."""

    def __init__(self, facts: Sequence[FactT], at: datetime, splits: Sequence[Split]) -> None:
        self.facts = facts
        self.at = at
        self.splits = splits
        self.index = {(f.metric_id, f.period_start, f.period_end): f for f in facts}
        self._series: dict[str, list[Quarter[FactT]]] = {}

    def series(self, metric: str) -> list[Quarter[FactT]]:
        if metric not in self._series:
            self._series[metric] = quarters(self.facts, metric)
        return self._series[metric]

    def ttm(self, metric: str, end: date, start: date | None = None) -> Input[FactT] | None:
        """The four quarters ending exactly on `end` (and starting on `start`, when given)."""
        found = trailing_twelve_months([q for q in self.series(metric) if q.period_end <= end])
        if found is None:
            return None
        total, last = found
        if last[-1].period_end != end or (start is not None and last[0].period_start != start):
            return None
        sources = tuple(dict.fromkeys(f for q in last for f in q.inputs))
        return Input(
            f"{metric}_ttm",
            total,
            last[0].period_start,
            end,
            sources,
            "sum of the last four quarters",
        )

    def flow(self, metric: str, window: Window) -> Input[FactT] | None:
        if window.kind == "ttm":
            return self.ttm(metric, window.end, window.start)
        fact = self.index.get((metric, window.start, window.end))
        if fact is None:
            return None
        return Input(metric, fact.value, window.start, window.end, (fact,))

    def instant(self, metric: str, day: date) -> Input[FactT] | None:
        fact = self.index.get((metric, None, day))
        return Input(metric, fact.value, None, day, (fact,)) if fact is not None else None

    def derived(self, value: Derived[FactT] | None, name: str) -> Input[FactT] | None:
        if value is None:
            return None
        note = (
            "not reported, counted as 0: " + ", ".join(value.assumed_zero)
            if value.assumed_zero
            else value.method
        )
        sources = tuple(f for _, f in value.inputs if f is not None)
        return Input(name, value.value, value.period_start, value.period_end, sources, note)

    def net_debt(self, day: date) -> Input[FactT] | None:
        return self.derived(net_debt(self.index, day), "net_debt")

    def invested_capital(self, day: date) -> tuple[Input[FactT] | None, list[str]]:
        """Equity + total debt - cash on `day`, or what is missing."""
        equity = self.instant("stockholders_equity", day)
        debt = self.net_debt(day)
        missing = [
            label
            for label, value in (("stockholders' equity", equity), ("net debt", debt))
            if value is None
        ]
        if equity is None or debt is None or equity.value is None or debt.value is None:
            return None, missing
        note = "stockholders' equity + total debt - cash" + (
            f"; {debt.note}" if debt.note and debt.note.startswith("not reported") else ""
        )
        return (
            Input(
                "invested_capital",
                equity.value + debt.value,
                None,
                day,
                equity.sources + debt.sources,
                note,
            ),
            [],
        )

    def free_cash_flow(self, window: Window) -> tuple[Input[FactT] | None, list[str]]:
        if window.kind == "fiscal_year":
            found = self.derived(
                free_cash_flow(self.index, window.start, window.end), "free_cash_flow"
            )
            if found is not None:
                return found, []
        ocf = self.flow("operating_cash_flow", window)
        capex = self.flow("capex", window)
        missing = [LABELS[m] for m, v in (("operating_cash_flow", ocf), ("capex", capex)) if not v]
        if ocf is None or capex is None or ocf.value is None or capex.value is None:
            return None, missing
        return (
            Input(
                "free_cash_flow" if window.kind == "fiscal_year" else "free_cash_flow_ttm",
                ocf.value - capex.value,
                window.start,
                window.end,
                ocf.sources + capex.sources,
                "operating cash flow - capex"
                + ("" if window.kind == "fiscal_year" else ", last four quarters"),
            ),
            [],
        )

    def dividends(self, window: Window) -> Input[FactT] | None:
        """Reported dividends, or 0 (named) when no dividend figure touches the period."""
        found = self.flow("dividends_paid", window)
        if found is not None:
            return found
        touching = any(
            f.metric_id == "dividends_paid"
            and f.period_start is not None
            and f.period_start <= window.end
            and f.period_end >= window.start
            for f in self.facts
        )
        if touching:
            return None
        return Input(
            "dividends_paid",
            Decimal(0),
            window.start,
            window.end,
            (),
            "not reported for this period, counted as 0",
        )

    def diluted_shares(self, window: Window, end: date) -> Input[FactT] | None:
        """Weighted diluted shares of the period like `window` ending on `end`, on T's basis."""
        if window.kind == "fiscal_year":
            fact = next(
                (
                    f
                    for f in self.facts
                    if f.metric_id == "diluted_shares"
                    and f.period_end == end
                    and f.period_start is not None
                    and (end - f.period_start).days in FISCAL_YEAR_DAYS
                ),
                None,
            )
        else:
            quarter = next((q for q in self.series("diluted_shares") if q.period_end == end), None)
            fact = quarter.inputs[0] if quarter is not None else None
        if fact is None:
            return None
        adjusted = adjust("diluted_shares", fact.value, fact.reported_at, self.at, self.splits)
        value = adjusted.value if adjusted is not None else fact.value
        note = (
            f"split-adjusted from {fact.value} (factor {adjusted.factor})"
            if adjusted is not None
            else None
        )
        return Input("diluted_shares", value, fact.period_start, fact.period_end, (fact,), note)


def valued[FactT: DatedFact](
    metric: str,
    unit: Unit,
    needed: Sequence[tuple[str, Input[FactT] | None]],
    compute: Callable[[list[Decimal]], Decimal],
    positive: Sequence[tuple[int, str]] = (),
    explain: Mapping[str, Sequence[str]] | None = None,
) -> Valued[FactT]:
    """`explain` names the missing parts of a missing derived input (free cash flow: capex)."""
    absent = [
        name
        for label, v in needed
        if v is None or v.value is None
        for name in ((explain or {}).get(label) or [label])
    ]
    if absent:
        return Valued(metric, unit, None, "unavailable", "not reported: " + ", ".join(absent))
    inputs = [v for _, v in needed if v is not None]
    values = [v.value for v in inputs if v.value is not None]
    for position, label in positive:
        if values[position] <= 0:
            return Valued(metric, unit, None, "not_meaningful", f"{label} is not positive", inputs)
    return Valued(metric, unit, compute(values), inputs=inputs)


def with_detail[FactT: DatedFact](value: Valued[FactT], detail: str | None) -> Valued[FactT]:
    if detail is None or value.value is None:
        return value
    return Valued(value.metric_id, value.unit, value.value, None, detail, value.inputs)


def _period_values[FactT: DatedFact](book: Book[FactT], window: Window) -> dict[str, Valued[FactT]]:
    """Every row's value for one period; the period a year earlier ends at its opening."""
    prior_end = window.opening
    flow: dict[str, Input[FactT] | None] = {
        m: book.flow(m, window) for m in LABELS if m != "diluted_shares"
    }
    flow["dividends_paid"] = book.dividends(window)
    prior_revenue: Input[FactT] | None
    if window.kind == "ttm":
        prior_revenue = book.ttm("revenue", prior_end)
    else:
        prior_revenue = next(
            (
                Input("revenue", f.value, f.period_start, f.period_end, (f,))
                for f in book.facts
                if f.metric_id == "revenue"
                and f.period_end == prior_end
                and f.period_start is not None
                and (prior_end - f.period_start).days in FISCAL_YEAR_DAYS
            ),
            None,
        )
    revenue: tuple[str, Input[FactT] | None] = ("revenue", flow["revenue"])
    out: dict[str, Valued[FactT]] = {}

    out["revenue_growth"] = valued(
        "revenue_growth",
        "percent",
        [revenue, ("revenue a year earlier", prior_revenue)],
        lambda v: growth(v[0], v[1]),
        [(1, "revenue a year earlier")],
    )
    for metric, part in (
        ("gross_margin", "gross_profit"),
        ("operating_margin", "operating_income"),
        ("net_margin", "net_income"),
    ):
        out[metric] = valued(
            metric,
            "percent",
            [(LABELS[part], flow[part]), revenue],
            lambda v: percent(v[0], v[1]),
            [(1, "revenue")],
        )

    tax, pretax = flow["income_tax_expense"], flow["pretax_income"]
    benefit = (
        "a tax benefit: the rate is negative"
        if tax is not None and tax.value is not None and tax.value < 0
        else None
    )
    out["effective_tax_rate"] = with_detail(
        valued(
            "effective_tax_rate",
            "percent",
            [("income tax expense", tax), ("pretax income", pretax)],
            lambda v: percent(v[0], v[1]),
            [(1, "pretax income")],
        ),
        benefit,
    )

    # ROIC: NOPAT over average invested capital.
    operating = flow["operating_income"]
    ic_open, open_missing = book.invested_capital(window.opening)
    ic_close, close_missing = book.invested_capital(window.end)
    missing = [
        *(f"{m} on {window.opening}" for m in open_missing),
        *(f"{m} on {window.end}" for m in close_missing),
    ]
    roic_needed = [
        ("operating income", operating),
        ("income tax expense", tax),
        ("pretax income", pretax),
    ]
    absent = [*(label for label, v in roic_needed if v is None), *missing]
    if absent:
        out["roic"] = Valued(
            "roic", "percent", None, "unavailable", "not reported: " + ", ".join(absent)
        )
    else:
        assert operating and tax and pretax and ic_open and ic_close
        assert operating.value is not None and tax.value is not None
        assert pretax.value is not None and ic_open.value is not None
        assert ic_close.value is not None
        if pretax.value <= 0:
            out["roic"] = Valued(
                "roic",
                "percent",
                None,
                "not_meaningful",
                "pretax income is not positive",
                [operating, tax, pretax, ic_open, ic_close],
            )
        else:
            rate = tax.value / pretax.value
            nopat = Input(
                "nopat",
                (operating.value * (1 - rate)).quantize(Decimal(1)),
                operating.period_start,
                operating.period_end,
                operating.sources + tax.sources + pretax.sources,
                f"operating income x (1 - tax rate {percent(tax.value, pretax.value)}%)",
            )
            out["roic"] = with_detail(
                valued(
                    "roic",
                    "percent",
                    [
                        ("NOPAT", nopat),
                        (f"invested capital on {window.opening}", ic_open),
                        (f"invested capital on {window.end}", ic_close),
                    ],
                    lambda v: percent(v[0], (v[1] + v[2]) / 2),
                    [
                        (1, f"invested capital on {window.opening}"),
                        (2, f"invested capital on {window.end}"),
                    ],
                ),
                benefit,
            )

    equity_open = book.instant("stockholders_equity", window.opening)
    equity_close = book.instant("stockholders_equity", window.end)
    out["roe"] = valued(
        "roe",
        "percent",
        [
            ("net income", flow["net_income"]),
            (f"stockholders' equity on {window.opening}", equity_open),
            (f"stockholders' equity on {window.end}", equity_close),
        ],
        lambda v: percent(v[0], (v[1] + v[2]) / 2),
        [
            (1, f"stockholders' equity on {window.opening}"),
            (2, f"stockholders' equity on {window.end}"),
        ],
    )

    fcf, fcf_missing = book.free_cash_flow(window)
    out["fcf_conversion"] = valued(
        "fcf_conversion",
        "percent",
        [("free cash flow", fcf), ("net income", flow["net_income"])],
        lambda v: percent(v[0], v[1]),
        [(1, "net income")],
        {"free cash flow": fcf_missing},
    )

    depreciation = flow["depreciation_amortization"]
    ebitda = (
        Input(
            "ebitda_ttm" if window.kind == "ttm" else "ebitda",
            operating.value + depreciation.value,
            window.start,
            window.end,
            operating.sources + depreciation.sources,
            "operating income + depreciation and amortization",
        )
        if operating is not None
        and depreciation is not None
        and operating.value is not None
        and depreciation.value is not None
        else None
    )
    ebitda_missing = [
        LABELS[m]
        for m, v in (("operating_income", operating), ("depreciation_amortization", depreciation))
        if v is None
    ]
    debt = book.net_debt(window.end)
    out["net_debt_to_ebitda"] = valued(
        "net_debt_to_ebitda",
        "x",
        [(f"net debt on {window.end}", debt), ("EBITDA", ebitda)],
        lambda v: (v[0] / v[1]).quantize(RATIO),
        [(1, "EBITDA")],
        {"EBITDA": ebitda_missing},
    )

    # Capital allocation.
    out["free_cash_flow"] = valued(
        "free_cash_flow",
        "USD",
        [("free cash flow", fcf)],
        lambda v: v[0],
        explain={"free cash flow": fcf_missing},
    )
    for metric in ("share_repurchases", "dividends_paid", "stock_based_compensation"):
        out[metric] = valued(metric, "USD", [(LABELS[metric], flow[metric])], lambda v: v[0])
    dividends = flow["dividends_paid"]
    zero_note = dividends.note if dividends is not None and not dividends.sources else None
    out["dividends_paid"] = with_detail(out["dividends_paid"], zero_note)
    buybacks = flow["share_repurchases"]
    returned = (
        Input(
            "cash_returned",
            buybacks.value + dividends.value,
            window.start,
            window.end,
            buybacks.sources + dividends.sources,
            "share repurchases + dividends paid"
            + (f"; dividends {zero_note}" if zero_note else ""),
        )
        if buybacks is not None
        and dividends is not None
        and buybacks.value is not None
        and dividends.value is not None
        else None
    )
    out["cash_returned"] = with_detail(
        valued(
            "cash_returned",
            "USD",
            [("share repurchases", buybacks), ("dividends paid", dividends)],
            lambda v: v[0] + v[1],
        ),
        f"dividends {zero_note}" if zero_note else None,
    )
    out["cash_returned_to_fcf"] = valued(
        "cash_returned_to_fcf",
        "percent",
        [("cash returned", returned), ("free cash flow", fcf)],
        lambda v: percent(v[0], v[1]),
        [(1, "free cash flow")],
        {
            "cash returned": [
                label
                for label, v in (("share repurchases", buybacks), ("dividends paid", dividends))
                if v is None
            ],
            "free cash flow": fcf_missing,
        },
    )

    shares_now = book.diluted_shares(window, window.end)
    shares_before = book.diluted_shares(window, prior_end)
    out["diluted_shares_change"] = valued(
        "diluted_shares_change",
        "percent",
        [("diluted shares", shares_now), ("diluted shares a year earlier", shares_before)],
        lambda v: growth(v[0], v[1]),
        [(1, "diluted shares a year earlier")],
    )
    return out


def periods[FactT: DatedFact](book: Book[FactT]) -> list[Window]:
    """TTM (when it ends after the last fiscal year), then the last five fiscal years."""
    years = [
        Window("fiscal_year", p.start, p.end)
        for p in annual_periods(book.facts, YEARS)
        if p.start is not None
    ]
    for metric in TTM_SOURCES:
        found = trailing_twelve_months(book.series(metric))
        if found is not None:
            _, last = found
            ttm = Window("ttm", last[0].period_start, last[-1].period_end)
            if not years or ttm.end > years[0].end:
                return [ttm, *years]
            break
    return years


def research_record[FactT: DatedFact](
    facts: Sequence[FactT], at: datetime, splits: Sequence[Split]
) -> Record[FactT]:
    """Every row for every period, as known at `at` (facts already filtered to it)."""
    book = Book(facts, at, splits)
    shown = periods(book)
    by_period = [_period_values(book, w) for w in shown]
    return Record(
        periods=shown,
        rows=[
            (section, metric, unit, [values[metric] for values in by_period])
            for section, metric, unit in ROWS
        ],
    )
