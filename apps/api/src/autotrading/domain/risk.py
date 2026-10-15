"""Paper portfolio and risk check (M2.3, ADR-031; build spec 02 §20). Pure; no I/O.

The paper portfolio is the journal's open paper TRADEs known at a time T, marked at the last
end-of-day close known then. Shares, entry prices and closes are moved to T's split basis
(domain/splits), so a split never looks like a gain or a loss. From it:
- positions with their market value, weight of the notional capital, P&L, beta and sector, and
  how many days of average volume they would take to exit;
- realized and unrealized P&L, equity, gross and net exposure, beta-weighted exposure and
  exposure by sector;
- the daily equity curve since the first entry, its peak and the drawdown from it.

A risk check adds a proposed trade to that portfolio and tests each limit of a versioned rule
set (config/risk_rules.yaml): the price, the stated maximum loss, the instrument's and its
sector's share of capital, the trade against the average daily volume, and gross exposure (no
leverage). Any veto refuses the trade. The same portfolio, prices and rule version always give
the same verdict. Paper only: nothing here places or prepares an order.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autotrading.domain.splits import NEW_YORK, Split, splits_between

Side = Literal["buy", "sell"]
Status = Literal["pass", "veto"]
Verdict = Literal["pass", "veto"]
CENTS = Decimal("0.01")
SHARES = Decimal("0.0001")
HUNDRED = Decimal(100)


def _round(value: Decimal, quantum: Decimal = CENTS) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


# ---------- rules ----------


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Limits(_Rule):
    position_pct: Annotated[Decimal, Field(gt=0)]
    max_loss_pct: Annotated[Decimal, Field(gt=0)]
    sector_pct: Annotated[Decimal, Field(gt=0)]
    volume_pct: Annotated[Decimal, Field(gt=0)]
    volume_sessions: Annotated[int, Field(gt=0)]
    gross_pct: Annotated[Decimal, Field(gt=0)]
    stale_after_days: Annotated[int, Field(gt=0)]


class Standard(_Rule):
    position_pct: Annotated[Decimal, Field(gt=0)]
    max_loss_pct: Annotated[Decimal, Field(gt=0)]


class SectorEntry(_Rule):
    sector: str
    source: str


class RiskRuleSet(_Rule):
    """One released rule version: immutable, like the regime rule sets (ADR-029)."""

    rule_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    released: date
    note: str
    capital: Annotated[Decimal, Field(gt=0)]
    limits: Limits
    drawdown_alert_pct: Annotated[Decimal, Field(gt=0)]
    standard: Standard
    unlimited_sectors: list[str]
    sectors: dict[str, SectorEntry]

    def content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"status"}, exclude_defaults=True)

    def content_sha256(self) -> str:
        canonical = json.dumps(self.content(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def pct(self, value: Decimal) -> Decimal:
        """A dollar amount as a percent of the notional capital, rounded for display."""
        return _round(value / self.capital * HUNDRED)

    def within(self, value: Decimal, pct: Decimal) -> bool:
        """Whether a dollar amount is at most `pct` percent of the capital, exactly (the
        displayed percent is rounded; the comparison is not)."""
        return value * HUNDRED <= self.capital * pct


class RiskRuleSetEntry(RiskRuleSet):
    status: Literal["active", "retired"]

    def rule_set(self) -> RiskRuleSet:
        return RiskRuleSet.model_validate(self.content())


class RiskRulesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    rule_sets: list[RiskRuleSetEntry]

    @model_validator(mode="after")
    def _one_active(self) -> "RiskRulesFile":
        versions = [r.rule_version for r in self.rule_sets]
        if len(versions) != len(set(versions)):
            raise ValueError("duplicate rule_version")
        if sum(r.status == "active" for r in self.rule_sets) != 1:
            raise ValueError("exactly one rule set must be active")
        return self

    def active(self) -> RiskRuleSet:
        return next(r.rule_set() for r in self.rule_sets if r.status == "active")


# ---------- inputs ----------


@dataclass(frozen=True)
class Bar:
    """One end-of-day bar known at T: the close and the shares traded, as reported then."""

    day: date
    close: Decimal
    volume: Decimal
    feed_status: str
    published_at: datetime


@dataclass(frozen=True)
class Fill:
    """The close a paper decision was recorded at (journal entry_close)."""

    day: date
    close: Decimal
    published_at: datetime


@dataclass(frozen=True)
class Trade:
    """A paper TRADE entry known at T, with its exit if one is known then."""

    decision_id: str
    ticker: str
    side: Side
    quantity: Decimal  # shares as recorded
    entry: Fill
    known_at: datetime
    max_loss: Decimal | None
    exit: Fill | None = None
    exit_known_at: datetime | None = None


@dataclass(frozen=True)
class Market:
    """One instrument's evidence at T: bars and splits public then, beta, sector."""

    ticker: str
    bars: Sequence[Bar]
    splits: Sequence[Split]
    beta: Decimal | None
    sector: str | None


# ---------- results ----------


class Position(BaseModel):
    decision_id: str
    ticker: str
    side: Side
    shares: Decimal  # on T's split basis
    entry_price: Decimal  # on T's split basis
    entry_day: date
    mark: Decimal | None
    mark_day: date | None
    market_value: Decimal | None  # signed: negative for a short
    weight_pct: Decimal | None  # gross market value / capital
    pnl: Decimal | None
    beta: Decimal | None
    sector: str | None
    days_to_exit: Decimal | None  # shares / average daily volume
    stale: bool
    max_loss: Decimal | None


class SectorExposure(BaseModel):
    sector: str
    gross: Decimal
    pct: Decimal
    limited: bool


class EquityPoint(BaseModel):
    day: date
    equity: Decimal


class Portfolio(BaseModel):
    """The paper portfolio at T: everything a portfolio snapshot stores."""

    rule_version: str
    known_at: datetime
    capital: Decimal
    positions: list[Position]
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    equity: Decimal
    cash: Decimal  # equity minus net exposure
    gross: Decimal
    net: Decimal
    gross_pct: Decimal
    net_pct: Decimal
    beta_exposure: Decimal | None  # sum of market value x beta; None when a beta is missing
    sectors: list[SectorExposure]
    curve: list[EquityPoint]
    peak_equity: Decimal
    drawdown_pct: Decimal
    notes: list[str]


class Proposal(BaseModel):
    ticker: str
    side: Side
    quantity: Decimal
    max_loss: Decimal | None


class LimitResult(BaseModel):
    limit_id: str
    label: str
    status: Status
    value: Decimal | None
    threshold: str
    detail: str


class Check(BaseModel):
    """A risk check: the proposed trade, its price, every limit and the verdict."""

    rule_version: str
    known_at: datetime
    proposal: Proposal
    price: Decimal | None
    price_day: date | None
    notional: Decimal | None
    verdict: Verdict
    limits: list[LimitResult]

    @property
    def vetoes(self) -> list[LimitResult]:
        return [limit for limit in self.limits if limit.status == "veto"]


# ---------- prices ----------


def _factor(splits: Sequence[Split], since: datetime, at: datetime) -> Fraction:
    factor = Fraction(1)
    for split in splits_between(splits, since, at):
        factor *= split.ratio
    return factor


def _per_share(value: Decimal, factor: Fraction) -> Decimal:
    exact = Fraction(value) / factor
    return Decimal(exact.numerator) / Decimal(exact.denominator)


def _shares(value: Decimal, factor: Fraction) -> Decimal:
    exact = Fraction(value) * factor
    return Decimal(exact.numerator) / Decimal(exact.denominator)


def _basis(day: date) -> datetime:
    """The split basis of a day's close: every split effective by the end of that day."""
    return datetime.combine(day, time(23, 59, 59), tzinfo=NEW_YORK)


def known_bars(market: Market, at: datetime) -> list[Bar]:
    """End-of-day (or recorded) bars public at T, close and volume on T's split basis."""
    by_day: dict[date, Bar] = {}
    for bar in market.bars:
        if bar.published_at > at:
            continue
        factor = _factor(market.splits, _basis(bar.day), at)
        by_day[bar.day] = Bar(
            bar.day,
            _per_share(bar.close, factor),
            _shares(bar.volume, factor),
            bar.feed_status,
            bar.published_at,
        )
    return [by_day[d] for d in sorted(by_day)]


def average_volume(bars: Sequence[Bar], sessions: int) -> Decimal | None:
    """The mean shares traded over the last `sessions` bars (T's basis); None if fewer."""
    if len(bars) < sessions:
        return None
    window = bars[-sessions:]
    return sum((b.volume for b in window), Decimal(0)) / sessions


def _stale(bar: Bar | None, at: datetime, days: int) -> bool:
    return (
        bar is None
        or bar.feed_status != "end_of_day"
        or at.astimezone(NEW_YORK).date() - bar.day > timedelta(days=days)
    )


# ---------- portfolio ----------


def _sign(side: Side) -> int:
    return 1 if side == "buy" else -1


def _close_on(bars: Sequence[Bar], day: date) -> Bar | None:
    """The last bar on or before `day`."""
    found = None
    for bar in bars:
        if bar.day > day:
            break
        found = bar
    return found


def portfolio(
    rules: RiskRuleSet, at: datetime, trades: Sequence[Trade], markets: Mapping[str, Market]
) -> Portfolio:
    """The paper portfolio at T from the trades and market evidence known then."""
    limits = rules.limits
    bars = {ticker: known_bars(m, at) for ticker, m in markets.items()}
    notes: list[str] = []
    positions: list[Position] = []
    realized = Decimal(0)
    for trade in sorted(trades, key=lambda t: (t.known_at, t.decision_id)):
        if trade.known_at > at:
            continue
        market = markets.get(trade.ticker)
        splits = market.splits if market else []
        factor = _factor(splits, _basis(trade.entry.day), at)
        shares = _shares(trade.quantity, factor)
        entry_price = _per_share(trade.entry.close, factor)
        sign = _sign(trade.side)
        if trade.exit is not None and trade.exit_known_at is not None and trade.exit_known_at <= at:
            exit_price = _per_share(trade.exit.close, _factor(splits, _basis(trade.exit.day), at))
            realized += sign * shares * (exit_price - entry_price)
            continue
        own = bars.get(trade.ticker, [])
        last = own[-1] if own else None
        adv = average_volume(own, limits.volume_sessions)
        if last is None:
            notes.append(f"{trade.ticker}: no close known, valued at its entry")
        mark = last.close if last else None
        value = sign * shares * mark if mark is not None else None
        positions.append(
            Position(
                decision_id=trade.decision_id,
                ticker=trade.ticker,
                side=trade.side,
                shares=_round(shares, SHARES),
                entry_price=_round(entry_price, SHARES),
                entry_day=trade.entry.day,
                mark=_round(mark, SHARES) if mark is not None else None,
                mark_day=last.day if last else None,
                market_value=_round(value) if value is not None else None,
                weight_pct=rules.pct(abs(value)) if value is not None else None,
                pnl=_round(sign * shares * (mark - entry_price)) if mark is not None else None,
                beta=market.beta if market else None,
                sector=market.sector if market else None,
                days_to_exit=_round(shares / adv) if adv else None,
                stale=_stale(last, at, limits.stale_after_days),
                max_loss=trade.max_loss,
            )
        )
    unrealized = sum((p.pnl or Decimal(0) for p in positions), Decimal(0))
    gross = sum((abs(p.market_value or Decimal(0)) for p in positions), Decimal(0))
    net = sum((p.market_value or Decimal(0) for p in positions), Decimal(0))
    equity = rules.capital + realized + unrealized
    missing_beta = [p.ticker for p in positions if p.beta is None or p.market_value is None]
    if missing_beta:
        notes.append(
            f"no beta known for {', '.join(missing_beta)}: beta-weighted exposure unavailable"
        )
    beta_exposure = (
        None
        if missing_beta
        else sum(
            ((p.market_value or Decimal(0)) * (p.beta or Decimal(0)) for p in positions), Decimal(0)
        )
    )
    curve = equity_curve(rules, at, trades, markets, bars)
    peak = max([rules.capital, *(point.equity for point in curve)])
    current = curve[-1].equity if curve else equity
    return Portfolio(
        rule_version=rules.rule_version,
        known_at=at,
        capital=rules.capital,
        positions=positions,
        realized_pnl=_round(realized),
        unrealized_pnl=_round(unrealized),
        equity=_round(equity),
        cash=_round(equity - net),
        gross=_round(gross),
        net=_round(net),
        gross_pct=rules.pct(gross),
        net_pct=rules.pct(net),
        beta_exposure=_round(beta_exposure) if beta_exposure is not None else None,
        sectors=sector_exposure(rules, positions),
        curve=curve,
        peak_equity=_round(peak),
        drawdown_pct=_round((peak - current) / peak * HUNDRED) if peak > 0 else Decimal(0),
        notes=notes,
    )


def sector_exposure(rules: RiskRuleSet, positions: Sequence[Position]) -> list[SectorExposure]:
    totals: dict[str, Decimal] = {}
    for p in positions:
        if p.market_value is None:
            continue
        key = p.sector or "unknown"
        totals[key] = totals.get(key, Decimal(0)) + abs(p.market_value)
    return [
        SectorExposure(
            sector=sector,
            gross=_round(gross),
            pct=rules.pct(gross),
            limited=sector not in rules.unlimited_sectors,
        )
        for sector, gross in sorted(totals.items())
    ]


def equity_curve(
    rules: RiskRuleSet,
    at: datetime,
    trades: Sequence[Trade],
    markets: Mapping[str, Market],
    bars: Mapping[str, list[Bar]],
) -> list[EquityPoint]:
    """Equity at the close of every session from the first entry's close to T: the capital
    plus the P&L realized by then plus each open position marked at that day's close."""
    known = [t for t in trades if t.known_at <= at]
    if not known:
        return []
    first = min(t.entry.day for t in known)
    days = sorted({b.day for t in known for b in bars.get(t.ticker, []) if b.day >= first})
    points = []
    for day in days:
        total = rules.capital
        for trade in known:
            if trade.entry.day > day:
                continue
            market = markets.get(trade.ticker)
            splits = market.splits if market else []
            factor = _factor(splits, _basis(trade.entry.day), at)
            shares = _shares(trade.quantity, factor)
            entry_price = _per_share(trade.entry.close, factor)
            sign = _sign(trade.side)
            done = (
                trade.exit
                if trade.exit_known_at is not None and trade.exit_known_at <= at
                else None
            )
            if done is not None and done.day <= day:
                exit_factor = _factor(splits, _basis(done.day), at)
                total += sign * shares * (_per_share(done.close, exit_factor) - entry_price)
                continue
            bar = _close_on(bars.get(trade.ticker, []), day)
            if bar is not None:
                total += sign * shares * (bar.close - entry_price)
        points.append(EquityPoint(day=day, equity=_round(total)))
    return points


# ---------- check ----------


def _limit(
    limit_id: str, label: str, ok: bool, value: Decimal | None, threshold: str, detail: str
) -> LimitResult:
    return LimitResult(
        limit_id=limit_id,
        label=label,
        status="pass" if ok else "veto",
        value=value,
        threshold=threshold,
        detail=detail,
    )


def check(
    rules: RiskRuleSet,
    at: datetime,
    book: Portfolio,
    proposal: Proposal,
    market: Market | None,
) -> Check:
    """The proposed trade added to the portfolio at T, against every limit."""
    limits = rules.limits
    own = known_bars(market, at) if market else []
    last = own[-1] if own else None
    price = last.close if last else None
    notional = proposal.quantity * price if price is not None else None
    results: list[LimitResult] = []

    stale = _stale(last, at, limits.stale_after_days)
    age = (at.astimezone(NEW_YORK).date() - last.day).days if last else None
    results.append(
        _limit(
            "price",
            "Usable price",
            not stale,
            Decimal(age) if age is not None else None,
            f"an end-of-day close at most {limits.stale_after_days} days old",
            "no close known"
            if last is None
            else f"close {last.day} ({last.feed_status}), {age} days before the date",
        )
    )

    stated = proposal.max_loss is not None
    results.append(
        _limit(
            "max_loss_stated",
            "Maximum loss stated",
            stated,
            proposal.max_loss,
            "a TRADE states its maximum loss in USD",
            "stated" if stated else "no maximum loss stated",
        )
    )
    ceiling = rules.capital * limits.max_loss_pct / HUNDRED
    max_loss_pct = rules.pct(proposal.max_loss) if proposal.max_loss is not None else None
    results.append(
        _limit(
            "max_loss",
            "Maximum loss",
            proposal.max_loss is not None and rules.within(proposal.max_loss, limits.max_loss_pct),
            max_loss_pct,
            f"at most {limits.max_loss_pct}% of capital ({_round(ceiling)} USD)",
            f"{proposal.max_loss} USD of {rules.capital} USD capital"
            if proposal.max_loss is not None
            else "no maximum loss stated",
        )
    )

    held = sum(
        (abs(p.market_value or Decimal(0)) for p in book.positions if p.ticker == proposal.ticker),
        Decimal(0),
    )
    position = held + notional if notional is not None else None
    position_pct = rules.pct(position) if position is not None else None
    results.append(
        _limit(
            "position",
            "Position size",
            position is not None and rules.within(position, limits.position_pct),
            position_pct,
            f"at most {limits.position_pct}% of capital",
            f"{_round(notional)} USD new plus {_round(held)} USD held in {proposal.ticker}"
            if notional is not None
            else "no price to value the trade",
        )
    )

    sector = market.sector if market else None
    if sector is None:
        results.append(
            _limit(
                "sector",
                "Sector concentration",
                False,
                None,
                f"at most {limits.sector_pct}% of capital in one sector",
                f"no sector for {proposal.ticker} in rules {rules.rule_version}",
            )
        )
    elif sector in rules.unlimited_sectors:
        results.append(
            _limit(
                "sector",
                "Sector concentration",
                True,
                None,
                f"at most {limits.sector_pct}% of capital in one sector",
                f"{sector} is not held to the sector limit",
            )
        )
    else:
        in_sector = sum(
            (abs(p.market_value or Decimal(0)) for p in book.positions if p.sector == sector),
            Decimal(0),
        )
        after = in_sector + notional if notional is not None else None
        sector_pct = rules.pct(after) if after is not None else None
        results.append(
            _limit(
                "sector",
                "Sector concentration",
                after is not None and rules.within(after, limits.sector_pct),
                sector_pct,
                f"at most {limits.sector_pct}% of capital in one sector",
                f"{sector}: {_round(after)} USD after the trade"
                if after is not None
                else "no price to value the trade",
            )
        )

    adv = average_volume(own, limits.volume_sessions)
    volume_pct = _round(proposal.quantity / adv * HUNDRED, Decimal("0.0001")) if adv else None
    volume_ok = adv is not None and proposal.quantity * HUNDRED <= adv * limits.volume_pct
    results.append(
        _limit(
            "volume",
            "Trade against average volume",
            volume_ok,
            volume_pct,
            f"at most {limits.volume_pct}% of the {limits.volume_sessions}-session average volume",
            f"{proposal.quantity} shares against {_round(adv, Decimal(1))} a day"
            if adv
            else f"fewer than {limits.volume_sessions} sessions of volume known",
        )
    )

    gross_after = book.gross + notional if notional is not None else None
    gross_pct = rules.pct(gross_after) if gross_after is not None else None
    results.append(
        _limit(
            "gross",
            "Gross exposure (no leverage)",
            gross_after is not None and rules.within(gross_after, limits.gross_pct),
            gross_pct,
            f"at most {limits.gross_pct}% of capital",
            f"{_round(gross_after)} USD of positions after the trade"
            if gross_after is not None
            else "no price to value the trade",
        )
    )

    verdict: Verdict = "pass" if all(r.status == "pass" for r in results) else "veto"
    return Check(
        rule_version=rules.rule_version,
        known_at=at,
        proposal=proposal,
        price=_round(price, SHARES) if price is not None else None,
        price_day=last.day if last else None,
        notional=_round(notional) if notional is not None else None,
        verdict=verdict,
        limits=results,
    )


def standard_proposal(rules: RiskRuleSet, ticker: str, price: Decimal | None) -> Proposal:
    """The position tried every day for TRADE-READY and L4 (R3): a whole number of shares
    worth the standard share of capital at the last close, and the standard maximum loss."""
    budget = rules.capital * rules.standard.position_pct / HUNDRED
    quantity = (budget / price).quantize(Decimal(1), rounding=ROUND_DOWN) if price else Decimal(1)
    return Proposal(
        ticker=ticker,
        side="buy",
        quantity=max(quantity, Decimal(1)),
        max_loss=_round(rules.capital * rules.standard.max_loss_pct / HUNDRED),
    )


def last_price(market: Market | None, at: datetime) -> Decimal | None:
    bars = known_bars(market, at) if market else []
    return bars[-1].close if bars else None
