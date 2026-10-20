"""Backtests (M2.5, ADR-033; 02 §23, 01 §23). Pure; no I/O.

A backtest replays a strategy's targets as they were known at each date T (an `Event`: the
target weights and the stored row they came from) on the closes, splits and dividends known at
the run's end. Each target is filled at the first session close published after T: a month-end
target is known at the end of that day's session, so its own close is never used. Between
targets the shares drift with prices; a split multiplies them on its ex-date; a cash dividend is
credited on its ex-date and stays in cash until the next target. Every trade pays the cost
model of its instrument type (half-spread plus slippage per side, times the scenario multiplier).

What a run reports (ADR-033 B1): the method, every trade as a change of weight with its fill
close and cost, turnover, holding periods, exposure (gross, by sector, weighted beta), costs in
basis points of the portfolio, calendar-year folds marked in-sample (before the strategy's rule
release) or out-of-sample, and the targets that would break the risk limits (for reference
only, B6). It never reports a return: the portfolio value is tracked as a normalized number
inside `simulate` only, and every performance metric is withheld (None) with the reason (OD-7,
KI-1, KI-16; errata E6). The same inputs always give the same document.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autotrading.domain.factors import Dividend
from autotrading.domain.risk import Bar
from autotrading.domain.splits import Split

Kind = Literal["equity", "etf"]
Sample = Literal["in_sample", "out_of_sample"]
HUNDRED = Decimal(100)
BPS = Decimal(10_000)
CENTS = Decimal("0.01")
MIN_WEIGHT_CHANGE = Decimal("0.01")  # percent: smaller changes are not traded
SESSIONS_PER_YEAR = Decimal(252)
WITHHELD = (
    "cagr",
    "volatility",
    "sharpe",
    "sortino",
    "max_drawdown",
    "hit_rate",
    "profit_factor",
    "tail_loss",
    "regime_performance",
    "trade_pnl",
)
WITHHELD_REASON = (
    "Performance is withheld (OD-7): the history holds only today's survivors (KI-1) and ETFs "
    "chosen today (KI-16), so returns would look better than they were. No return, ratio, "
    "drawdown or hit rate is computed or stored."
)


def _round(value: Decimal, quantum: Decimal = CENTS) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


# ---------- rules ----------


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SideCost(_Rule):
    half_spread_bps: Annotated[Decimal, Field(ge=0)]
    slippage_bps: Annotated[Decimal, Field(ge=0)]


class Costs(_Rule):
    commission_bps: Annotated[Decimal, Field(ge=0)]
    equity: SideCost
    etf: SideCost
    scenarios: dict[str, Annotated[Decimal, Field(gt=0)]]

    def bps(self, kind: Kind, scenario: str) -> Decimal:
        """Basis points of the traded value per side, for one instrument type and scenario."""
        side = self.equity if kind == "equity" else self.etf
        return (self.commission_bps + side.half_spread_bps + side.slippage_bps) * self.scenarios[
            scenario
        ]


class StrategySpec(_Rule):
    rules: Literal["buyback", "rotation", "momentum"]
    rule_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    released: date  # the rule version's release: out-of-sample after it
    since: date
    holds: list[str] = []  # buyback states that hold (S1)
    state_stale_after_days: int | None = None  # S1: an assignment older than this is ignored
    # S4: targets assessed from the factor snapshots at month ends (0.1.0), or the stored daily
    # momentum assessments that set a target (0.2.0, ADR-036 D7). The default keeps 0.1.0's hash.
    targets_from: Literal["factor_snapshots", "momentum_assessments"] = "factor_snapshots"


class BacktestRuleSet(_Rule):
    """One released rule version: immutable, like the risk rule sets (ADR-031)."""

    rule_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    released: date
    note: str
    capital: Annotated[Decimal, Field(gt=0)]
    benchmark: str
    costs: Costs
    strategies: dict[str, StrategySpec]
    risk_rule_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]

    @model_validator(mode="after")
    def _base(self) -> "BacktestRuleSet":
        if "base" not in self.costs.scenarios:
            raise ValueError("the costs need a base scenario")
        return self

    def content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"status"}, exclude_defaults=True)

    def content_sha256(self) -> str:
        canonical = json.dumps(self.content(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class BacktestRuleSetEntry(BacktestRuleSet):
    status: Literal["active", "retired"]

    def rule_set(self) -> BacktestRuleSet:
        return BacktestRuleSet.model_validate(self.content())


class BacktestRulesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    rule_sets: list[BacktestRuleSetEntry]

    @model_validator(mode="after")
    def _one_active(self) -> "BacktestRulesFile":
        versions = [r.rule_version for r in self.rule_sets]
        if len(versions) != len(set(versions)):
            raise ValueError("duplicate rule_version")
        if sum(r.status == "active" for r in self.rule_sets) != 1:
            raise ValueError("exactly one rule set must be active")
        return self

    def active(self) -> BacktestRuleSet:
        return next(r.rule_set() for r in self.rule_sets if r.status == "active")


# ---------- inputs ----------


@dataclass(frozen=True)
class Instrument:
    """One instrument's evidence known at the run's end: raw end-of-day bars (each on its own
    day's split basis), splits, cash dividends and its sector (for exposure and the limits)."""

    symbol: str
    kind: Kind
    bars: Sequence[Bar]
    splits: Sequence[Split] = ()
    dividends: Sequence[Dividend] = ()
    sector: str | None = None


@dataclass(frozen=True)
class Event:
    """A target as known at T: weights in percent, why it was set and the row it came from."""

    at: datetime
    weights: Mapping[str, Decimal]
    reason: str
    source: Mapping[str, str]  # {"table": ..., "id": ...}
    betas: Mapping[str, Decimal | None] = field(default_factory=dict)


@dataclass(frozen=True)
class Limits:
    """The risk limits each target is compared with, for reference (risk rules; B6)."""

    rule_version: str
    position_pct: Decimal
    sector_pct: Decimal
    gross_pct: Decimal
    volume_pct: Decimal
    volume_sessions: int
    unlimited_sectors: frozenset[str]


# ---------- results ----------


class Trade(BaseModel):
    day: date  # the session whose close filled it
    symbol: str
    side: Literal["buy", "sell"]
    weight_before: Decimal  # percent of the portfolio before the trade
    weight_after: Decimal
    price: Decimal  # the fill close
    cost_bps: Decimal  # of the traded value
    portfolio_cost_bps: Decimal  # of the portfolio


class Veto(BaseModel):
    limit: Literal["position", "sector", "gross", "volume"]
    subject: str  # a symbol, a sector or "portfolio"
    value: Decimal
    threshold: Decimal


class Rebalance(BaseModel):
    at: datetime  # T: when the target was known
    fill_day: date | None  # None: no session close after T yet
    reason: str
    source: dict[str, str]
    target: dict[str, Decimal]
    skipped: list[str]  # targets without a close on the fill day (left in cash)
    turnover_pct: Decimal  # buys plus sells, percent of the portfolio
    cost_bps: Decimal  # of the portfolio
    gross_pct: Decimal  # target weights held
    beta: Decimal | None  # weighted beta of the target (where known)
    sectors: dict[str, Decimal]
    vetoes: list[Veto]


class Fold(BaseModel):
    label: str
    year: int
    sample: Sample
    start: date
    end: date
    sessions: int
    rebalances: int
    trades: int
    turnover_pct: Decimal
    cost_bps: Decimal
    cost_bps_per_year: Decimal
    average_gross_pct: Decimal


class HeldPosition(BaseModel):
    symbol: str
    entry: date
    exit: date | None  # None: still held at the end
    sessions: int


class ScenarioResult(BaseModel):
    scenario: str
    multiplier: Decimal
    folds: list[Fold]
    trades: int
    turnover_pct: Decimal
    cost_bps: Decimal


class Withheld(BaseModel):
    metric: str
    value: None = None


class Run(BaseModel):
    """Everything a stored backtest run holds: recomputing it gives the same document."""

    rule_version: str
    strategy_id: str
    strategy_rule_version: str
    known_at: datetime
    released: date
    since: date
    start: date | None  # the first fill
    end: date | None  # the last session
    cost_bps: dict[str, Decimal]  # per side, base scenario, by instrument type
    rebalances: list[Rebalance]
    trades: list[Trade]
    positions: list[HeldPosition]
    scenarios: list[ScenarioResult]
    withheld: list[Withheld]
    withheld_reason: str
    notes: list[str]


# ---------- simulation ----------


@dataclass
class _FoldAcc:
    start: date
    end: date
    sessions: int = 0
    rebalances: int = 0
    trades: int = 0
    turnover: Decimal = Decimal(0)
    cost: Decimal = Decimal(0)
    gross: Decimal = Decimal(0)


@dataclass
class _Sim:
    trades: list[Trade]
    rebalances: list[Rebalance]
    positions: list[HeldPosition]
    folds: list[Fold]


def sessions(benchmark: Instrument, at: datetime) -> list[tuple[date, datetime]]:
    """The sessions known at the run's end: the benchmark's close days and their publication."""
    days = {b.day: b.published_at for b in benchmark.bars if b.published_at <= at}
    return sorted(days.items())


def fill_day(calendar: Sequence[tuple[date, datetime]], at: datetime) -> date | None:
    """The first session whose close was published after T."""
    return next((day for day, published in calendar if published > at), None)


def _closes(instrument: Instrument, at: datetime) -> dict[date, Bar]:
    return {
        b.day: b
        for b in instrument.bars
        if b.published_at <= at and b.feed_status in ("end_of_day", "fixture")
    }


def _ratio(splits: Sequence[Split], after: date, through: date) -> Fraction:
    """Shares after per share before, for splits effective after `after` up to `through`."""
    out = Fraction(1)
    for split in splits:
        if after < split.ex_date <= through:
            out *= split.ratio
    return out


def _volume(
    instrument: Instrument, bars: Mapping[date, Bar], day: date, sessions_: int
) -> Decimal | None:
    """The average shares traded over the last sessions up to `day`, on `day`'s basis."""
    window = sorted(d for d in bars if d <= day)[-sessions_:]
    if len(window) < sessions_:
        return None
    total = Decimal(0)
    for d in window:
        ratio = _ratio(instrument.splits, d, day)
        total += bars[d].volume * Decimal(ratio.numerator) / Decimal(ratio.denominator)
    return total / sessions_


def _vetoes(
    target: Mapping[str, Decimal],
    before: Mapping[str, Decimal],
    instruments: Mapping[str, Instrument],
    bars: Mapping[str, Mapping[date, Bar]],
    day: date | None,
    limits: Limits | None,
    capital: Decimal,
) -> list[Veto]:
    if limits is None:
        return []
    out: list[Veto] = []
    for symbol, weight in target.items():
        if weight > limits.position_pct:
            out.append(
                Veto(limit="position", subject=symbol, value=weight, threshold=limits.position_pct)
            )
    sectors: dict[str, Decimal] = {}
    for symbol, weight in target.items():
        sector = instruments[symbol].sector if symbol in instruments else None
        if sector is not None and sector not in limits.unlimited_sectors:
            sectors[sector] = sectors.get(sector, Decimal(0)) + weight
    for sector, weight in sorted(sectors.items()):
        if weight > limits.sector_pct:
            out.append(
                Veto(limit="sector", subject=sector, value=weight, threshold=limits.sector_pct)
            )
    gross = sum(target.values(), Decimal(0))
    if gross > limits.gross_pct:
        out.append(
            Veto(limit="gross", subject="portfolio", value=gross, threshold=limits.gross_pct)
        )
    if day is not None:
        for symbol in sorted(set(target) | set(before)):
            change = abs(target.get(symbol, Decimal(0)) - before.get(symbol, Decimal(0)))
            bar = bars.get(symbol, {}).get(day)
            if change < MIN_WEIGHT_CHANGE or bar is None or symbol not in instruments:
                continue
            average = _volume(instruments[symbol], bars[symbol], day, limits.volume_sessions)
            if not average:
                continue
            shares = capital * change / HUNDRED / bar.close
            share = _round(shares / average * HUNDRED, Decimal("0.0001"))
            if share > limits.volume_pct:
                out.append(
                    Veto(limit="volume", subject=symbol, value=share, threshold=limits.volume_pct)
                )
    return out


def _beta(target: Mapping[str, Decimal], betas: Mapping[str, Decimal | None]) -> Decimal | None:
    known = {s: betas[s] for s in target if betas.get(s) is not None}
    weight = sum((target[s] for s in known), Decimal(0))
    if not known or weight == 0:
        return None
    total = sum((target[s] * b for s, b in known.items() if b is not None), Decimal(0))
    return _round(total / weight, Decimal("0.001"))


def simulate(
    rules: BacktestRuleSet,
    spec: StrategySpec,
    at: datetime,
    events: Sequence[Event],
    instruments: Mapping[str, Instrument],
    scenario: str,
    limits: Limits | None = None,
) -> _Sim:
    """One cost scenario of a run. The normalized portfolio value never leaves this function."""
    calendar = sessions(instruments[rules.benchmark], at)
    bars = {s: _closes(i, at) for s, i in instruments.items()}
    fills: dict[date, Event] = {}
    unfilled: list[Event] = []
    for event in sorted(events, key=lambda e: e.at):
        day = fill_day(calendar, event.at)
        if day is None:
            unfilled.append(event)
        else:
            fills[day] = event  # a later target known before the same close replaces an earlier one
    shares: dict[str, Decimal] = {}
    last: dict[str, Decimal] = {}
    entries: dict[str, date] = {}
    held_sessions: dict[str, int] = {}
    cash = Decimal(1)
    trades: list[Trade] = []
    rebalances: list[Rebalance] = []
    positions: list[HeldPosition] = []
    folds: dict[tuple[int, Sample], _FoldAcc] = {}
    started = False

    def price(symbol: str) -> Decimal | None:
        return last.get(symbol)

    for day, _published in calendar:
        for symbol, bar_map in bars.items():
            if day in bar_map:
                last[symbol] = bar_map[day].close
        if not started and day not in fills:
            continue
        started = True
        for symbol in list(shares):
            ratio = Fraction(1)
            for split in instruments[symbol].splits:
                if split.ex_date == day:
                    ratio *= split.ratio
            if ratio != 1:
                shares[symbol] *= Decimal(ratio.numerator) / Decimal(ratio.denominator)
            for dividend in instruments[symbol].dividends:
                if dividend.ex_date == day:
                    cash += shares[symbol] * dividend.rate
        sample: Sample = "out_of_sample" if day > spec.released else "in_sample"
        key = (day.year, sample)
        fold = folds.setdefault(key, _FoldAcc(start=day, end=day))
        if day in fills:
            event = fills[day]
            value = cash + sum(
                (n * (price(s) or Decimal(0)) for s, n in shares.items()), Decimal(0)
            )
            before = {s: n * (price(s) or Decimal(0)) / value * HUNDRED for s, n in shares.items()}
            skipped = sorted(s for s in event.weights if day not in bars.get(s, {}))
            target = {s: w for s, w in event.weights.items() if s not in skipped}
            symbols = sorted(set(target) | set(shares))
            planned: dict[str, Decimal] = {}
            for symbol in symbols:
                change = target.get(symbol, Decimal(0)) - before.get(symbol, Decimal(0))
                if abs(change) >= MIN_WEIGHT_CHANGE or (symbol not in target and symbol in shares):
                    planned[symbol] = change
            costs = {s: rules.costs.bps(instruments[s].kind, scenario) for s in planned}
            expected = sum(
                (abs(c) / HUNDRED * value * costs[s] / BPS for s, c in planned.items()), Decimal(0)
            )
            invest = value - expected
            traded = Decimal(0)
            paid = Decimal(0)
            for symbol in planned:
                close = bars[symbol][day].close if day in bars.get(symbol, {}) else price(symbol)
                if close is None or close == 0:
                    continue
                wanted = invest * target.get(symbol, Decimal(0)) / HUNDRED / close
                delta = wanted - shares.get(symbol, Decimal(0))
                notional = abs(delta) * close
                cost = notional * costs[symbol] / BPS
                cash -= delta * close + cost
                traded += notional
                paid += cost
                if wanted == 0:
                    shares.pop(symbol, None)
                    if symbol in entries:
                        positions.append(
                            HeldPosition(
                                symbol=symbol,
                                entry=entries.pop(symbol),
                                exit=day,
                                sessions=held_sessions.pop(symbol, 0),
                            )
                        )
                else:
                    if symbol not in shares:
                        entries[symbol] = day
                        held_sessions[symbol] = 0
                    shares[symbol] = wanted
                trades.append(
                    Trade(
                        day=day,
                        symbol=symbol,
                        side="buy" if delta > 0 else "sell",
                        weight_before=_round(before.get(symbol, Decimal(0))),
                        weight_after=_round(target.get(symbol, Decimal(0))),
                        price=close,
                        cost_bps=_round(costs[symbol]),
                        portfolio_cost_bps=_round(cost / value * BPS, Decimal("0.0001")),
                    )
                )
            turnover = traded / value * HUNDRED
            cost_bps = paid / value * BPS
            sectors: dict[str, Decimal] = {}
            for symbol, weight in target.items():
                sector = instruments[symbol].sector or "unclassified"
                sectors[sector] = sectors.get(sector, Decimal(0)) + weight
            rebalances.append(
                Rebalance(
                    at=event.at,
                    fill_day=day,
                    reason=event.reason,
                    source=dict(event.source),
                    target={s: _round(w) for s, w in target.items()},
                    skipped=skipped,
                    turnover_pct=_round(turnover),
                    cost_bps=_round(cost_bps, Decimal("0.0001")),
                    gross_pct=_round(sum(target.values(), Decimal(0))),
                    beta=_beta(target, event.betas),
                    sectors={s: _round(w) for s, w in sorted(sectors.items())},
                    vetoes=_vetoes(target, before, instruments, bars, day, limits, rules.capital),
                )
            )
            fold.rebalances += 1
            fold.trades += len(planned)
            fold.turnover += turnover
            fold.cost += cost_bps
        value = cash + sum((n * (price(s) or Decimal(0)) for s, n in shares.items()), Decimal(0))
        gross = (value - cash) / value * HUNDRED if value else Decimal(0)
        for symbol in shares:
            held_sessions[symbol] = held_sessions.get(symbol, 0) + 1
        fold.end = day
        fold.sessions += 1
        fold.gross += gross
    for symbol in sorted(entries):
        positions.append(
            HeldPosition(
                symbol=symbol,
                entry=entries[symbol],
                exit=None,
                sessions=held_sessions.get(symbol, 0),
            )
        )
    for event in unfilled:
        rebalances.append(
            Rebalance(
                at=event.at,
                fill_day=None,
                reason=event.reason,
                source=dict(event.source),
                target={s: _round(w) for s, w in event.weights.items()},
                skipped=[],
                turnover_pct=Decimal(0),
                cost_bps=Decimal(0),
                gross_pct=_round(sum(event.weights.values(), Decimal(0))),
                beta=_beta(event.weights, event.betas),
                sectors={},
                vetoes=_vetoes(event.weights, {}, instruments, bars, None, limits, rules.capital),
            )
        )
    out: list[Fold] = []
    years = [year for year, _ in folds]
    for (year, sample), acc in sorted(folds.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        split_year = years.count(year) > 1
        out.append(
            Fold(
                label=f"{year} {sample.replace('_', '-')}" if split_year else f"{year}",
                year=year,
                sample=sample,
                start=acc.start,
                end=acc.end,
                sessions=acc.sessions,
                rebalances=acc.rebalances,
                trades=acc.trades,
                turnover_pct=_round(acc.turnover),
                cost_bps=_round(acc.cost, Decimal("0.0001")),
                cost_bps_per_year=_round(
                    acc.cost * SESSIONS_PER_YEAR / acc.sessions, Decimal("0.0001")
                )
                if acc.sessions
                else Decimal(0),
                average_gross_pct=_round(acc.gross / acc.sessions) if acc.sessions else Decimal(0),
            )
        )
    return _Sim(trades=trades, rebalances=rebalances, positions=positions, folds=out)


def run(
    rules: BacktestRuleSet,
    strategy_id: str,
    at: datetime,
    events: Sequence[Event],
    instruments: Mapping[str, Instrument],
    limits: Limits | None,
    notes: Sequence[str] = (),
) -> Run:
    """A backtest of one strategy at the run's end T: the base scenario in full, every scenario's
    folds and totals; performance withheld."""
    spec = rules.strategies[strategy_id]
    results: dict[str, _Sim] = {
        name: simulate(
            rules, spec, at, events, instruments, name, limits if name == "base" else None
        )
        for name in rules.costs.scenarios
    }
    base = results["base"]
    filled = [r for r in base.rebalances if r.fill_day is not None]
    return Run(
        rule_version=rules.rule_version,
        strategy_id=strategy_id,
        strategy_rule_version=spec.rule_version,
        known_at=at,
        released=spec.released,
        since=spec.since,
        start=filled[0].fill_day if filled else None,
        end=base.folds[-1].end if base.folds else None,
        cost_bps={kind: rules.costs.bps(kind, "base") for kind in ("equity", "etf")},
        rebalances=base.rebalances,
        trades=base.trades,
        positions=base.positions,
        scenarios=[
            ScenarioResult(
                scenario=name,
                multiplier=rules.costs.scenarios[name],
                folds=sim.folds,
                trades=sum(f.trades for f in sim.folds),
                turnover_pct=_round(sum((f.turnover_pct for f in sim.folds), Decimal(0))),
                cost_bps=_round(
                    sum((f.cost_bps for f in sim.folds), Decimal(0)), Decimal("0.0001")
                ),
            )
            for name, sim in results.items()
        ],
        withheld=[Withheld(metric=m) for m in WITHHELD],
        withheld_reason=WITHHELD_REASON,
        notes=list(notes),
    )


def equal_weights(symbols: Sequence[str], quantum: Decimal = CENTS) -> dict[str, Decimal]:
    """Equal weights in percent, rounded down to the quantum; the rest is cash."""
    if not symbols:
        return {}
    weight = (HUNDRED / len(symbols)).quantize(quantum, rounding=ROUND_DOWN)
    return {s: weight for s in symbols}
