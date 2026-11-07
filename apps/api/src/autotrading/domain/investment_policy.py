"""Investment policy and rebalancing (M3.12, ADR-043): Steven's own targets against his holdings
at a time T. Pure; no I/O. Arithmetic on his targets, never advice; nothing is sent anywhere.

- A policy version is written by Steven: goals, horizon and risk in his words, an optional cap
  on any one position, and sleeves. A sleeve is an asset class in a market with a target share
  of the USD total, a band (± percentage points) and its members: listings (`US:SPY`,
  `TW:2330`), each with an optional target, or currencies for a cash sleeve. The targets add up
  to exactly 100%; a listing or currency belongs to one sleeve at most.
- A position is one instrument summed over the accounts, cash one currency summed over the
  accounts, weighed as in the valuation (a share of the USD total, cash included). Each is
  assigned to the sleeve that names it; what no sleeve names is unassigned.
- Drift is the actual weight less the target; a sleeve whose drift exceeds its band is outside.
  The asset classes and markets add up their sleeves (targets and weights, no bands), and a
  position above the cap is flagged (a check only, never traded).
- Rebalancing (0.1.0) is due when any sleeve is outside its band. Every listing sleeve then
  goes to its target: each member to its own target when the sleeve gives them, else in
  proportion to the members' current values, else (nothing held yet) in equal parts. A cash
  sleeve is what the trades leave. The USD amount is converted at the valuation's rate and
  divided by the last close known at T, rounded toward zero to whole shares; fees, taxes and
  board lots are not counted. No trade is listed without a USD total, while anything held is
  unassigned, or without a policy.
"""

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from fractions import Fraction
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from autotrading.domain.holdings import (
    BASE_CURRENCY,
    MONEY,
    PRICE,
    QUANTITY,
    STALE_MARK_DAYS,
    WEIGHT,
    Fx,
    Mark,
    Valuation,
)
from autotrading.domain.markets import Market

REBALANCING_VERSION = "0.1.0"
MAX_SLEEVES = 12
MAX_MEMBERS = 40
HUNDRED = Decimal(100)

AssetClass = Literal["equity", "bond", "commodity", "real_estate", "cash", "other"]
ASSET_CLASSES: tuple[AssetClass, ...] = (
    "equity",
    "bond",
    "commodity",
    "real_estate",
    "cash",
    "other",
)
SleeveMarket = Literal["US", "TW", "cash", "mixed"]
SLEEVE_MARKETS: tuple[SleeveMarket, ...] = ("US", "TW", "cash", "mixed")
Blocked = Literal["no_policy", "no_holdings", "no_rate", "unassigned"]
TradeFlag = Literal["no_close", "stale_mark"]

Percent = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
Band = Annotated[Decimal, Field(ge=0, le=50, max_digits=4, decimal_places=2)]
MemberKey = Annotated[str, StringConstraints(pattern=r"^((US|TW):[A-Z0-9.]{1,10}|USD|TWD)$")]


class Member(BaseModel):
    """A listing (`US:SPY`, `TW:2330`) with an optional target share of the total, or a
    currency (`USD`, `TWD`) of a cash sleeve."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: MemberKey
    target_pct: Percent | None = None

    @property
    def is_cash(self) -> bool:
        return ":" not in self.key

    @property
    def market(self) -> Market | None:
        return None if self.is_cash else self.key.split(":")[0]  # type: ignore[return-value]

    @property
    def symbol(self) -> str | None:
        return None if self.is_cash else self.key.split(":")[1]


class Sleeve(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
    asset_class: AssetClass
    market: SleeveMarket
    target_pct: Percent
    band_pp: Band
    members: tuple[Member, ...] = Field(min_length=1, max_length=MAX_MEMBERS)

    @model_validator(mode="after")
    def _members_fit(self) -> "Sleeve":
        cash = self.asset_class == "cash"
        if cash != (self.market == "cash"):
            raise ValueError("a cash sleeve has asset class cash and market cash, and only it")
        for member in self.members:
            if member.is_cash != cash:
                raise ValueError(
                    f"{member.key}: a cash sleeve holds currencies, any other sleeve listings"
                )
            if member.market and self.market in ("US", "TW") and member.market != self.market:
                raise ValueError(f"{member.key} is not a {self.market} listing")
            if cash and member.target_pct is not None:
                raise ValueError(f"{member.key}: a currency takes no target of its own")
        given = [m.target_pct for m in self.members if m.target_pct is not None]
        if given and len(given) != len(self.members):
            raise ValueError(f"{self.name}: give every member a target, or none")
        if given and sum(given, Decimal(0)) != self.target_pct:
            raise ValueError(f"{self.name}: the members' targets add up to {sum(given)}%")
        return self


class PolicyContent(BaseModel):
    """One version of Steven's investment policy, as he wrote it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goals: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    horizon_years: Annotated[int, Field(ge=1, le=60)]
    risk: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    max_drawdown_pct: Percent | None = None
    position_cap_pct: Percent | None = None
    sleeves: tuple[Sleeve, ...] = Field(min_length=1, max_length=MAX_SLEEVES)

    @model_validator(mode="after")
    def _sleeves_fit(self) -> "PolicyContent":
        names = [s.name.casefold() for s in self.sleeves]
        if len(set(names)) != len(names):
            raise ValueError("two sleeves share a name")
        total = sum((s.target_pct for s in self.sleeves), Decimal(0))
        if total != HUNDRED:
            raise ValueError(f"the sleeves' targets add up to {total}%, not 100%")
        keys = [m.key for s in self.sleeves for m in s.members]
        twice = sorted({k for k in keys if keys.count(k) > 1})
        if twice:
            raise ValueError(f"in more than one sleeve: {', '.join(twice)}")
        return self

    def content(self) -> dict[str, Any]:
        content: dict[str, Any] = self.model_dump(mode="json")
        return content

    def content_sha256(self) -> str:
        canonical = json.dumps(self.content(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class Policy:
    """A stored version."""

    version: int
    content: PolicyContent
    reason: str
    recorded_at: datetime


@dataclass(frozen=True)
class Quote:
    """The last close known at T of a listing a sleeve names but nothing holds."""

    instrument_id: UUID
    mark: Mark | None


@dataclass(frozen=True)
class Holding:
    """One instrument over the accounts, or one currency of cash."""

    key: str  # `US:SPY`, `TW:2330`, `USD`
    market: Market | None
    instrument_id: UUID | None
    currency: str
    quantity: Decimal | None  # shares on T's basis; None for cash
    price: Decimal | None
    mark: Mark | None
    value: Decimal  # in its currency
    value_usd: Decimal | None
    weight: Decimal | None
    sleeve: str | None  # None: unassigned
    over_cap: bool
    flags: tuple[str, ...]


@dataclass(frozen=True)
class SleeveDrift:
    name: str
    asset_class: AssetClass
    market: SleeveMarket
    target: Decimal  # shares of the total (0.25 is 25%)
    band: Decimal
    actual: Decimal | None
    drift: Decimal | None
    outside: bool
    after: Decimal | None  # after the listed trades (whole shares)


@dataclass(frozen=True)
class GroupDrift:
    group: str  # an asset class or a sleeve market
    target: Decimal
    actual: Decimal | None
    drift: Decimal | None


@dataclass(frozen=True)
class Trade:
    sleeve: str
    key: str
    market: Market
    instrument_id: UUID | None
    currency: str
    side: Literal["buy", "sell"]
    amount_usd: Decimal  # to the target, before rounding to shares
    price: Decimal | None
    mark: Mark | None
    shares: Decimal | None  # whole shares toward zero; None without a close
    amount: Decimal | None  # shares at the price, in its currency
    weight_before: Decimal
    weight_target: Decimal
    flags: tuple[TradeFlag, ...]


@dataclass(frozen=True)
class CashFlow:
    """What the listed trades move in one currency (sells less buys)."""

    currency: str
    balance: Decimal
    flow: Decimal
    after: Decimal


@dataclass(frozen=True)
class Assessment:
    version: str
    known_at: datetime
    system_time: datetime
    policy: Policy | None
    equity_usd: Decimal | None
    fx: Fx | None  # the valuation's rate, which the trades convert at
    fx_lag_days: int | None
    holdings: tuple[Holding, ...]
    sleeves: tuple[SleeveDrift, ...]
    asset_classes: tuple[GroupDrift, ...]
    markets: tuple[GroupDrift, ...]
    due: bool
    blocked: tuple[Blocked, ...]
    trades: tuple[Trade, ...]
    cash_flows: tuple[CashFlow, ...]


def _decimal(value: Fraction, quantum: Decimal) -> Decimal:
    return (Decimal(value.numerator) / Decimal(value.denominator)).quantize(quantum)


def _share(pct: Decimal) -> Fraction:
    return Fraction(pct) / 100


@dataclass
class _Sum:
    key: str
    market: Market | None
    instrument_id: UUID | None
    currency: str
    quantity: Fraction | None
    price: Decimal | None
    mark: Mark | None
    value: Fraction
    value_usd: Fraction | None
    flags: set[str]


def _holdings(valuation: Valuation) -> list[_Sum]:
    sums: dict[str, _Sum] = {}
    for p in valuation.positions:
        key = f"{p.market}:{p.symbol}"
        held = sums.get(key)
        if held is None:
            held = sums[key] = _Sum(
                key=key,
                market=p.market,
                instrument_id=p.instrument_id,
                currency=p.currency,
                quantity=Fraction(0),
                price=p.price,
                mark=p.mark,
                value=Fraction(0),
                value_usd=Fraction(0),
                flags=set(),
            )
        assert held.quantity is not None
        held.quantity += Fraction(p.quantity)
        held.value += Fraction(p.market_value)
        held.value_usd = (
            None
            if p.value_usd is None or held.value_usd is None
            else held.value_usd + Fraction(p.value_usd)
        )
        held.flags.update(p.flags)
    for c in valuation.cash:
        held = sums.get(c.currency)
        if held is None:
            held = sums[c.currency] = _Sum(
                key=c.currency,
                market=None,
                instrument_id=None,
                currency=c.currency,
                quantity=None,
                price=None,
                mark=None,
                value=Fraction(0),
                value_usd=Fraction(0),
                flags=set(),
            )
        held.value += Fraction(c.balance)
        held.value_usd = (
            None
            if c.value_usd is None or held.value_usd is None
            else held.value_usd + Fraction(c.value_usd)
        )
    return sorted(sums.values(), key=lambda s: (s.market is None, s.key))


def _in_currency(amount_usd: Fraction, currency: str, fx: Fx | None) -> Fraction | None:
    if currency == BASE_CURRENCY:
        return amount_usd
    return amount_usd * Fraction(fx.value) if fx is not None else None


def _to_usd(amount: Fraction, currency: str, fx: Fx | None) -> Fraction:
    if currency == BASE_CURRENCY:
        return amount
    assert fx is not None
    return amount / Fraction(fx.value)


def assess(valuation: Valuation, policy: Policy | None, quotes: Mapping[str, Quote]) -> Assessment:
    """The policy in force at T against the holdings at (T, S). `quotes`: the last close known
    at T of each listing a sleeve names but nothing holds, by member key."""
    sums = _holdings(valuation)
    equity = (
        Fraction(valuation.equity_usd)
        if valuation.equity_usd is not None and valuation.equity_usd > 0
        else None
    )
    content = policy.content if policy else None
    sleeve_of = {m.key: s.name for s in content.sleeves for m in s.members} if content else {}
    cap = _share(content.position_cap_pct) if content and content.position_cap_pct else None

    def weight(s: _Sum) -> Fraction | None:
        return s.value_usd / equity if equity is not None and s.value_usd is not None else None

    def holding(s: _Sum) -> Holding:
        w = weight(s)
        return Holding(
            key=s.key,
            market=s.market,
            instrument_id=s.instrument_id,
            currency=s.currency,
            quantity=_decimal(s.quantity, QUANTITY) if s.quantity is not None else None,
            price=s.price,
            mark=s.mark,
            value=_decimal(s.value, MONEY),
            value_usd=_decimal(s.value_usd, MONEY) if s.value_usd is not None else None,
            weight=_decimal(w, WEIGHT) if w is not None else None,
            sleeve=sleeve_of.get(s.key),
            over_cap=cap is not None and s.market is not None and w is not None and w > cap,
            flags=tuple(sorted(s.flags)),
        )

    holdings = tuple(holding(s) for s in sums)

    blocked: list[Blocked] = []
    if content is None:
        blocked.append("no_policy")
    if valuation.equity_usd is None:
        blocked.append("no_rate")
    elif equity is None:
        blocked.append("no_holdings")
    if content is not None and any(h.sleeve is None for h in holdings if h.value):
        blocked.append("unassigned")
    if content is None:
        return Assessment(
            version=REBALANCING_VERSION,
            known_at=valuation.known_at,
            system_time=valuation.system_time,
            policy=None,
            equity_usd=valuation.equity_usd,
            fx=valuation.fx,
            fx_lag_days=valuation.fx_lag_days,
            holdings=holdings,
            sleeves=(),
            asset_classes=(),
            markets=(),
            due=False,
            blocked=tuple(blocked),
            trades=(),
            cash_flows=(),
        )

    actual: dict[str, Fraction] = defaultdict(Fraction)
    for s in sums:
        if (name := sleeve_of.get(s.key)) is not None and (w := weight(s)) is not None:
            actual[name] += w
    outside = {
        s.name: equity is not None
        and abs(actual[s.name] - _share(s.target_pct)) > _share(s.band_pp)
        for s in content.sleeves
    }
    due = any(outside.values())
    trades: list[Trade] = []
    moved_usd: dict[str, Fraction] = defaultdict(Fraction)  # by sleeve, rounded trades
    flows: dict[str, Fraction] = defaultdict(Fraction)  # by currency, rounded trades
    if due and not blocked:
        assert equity is not None
        by_key = {s.key: s for s in sums}
        for sleeve in content.sleeves:
            if sleeve.asset_class == "cash":
                continue
            for member, goal in _goals(sleeve, by_key, equity):
                trade = _trade(
                    sleeve.name, member, goal, by_key.get(member.key), quotes, valuation, equity
                )
                if trade is None:
                    continue
                trades.append(trade)
                if trade.amount is not None:
                    signed = trade.amount if trade.side == "buy" else -trade.amount
                    moved_usd[sleeve.name] += _to_usd(
                        Fraction(signed), trade.currency, valuation.fx
                    )
                    flows[trade.currency] -= Fraction(signed)

    def after(sleeve: Sleeve) -> Decimal | None:
        if not trades or equity is None:
            return None
        if sleeve.asset_class != "cash":
            return _decimal(actual[sleeve.name] + moved_usd[sleeve.name] / equity, WEIGHT)
        moved = sum(
            (_to_usd(flows[m.key], m.key, valuation.fx) for m in sleeve.members), Fraction(0)
        )
        return _decimal(actual[sleeve.name] + moved / equity, WEIGHT)

    sleeves = tuple(
        SleeveDrift(
            name=s.name,
            asset_class=s.asset_class,
            market=s.market,
            target=_decimal(_share(s.target_pct), WEIGHT),
            band=_decimal(_share(s.band_pp), WEIGHT),
            actual=_decimal(actual[s.name], WEIGHT) if equity is not None else None,
            drift=(
                _decimal(actual[s.name] - _share(s.target_pct), WEIGHT)
                if equity is not None
                else None
            ),
            outside=outside[s.name],
            after=after(s),
        )
        for s in content.sleeves
    )
    cash_flows = []
    if trades:
        balances = {s.key: s.value for s in sums if s.market is None}
        for currency in sorted(set(flows) | set(balances)):
            if not flows[currency]:
                continue
            balance = balances.get(currency, Fraction(0))
            cash_flows.append(
                CashFlow(
                    currency=currency,
                    balance=_decimal(balance, MONEY),
                    flow=_decimal(flows[currency], MONEY),
                    after=_decimal(balance + flows[currency], MONEY),
                )
            )
    return Assessment(
        version=REBALANCING_VERSION,
        known_at=valuation.known_at,
        system_time=valuation.system_time,
        policy=policy,
        equity_usd=valuation.equity_usd,
        fx=valuation.fx,
        fx_lag_days=valuation.fx_lag_days,
        holdings=holdings,
        sleeves=sleeves,
        asset_classes=_groups(content.sleeves, actual, equity, lambda s: s.asset_class),
        markets=_groups(content.sleeves, actual, equity, lambda s: s.market),
        due=due,
        blocked=tuple(blocked),
        trades=tuple(trades),
        cash_flows=tuple(cash_flows),
    )


def _goals(
    sleeve: Sleeve, by_key: Mapping[str, _Sum], equity: Fraction
) -> Iterable[tuple[Member, Fraction]]:
    """Each member's target in USD: its own target, else in proportion to the members'
    current values, else (nothing held yet) in equal parts of the sleeve's target."""
    target = _share(sleeve.target_pct) * equity
    if all(m.target_pct is not None for m in sleeve.members):
        return [(m, _share(m.target_pct or Decimal(0)) * equity) for m in sleeve.members]
    values = {
        m.key: (by_key[m.key].value_usd or Fraction(0)) if m.key in by_key else Fraction(0)
        for m in sleeve.members
    }
    held = sum(values.values(), Fraction(0))
    if held > 0:
        return [(m, target * values[m.key] / held) for m in sleeve.members]
    return [(m, target / len(sleeve.members)) for m in sleeve.members]


def _trade(
    sleeve: str,
    member: Member,
    goal: Fraction,
    held: _Sum | None,
    quotes: Mapping[str, Quote],
    valuation: Valuation,
    equity: Fraction,
) -> Trade | None:
    assert member.market is not None
    current = (held.value_usd or Fraction(0)) if held else Fraction(0)
    delta = goal - current
    if delta == 0:
        return None
    currency = "USD" if member.market == "US" else "TWD"
    quote = quotes.get(member.key)
    mark = held.mark if held else (quote.mark if quote else None)
    price = held.price if held else (mark.close if mark else None)
    flags: list[TradeFlag] = []
    shares: Decimal | None = None
    amount: Decimal | None = None
    in_currency = _in_currency(abs(delta), currency, valuation.fx)
    if price is None or price <= 0 or in_currency is None:
        flags.append("no_close")
    else:
        shares = _decimal(in_currency / Fraction(price), QUANTITY).quantize(
            Decimal(1), rounding=ROUND_DOWN
        )
        if shares == 0:
            return None
        amount = _decimal(Fraction(shares) * Fraction(price), MONEY)
        assert mark is not None
        if valuation.known_at - mark.published_at > timedelta(days=STALE_MARK_DAYS[member.market]):
            flags.append("stale_mark")
    return Trade(
        sleeve=sleeve,
        key=member.key,
        market=member.market,
        instrument_id=held.instrument_id if held else (quote.instrument_id if quote else None),
        currency=currency,
        side="buy" if delta > 0 else "sell",
        amount_usd=_decimal(abs(delta), MONEY),
        price=price.quantize(PRICE) if price is not None else None,
        mark=mark,
        shares=shares,
        amount=amount,
        weight_before=_decimal(current / equity, WEIGHT),
        weight_target=_decimal(goal / equity, WEIGHT),
        flags=tuple(flags),
    )


def _groups(
    sleeves: Iterable[Sleeve],
    actual: Mapping[str, Fraction],
    equity: Fraction | None,
    group_of: Callable[[Sleeve], str],
) -> tuple[GroupDrift, ...]:
    targets: dict[str, Fraction] = defaultdict(Fraction)
    weights: dict[str, Fraction] = defaultdict(Fraction)
    for s in sleeves:
        targets[group_of(s)] += _share(s.target_pct)
        weights[group_of(s)] += actual.get(s.name, Fraction(0))
    return tuple(
        GroupDrift(
            group=group,
            target=_decimal(target, WEIGHT),
            actual=_decimal(weights[group], WEIGHT) if equity is not None else None,
            drift=_decimal(weights[group] - target, WEIGHT) if equity is not None else None,
        )
        for group, target in targets.items()
    )
