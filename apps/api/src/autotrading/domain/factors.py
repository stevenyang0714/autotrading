"""Price, trend and factor measures (M2.2, ADR-030; build spec 02 §13). Pure; no I/O.

From the end-of-day closes, splits and cash dividends known at a time T, for one instrument and
its market's benchmark (SPY; 0050 for Taiwan since M3.7, ADR-039 TW10), the measures of a
versioned definition set (config/factor_definitions.yaml), on the market's own dates:
- trend: 12-1 and 6-1 month momentum, 1-month reversal (total returns), the close against its
  50- and 200-session averages (prices);
- risk: 60-session volatility of daily total returns, annualized; 252-session beta to the
  benchmark;
- relative: momentum minus the benchmark's same momentum.
Closes and dividends are moved to T's split basis (domain/splits); a total return reinvests each
cash dividend at the close of its ex-date. Sessions are the days that have a close. A measure
without enough closes is `unavailable`, never guessed; one that may miss a dividend says so.
Value and quality measures come from the Research Record (domain/valuation, domain/research)
and are put in the same shape by the caller. Time-series only (P2-3): nothing is ranked against
other instruments, and nothing here is a signal or prepares an order.
"""

import hashlib
import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from itertools import pairwise
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autotrading.domain.markets import MARKETS, Market
from autotrading.domain.splits import NEW_YORK, Split, adjust, effective_at
from autotrading.domain.valuation import Close, close_basis

PRICE_MEASURES = (
    "momentum_12_1",
    "momentum_6_1",
    "reversal_1m",
    "close_vs_sma_50",
    "close_vs_sma_200",
    "volatility_60d",
    "beta_252d",
)
Group = Literal["trend", "risk", "relative", "value", "quality"]
MeasureUnit = Literal["percent", "x", "ratio"]
Reason = Literal["unavailable", "not_meaningful"]
TWO = Decimal("0.01")
THREE = Decimal("0.001")
HUNDRED = Decimal(100)


# ---------- definitions ----------


class _Def(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MomentumDef(_Def):
    from_sessions: Annotated[int, Field(gt=0)]
    to_sessions: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _ordered(self) -> "MomentumDef":
        if self.to_sessions >= self.from_sessions:
            raise ValueError("to_sessions must be fewer than from_sessions")
        return self


class ReturnDef(_Def):
    sessions: Annotated[int, Field(gt=0)]


class AverageDef(_Def):
    sessions: Annotated[int, Field(gt=1)]


class VolatilityDef(_Def):
    sessions: Annotated[int, Field(gt=2)]
    annualization_sessions: Annotated[int, Field(gt=0)]


class BetaDef(_Def):
    sessions: Annotated[int, Field(gt=2)]
    min_paired_share: Annotated[Decimal, Field(gt=0, le=1)]


class PriceDefinitions(_Def):
    momentum_12_1: MomentumDef
    momentum_6_1: MomentumDef
    reversal_1m: ReturnDef
    close_vs_sma_50: AverageDef
    close_vs_sma_200: AverageDef
    volatility_60d: VolatilityDef
    beta_252d: BetaDef
    relative: list[Literal["momentum_12_1", "momentum_6_1"]]


class FundamentalDefinitions(_Def):
    value: list[str]
    quality: list[str]


class FactorDefinitionSet(_Def):
    """One released definition version: immutable, like the regime rule sets (ADR-029)."""

    definition_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    released: date
    note: str
    benchmark: str
    stale_after_days: Annotated[int, Field(gt=0)]
    dividend_gap_ratio: Annotated[Decimal, Field(gt=1)]
    dividends_since: date
    price: PriceDefinitions
    fundamentals: FundamentalDefinitions
    percentile_since: date
    # M3.7 (ADR-039 TW10): the market a set measures, and the fewest month-end snapshots a
    # percentile needs. Defaults keep 0.1.0's content and hash.
    market: Market = "US"
    percentile_min_observations: Annotated[int, Field(gt=0)] | None = None

    @property
    def zone(self) -> ZoneInfo:
        """The time zone of the market's dates (its sessions and the stale check)."""
        return MARKETS[self.market].zone

    def content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"status"}, exclude_defaults=True)

    def content_sha256(self) -> str:
        canonical = json.dumps(self.content(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class FactorDefinitionSetEntry(FactorDefinitionSet):
    status: Literal["active", "retired"]

    def definitions(self) -> FactorDefinitionSet:
        return FactorDefinitionSet.model_validate(self.content())


class FactorDefinitionsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    definition_sets: list[FactorDefinitionSetEntry]

    @model_validator(mode="after")
    def _one_active(self) -> "FactorDefinitionsFile":
        versions = [d.definition_version for d in self.definition_sets]
        if len(versions) != len(set(versions)):
            raise ValueError("duplicate definition_version")
        markets = {d.market for d in self.definition_sets}
        for market in markets:
            active = [d for d in self.definition_sets if d.market == market]
            if sum(d.status == "active" for d in active) != 1:
                raise ValueError(f"exactly one {market} definition set must be active")
        if "US" not in markets:
            raise ValueError("exactly one US definition set must be active")
        return self

    def active(self, market: Market = "US") -> FactorDefinitionSet:
        """The active set of a market (one per market since M3.7, ADR-039 TW10)."""
        return next(
            d.definitions()
            for d in self.definition_sets
            if d.status == "active" and d.market == market
        )


# ---------- inputs ----------


@dataclass(frozen=True)
class Dividend:
    """One cash dividend per share as of its ex-date, known from the start of the ex-date."""

    ex_date: date
    rate: Decimal
    special: bool
    zone: ZoneInfo = NEW_YORK  # the market's zone of the ex-date (Taipei for TWSE)

    @property
    def published_at(self) -> datetime:
        return effective_at(self.ex_date, self.zone)


@dataclass(frozen=True)
class Series:
    """One instrument's evidence at T: closes, splits and dividends public then."""

    symbol: str
    closes: Sequence[Close]
    splits: Sequence[Split]
    dividends: Sequence[Dividend]


# ---------- result ----------


class FactorInput(BaseModel):
    name: str  # "close", "average close", "dividends", "benchmark ...", or a metric id
    value: Decimal | None
    start: date | None = None
    end: date | None = None
    note: str | None = None
    sources: list[str] = []  # accession numbers of the filings behind a reported value


class Measure(BaseModel):
    measure_id: str
    group: Group
    unit: MeasureUnit
    value: Decimal | None
    reason: Reason | None = None
    detail: str
    start: date | None = None  # the first close (or period start) the value reads
    end: date | None = None  # the last close (or period end)
    inputs: list[FactorInput] = []
    notes: list[str] = []  # e.g. a dividend that may be missing in the window


class FactorSnapshot(BaseModel):
    """Everything a factor snapshot stores: recomputing it gives the same document."""

    definition_version: str
    known_at: datetime
    symbol: str
    instrument_type: Literal["equity", "etf"]
    scope: Literal["price", "all"]  # price: the fundamentals were not computed for this T
    last_close: date | None
    feed_status: str | None  # of the last close: end_of_day, or fixture for recorded data
    measures: list[Measure]

    def values(self) -> dict[str, str | None]:
        """measure id -> value, for the history and percentiles."""
        return {m.measure_id: None if m.value is None else str(m.value) for m in self.measures}


# ---------- prices ----------


def _round(value: Decimal, quantum: Decimal = TWO) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def known_closes(closes: Sequence[Close], at: datetime, splits: Sequence[Split]) -> list[Close]:
    """End-of-day (or recorded fixture) closes public at T, each on T's split basis, oldest
    first; one per day."""
    by_day: dict[date, Close] = {}
    for close in closes:
        if close.published_at > at or close.feed_status not in ("end_of_day", "fixture"):
            continue
        moved = adjust("close", close.close, close_basis(close), at, splits)
        by_day[close.day] = Close(
            close.day,
            moved.value if moved else close.close,
            close.feed_status,
            close.published_at,
            close.zone,
        )
    return [by_day[day] for day in sorted(by_day)]


def known_dividends(
    dividends: Sequence[Dividend], at: datetime, splits: Sequence[Split]
) -> list[Dividend]:
    """Dividends public at T, each per share on T's split basis, by ex-date."""
    out = []
    for dividend in sorted(dividends, key=lambda d: (d.ex_date, d.special)):
        if dividend.published_at > at:
            continue
        moved = adjust("close", dividend.rate, dividend.published_at, at, splits)
        out.append(
            Dividend(
                dividend.ex_date,
                moved.value if moved else dividend.rate,
                dividend.special,
                dividend.zone,
            )
        )
    return out


@dataclass(frozen=True)
class Returns:
    """Daily total returns: `growth[k]` is (close k + dividends going ex after close k-1 and by
    day k) / close k-1, for k >= 1; `paid[k]` those dividends."""

    closes: list[Close]
    growth: list[Decimal | None]
    paid: list[Decimal]


def total_returns(closes: list[Close], dividends: Sequence[Dividend]) -> Returns:
    growth: list[Decimal | None] = [None]
    paid = [Decimal(0)]
    i = 0
    ordered = sorted(dividends, key=lambda d: d.ex_date)
    # dividends that went ex before the first close are not part of any return
    while i < len(ordered) and closes and ordered[i].ex_date <= closes[0].day:
        i += 1
    with localcontext() as ctx:
        ctx.prec = 28
        for k in range(1, len(closes)):
            amount = Decimal(0)
            while i < len(ordered) and ordered[i].ex_date <= closes[k].day:
                amount += ordered[i].rate
                i += 1
            previous = closes[k - 1].close
            growth.append((closes[k].close + amount) / previous if previous > 0 else None)
            paid.append(amount)
    return Returns(closes, growth, paid)


def _compound(returns: Returns, start: int, end: int) -> Decimal | None:
    """Total return in percent from close `start` to close `end` (indexes)."""
    with localcontext() as ctx:
        ctx.prec = 28
        product = Decimal(1)
        for k in range(start + 1, end + 1):
            g = returns.growth[k]
            if g is None:
                return None
            product *= g
        return _round((product - 1) * HUNDRED)


def _dividend_inputs(returns: Returns, start: int, end: int) -> FactorInput:
    total = sum(returns.paid[start + 1 : end + 1], Decimal(0))
    count = sum(1 for p in returns.paid[start + 1 : end + 1] if p)
    return FactorInput(
        name="dividends",
        value=total.normalize() if total else Decimal(0),
        start=returns.closes[start].day,
        end=returns.closes[end].day,
        note=f"{count} ex-date{'s' if count != 1 else ''} reinvested at the close",
    )


def dividend_gaps(
    dividends: Sequence[Dividend], start: date, end: date, since: date, ratio: Decimal
) -> list[str]:
    """Possible missing payments in [start, end]: an interval between recorded ex-dates (or from
    the start of the recorded history, or up to `end`) longer than `ratio` times the usual one.
    Needs at least four regular payments to know the usual interval."""
    days = sorted({d.ex_date for d in dividends if not d.special})
    if len(days) < 4:
        return []
    usual = Decimal(statistics.median((b - a).days for a, b in pairwise(days)))
    limit = usual * ratio
    notes = []
    if (
        days[0] - since <= timedelta(days=366)
        and Decimal((days[0] - since).days) > limit
        and start < days[0]
    ):
        notes.append(f"no dividend recorded before {days[0]} (history from {since})")
    for a, b in pairwise(days):
        if Decimal((b - a).days) > limit and a < end and b > start:
            notes.append(f"no dividend recorded between {a} and {b} (usually every {usual} days)")
    if days[-1] < end and Decimal((end - days[-1]).days) > limit:
        notes.append(f"no dividend recorded since {days[-1]} (usually every {usual} days)")
    return notes


def _unavailable(measure_id: str, group: Group, unit: MeasureUnit, detail: str) -> Measure:
    return Measure(
        measure_id=measure_id,
        group=group,
        unit=unit,
        value=None,
        reason="unavailable",
        detail=detail,
    )


def _window_return(
    measure_id: str,
    returns: Returns,
    from_sessions: int,
    to_sessions: int,
    gaps: list[str],
    label: str,
) -> Measure:
    n = len(returns.closes)
    if n < from_sessions + 1:
        return _unavailable(
            measure_id, "trend", "percent", f"{n} closes known; {from_sessions + 1} needed"
        )
    start, end = n - 1 - from_sessions, n - 1 - to_sessions
    value = _compound(returns, start, end)
    if value is None:
        return _unavailable(measure_id, "trend", "percent", "a close of zero in the window")
    first, last = returns.closes[start], returns.closes[end]
    return Measure(
        measure_id=measure_id,
        group="trend",
        unit="percent",
        value=value,
        detail=label,
        start=first.day,
        end=last.day,
        inputs=[
            FactorInput(name="close", value=first.close, start=first.day, end=first.day),
            FactorInput(name="close", value=last.close, start=last.day, end=last.day),
            _dividend_inputs(returns, start, end),
        ],
        notes=gaps,
    )


def _average(measure_id: str, closes: list[Close], sessions: int) -> Measure:
    if len(closes) < sessions:
        return _unavailable(
            measure_id, "trend", "percent", f"{len(closes)} closes known; {sessions} needed"
        )
    window = closes[-sessions:]
    with localcontext() as ctx:
        ctx.prec = 28
        mean = sum((c.close for c in window), Decimal(0)) / sessions
        value = _round((window[-1].close / mean - 1) * HUNDRED)
    return Measure(
        measure_id=measure_id,
        group="trend",
        unit="percent",
        value=value,
        detail=f"close {window[-1].day} against its {sessions}-session average close",
        start=window[0].day,
        end=window[-1].day,
        inputs=[
            FactorInput(
                name="close", value=window[-1].close, start=window[-1].day, end=window[-1].day
            ),
            FactorInput(
                name="average close",
                value=_round(mean, Decimal("0.0001")),
                start=window[0].day,
                end=window[-1].day,
                note=f"mean of {sessions} closes on the split basis of the date",
            ),
        ],
    )


def _daily(returns: Returns, sessions: int) -> list[tuple[date, Decimal]] | None:
    """The last `sessions` daily total returns (as fractions), by day; None if a close is zero."""
    out = []
    for k in range(len(returns.closes) - sessions, len(returns.closes)):
        g = returns.growth[k]
        if g is None:
            return None
        out.append((returns.closes[k].day, g - 1))
    return out


def _volatility(definition: VolatilityDef, returns: Returns, gaps: list[str]) -> Measure:
    n = len(returns.closes)
    need = definition.sessions + 1
    if n < need:
        return _unavailable("volatility_60d", "risk", "percent", f"{n} closes known; {need} needed")
    daily = _daily(returns, definition.sessions)
    if daily is None:
        return _unavailable("volatility_60d", "risk", "percent", "a close of zero in the window")
    with localcontext() as ctx:
        ctx.prec = 28
        values = [r for _, r in daily]
        mean = sum(values, Decimal(0)) / len(values)
        variance = sum(((r - mean) ** 2 for r in values), Decimal(0)) / (len(values) - 1)
        annual = (variance * definition.annualization_sessions).sqrt()
        value = _round(annual * HUNDRED)
    return Measure(
        measure_id="volatility_60d",
        group="risk",
        unit="percent",
        value=value,
        detail=(
            f"standard deviation of {definition.sessions} daily total returns, "
            f"times the square root of {definition.annualization_sessions}"
        ),
        start=returns.closes[n - 1 - definition.sessions].day,
        end=returns.closes[-1].day,
        inputs=[_dividend_inputs(returns, n - 1 - definition.sessions, n - 1)],
        notes=gaps,
    )


def _beta(definition: BetaDef, returns: Returns, benchmark: Returns | None, name: str) -> Measure:
    n = len(returns.closes)
    need = definition.sessions + 1
    if benchmark is None:
        return _unavailable("beta_252d", "risk", "ratio", f"no {name} closes known")
    if n < need:
        return _unavailable("beta_252d", "risk", "ratio", f"{n} closes known; {need} needed")
    own = _daily(returns, definition.sessions)
    theirs = dict(
        (benchmark.closes[k].day, g - 1)
        for k, g in enumerate(benchmark.growth)
        if g is not None and k > 0
    )
    if own is None:
        return _unavailable("beta_252d", "risk", "ratio", "a close of zero in the window")
    paired = [(r, theirs[day]) for day, r in own if day in theirs]
    if Decimal(len(paired)) < definition.min_paired_share * definition.sessions or len(paired) < 3:
        return _unavailable(
            "beta_252d",
            "risk",
            "ratio",
            f"{len(paired)} of {definition.sessions} sessions have a {name} return",
        )
    with localcontext() as ctx:
        ctx.prec = 28
        mx = sum((a for a, _ in paired), Decimal(0)) / len(paired)
        my = sum((b for _, b in paired), Decimal(0)) / len(paired)
        covariance = sum(((a - mx) * (b - my) for a, b in paired), Decimal(0))
        variance = sum(((b - my) ** 2 for _, b in paired), Decimal(0))
        if variance == 0:
            return _unavailable("beta_252d", "risk", "ratio", f"{name} returns did not vary")
        value = _round(covariance / variance, THREE)
    return Measure(
        measure_id="beta_252d",
        group="risk",
        unit="ratio",
        value=value,
        detail=f"daily total returns against {name}'s over {len(paired)} common sessions",
        start=returns.closes[n - 1 - definition.sessions].day,
        end=returns.closes[-1].day,
    )


def _relative(measure: Measure, theirs: Measure | None, symbol: str, benchmark: str) -> Measure:
    measure_id = f"relative_{measure.measure_id}"
    if symbol == benchmark:
        return Measure(
            measure_id=measure_id,
            group="relative",
            unit="percent",
            value=None,
            reason="not_meaningful",
            detail=f"{benchmark} is the benchmark",
        )
    if measure.value is None:
        return _unavailable(measure_id, "relative", "percent", measure.detail)
    if theirs is None or theirs.value is None:
        return _unavailable(
            measure_id, "relative", "percent", f"no {benchmark} value for the same closes"
        )
    if (theirs.start, theirs.end) != (measure.start, measure.end):
        return _unavailable(
            measure_id,
            "relative",
            "percent",
            f"{benchmark}'s window {theirs.start} to {theirs.end} differs from "
            f"{measure.start} to {measure.end}",
        )
    return Measure(
        measure_id=measure_id,
        group="relative",
        unit="percent",
        value=_round(measure.value - theirs.value),
        detail=f"{measure.measure_id} minus {benchmark}'s over the same closes",
        start=measure.start,
        end=measure.end,
        inputs=[
            FactorInput(
                name=measure.measure_id, value=measure.value, start=measure.start, end=measure.end
            ),
            FactorInput(
                name=f"{benchmark} {theirs.measure_id}",
                value=theirs.value,
                start=theirs.start,
                end=theirs.end,
            ),
        ],
        notes=measure.notes + theirs.notes,
    )


def _trend(
    definitions: FactorDefinitionSet,
    returns: Returns,
    dividends: Sequence[Dividend],
) -> dict[str, Measure]:
    price = definitions.price

    def gaps(sessions: int) -> list[str]:
        n = len(returns.closes)
        if n < sessions + 1:
            return []
        return dividend_gaps(
            dividends,
            returns.closes[n - 1 - sessions].day,
            returns.closes[-1].day,
            definitions.dividends_since,
            definitions.dividend_gap_ratio,
        )

    out = {
        "momentum_12_1": _window_return(
            "momentum_12_1",
            returns,
            price.momentum_12_1.from_sessions,
            price.momentum_12_1.to_sessions,
            gaps(price.momentum_12_1.from_sessions),
            f"total return from {price.momentum_12_1.from_sessions} to "
            f"{price.momentum_12_1.to_sessions} sessions before the last close",
        ),
        "momentum_6_1": _window_return(
            "momentum_6_1",
            returns,
            price.momentum_6_1.from_sessions,
            price.momentum_6_1.to_sessions,
            gaps(price.momentum_6_1.from_sessions),
            f"total return from {price.momentum_6_1.from_sessions} to "
            f"{price.momentum_6_1.to_sessions} sessions before the last close",
        ),
        "reversal_1m": _window_return(
            "reversal_1m",
            returns,
            price.reversal_1m.sessions,
            0,
            gaps(price.reversal_1m.sessions),
            f"total return over the last {price.reversal_1m.sessions} sessions",
        ),
        "close_vs_sma_50": _average(
            "close_vs_sma_50", returns.closes, price.close_vs_sma_50.sessions
        ),
        "close_vs_sma_200": _average(
            "close_vs_sma_200", returns.closes, price.close_vs_sma_200.sessions
        ),
        "volatility_60d": _volatility(
            price.volatility_60d, returns, gaps(price.volatility_60d.sessions)
        ),
    }
    return out


def _benchmark_itself(measure_id: str, group: Group, unit: MeasureUnit, name: str) -> Measure:
    return Measure(
        measure_id=measure_id,
        group=group,
        unit=unit,
        value=None,
        reason="not_meaningful",
        detail=f"{name} is the benchmark",
    )


def _all_unavailable(definitions: FactorDefinitionSet, symbol: str, detail: str) -> list[Measure]:
    """Every price measure unavailable for `detail`; the benchmark's beta and relative measures
    stay not meaningful."""
    name = definitions.benchmark
    out = [
        _benchmark_itself(m, "risk", "ratio", name)
        if m == "beta_252d" and symbol == name
        else _unavailable(
            m,
            "risk" if m in ("volatility_60d", "beta_252d") else "trend",
            "ratio" if m == "beta_252d" else "percent",
            detail,
        )
        for m in PRICE_MEASURES
    ]
    return out + [
        _benchmark_itself(f"relative_{m}", "relative", "percent", name)
        if symbol == name
        else _unavailable(f"relative_{m}", "relative", "percent", detail)
        for m in definitions.price.relative
    ]


def price_measures(
    definitions: FactorDefinitionSet, at: datetime, series: Series, benchmark: Series | None
) -> tuple[list[Measure], Close | None]:
    """The price measures of one instrument at T, and the last close they read. `benchmark` is
    the benchmark's evidence at T (None when it has none)."""
    closes = known_closes(series.closes, at, series.splits)
    last = closes[-1] if closes else None
    stale = definitions.stale_after_days
    if last is None:
        return _all_unavailable(definitions, series.symbol, "no close known at this time"), None
    if at.astimezone(definitions.zone).date() - last.day > timedelta(days=stale):
        detail = f"the last close ({last.day}) is older than {stale} days"
        return _all_unavailable(definitions, series.symbol, detail), last
    dividends = known_dividends(series.dividends, at, series.splits)
    returns = total_returns(closes, dividends)
    own = _trend(definitions, returns, dividends)
    measures = list(own.values())

    name = definitions.benchmark
    if series.symbol == name:
        measures.append(
            Measure(
                measure_id="beta_252d",
                group="risk",
                unit="ratio",
                value=None,
                reason="not_meaningful",
                detail=f"{name} is the benchmark",
            )
        )
        measures += [
            _relative(own[m], None, series.symbol, name) for m in definitions.price.relative
        ]
        return measures, last

    theirs: dict[str, Measure] = {}
    bench_returns: Returns | None = None
    if benchmark is not None:
        bench_closes = [
            c for c in known_closes(benchmark.closes, at, benchmark.splits) if c.day <= last.day
        ]
        if bench_closes:
            bench_dividends = known_dividends(benchmark.dividends, at, benchmark.splits)
            bench_returns = total_returns(bench_closes, bench_dividends)
            theirs = _trend(definitions, bench_returns, bench_dividends)
    measures.append(_beta(definitions.price.beta_252d, returns, bench_returns, name))
    measures += [
        _relative(own[m], theirs.get(m), series.symbol, name) for m in definitions.price.relative
    ]
    return measures, last
